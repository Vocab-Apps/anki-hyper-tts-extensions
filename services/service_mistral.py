# Mistral AI Voxtral text-to-speech service for HyperTTS
#
# API reference:
# - speech: https://docs.mistral.ai/api/endpoint/audio/speech
# - voices: https://docs.mistral.ai/api/endpoint/audio/voices
#
# POST https://api.mistral.ai/v1/audio/speech
# Body: { model, input, voice_id, response_format }
# Response: JSON { "audio_data": "<base64 encoded audio>" }
# Auth: Bearer token in the Authorization header.
#
# Voices:
# - the preset voices provided by Mistral are listed below.
# - custom voices (created in Mistral AI Studio or with POST /v1/audio/voices) are fetched
#   from the user's account using the configured API key, and show up in the voice list
#   with a "(custom)" suffix. They are identified by their voice id.
#
# Voxtral supports cross-lingual speech: every voice can speak any of the supported
# languages, so each voice is listed under all of them, starting with its native language.

import base64
import time
import requests
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

DEFAULT_MODEL = 'voxtral-mini-tts-2603'
MODELS = [DEFAULT_MODEL, 'voxtral-mini-tts-latest']

# the voice list is requested when Anki starts, don't block for too long
VOICES_REQUEST_TIMEOUT = 10
# custom voices are re-fetched after this delay, so that newly created voices show up
CUSTOM_VOICES_CACHE_SECONDS = 600
VOICES_PAGE_SIZE = 100

# Mistral returns Ogg-wrapped Opus for response_format=opus
AUDIO_FORMAT_MAP = {
    options.AudioFormat.mp3: 'mp3',
    options.AudioFormat.ogg_opus: 'opus',
}

VOICE_OPTIONS = {
    'model': {
        'type': options.ParameterType.list.name,
        'values': MODELS,
        'default': DEFAULT_MODEL,
    },
    options.AUDIO_FORMAT_PARAMETER: {
        'type': options.ParameterType.list.name,
        'values': [audio_format.name for audio_format in AUDIO_FORMAT_MAP],
        'default': options.AudioFormat.mp3.name,
    },
}

SUPPORTED_AUDIO_LANGUAGES = [
    languages.AudioLanguage.en_US,
    languages.AudioLanguage.en_GB,
    languages.AudioLanguage.fr_FR,
    languages.AudioLanguage.es_ES,
    languages.AudioLanguage.de_DE,
    languages.AudioLanguage.it_IT,
    languages.AudioLanguage.pt_PT,
    languages.AudioLanguage.pt_BR,
    languages.AudioLanguage.nl_NL,
    languages.AudioLanguage.hi_IN,
    languages.AudioLanguage.ar_XA,
]

# language codes returned by the voices API: "en", "fr", or "en_us", "fr_fr", ...
LANGUAGE_CODE_MAP = {
    'en': languages.AudioLanguage.en_US,
    'en_us': languages.AudioLanguage.en_US,
    'en_gb': languages.AudioLanguage.en_GB,
    'fr': languages.AudioLanguage.fr_FR,
    'fr_fr': languages.AudioLanguage.fr_FR,
    'es': languages.AudioLanguage.es_ES,
    'es_es': languages.AudioLanguage.es_ES,
    'de': languages.AudioLanguage.de_DE,
    'de_de': languages.AudioLanguage.de_DE,
    'it': languages.AudioLanguage.it_IT,
    'it_it': languages.AudioLanguage.it_IT,
    'pt': languages.AudioLanguage.pt_PT,
    'pt_pt': languages.AudioLanguage.pt_PT,
    'pt_br': languages.AudioLanguage.pt_BR,
    'nl': languages.AudioLanguage.nl_NL,
    'nl_nl': languages.AudioLanguage.nl_NL,
    'hi': languages.AudioLanguage.hi_IN,
    'hi_in': languages.AudioLanguage.hi_IN,
    'ar': languages.AudioLanguage.ar_XA,
}

GENDER_MAP = {
    'male': constants.Gender.Male,
    'female': constants.Gender.Female,
}

# (voice_id, display name, gender, native language)
PRESET_VOICES = [
    ('en_paul_neutral', 'Paul - Neutral', 'male', 'en_us'),
    ('en_paul_happy', 'Paul - Happy', 'male', 'en_us'),
    ('en_paul_cheerful', 'Paul - Cheerful', 'male', 'en_us'),
    ('en_paul_confident', 'Paul - Confident', 'male', 'en_us'),
    ('en_paul_excited', 'Paul - Excited', 'male', 'en_us'),
    ('en_paul_sad', 'Paul - Sad', 'male', 'en_us'),
    ('en_paul_frustrated', 'Paul - Frustrated', 'male', 'en_us'),
    ('en_paul_angry', 'Paul - Angry', 'male', 'en_us'),
    ('gb_oliver_neutral', 'Oliver - Neutral', 'male', 'en_gb'),
    ('gb_oliver_cheerful', 'Oliver - Cheerful', 'male', 'en_gb'),
    ('gb_oliver_confident', 'Oliver - Confident', 'male', 'en_gb'),
    ('gb_oliver_curious', 'Oliver - Curious', 'male', 'en_gb'),
    ('gb_oliver_excited', 'Oliver - Excited', 'male', 'en_gb'),
    ('gb_oliver_sad', 'Oliver - Sad', 'male', 'en_gb'),
    ('gb_oliver_angry', 'Oliver - Angry', 'male', 'en_gb'),
    ('gb_jane_neutral', 'Jane - Neutral', 'female', 'en_gb'),
    ('gb_jane_confident', 'Jane - Confident', 'female', 'en_gb'),
    ('gb_jane_curious', 'Jane - Curious', 'female', 'en_gb'),
    ('gb_jane_confused', 'Jane - Confused', 'female', 'en_gb'),
    ('gb_jane_sarcasm', 'Jane - Sarcasm', 'female', 'en_gb'),
    ('gb_jane_sad', 'Jane - Sad', 'female', 'en_gb'),
    ('gb_jane_shameful', 'Jane - Shameful', 'female', 'en_gb'),
    ('gb_jane_jealousy', 'Jane - Jealousy', 'female', 'en_gb'),
    ('gb_jane_frustrated', 'Jane - Frustrated', 'female', 'en_gb'),
    ('fr_marie_neutral', 'Marie - Neutral', 'female', 'fr_fr'),
    ('fr_marie_happy', 'Marie - Happy', 'female', 'fr_fr'),
    ('fr_marie_curious', 'Marie - Curious', 'female', 'fr_fr'),
    ('fr_marie_excited', 'Marie - Excited', 'female', 'fr_fr'),
    ('fr_marie_sad', 'Marie - Sad', 'female', 'fr_fr'),
    ('fr_marie_angry', 'Marie - Angry', 'female', 'fr_fr'),
]


def _audio_languages(language_codes) -> List[languages.AudioLanguage]:
    """the voice's own languages first, followed by all the other supported languages"""
    native = []
    for code in language_codes or []:
        audio_language = LANGUAGE_CODE_MAP.get(str(code).lower().replace('-', '_'))
        if audio_language is not None and audio_language not in native:
            native.append(audio_language)
    return native + [l for l in SUPPORTED_AUDIO_LANGUAGES if l not in native]


class Mistral(service.ServiceBase):
    CONFIG_API_KEY = 'api_key'

    def __init__(self):
        service.ServiceBase.__init__(self)
        self._custom_voices_cache_key: Optional[str] = None
        self._custom_voices_cache_time = 0.0
        self._custom_voices: List[voice.TtsVoice_v3] = []

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

    def _build_voice(self, name, voice_id, gender, language_codes) -> voice.TtsVoice_v3:
        return voice.TtsVoice_v3(
            name=name,
            gender=GENDER_MAP.get(str(gender).lower(), constants.Gender.Any),
            audio_languages=_audio_languages(language_codes),
            service=self.name,
            voice_key={'voice_id': voice_id},
            options=VOICE_OPTIONS,
            service_fee=self.service_fee,
        )

    def _preset_voices(self) -> List[voice.TtsVoice_v3]:
        return [self._build_voice(name, voice_id, gender, [language])
                for voice_id, name, gender, language in PRESET_VOICES]

    def _fetch_custom_voices(self, api_key) -> List[voice.TtsVoice_v3]:
        headers = {'Authorization': f'Bearer {api_key}'}
        result = []
        offset = 0
        while True:
            response = requests.get(
                MISTRAL_VOICES_URL,
                params={'type': 'custom', 'limit': VOICES_PAGE_SIZE, 'offset': offset},
                headers=headers,
                timeout=VOICES_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            items = data.get('items', [])
            for item in items:
                voice_name = item.get('name') or item['id']
                result.append(self._build_voice(
                    f'{voice_name} (custom)', item['id'], item.get('gender'), item.get('languages')))
            offset += len(items)
            if len(items) == 0 or offset >= data.get('total', 0):
                return result

    def _custom_voice_list(self) -> List[voice.TtsVoice_v3]:
        api_key = self._config.get(self.CONFIG_API_KEY)
        if not api_key:
            return []
        cache_expired = time.monotonic() - self._custom_voices_cache_time > CUSTOM_VOICES_CACHE_SECONDS
        if api_key != self._custom_voices_cache_key or cache_expired:
            try:
                self._custom_voices = self._fetch_custom_voices(api_key)
            except Exception as e:
                # keep the previous list, the preset voices remain usable
                logger.warning(f'Mistral: could not retrieve custom voices: {e}')
            # also cache failures, to avoid repeatedly waiting on the API
            self._custom_voices_cache_key = api_key
            self._custom_voices_cache_time = time.monotonic()
        return self._custom_voices

    def voice_list(self) -> List[voice.TtsVoice_v3]:
        return self._preset_voices() + self._custom_voice_list()

    def get_tts_audio(self, source_text, voice: voice.TtsVoice_v3, voice_options) -> bytes:
        api_key = self.get_configuration_value_mandatory(self.CONFIG_API_KEY)

        model = voice_options.get('model', VOICE_OPTIONS['model']['default'])
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
            raise errors.UnknownServiceError(source_text, voice, message)

        try:
            return base64.b64decode(response.json()['audio_data'])
        except (ValueError, KeyError, TypeError) as e:
            raise errors.UnknownServiceError(
                source_text, voice, f'Mistral: unexpected response: {e}') from e
