# OpenRouter TTS service for HyperTTS
# 
# API reference: https://openrouter.ai/docs/api-reference/tts
#
# OpenRouter exposes an OpenAI-compatible text-to-speech endpoint:  
# POST https://openrouter.ai/api/v1/audio/speech  
# Body: { model, input, voice, response_format, speed }  
# Auth: Bearer token in the Authorization header.
#
# The voice list is generated automatically by
# ../tools/refresh_openrouter_voices.py, which queries OpenRouter's public
# models API (output modality "speech") and writes
# ../services/openrouter_voices.json. The refresh does not happen automatically.
# You should run the script periodically and commit the regenerated JSON. The
# service loads that JSON at runtime.

import json
import os
import requests
from typing import List, Dict, Any

from hypertts_addon import voice
from hypertts_addon import service
from hypertts_addon import errors
from hypertts_addon import constants
from hypertts_addon import languages
from hypertts_addon import options
from hypertts_addon import logging_utils

logger = logging_utils.get_child_logger(__name__)

OPENROUTER_TTS_URL = 'https://openrouter.ai/api/v1/audio/speech'

_HERE = os.path.dirname(os.path.abspath(__file__))
_VOICES_JSON = os.path.join(_HERE, 'openrouter_voices.json')

# Map HyperTTS AudioFormat -> OpenRouter response_format value.
AUDIO_FORMAT_MAP = {
    options.AudioFormat.mp3: 'mp3',
    options.AudioFormat.ogg_opus: 'opus',
    options.AudioFormat.ogg_vorbis: 'ogg',
}

# Map AudioLanguage enum name -> enum member.
_AUDIO_LANGUAGE_BY_NAME = {e.name: e for e in languages.AudioLanguage}
_GENDER_BY_NAME = {
    'Male': constants.Gender.Male,
    'Female': constants.Gender.Female,
    'Any': constants.Gender.Any,
}


def _load_models_data() -> Dict[str, Any]:
    """Load the voice data from JSON file."""
    if not os.path.exists(_VOICES_JSON):
        logger.warning(
            'openrouter_voices.json not found; run tools/refresh_openrouter_voices.py'
        )
        return {'voice_options': {}, 'models': []}
    try:
        with open(_VOICES_JSON, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        return {
            'voice_options': data.get('voice_options', {}),
            'models': data.get('models', []),
        }
    except (ValueError, KeyError) as exc:
        logger.error(f'openrouter_voices.json unreadable ({exc}); no voices available')
        return {'voice_options': {}, 'models': []}


def _build_voice_list() -> List[voice.TtsVoice_v3]:
    """Build the voice list across all models."""
    data = _load_models_data()
    voice_options = data['voice_options']
    voices: List[voice.TtsVoice_v3] = []

    for model in data['models']:
        model_id = model['id']
        model_short = model.get('short', model['display_name'])
        for v in model['voices']:
            audio_languages = [
                _AUDIO_LANGUAGE_BY_NAME[al] for al in v['audio_languages']
            ]
            # Prefix the display name with the model so users can tell voices
            # apart in the dropdown (e.g. "Voxtral Mini TTS · en_paul_neutral").
            display_name = f'{model_short} · {v["name"]}'
            voices.append(
                voice.TtsVoice_v3(
                    name=display_name,
                    gender=_GENDER_BY_NAME.get(v['gender'], constants.Gender.Any),
                    audio_languages=audio_languages,
                    service='OpenRouter',
                    # voice_key carries both the model and the provider voice id
                    # so get_tts_audio can route to the right model.
                    voice_key={'model': model_id, 'voice': v['voice_key']},
                    options=voice_options,
                    service_fee=constants.ServiceFee.paid,
                )
            )

    return voices


class OpenRouter(service.ServiceBase):
    CONFIG_API_KEY = 'api_key'

    def __init__(self):
        service.ServiceBase.__init__(self)
        self._voices: List[voice.TtsVoice_v3] = _build_voice_list()

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

    def voice_list(self) -> List[voice.TtsVoice_v3]:
        return self._voices

    def get_tts_audio(self, source_text, voice: voice.TtsVoice_v3, voice_options) -> bytes:
        api_key = self.get_configuration_value_mandatory(self.CONFIG_API_KEY)
        # The model is always carried in the voice_key (populated from
        # openrouter_voices.json), so each voice routes to its own model.
        if isinstance(voice.voice_key, dict):
            model = voice.voice_key['model']
            provider_voice = voice.voice_key.get('voice')
        else:
            model = voice.voice_key
            provider_voice = voice.voice_key

        speed = voice_options.get('speed', voice.options['speed']['default'])
        audio_format_str = voice_options.get(
            options.AUDIO_FORMAT_PARAMETER, options.AudioFormat.mp3.name
        )
        audio_format = options.AudioFormat[audio_format_str]
        if audio_format not in AUDIO_FORMAT_MAP:
            raise errors.ServiceInputError(
                source_text, voice,
                f'OpenRouter does not support audio format {audio_format.name}'
            )
        response_format = AUDIO_FORMAT_MAP[audio_format]

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'HTTP-Referer': 'https://github.com/Vocab-Apps/anki-hyper-tts',
            'X-Title': 'HyperTTS',
        }
        payload = {
            'model': model,
            'input': source_text,
            'voice': provider_voice,
            'response_format': response_format,
            'speed': speed,
        }

        try:
            response = requests.post(
                OPENROUTER_TTS_URL,
                json=payload,
                headers=headers,
                timeout=60,
            )
        except requests.exceptions.Timeout as e:
            raise errors.ServiceTimeoutError(source_text, voice, str(e)) from e
        except requests.exceptions.ConnectionError as e:
            raise errors.ServiceConnectionError(source_text, voice, str(e)) from e

        if response.status_code in (401, 403):
            raise errors.ServicePermissionError(
                source_text, voice, f'OpenRouter auth failed: {response.status_code} {response.text}'
            )
        if response.status_code == 402:
            raise errors.PermanentError(
                source_text, voice,
                f'OpenRouter: insufficient credits. {response.text}'
            )
        if response.status_code == 429:
            retry_after = response.headers.get('Retry-After')
            if retry_after is not None:
                try:
                    raise errors.RateLimitRetryAfterError(
                        source_text, voice, response.text, int(retry_after)
                    )
                except (ValueError, TypeError):
                    pass
            raise errors.RateLimitError(source_text, voice, f'OpenRouter rate limited: {response.text}')
        if response.status_code == 400:
            raise errors.ServiceInputError(
                source_text, voice, f'OpenRouter bad request: {response.status_code} {response.text}'
            )
        if response.status_code >= 500:
            # 500/502/503/524/529 and other upstream failures may succeed on retry.
            raise errors.UnknownServiceError(
                source_text, voice, f'OpenRouter upstream error: {response.status_code} {response.text}'
            )
        if response.status_code != 200:
            raise errors.UnknownServiceError(
                source_text, voice, f'OpenRouter error: HTTP {response.status_code}: {response.text}'
            )

        return response.content
