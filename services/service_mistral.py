# Mistral AI Voxtral text-to-speech service for HyperTTS
#
# API reference:
# - speech: https://docs.mistral.ai/studio/audio/text-to-speech/generate-speech
# - voices: https://docs.mistral.ai/studio/audio/text-to-speech/voices
# - models: https://docs.mistral.ai/api/endpoint/models
#
# POST https://api.mistral.ai/v1/audio/speech
# Body: { model, input, voice_id, response_format, expressiveness? }
# Response: JSON { "audio_data": "<base64 encoded audio>" }
# Auth: Bearer token in the Authorization header.
#
# Voxtral TTS 3 is the current speech model (voxtral-mini-tts-3-0). Its preset voices use
# IDs such as voice_481 (Heidi, German). The "voxtral-mini-tts-latest" alias still points at
# Voxtral 2 in some accounts, which rejects those voices with "voice is not supported for
# speech v1". This service therefore uses the explicit Voxtral 3 model and upgrades saved
# presets which still contain the old alias.
#
# Mistral's pcm response is raw float32 little-endian mono samples at 24 kHz. For mp3 we
# request pcm, convert it to 16-bit PCM, and encode it locally with LAME's extreme preset
# (-V 0, high-quality VBR), just like the KugelAudio service. The ogg_opus option uses the
# provider's Ogg Opus response directly.
#
# Everything is retrieved from the Mistral API with the configured API key, so that new
# voices, Voxtral 3 model versions and languages show up without updating this file:
# - voices: GET /v2/audio/voices returns the preset voices provided by Mistral and the user's
#   custom voices (created in Mistral AI Studio or with POST /v1/audio/voices). Custom voices
#   show up with a "(custom)" suffix. The deprecated /v1/audio/voices endpoint is used as a
#   fallback if /v2 is unavailable.
# - models: GET /v1/models, keeping the Voxtral 3 speech models. The "latest" alias is not
#   listed because it can still resolve to Voxtral 2.
# - languages: each voice has its own native language and accent. Voices are listed under
#   the language tags returned by the API; there is no language request field for speech
#   generation, because the selected voice determines the accent. A custom voice without
#   language metadata is listed under the documented preset languages.

import array
import base64
import os
import subprocess
import sys
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

MISTRAL_SPEECH_URL = 'https://api.mistral.ai/v1/audio/speech'
MISTRAL_VOICES_URL = 'https://api.mistral.ai/v2/audio/voices'
MISTRAL_VOICES_V1_URL = 'https://api.mistral.ai/v1/audio/voices'
MISTRAL_MODELS_URL = 'https://api.mistral.ai/v1/models'

# the voice list is requested when Anki starts, don't block for too long
REQUEST_TIMEOUT = 10
# the voice list is re-fetched after this delay
VOICE_LIST_CACHE_SECONDS = 600
VOICES_PAGE_SIZE = 100

# explicit model name for Voxtral TTS 3. "voxtral-mini-tts-latest" is deliberately not used:
# it still resolves to Voxtral 2 in some accounts and then rejects Voxtral 3 voices.
DEFAULT_MODEL = 'voxtral-mini-tts-3-0'
SPEECH_MODEL_PREFIX = 'voxtral-mini-tts-3'
MODEL_EXCLUDE_PATTERNS = ['realtime', 'solutions', 'latest']

# Mistral's expressiveness is the flow-matching classifier-free guidance scale. The model's
# reference inference setting is 1.2; higher values trade voice similarity and stability for
# a stronger delivery.
DEFAULT_EXPRESSIVENESS = 1.2
MIN_EXPRESSIVENESS = 1.0
MAX_EXPRESSIVENESS = 5.0

# Mistral's pcm response is raw float32 LE samples, mono at 24 kHz. MP3 is encoded locally
# from that lossless response; Opus is returned by Mistral already Ogg-wrapped.
AUDIO_FORMAT_MAP = {
    options.AudioFormat.mp3: 'pcm',
    options.AudioFormat.ogg_opus: 'opus',
}

MISTRAL_PCM_SAMPLE_RATE = 24000

# LAME's extreme preset is -V 0, a high-quality variable-bitrate setting.
LAME_PRESET_ARGS = ['-V', '0']

# Languages with Voxtral TTS 3 preset voices which HyperTTS knows about. The API returns
# the native languages for each voice, so this list is only used for custom voices which
# have no language metadata.
# https://docs.mistral.ai/studio/audio/specs-and-limits/languages
DOCUMENTED_LANGUAGES = [
    'ar', 'ca', 'zh', 'nl', 'en_us', 'en_gb', 'fr', 'de', 'hi', 'hu', 'it', 'ja',
    'ko', 'no', 'pl', 'pt_pt', 'pt_br', 'ro', 'ru', 'es', 'tr', 'uk', 'vi',
]

# language codes which don't match a HyperTTS language name
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

AUDIO_LANGUAGE_BY_NAME = {
    audio_language.name.lower(): audio_language
    for audio_language in languages.AudioLanguage
}

GENDER_MAP = {
    'male': constants.Gender.Male,
    'female': constants.Gender.Female,
}


def _language_tag_parts(code) -> list:
    """split a BCP-47 language tag ("fr", "en_us", "zh-Hant-TW") into lowercase parts"""
    normalized = str(code or '').strip().replace('_', '-').lower()
    return [part for part in normalized.split('-') if part]


def to_audio_language(code) -> Optional[languages.AudioLanguage]:
    """convert a language code returned by the voices API ("fr", "en_us", "pt-BR") to an
    AudioLanguage. returns None for a language HyperTTS doesn't know about."""
    parts = _language_tag_parts(code)
    if not parts:
        return None

    # Prefer the complete tag, then the language+region form, then the region alone.
    # This handles tags such as en-GB-WLS and zh-Hant-TW as well as normal two-part
    # locales. The candidate names are lower-case keys of AudioLanguage.
    candidates = ['_'.join(parts)]
    if len(parts) >= 2:
        candidates.append(f'{parts[0]}_{parts[1]}')
        candidates.append(f'{parts[0]}_{parts[-1]}')
    for candidate in candidates:
        audio_language = AUDIO_LANGUAGE_BY_NAME.get(candidate)
        if audio_language is not None:
            return audio_language

    # "fr", or a locale HyperTTS doesn't have: use the default locale of the language.
    # aliases such as "pt" point directly at one of several regional variants.
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


def unique_audio_languages(codes) -> List[languages.AudioLanguage]:
    if isinstance(codes, str):
        codes = [codes]
    result = []
    for code in codes or []:
        if code is None:
            continue
        audio_language = to_audio_language(code)
        if audio_language is None:
            logger.warning(f'Mistral: unknown language code {code}')
        elif audio_language not in result:
            result.append(audio_language)
    return result


def float32_pcm_to_pcm16(pcm_bytes: bytes) -> bytes:
    """convert Mistral's raw float32 LE samples to signed 16-bit PCM"""
    if len(pcm_bytes) % 4 != 0:
        raise ValueError(f'float32 PCM byte count {len(pcm_bytes)} is not a multiple of 4')

    samples = array.array('f')
    samples.frombytes(pcm_bytes)
    if sys.byteorder == 'big':
        samples.byteswap()

    pcm16 = array.array('h')
    for sample in samples:
        if sample != sample:  # NaN
            sample = 0.0
        elif sample > 1.0:
            sample = 1.0
        elif sample < -1.0:
            sample = -1.0
        pcm16.append(int(round(sample * 32767.0)))
    if sys.byteorder == 'big':
        pcm16.byteswap()
    return pcm16.tobytes()


def encode_wav_to_mp3_extreme(wav_bytes: bytes) -> bytes:
    """encode WAV audio with Anki's bundled LAME using the extreme (-V 0) preset.

    The shared audio_encoding.encode_wav_to_mp3 helper only exposes a CBR bitrate, so this
    service drives LAME directly. The invocation is otherwise identical to that helper.
    """
    wav_fh, wav_path = tempfile.mkstemp(prefix='hypertts_mistral_', suffix='.wav')
    os.close(wav_fh)
    mp3_fh, mp3_path = tempfile.mkstemp(prefix='hypertts_mistral_', suffix='.mp3')
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


def is_speech_model(model) -> bool:
    model_id = model.get('id', '')
    return ((model.get('capabilities') or {}).get('audio_speech', False)
            and model_id.startswith(SPEECH_MODEL_PREFIX)
            and not any(pattern in model_id for pattern in MODEL_EXCLUDE_PATTERNS)
            and model.get('deprecation') is None)


class Mistral(service.ServiceBase):
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

    def _get(self, api_key, url, params=None):
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT,
                                headers={'Authorization': f'Bearer {api_key}'})
        response.raise_for_status()
        return response.json()

    def _fetch_voices_v2(self, api_key) -> list:
        """preset and custom voices, following the cursor pagination of /v2/audio/voices"""
        result = []
        page_token = None
        seen_tokens = set()
        while True:
            params = {'page_size': VOICES_PAGE_SIZE, 'type': 'all'}
            if page_token is not None:
                params['page_token'] = page_token
            data = self._get(api_key, MISTRAL_VOICES_URL, params=params)
            # the REST endpoint returns data/next_page_token at the top level; accept the
            # nested "result" shape too, as used by the generated SDK.
            page = data.get('result') or data
            items = page.get('data') or page.get('items') or []
            result.extend(items)
            page_token = page.get('next_page_token')
            if not page_token or page_token in seen_tokens:
                return result
            seen_tokens.add(page_token)

    def _fetch_voices_v1(self, api_key) -> list:
        """fallback for accounts where /v2/audio/voices is not available"""
        result = []
        offset = 0
        while True:
            data = self._get(api_key, MISTRAL_VOICES_V1_URL,
                             params={'limit': VOICES_PAGE_SIZE, 'offset': offset})
            items = data.get('items', [])
            result.extend(items)
            offset += len(items)
            if len(items) == 0 or offset >= data.get('total', 0):
                return result

    def _fetch_voices(self, api_key) -> list:
        try:
            return self._fetch_voices_v2(api_key)
        except Exception as e:
            logger.warning(f'Mistral: could not retrieve voices from /v2: {e}; '
                           f'falling back to /v1')
            return self._fetch_voices_v1(api_key)

    def _fetch_models(self, api_key) -> List[str]:
        models = set()
        for model in self._get(api_key, MISTRAL_MODELS_URL).get('data', []):
            # keep the canonical model name, not the aliases
            model_id = model.get('id')
            if model_id and is_speech_model(model) and model_id == model.get('name'):
                models.add(model_id)
        # always offer the explicit Voxtral 3 model, even if the model list is incomplete
        models.add(DEFAULT_MODEL)
        return [DEFAULT_MODEL] + sorted(models - {DEFAULT_MODEL}, reverse=True)

    def _voice_options(self, models: List[str]) -> dict:
        return {
            'model': {
                'type': options.ParameterType.list.name,
                'values': models,
                'default': models[0],
            },
            options.AUDIO_FORMAT_PARAMETER: {
                'type': options.ParameterType.list.name,
                'values': [audio_format.name for audio_format in AUDIO_FORMAT_MAP],
                'default': options.AudioFormat.mp3.name,
            },
            'expressiveness': {
                'type': options.ParameterType.number.name,
                'min': MIN_EXPRESSIVENESS,
                'max': MAX_EXPRESSIVENESS,
                'default': DEFAULT_EXPRESSIVENESS,
            },
        }

    def _build_voice_list(self, api_key) -> List[voice.TtsVoice_v3]:
        voice_items = self._fetch_voices(api_key)
        try:
            models = self._fetch_models(api_key)
        except Exception as e:
            logger.warning(f'Mistral: could not retrieve the model list: {e}')
            models = []
        voice_options = self._voice_options(models or [DEFAULT_MODEL])

        # all languages known to this service, including languages only found on custom
        # voices. Used only when the API doesn't tag a voice with any language.
        all_languages = unique_audio_languages(DOCUMENTED_LANGUAGES)
        for item in voice_items:
            for audio_language in unique_audio_languages(item.get('languages')):
                if audio_language not in all_languages:
                    all_languages.append(audio_language)

        result = []
        for item in voice_items:
            custom = item.get('type') == 'custom'
            name = item.get('name') or item['id']
            if custom:
                name = f'{name} (custom)'

            # a voice's accent comes from its own language, so list it only under the
            # languages it advertises. A voice in the wrong language would read the text
            # with its native accent; the speech endpoint has no accent override.
            native_languages = unique_audio_languages(item.get('languages'))
            if not native_languages:
                # custom voices created without language metadata: keep them selectable
                native_languages = list(all_languages)

            result.append(voice.TtsVoice_v3(
                name=name,
                gender=GENDER_MAP.get(str(item.get('gender')).lower(), constants.Gender.Any),
                audio_languages=native_languages,
                service=self.name,
                # preset voices are identified by their slug (e.g. fr_marie_neutral or
                # voice_481) which, unlike their id, is stable and readable. custom voices
                # only have an id.
                voice_key={'voice_id': item['id'] if custom else (item.get('slug') or item['id'])},
                options=voice_options,
                service_fee=self.service_fee,
            ))
        return sorted(result, key=lambda v: (v.name.endswith('(custom)'), v.name))

    @cachetools.cached(cache=cachetools.TTLCache(maxsize=4, ttl=VOICE_LIST_CACHE_SECONDS),
                       key=lambda self, api_key: api_key)
    def _voice_list_cached(self, api_key) -> List[voice.TtsVoice_v3]:
        try:
            return self._build_voice_list(api_key)
        except Exception as e:
            logger.warning(f'Mistral: could not retrieve the voice list: {e}')
            return []

    def voice_list(self) -> List[voice.TtsVoice_v3]:
        api_key = self._config.get(self.CONFIG_API_KEY)
        if not api_key:
            return []
        return self._voice_list_cached(api_key)

    def get_tts_audio(self, source_text, voice: voice.TtsVoice_v3, voice_options) -> bytes:
        api_key = self.get_configuration_value_mandatory(self.CONFIG_API_KEY)

        voice_id = voice.voice_key['voice_id']
        model = str(voice_options.get(
            'model', voice.options['model']['default']) or '').strip()

        # Saved presets may still contain "voxtral-mini-tts-latest" or an old Voxtral 2
        # model, both of which can reject Voxtral 3 voices. This service only offers Voxtral
        # 3 models, and Voxtral 3 still accepts the Voxtral 2 presets, so always use the
        # explicit current model. This makes old presets work without being recreated.
        if not model.startswith(SPEECH_MODEL_PREFIX):
            model = DEFAULT_MODEL

        audio_format_str = voice_options.get(
            options.AUDIO_FORMAT_PARAMETER, options.AudioFormat.mp3.name)
        audio_format = options.AudioFormat[audio_format_str]
        if audio_format not in AUDIO_FORMAT_MAP:
            raise errors.ServiceInputError(
                source_text, voice, f'Mistral does not support audio format {audio_format.name}')

        payload = {
            'model': model,
            'input': source_text,
            'voice_id': voice_id,
            'response_format': AUDIO_FORMAT_MAP[audio_format],
        }

        expressiveness = voice_options.get('expressiveness', DEFAULT_EXPRESSIVENESS)
        try:
            expressiveness = float(expressiveness)
        except (TypeError, ValueError) as e:
            raise errors.ServiceInputError(
                source_text, voice,
                f'Mistral: invalid expressiveness {expressiveness!r}') from e
        if not MIN_EXPRESSIVENESS <= expressiveness <= MAX_EXPRESSIVENESS:
            raise errors.ServiceInputError(
                source_text, voice,
                f'Mistral: expressiveness must be between '
                f'{MIN_EXPRESSIVENESS} and {MAX_EXPRESSIVENESS}')
        payload['expressiveness'] = expressiveness

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }

        try:
            response = requests.post(
                MISTRAL_SPEECH_URL, json=payload, headers=headers, timeout=60)
        except requests.exceptions.Timeout as e:
            raise errors.ServiceTimeoutError(source_text, voice, str(e)) from e
        except requests.exceptions.ConnectionError as e:
            raise errors.ServiceConnectionError(source_text, voice, str(e)) from e

        status = response.status_code
        if status != 200:
            message = f'Mistral error: HTTP {status}: {response.text}'
            # 403 is also returned when the text is rejected by content moderation
            if status in (401, 403):
                raise errors.ServicePermissionError(source_text, voice, message)
            if status == 429:
                retry_after = response.headers.get('Retry-After')
                if retry_after is not None and retry_after.isdigit():
                    raise errors.RateLimitRetryAfterError(
                        source_text, voice, message, int(retry_after))
                raise errors.RateLimitError(source_text, voice, message)
            # 400: invalid model / arguments, 404: voice not found, 422: validation error
            if status in (400, 404, 422):
                raise errors.ServiceInputError(source_text, voice, message)
            if status == 502:
                raise errors.ServiceGatewayError(source_text, voice, message)
            raise errors.UnknownServiceError(source_text, voice, message)

        try:
            audio_data = base64.b64decode(response.json()['audio_data'])
        except (ValueError, KeyError, TypeError) as e:
            raise errors.UnknownServiceError(
                source_text, voice, f'Mistral: unexpected response: {e}') from e

        if AUDIO_FORMAT_MAP[audio_format] != 'pcm':
            return audio_data

        try:
            pcm16 = float32_pcm_to_pcm16(audio_data)
        except ValueError as e:
            raise errors.UnknownServiceError(
                source_text, voice, f'Mistral: invalid pcm response: {e}') from e
        wav_bytes = audio_encoding.wrap_pcm_in_wav(pcm16, MISTRAL_PCM_SAMPLE_RATE)
        return encode_wav_to_mp3_extreme(wav_bytes)
