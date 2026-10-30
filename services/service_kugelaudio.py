# KugelAudio text-to-speech service for HyperTTS
#
# API reference:
# - https://docs.kugelaudio.com/api-reference/introduction
# - generate: https://docs.kugelaudio.com/api-reference/tts/generate
# - voices: https://docs.kugelaudio.com/api-reference/endpoints/voices
# - models: https://docs.kugelaudio.com/models
#
# GET  /v1/voices?limit=100&offset=0   all voices visible to the API key
# POST /v1/tts/generate                { text, voice_id, model_id, cfg_scale, speed, normalize,
#                                        language, sample_rate } -> headerless PCM16 audio
# Auth: Authorization: Bearer <api key>
#
# The generate endpoint never returns mp3: the response is raw PCM16, mono. We ask for
# KugelAudio's native 24 kHz so the provider does not have to resample it. The PCM is wrapped
# in a WAV container and encoded with Anki's bundled lame using LAME's extreme preset
# (-V 0, high-quality VBR), the same bundled encoder service_gemini.py uses for Gemini's
# lossless output.
#
# Expressiveness: KugelAudio has no emotion or style parameter, and no voice-direction layer.
# The model-level lever is cfg_scale (higher = more expressive, max 2.5); temperature only
# varies pacing between takes. Beyond that, the input text itself is the control: exclamation
# marks, ?!, ALL CAPS, punctuation, <break> and <prosody rate> are all interpreted.
#
# A key issued in the EU has the form "eu-ka_...". Like the official SDK, strip the prefix
# before authentication and call the EU endpoint instead of the geo-routed one.
#
# Languages: the service is language-independent. GET /v1/voices is queried without a
# language filter, and each voice is listed under every language in its
# supported_languages tags (BCP-47, e.g. de-DE or en-GB). KugelAudio accepts 39 TTS
# languages and uses an ISO 639-1 code for text normalization and dictionary selection.
# A voice which supports several languages therefore becomes one HyperTTS voice per
# language, and each variant sends that language on the generate request. Voices without
# language metadata are listed under English, which is KugelAudio's documented fallback.
#
# KugelAudio dictionaries (pronunciation overrides for brand names, acronyms and domain
# vocabulary) are applied automatically from the project the API key belongs to. They are
# not a word-pronunciation audio API, so this is a TTS service, not a HyperTTS dictionary
# service.

import os
import subprocess
import tempfile

import aqt.sound
import aqt.utils
import requests
import cachetools
from typing import List, Optional

from hypertts_addon import voice
from hypertts_addon import service
from hypertts_addon import errors
from hypertts_addon import constants
from hypertts_addon import languages
from hypertts_addon import options
from hypertts_addon import audio_encoding
from hypertts_addon import logging_utils

logger = logging_utils.get_child_logger(__name__)

KUGELEAUDIO_API_URL = 'https://api.kugelaudio.com'
KUGELEAUDIO_EU_API_URL = 'https://api.eu.kugelaudio.com'
KUGELEAUDIO_EU_KEY_PREFIX = 'eu-'

# the voice list is requested when Anki starts, don't block for too long
REQUEST_TIMEOUT = 10
# synthesizing a longer text can take a while, especially the first request for a voice
TTS_TIMEOUT = 60
# the voice list is re-fetched after this delay
VOICE_LIST_CACHE_SECONDS = 600
VOICES_PAGE_SIZE = 100

# https://docs.kugelaudio.com/models -- 'kugel-3.5' is the default, 'kugel-3' is still served
MODELS = ['kugel-3.5', 'kugel-3']
DEFAULT_MODEL = MODELS[0]

# KugelAudio generates natively at 24 kHz and recommends requesting that rate because it
# requires no server-side resampling. Resampling to a higher rate adds no audio information.
OUTPUT_SAMPLE_RATE = 24000
PCM_AUDIO_FORMAT = 'pcm_s16le'

# LAME's extreme preset is -V 0, a high-quality variable-bitrate setting.
LAME_PRESET_ARGS = ['-V', '0']

# KugelAudio's text-to-speech languages. The API takes two-letter ISO 639-1 codes for
# normalization; regional tags in supported_languages are reduced to these codes.
# https://docs.kugelaudio.com/features/text-processing#supported-languages
SUPPORTED_LANGUAGES = frozenset({
    'ar', 'bg', 'bn', 'cs', 'da', 'de', 'el', 'en', 'es', 'fa', 'fi', 'fr', 'he',
    'hi', 'hr', 'hu', 'id', 'it', 'ja', 'ko', 'ms', 'nl', 'no', 'pl', 'pt', 'ro',
    'ru', 'sk', 'sl', 'sr', 'sv', 'ta', 'th', 'tr', 'uk', 'ur', 'vi', 'yue', 'zh',
})

# Language names in HyperTTS which don't match the provider's ISO 639-1 code.
LANGUAGE_ALIASES = {
    'cmn': 'zh_cn',
    'id': 'id_',
    'in': 'id_',
    'iw': 'he',
    'no': 'nb',
    'pt': 'pt_pt',
    'sr': 'sr_cyrl',
    'tl': 'fil',
    'zh': 'zh_cn',
    'zho': 'zh_cn',
}

# A few AudioLanguage values map to a different provider code. zh_HK is Cantonese in
# HyperTTS, so it needs KugelAudio's yue rather than its Mandarin zh. The two Norwegian
# AudioLanguage values both use KugelAudio's no.
AUDIO_LANGUAGE_PROVIDER_OVERRIDES = {
    languages.AudioLanguage.nb_NO: 'no',
    languages.AudioLanguage.nn_NO: 'no',
    languages.AudioLanguage.zh_HK: 'yue',
}

AUDIO_LANGUAGE_BY_NAME = {
    audio_language.name.lower(): audio_language
    for audio_language in languages.AudioLanguage
}

GENDER_MAP = {
    'male': constants.Gender.Male,
    'female': constants.Gender.Female,
}

# KugelAudio documents English as the normalization fallback when a voice has no language.
FALLBACK_AUDIO_LANGUAGE = languages.AudioLanguage.en_US
FALLBACK_LANGUAGE = 'en'


def _language_tag_parts(code) -> list:
    """split a BCP-47 tag ("de-DE", "zh-Hant-TW") or a HyperTTS code into lowercase parts"""
    normalized = str(code or '').strip().replace('_', '-').lower()
    return [part for part in normalized.split('-') if part]


def to_audio_language(code) -> Optional[languages.AudioLanguage]:
    """convert a BCP-47 language tag to a HyperTTS AudioLanguage. returns None when
    HyperTTS doesn't know the language."""
    parts = _language_tag_parts(code)
    if not parts:
        return None

    # Prefer the complete tag, then the language+region form, then the region alone.
    # This handles tags such as de-DE-1996 and zh-Hant-TW, whose important part is the
    # final region, as well as normal two-part tags such as en-GB.
    candidates = ['_'.join(parts)]
    if len(parts) >= 2:
        candidates.append(f'{parts[0]}_{parts[1]}')
        candidates.append(f'{parts[0]}_{parts[-1]}')
    for candidate in candidates:
        audio_language = AUDIO_LANGUAGE_BY_NAME.get(candidate)
        if audio_language is not None:
            return audio_language

    # A bare language code or a regional variant HyperTTS has no locale for: use the
    # language's default locale.
    base = parts[0]
    for language_name in (base, LANGUAGE_ALIASES.get(base)):
        if not language_name:
            continue
        if language_name in languages.Language.__members__:
            default = languages.AudioLanguageDefaults.get(languages.Language[language_name])
            if default is not None:
                return default
        if language_name in languages.AudioLanguage.__members__:
            return languages.AudioLanguage[language_name]
    return None


def provider_language_for_audio_language(audio_language) -> Optional[str]:
    """return the ISO 639-1 code KugelAudio expects for an AudioLanguage"""
    language = AUDIO_LANGUAGE_PROVIDER_OVERRIDES.get(audio_language)
    if language is None:
        language = audio_language.name.split('_')[0].lower()
    return language if language in SUPPORTED_LANGUAGES else None


def to_provider_language(code) -> Optional[str]:
    """convert a voice language tag to the ISO 639-1 code used by the generate request"""
    audio_language = to_audio_language(code)
    if audio_language is not None:
        language = provider_language_for_audio_language(audio_language)
        if language is not None:
            return language
    # if HyperTTS doesn't know the full tag, a supported bare code is still usable
    parts = _language_tag_parts(code)
    if parts:
        language = LANGUAGE_ALIASES.get(parts[0], parts[0])
        if language in SUPPORTED_LANGUAGES:
            return language
    return None


def unique_language_variants(codes) -> dict:
    """group a voice's supported_languages tags by the provider's request language.
    Returns {ISO 639-1 code: [AudioLanguage, ...]}."""
    if isinstance(codes, str):
        codes = [codes]
    variants = {}
    for code in codes or []:
        if code is None:
            continue
        audio_language = to_audio_language(code)
        language = to_provider_language(code)
        if audio_language is None or language is None:
            logger.warning(f'KugelAudio: unsupported voice language tag {code!r}')
            continue
        variants.setdefault(language, [])
        if audio_language not in variants[language]:
            variants[language].append(audio_language)
    return variants


def encode_wav_to_mp3_extreme(wav_bytes: bytes) -> bytes:
    """encode WAV audio with Anki's bundled LAME using the extreme (-V 0) preset.

    The shared audio_encoding.encode_wav_to_mp3 helper only exposes a CBR bitrate, so this
    service drives LAME directly. The invocation is otherwise identical to that helper.
    """
    wav_fh, wav_path = tempfile.mkstemp(prefix='hypertts_kugel_', suffix='.wav')
    os.close(wav_fh)
    mp3_fh, mp3_path = tempfile.mkstemp(prefix='hypertts_kugel_', suffix='.mp3')
    os.close(mp3_fh)
    try:
        with open(wav_path, 'wb') as f:
            f.write(wav_bytes)
        cmd = ['lame', wav_path, mp3_path, '--noreplaygain', '--quiet', *LAME_PRESET_ARGS]
        cmd, env = aqt.sound._packagedCmd(cmd)
        logger.debug(f'encoding mp3 with LAME preset extreme (-V 0): {cmd}')
        try:
            process = subprocess.Popen(cmd, startupinfo=aqt.utils.startup_info(), env=env)
            retcode = aqt.sound.retryWait(process)
        except Exception as e:
            raise errors.AudioEncodingError(
                f'could not run {" ".join(cmd)}: {e}') from e
        if retcode != 0:
            raise errors.AudioEncodingError(f'{" ".join(cmd)} returned {retcode}')
        with open(mp3_path, 'rb') as f:
            return f.read()
    finally:
        for path in (wav_path, mp3_path):
            if os.path.exists(path):
                os.remove(path)


class KugelAudio(service.ServiceBase):
    CONFIG_API_KEY = 'api_key'

    def __init__(self):
        service.ServiceBase.__init__(self)

    @property
    def service_type(self) -> constants.ServiceType:
        return constants.ServiceType.tts

    @property
    def service_fee(self) -> constants.ServiceFee:
        return constants.ServiceFee.paid

    def configuration_options(self):
        return {
            self.CONFIG_API_KEY: str,
        }

    def configure(self, config):
        self._config = config
        self.api_key = self.get_configuration_value_mandatory(self.CONFIG_API_KEY)

    @staticmethod
    def split_key(api_key):
        """return (<api key>, <base url>). an eu- prefixed key selects the EU endpoint,
        and the prefix is stripped before authentication, like the official SDK does."""
        api_key = (api_key or '').strip()
        if api_key.startswith(KUGELEAUDIO_EU_KEY_PREFIX):
            return api_key[len(KUGELEAUDIO_EU_KEY_PREFIX):], KUGELEAUDIO_EU_API_URL
        return api_key, KUGELEAUDIO_API_URL

    @staticmethod
    def headers(api_key):
        return {
            'Authorization': f'Bearer {api_key}',
        }

    def _fetch_voices(self, api_key) -> list:
        """all voices visible to the key, following pagination"""
        key, base_url = self.split_key(api_key)
        result = []
        offset = 0
        while True:
            response = requests.get(
                f'{base_url}/v1/voices',
                params={'limit': VOICES_PAGE_SIZE, 'offset': offset},
                headers=self.headers(key),
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            items = data.get('voices', [])
            result.extend(items)
            offset += len(items)
            if not items or offset >= data.get('total', 0):
                return result

    def _voice_options(self) -> dict:
        return {
            'model': {
                'type': options.ParameterType.list.name,
                'values': MODELS,
                'default': DEFAULT_MODEL,
            },
            # pitch-preserving time-stretching; the API rejects values outside this range
            'speed': {
                'type': options.ParameterType.number.name,
                'min': 0.8,
                'max': 1.2,
                'default': 1.0,
            },
            # higher values are more expressive; 2.5 is the API maximum, so default to it
            'cfg_scale': {
                'type': options.ParameterType.number.name,
                'min': 1.2,
                'max': 2.5,
                'default': 2.5,
            },
            # sampling variance for pacing/pause decisions: 0 = most stable, 1 = most variation.
            # adds variation between takes; it is not an emotion control.
            'temperature': {
                'type': options.ParameterType.number.name,
                'min': 0.0,
                'max': 1.0,
                'default': 0.3,
            },
            # numbers, dates and times to spoken words
            'normalize': {
                'type': options.ParameterType.list.name,
                'values': ['true', 'false'],
                'default': 'true',
            },
        }

    def _build_voice_list(self, api_key) -> List[voice.TtsVoice_v3]:
        voice_options = self._voice_options()
        result = []
        for item in self._fetch_voices(api_key):
            voice_id = item.get('id') or item.get('voice_id')
            if voice_id is None:
                logger.warning(f'KugelAudio: voice without an id: {item}')
                continue

            supported_languages = item.get('supported_languages') or []
            if isinstance(supported_languages, str):
                supported_languages = [supported_languages]
            language_variants = unique_language_variants(supported_languages)
            if not language_variants:
                if supported_languages:
                    logger.warning(f'KugelAudio: skipping voice {voice_id} '
                                   f'({item.get("name")}), no supported language could be mapped')
                    continue
                # KugelAudio normalizes in English when the voice has no language metadata.
                logger.warning(f'KugelAudio: voice {voice_id} ({item.get("name")}) has no '
                               f'supported_languages, listing it as English')
                language_variants = {FALLBACK_LANGUAGE: [FALLBACK_AUDIO_LANGUAGE]}

            name = item.get('name') or str(voice_id)
            gender = GENDER_MAP.get(str(item.get('sex')).lower(), constants.Gender.Any)
            for language, audio_languages in language_variants.items():
                result.append(voice.TtsVoice_v3(
                    name=name,
                    gender=gender,
                    audio_languages=audio_languages,
                    service=self.name,
                    # the language is part of the identity: one physical voice can be
                    # listed under several languages, each with its own normalization.
                    voice_key={'voice_id': voice_id, 'language': language},
                    options=voice_options,
                    service_fee=self.service_fee,
                ))
        return sorted(result, key=lambda v: (v.name.lower(),
                                             str(v.voice_key.get('language')),
                                             str(v.voice_key['voice_id'])))

    @cachetools.cached(cache=cachetools.TTLCache(maxsize=4, ttl=VOICE_LIST_CACHE_SECONDS),
                       key=lambda self, api_key: api_key)
    def _voice_list_cached(self, api_key) -> List[voice.TtsVoice_v3]:
        try:
            return self._build_voice_list(api_key)
        except Exception as e:
            logger.warning(f'KugelAudio: could not retrieve the voice list: {e}')
            return []

    def voice_list(self) -> List[voice.TtsVoice_v3]:
        api_key = (self._config.get(self.CONFIG_API_KEY) or '').strip()
        if not api_key:
            return []
        return self._voice_list_cached(api_key)

    @staticmethod
    def _raise_for_error_status(response, source_text, voice):
        status = response.status_code
        try:
            data = response.json()
            detail = data.get('error') or response.text
            error_code = data.get('error_code')
        except ValueError:
            detail = response.text
            error_code = None
        message = f'KugelAudio error (HTTP {status}{" " + error_code if error_code else ""}): {detail}'
        request_id = response.headers.get('x-request-id')
        if request_id:
            message += f' (request id: {request_id})'

        if status == 429:
            retry_after = response.headers.get('Retry-After')
            retry_after_seconds = None
            if retry_after is not None:
                try:
                    retry_after_seconds = max(1, int(float(retry_after)))
                except (TypeError, ValueError):
                    # some servers send an HTTP date instead of a number of seconds
                    pass
            if retry_after_seconds is not None:
                raise errors.RateLimitRetryAfterError(
                    source_text, voice, message, retry_after_seconds)
            raise errors.RateLimitError(source_text, voice, message)
        if status in (401, 403):
            raise errors.ServicePermissionError(source_text, voice, message)
        if status in (400, 404, 413, 422):
            # 400 validation / missing voice id, 404 unknown voice, 413 text too long
            raise errors.ServiceInputError(source_text, voice, message)
        if 500 <= status < 600:
            raise errors.ServiceGatewayError(source_text, voice, message)
        raise errors.UnknownServiceError(source_text, voice, message)

    def get_tts_audio(self, source_text, voice: voice.TtsVoice_v3, voice_options) -> bytes:
        api_key = self.get_configuration_value_mandatory(self.CONFIG_API_KEY)
        key, base_url = self.split_key(api_key)

        model = voice_options.get('model', voice.options['model']['default'])
        speed = voice_options.get('speed', voice.options['speed']['default'])
        cfg_scale = voice_options.get('cfg_scale', voice.options['cfg_scale']['default'])
        temperature = voice_options.get('temperature', voice.options['temperature']['default'])
        normalize_value = voice_options.get('normalize', voice.options['normalize']['default'])
        normalize = str(normalize_value).lower() == 'true'

        # the voice list stores the provider language in the voice key. As a fallback for
        # voices created by older versions of this service, infer it from the locale.
        language = voice.voice_key.get('language')
        if not language:
            for audio_language in voice.audio_languages:
                language = provider_language_for_audio_language(audio_language)
                if language is not None:
                    break
        if not language:
            raise errors.ServiceInputError(
                source_text, voice, 'KugelAudio: the selected voice has no language')

        payload = {
            'text': source_text,
            'voice_id': voice.voice_key['voice_id'],
            'model_id': model,
            'cfg_scale': cfg_scale,
            'temperature': temperature,
            'speed': speed,
            'normalize': normalize,
            'language': language,
            'sample_rate': OUTPUT_SAMPLE_RATE,
        }

        try:
            response = requests.post(
                f'{base_url}/v1/tts/generate',
                json=payload,
                headers=self.headers(key),
                timeout=TTS_TIMEOUT,
            )
        except requests.exceptions.Timeout as e:
            raise errors.ServiceTimeoutError(source_text, voice, str(e)) from e
        except requests.exceptions.ConnectionError as e:
            raise errors.ServiceConnectionError(source_text, voice, str(e)) from e

        if response.status_code != 200:
            self._raise_for_error_status(response, source_text, voice)

        audio_bytes = response.content
        if not audio_bytes:
            raise errors.UnknownServiceError(
                source_text, voice, 'KugelAudio returned an empty audio response')

        audio_format = response.headers.get('X-Audio-Format', PCM_AUDIO_FORMAT)
        if audio_format != PCM_AUDIO_FORMAT:
            raise errors.UnknownServiceError(
                source_text, voice, f'KugelAudio returned unexpected audio format {audio_format}')

        sample_rate = OUTPUT_SAMPLE_RATE
        try:
            sample_rate = int(float(response.headers.get('X-Sample-Rate', OUTPUT_SAMPLE_RATE)))
        except (TypeError, ValueError):
            logger.warning(f'KugelAudio: invalid X-Sample-Rate header '
                           f'{response.headers.get("X-Sample-Rate")}, using {OUTPUT_SAMPLE_RATE}')

        # the REST endpoint streams headerless PCM16; wrap it and let Anki's bundled lame
        # produce a high-quality variable-bitrate mp3 with the extreme (-V 0) preset
        wav_bytes = audio_encoding.ensure_wav(
            audio_bytes, response.headers.get('Content-Type', ''), sample_rate)
        return encode_wav_to_mp3_extreme(wav_bytes)
