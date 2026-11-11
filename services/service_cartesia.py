# Cartesia text-to-speech service for HyperTTS
#
# API reference:
# - text to speech (bytes): https://docs.cartesia.ai/api-reference/tts/bytes
# - voices: https://docs.cartesia.ai/api-reference/voices/list
# - models: https://docs.cartesia.ai/build-with-cartesia/tts-models/latest
# - audio formats: https://docs.cartesia.ai/build-with-cartesia/capability-guides/tts-output-audio-format
#
# GET  /voices?limit=100&starting_after=...  voices visible to the API key
# POST /tts/bytes                            { model_id, transcript, voice, locale/language,
#                                              normalization, generation_config, output_format }
# Auth: Authorization: Bearer <api key>
# Header: Cartesia-Version: 2026-08-14
#
# Voices have an `accents` array. Every entry in that array is an accent the voice speaks
# natively; `is_native` only marks the accent the voice was originally recorded in. The
# extension turns each accent locale into a separate HyperTTS voice, and that locale is sent
# with the request so Cartesia selects the matching accent and normalizes numbers, dates and
# units for the right language and region. A voice without accent metadata falls back to its
# deprecated `language` field, and then to English.
#
# Sonic 3.6 and newer accept the regional `locale` field. Older Sonic models use the
# older `language` field, but it accepts the same language and regional locale codes, so
# the selected accent and regional normalizer are preserved either way. Every model returns
# WAV here; the WAV is encoded with Anki's bundled LAME using the extreme preset (-V 0,
# high-quality VBR). That avoids Cartesia's maximum mp3 bitrate of 192 kbps.
#
# The request language is part of the voice identity because HyperTTS does not pass the
# selected AudioLanguage to get_tts_audio. A multilingual Cartesia voice can therefore be
# listed more than once, once per native accent.

import os
import subprocess
import tempfile
from typing import List, Optional

import aqt.sound
import aqt.utils
import cachetools
import requests

from hypertts_addon import voice
from hypertts_addon import service
from hypertts_addon import errors
from hypertts_addon import constants
from hypertts_addon import languages
from hypertts_addon import options
from hypertts_addon import logging_utils

logger = logging_utils.get_child_logger(__name__)

CARTESIA_API_URL = 'https://api.cartesia.ai'
CARTESIA_VERSION = '2026-08-14'
CARTESIA_VOICES_URL = f'{CARTESIA_API_URL}/voices'
CARTESIA_TTS_URL = f'{CARTESIA_API_URL}/tts/bytes'

# the voice list is requested when Anki starts, don't block for too long
REQUEST_TIMEOUT = 10
# a longer transcript can take a while to synthesize
TTS_TIMEOUT = 60
# the voice list is re-fetched after this delay
VOICE_LIST_CACHE_SECONDS = 600
VOICES_PAGE_SIZE = 100

# https://docs.cartesia.ai/build-with-cartesia/tts-models/latest
MODELS = ['sonic-3.6', 'sonic-3.5', 'sonic-3']
DEFAULT_MODEL = MODELS[0]

# CD-quality lossless output. The local LAME encoder receives a normal WAV file, so no
# provider-side bitrate ceiling applies.
OUTPUT_SAMPLE_RATE = 44100
OUTPUT_ENCODING = 'pcm_s16le'

# LAME's extreme preset is -V 0, a high-quality variable-bitrate setting.
LAME_PRESET_ARGS = ['-V', '0']

# Cartesia's text-to-speech languages. Sonic 3.5 and sonic-3 omit Odia and Urdu.
# https://docs.cartesia.ai/build-with-cartesia/tts-models/latest#language-support
SUPPORTED_LANGUAGES = frozenset({
    'ar', 'bg', 'bn', 'cs', 'da', 'de', 'el', 'en', 'es', 'fi', 'fr', 'gu',
    'he', 'hi', 'hr', 'hu', 'id', 'it', 'ja', 'ka', 'kn', 'ko', 'ml', 'mr',
    'ms', 'nl', 'no', 'or', 'pa', 'pl', 'pt', 'ro', 'ru', 'sk', 'sv', 'ta',
    'te', 'th', 'tl', 'tr', 'uk', 'ur', 'vi', 'zh',
})
# Odia and Urdu were added in Sonic 3.6.
OLDER_MODEL_LANGUAGES = SUPPORTED_LANGUAGES - {'or', 'ur'}

# Alternate language names mapped to the key used by DEFAULT_AUDIO_LANGUAGE_BY_BASE.
LANGUAGE_ALIASES = {
    'cmn': 'zh',
    'zho': 'zh',
    'in': 'id',
    'iw': 'he',
    'no': 'nb',
    'tl': 'fil',
}

# Some HyperTTS locales use a different provider code. The two Norwegian AudioLanguage
# values both use Cartesia's no. Cantonese (zh_HK) is not a Cartesia TTS language.
AUDIO_LANGUAGE_LOCALE_OVERRIDES = {
    languages.AudioLanguage.ar_XA: 'ar',
    languages.AudioLanguage.bn_BD: 'bn',
    languages.AudioLanguage.en_CB: 'en',
    languages.AudioLanguage.es_LA: 'es',
    languages.AudioLanguage.nb_NO: 'no-NO',
    languages.AudioLanguage.nn_NO: 'no-NO',
    languages.AudioLanguage.fil_PH: 'tl-PH',
    languages.AudioLanguage.ta_LK: 'ta',
    languages.AudioLanguage.ta_MY: 'ta',
    languages.AudioLanguage.ta_SG: 'ta',
    languages.AudioLanguage.ur_PK: 'ur',
    languages.AudioLanguage.zh_HK: None,
}

# Default locale for each base language. Exact regional tags in voice metadata take
# precedence; this is only used for voices without accents and for older saved presets.
DEFAULT_AUDIO_LANGUAGE_BY_BASE = {
    'ar': languages.AudioLanguage.ar_XA,
    'bg': languages.AudioLanguage.bg_BG,
    'bn': languages.AudioLanguage.bn_IN,
    'cs': languages.AudioLanguage.cs_CZ,
    'da': languages.AudioLanguage.da_DK,
    'de': languages.AudioLanguage.de_DE,
    'el': languages.AudioLanguage.el_GR,
    'en': languages.AudioLanguage.en_US,
    'es': languages.AudioLanguage.es_ES,
    'fi': languages.AudioLanguage.fi_FI,
    'fil': languages.AudioLanguage.fil_PH,
    'fr': languages.AudioLanguage.fr_FR,
    'gu': languages.AudioLanguage.gu_IN,
    'he': languages.AudioLanguage.he_IL,
    'hi': languages.AudioLanguage.hi_IN,
    'hr': languages.AudioLanguage.hr_HR,
    'hu': languages.AudioLanguage.hu_HU,
    'id': languages.AudioLanguage.id_ID,
    'it': languages.AudioLanguage.it_IT,
    'ja': languages.AudioLanguage.ja_JP,
    'ka': languages.AudioLanguage.ka_GE,
    'kn': languages.AudioLanguage.kn_IN,
    'ko': languages.AudioLanguage.ko_KR,
    'ml': languages.AudioLanguage.ml_IN,
    'mr': languages.AudioLanguage.mr_IN,
    'ms': languages.AudioLanguage.ms_MY,
    'nb': languages.AudioLanguage.nb_NO,
    'nl': languages.AudioLanguage.nl_NL,
    'no': languages.AudioLanguage.nb_NO,
    'or': languages.AudioLanguage.or_IN,
    'pa': languages.AudioLanguage.pa_IN,
    'pl': languages.AudioLanguage.pl_PL,
    'pt': languages.AudioLanguage.pt_BR,
    'ro': languages.AudioLanguage.ro_RO,
    'ru': languages.AudioLanguage.ru_RU,
    'sk': languages.AudioLanguage.sk_SK,
    'sv': languages.AudioLanguage.sv_SE,
    'ta': languages.AudioLanguage.ta_IN,
    'te': languages.AudioLanguage.te_IN,
    'th': languages.AudioLanguage.th_TH,
    'tl': languages.AudioLanguage.fil_PH,
    'tr': languages.AudioLanguage.tr_TR,
    'uk': languages.AudioLanguage.uk_UA,
    'ur': languages.AudioLanguage.ur_IN,
    'vi': languages.AudioLanguage.vi_VN,
    'zh': languages.AudioLanguage.zh_CN,
}

# A few BCP-47 tags don't have a matching AudioLanguage member.
AUDIO_LANGUAGE_BY_TAG = {
    'es-419': languages.AudioLanguage.es_LA,
    'zh-hant': languages.AudioLanguage.zh_TW,
}

AUDIO_LANGUAGE_BY_NAME = {
    audio_language.name.lower(): audio_language
    for audio_language in languages.AudioLanguage
}

GENDER_MAP = {
    'masculine': constants.Gender.Male,
    'feminine': constants.Gender.Female,
    'gender_neutral': constants.Gender.Any,
}

EMOTIONS = [
    'neutral', 'happy', 'excited', 'enthusiastic', 'elated', 'euphoric',
    'triumphant', 'amazed', 'surprised', 'flirtatious', 'curious', 'content',
    'peaceful', 'serene', 'calm', 'grateful', 'affectionate', 'trust',
    'sympathetic', 'anticipation', 'mysterious', 'angry', 'mad', 'outraged',
    'frustrated', 'agitated', 'threatened', 'disgusted', 'contempt', 'envious',
    'sarcastic', 'ironic', 'sad', 'dejected', 'melancholic', 'disappointed',
    'hurt', 'guilty', 'bored', 'tired', 'rejected', 'nostalgic', 'wistful',
    'apologetic', 'hesitant', 'insecure', 'confused', 'resigned', 'anxious',
    'panicked', 'alarmed', 'scared', 'proud', 'confident', 'distant', 'skeptical',
    'contemplative', 'determined',
]
AUTO_EMOTION = 'auto'

# Cartesia defaults to English when a voice has no language metadata.
FALLBACK_AUDIO_LANGUAGE = languages.AudioLanguage.en_US
FALLBACK_LOCALE = 'en-US'


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
    for candidate in candidates:
        audio_language = AUDIO_LANGUAGE_BY_TAG.get(candidate.replace('_', '-'))
        if audio_language is not None:
            return audio_language

    # A bare language code or a regional variant HyperTTS has no locale for: use the
    # language's default locale.
    base = parts[0]
    for language_name in (base, LANGUAGE_ALIASES.get(base)):
        if not language_name:
            continue
        audio_language = DEFAULT_AUDIO_LANGUAGE_BY_BASE.get(language_name)
        if audio_language is not None:
            return audio_language
        if language_name in languages.AudioLanguage.__members__:
            return languages.AudioLanguage[language_name]
    return None


def provider_locale_for_audio_language(audio_language) -> Optional[str]:
    """return the BCP-47 locale Cartesia should receive for an AudioLanguage"""
    if audio_language in AUDIO_LANGUAGE_LOCALE_OVERRIDES:
        return AUDIO_LANGUAGE_LOCALE_OVERRIDES[audio_language]
    parts = audio_language.name.split('_')
    locale = parts[0].lower()
    if len(parts) > 1 and len(parts[1]) == 2:
        locale += '-' + parts[1].upper()
    return locale


def provider_base_language(code) -> Optional[str]:
    """return the base language code for a provider language or locale tag"""
    parts = _language_tag_parts(code)
    if not parts:
        return None
    language = parts[0]
    # HyperTTS uses fil, nb and cmn; Cartesia uses tl, no and zh.
    language = {
        'fil': 'tl',
        'nb': 'no',
        'nn': 'no',
        'cmn': 'zh',
        'zho': 'zh',
        'in': 'id',
        'iw': 'he',
        'ory': 'or',
    }.get(language, language)
    return language if language in SUPPORTED_LANGUAGES else None


def to_provider_locale(code) -> Optional[str]:
    """convert a voice language tag to the locale or base code sent to Cartesia"""
    parts = _language_tag_parts(code)
    if not parts:
        return None
    # Keep the region so Cartesia can select the matching accent. Exact accent locales
    # in the voice metadata are valid Cartesia locales.
    base = provider_base_language(code)
    if base is None:
        return None
    for region in parts[1:]:
        if len(region) == 2:
            return f'{base}-{region.upper()}'
    return base


def unique_locale_variants(accents) -> list:
    """return [(AudioLanguage, provider locale)] for the accent locales of one voice"""
    variants = {}
    for accent in accents or []:
        if not isinstance(accent, dict):
            continue
        locale = accent.get('locale')
        audio_language = to_audio_language(locale)
        provider_locale = to_provider_locale(locale)
        if audio_language is None or provider_locale is None:
            logger.warning(f'Cartesia: unsupported voice accent locale {locale!r}')
            continue
        # A voice can have several accents in the same locale; one entry per locale is
        # enough because Cartesia selects the closest accent from the locale.
        variants.setdefault(audio_language, provider_locale)
    return list(variants.items())


def encode_wav_to_mp3_extreme(wav_bytes: bytes) -> bytes:
    """encode WAV audio with Anki's bundled LAME using the extreme (-V 0) preset.

    The shared audio_encoding.encode_wav_to_mp3 helper only exposes a CBR bitrate, so this
    service drives LAME directly. The invocation is otherwise identical to that helper.
    """
    wav_fh, wav_path = tempfile.mkstemp(prefix='hypertts_cartesia_', suffix='.wav')
    os.close(wav_fh)
    mp3_fh, mp3_path = tempfile.mkstemp(prefix='hypertts_cartesia_', suffix='.mp3')
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


class Cartesia(service.ServiceBase):
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
    def headers(api_key):
        return {
            'Authorization': f'Bearer {api_key}',
            'Cartesia-Version': CARTESIA_VERSION,
            'Content-Type': 'application/json',
        }

    def _fetch_voices(self, api_key) -> list:
        """all voices visible to the key, following cursor pagination"""
        result = []
        params = {'limit': VOICES_PAGE_SIZE}
        seen_cursors = set()
        while True:
            response = requests.get(
                CARTESIA_VOICES_URL,
                params=params,
                headers=self.headers(api_key),
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            items = data.get('data', []) or []
            result.extend(items)
            if not data.get('has_more') or not items:
                return result
            cursor = data.get('next_page') or items[-1].get('id')
            if not cursor or cursor in seen_cursors:
                logger.warning('Cartesia: voice pagination did not advance; returning partial list')
                return result
            seen_cursors.add(cursor)
            params = {'limit': VOICES_PAGE_SIZE, 'starting_after': cursor}

    def _voice_options(self) -> dict:
        return {
            'model': {
                'type': options.ParameterType.list.name,
                'values': MODELS,
                'default': DEFAULT_MODEL,
            },
            # generation_config.speed: the API accepts 0.6-1.5
            'speed': {
                'type': options.ParameterType.number.name,
                'min': 0.6,
                'max': 1.5,
                'default': 1.0,
            },
            # generation_config.volume: the API accepts 0.5-2.0
            'volume': {
                'type': options.ParameterType.number.name,
                'min': 0.5,
                'max': 2.0,
                'default': 1.0,
            },
            # omitted when auto; otherwise Cartesia receives the selected emotion
            'emotion': {
                'type': options.ParameterType.list.name,
                'values': [AUTO_EMOTION] + EMOTIONS,
                'default': AUTO_EMOTION,
            },
            # auto follows the request locale; off is for pre-normalized transcripts
            'normalization': {
                'type': options.ParameterType.list.name,
                'values': ['auto', 'off'],
                'default': 'auto',
            },
        }

    def _build_voice_list(self, api_key) -> List[voice.TtsVoice_v3]:
        voice_options = self._voice_options()
        result = []
        for item in self._fetch_voices(api_key):
            voice_id = item.get('id')
            if not voice_id:
                logger.warning(f'Cartesia: voice without an id: {item}')
                continue

            variants = unique_locale_variants(item.get('accents'))
            if not variants:
                # Voices with no accent metadata (for example freshly cloned voices) use
                # the deprecated language field; English is the provider default.
                language = item.get('language')
                audio_language = to_audio_language(language)
                if audio_language is None:
                    if language:
                        logger.warning(f'Cartesia: voice {voice_id} ({item.get("name")}) '
                                       f'has unsupported language {language!r}; listing it '
                                       f'as English')
                    audio_language = FALLBACK_AUDIO_LANGUAGE
                provider_locale = (provider_locale_for_audio_language(audio_language)
                                   or FALLBACK_LOCALE)
                variants = [(audio_language, provider_locale)]

            name = item.get('name') or str(voice_id)
            if item.get('is_owner'):
                name += ' (custom)'
            gender = GENDER_MAP.get(str(item.get('gender')).lower(), constants.Gender.Any)
            for audio_language, provider_locale in variants:
                result.append(voice.TtsVoice_v3(
                    name=name,
                    gender=gender,
                    audio_languages=[audio_language],
                    service=self.name,
                    # the accent locale is part of the identity: one physical voice can
                    # be listed once per native accent.
                    voice_key={'voice_id': voice_id, 'locale': provider_locale},
                    options=voice_options,
                    service_fee=self.service_fee,
                ))
        return sorted(result, key=lambda v: (v.name.lower(),
                                             v.audio_languages[0].name,
                                             str(v.voice_key['voice_id'])))

    @cachetools.cached(cache=cachetools.TTLCache(maxsize=4, ttl=VOICE_LIST_CACHE_SECONDS),
                       key=lambda self, api_key: api_key)
    def _voice_list_cached(self, api_key) -> List[voice.TtsVoice_v3]:
        try:
            return self._build_voice_list(api_key)
        except Exception as e:
            logger.warning(f'Cartesia: could not retrieve the voice list: {e}')
            return []

    def voice_list(self) -> List[voice.TtsVoice_v3]:
        api_key = (self._config.get(self.CONFIG_API_KEY) or '').strip()
        if not api_key:
            return []
        return self._voice_list_cached(api_key)

    @staticmethod
    def _raise_for_error_status(response, source_text, voice):
        status = response.status_code
        error_code = None
        try:
            data = response.json()
        except ValueError:
            data = None

        if isinstance(data, dict):
            error_code = data.get('error_code')
            title = data.get('title')
            detail = data.get('message') or title or response.text
            request_id = data.get('request_id')
        else:
            detail = response.text
            request_id = None
        if not request_id:
            request_id = response.headers.get('x-request-id')

        message = (f'Cartesia error (HTTP {status}'
                   f'{" " + error_code if error_code else ""}): {detail}')
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
        if status == 402 or error_code in ('quota_exceeded', 'plan_upgrade_required'):
            raise errors.PermanentError(source_text, voice, message)
        if status in (400, 404, 413, 422) or error_code in (
            'voice_not_found', 'model_not_found', 'language_not_supported',
            'voice_model_mismatch', 'unsupported_audio_format',
        ):
            # validation, unknown voice/model, unsupported language or text too long
            raise errors.ServiceInputError(source_text, voice, message)
        if 500 <= status < 600:
            raise errors.ServiceGatewayError(source_text, voice, message)
        if 400 <= status < 500:
            raise errors.PermanentError(source_text, voice, message)
        raise errors.UnknownServiceError(source_text, voice, message)

    @staticmethod
    def _uses_locale(model) -> bool:
        return model == 'sonic-3.6' or str(model).startswith('sonic-3.6-')

    def get_tts_audio(self, source_text, voice: voice.TtsVoice_v3, voice_options) -> bytes:
        api_key = self.get_configuration_value_mandatory(self.CONFIG_API_KEY).strip()

        model = voice_options.get('model', voice.options['model']['default'])
        speed = voice_options.get('speed', voice.options['speed']['default'])
        volume = voice_options.get('volume', voice.options['volume']['default'])
        emotion = voice_options.get('emotion', voice.options['emotion']['default'])
        normalization = voice_options.get(
            'normalization', voice.options['normalization']['default'])

        # the voice list stores the provider locale in the voice key. As a fallback for
        # voices created by older versions of this service, infer it from the locale.
        locale = voice.voice_key.get('locale')
        if not locale:
            locale = None
            for audio_language in voice.audio_languages:
                locale = provider_locale_for_audio_language(audio_language)
                if locale:
                    break
        if not locale:
            raise errors.ServiceInputError(
                source_text, voice, 'Cartesia: the selected voice has no locale')

        voice_id = voice.voice_key.get('voice_id')
        if not voice_id:
            raise errors.ServiceInputError(
                source_text, voice, 'Cartesia: the selected voice has no voice id')

        generation_config = {
            'speed': speed,
            'volume': volume,
        }
        if emotion and emotion != AUTO_EMOTION:
            generation_config['emotion'] = emotion

        payload = {
            'model_id': model,
            'transcript': source_text,
            'voice': voice_id,
            'normalization': normalization,
            'output_format': {
                'container': 'wav',
                'encoding': OUTPUT_ENCODING,
                'sample_rate': OUTPUT_SAMPLE_RATE,
            },
            'generation_config': generation_config,
        }
        if self._uses_locale(model):
            payload['locale'] = locale
        else:
            # the locale field requires Sonic 3.6 or newer; the older language field
            # accepts the same language and regional locale codes.
            base_language = provider_base_language(locale)
            if not base_language:
                raise errors.ServiceInputError(
                    source_text, voice,
                    f'Cartesia: {model} does not support language {locale!r}')
            if base_language not in OLDER_MODEL_LANGUAGES:
                raise errors.ServiceInputError(
                    source_text, voice,
                    f'Cartesia: {model} does not support language {locale!r}; '
                    f'choose sonic-3.6 for Odia or Urdu')
            payload['language'] = locale

        headers = self.headers(api_key)
        headers['Accept'] = 'audio/wav'
        try:
            response = requests.post(
                CARTESIA_TTS_URL,
                json=payload,
                headers=headers,
                timeout=TTS_TIMEOUT,
            )
        except requests.exceptions.Timeout as e:
            raise errors.ServiceTimeoutError(source_text, voice, str(e)) from e
        except requests.exceptions.ConnectionError as e:
            raise errors.ServiceConnectionError(source_text, voice, str(e)) from e
        except requests.exceptions.RequestException as e:
            raise errors.UnknownServiceError(source_text, voice, str(e)) from e

        if response.status_code != 200:
            self._raise_for_error_status(response, source_text, voice)

        audio_bytes = response.content
        if not audio_bytes:
            raise errors.UnknownServiceError(
                source_text, voice, 'Cartesia returned an empty audio response')
        if not audio_bytes.startswith(b'RIFF'):
            raise errors.UnknownServiceError(
                source_text, voice,
                f'Cartesia returned unexpected audio data (Content-Type: '
                f'{response.headers.get("Content-Type", "")})')

        return encode_wav_to_mp3_extreme(audio_bytes)
