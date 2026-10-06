# Mistral AI Voxtral text-to-speech service for HyperTTS
#
# API reference:
# - speech: https://docs.mistral.ai/api/endpoint/audio/speech
# - voices: https://docs.mistral.ai/api/endpoint/audio/voices
# - models: https://docs.mistral.ai/api/endpoint/models
#
# POST https://api.mistral.ai/v1/audio/speech
# Body: { model, input, voice_id, response_format }
# Response: JSON { "audio_data": "<base64 encoded audio>" }
# Auth: Bearer token in the Authorization header.
#
# Everything is retrieved from the Mistral API with the configured API key, so that new
# voices, models and languages show up without updating this file:
# - voices: GET /v1/audio/voices returns the preset voices provided by Mistral and the user's
#   custom voices (created in Mistral AI Studio or with POST /v1/audio/voices). Custom voices
#   show up with a "(custom)" suffix.
# - models: GET /v1/models, keeping the Voxtral models which can generate speech.
# - languages: Voxtral supports cross-lingual speech, every voice can speak every supported
#   language. The API doesn't list the languages a model supports, so the documented ones are
#   listed below, and any language a voice is tagged with is added to them. Each voice is listed
#   under all of them, starting with its own languages.

import base64
import requests
import cachetools
from typing import List, Optional

from hypertts_addon import voice
from hypertts_addon import service
from hypertts_addon import errors
from hypertts_addon import constants
from hypertts_addon import languages
from hypertts_addon import options
from hypertts_addon import logging_utils

logger = logging_utils.get_child_logger(__name__)

MISTRAL_SPEECH_URL = 'https://api.mistral.ai/v1/audio/speech'
MISTRAL_VOICES_URL = 'https://api.mistral.ai/v1/audio/voices'
MISTRAL_MODELS_URL = 'https://api.mistral.ai/v1/models'

# the voice list is requested when Anki starts, don't block for too long
REQUEST_TIMEOUT = 10
# the voice list is re-fetched after this delay
VOICE_LIST_CACHE_SECONDS = 600
VOICES_PAGE_SIZE = 100

# alias of the most recent stable model, maintained by Mistral. it's the default model, and the
# only one listed if the model list can't be retrieved
DEFAULT_MODEL = 'voxtral-mini-tts-latest'
# Mistral also exposes customer specific speech models, only list the generally available ones
MODEL_PREFIX = 'voxtral-mini-tts-'
MODEL_EXCLUDE_PATTERNS = ['solutions']

# Mistral returns Ogg-wrapped Opus for response_format=opus
AUDIO_FORMAT_MAP = {
    options.AudioFormat.mp3: 'mp3',
    options.AudioFormat.ogg_opus: 'opus',
}

# languages documented as supported by Voxtral TTS, extended with the languages of the voices
# returned by the API. https://docs.mistral.ai/capabilities/audio/text_to_speech
DOCUMENTED_LANGUAGES = ['en_us', 'en_gb', 'fr', 'es', 'de', 'it', 'pt_pt', 'pt_br', 'nl', 'hi', 'ar']

# language codes which don't match a HyperTTS language name
LANGUAGE_ALIASES = {
    'pt': 'pt_pt',
    'zh': 'zh_cn',
}

GENDER_MAP = {
    'male': constants.Gender.Male,
    'female': constants.Gender.Female,
}


def to_audio_language(code) -> Optional[languages.AudioLanguage]:
    """convert a language code returned by the voices API ("fr", "en_us", "pt-BR") to an
    AudioLanguage. returns None for a language HyperTTS doesn't know about."""
    code = str(code).strip().replace('-', '_')
    parts = code.split('_')
    if len(parts) == 2:
        try:
            return languages.AudioLanguage[f'{parts[0].lower()}_{parts[1].upper()}']
        except KeyError:
            pass
    # "fr", or a locale HyperTTS doesn't have: use the default locale of the language
    for language_name in [code.lower(), parts[0].lower(), LANGUAGE_ALIASES.get(parts[0].lower())]:
        if language_name in languages.Language.__members__:
            return languages.AudioLanguageDefaults.get(languages.Language[language_name])
    return None


def unique_audio_languages(codes) -> List[languages.AudioLanguage]:
    result = []
    for code in codes or []:
        audio_language = to_audio_language(code)
        if audio_language is None:
            logger.warning(f'Mistral: unknown language code {code}')
        elif audio_language not in result:
            result.append(audio_language)
    return result


def is_speech_model(model) -> bool:
    model_id = model.get('id', '')
    return (model.get('capabilities', {}).get('audio_speech', False)
            and model_id.startswith(MODEL_PREFIX)
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

    def _fetch_voices(self, api_key) -> list:
        """preset and custom voices, following pagination"""
        result = []
        offset = 0
        while True:
            data = self._get(api_key, MISTRAL_VOICES_URL,
                             params={'limit': VOICES_PAGE_SIZE, 'offset': offset})
            items = data.get('items', [])
            result.extend(items)
            offset += len(items)
            if len(items) == 0 or offset >= data.get('total', 0):
                return result

    def _fetch_models(self, api_key) -> List[str]:
        # each alias is listed as a separate model (voxtral-mini-tts-3 / voxtral-mini-tts-3-0),
        # keep the canonical name, plus the "latest" alias maintained by Mistral, used by default
        models = set()
        for model in self._get(api_key, MISTRAL_MODELS_URL).get('data', []):
            if is_speech_model(model) and (model['id'] == model.get('name') or model['id'] == DEFAULT_MODEL):
                models.add(model['id'])
        others = sorted(models - {DEFAULT_MODEL}, reverse=True)
        return ([DEFAULT_MODEL] if DEFAULT_MODEL in models else []) + others

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
        }

    def _build_voice_list(self, api_key) -> List[voice.TtsVoice_v3]:
        voice_items = self._fetch_voices(api_key)
        try:
            models = self._fetch_models(api_key)
        except Exception as e:
            logger.warning(f'Mistral: could not retrieve the model list: {e}')
            models = []
        voice_options = self._voice_options(models or [DEFAULT_MODEL])

        # every voice speaks every language, also add the languages Mistral tagged voices with
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
            native_languages = unique_audio_languages(item.get('languages'))
            result.append(voice.TtsVoice_v3(
                name=name,
                gender=GENDER_MAP.get(str(item.get('gender')).lower(), constants.Gender.Any),
                audio_languages=native_languages + [l for l in all_languages if l not in native_languages],
                service=self.name,
                # preset voices are identified by their slug (e.g. fr_marie_neutral) which, unlike
                # their id, is stable and readable. custom voices only have an id.
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

        model = voice_options.get('model', voice.options['model']['default'])
        audio_format_str = voice_options.get(
            options.AUDIO_FORMAT_PARAMETER, options.AudioFormat.mp3.name)
        audio_format = options.AudioFormat[audio_format_str]
        if audio_format not in AUDIO_FORMAT_MAP:
            raise errors.ServiceInputError(
                source_text, voice, f'Mistral does not support audio format {audio_format.name}')

        payload = {
            'model': model,
            'input': source_text,
            'voice_id': voice.voice_key['voice_id'],
            'response_format': AUDIO_FORMAT_MAP[audio_format],
        }
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
            return base64.b64decode(response.json()['audio_data'])
        except (ValueError, KeyError, TypeError) as e:
            raise errors.UnknownServiceError(
                source_text, voice, f'Mistral: unexpected response: {e}') from e
