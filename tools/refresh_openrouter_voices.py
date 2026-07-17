#!/usr/bin/env python3
"""Refresh the OpenRouter voice data, fully automatically.

OpenRouter exposes a public models API that lists every speech/TTS model and,
for most providers, the exact voice ids those models accept
(``supported_voices``). This script:

  1. Fetches all models with output modality ``speech`` from the OpenRouter API.
  2. For each model, takes its ``supported_voices`` list (skipping models that
     accept arbitrary voice ids, e.g. MiniMax, where no enumeration exists).
  3. Infers each voice's language and gender from the provider's voice-id
     *naming pattern* (a deterministic parser per provider -- no hand-maintained
     voice catalog). Models whose pattern is unknown fall back to sensible
     defaults (multilingual / gender Any).
  4. Writes services/openrouter_voices.json, which the service loads at runtime.

The script needs no API key and only the Python standard library, so it runs in
CI without the addon installed. It is idempotent: given the same API state it
produces byte-identical output, and it never writes anything other than the
single JSON file.

Usage:
    python tools/refresh_openrouter_voices.py
"""
import json
import os
import sys
import urllib.request
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
SERVICES_DIR = os.path.join(os.path.dirname(HERE), 'services')
OUTPUT_PATH = os.path.join(SERVICES_DIR, 'openrouter_voices.json')
OPENROUTER_SPEECH_URL = 'https://openrouter.ai/api/v1/models?output_modalities=speech'

# Shared voice options applied to every voice. Keys match the HyperTTS
# options.AudioFormat enum names (mp3, ogg_opus, ogg_vorbis) and the speed slider.
VOICE_OPTIONS = {
    'speed': {
        'type': 'number',
        'min': 0.25,
        'max': 4.0,
        'default': 1.0,
    },
    'format': {
        'type': 'list',
        'values': ['mp3', 'ogg_opus', 'ogg_vorbis'],
        'default': 'mp3',
    },
}

# AudioLanguage enum names used for multilingual models (auto language detect).
MULTILINGUAL = [
    'en_US', 'en_GB', 'fr_FR', 'de_DE', 'es_ES', 'it_IT', 'pt_BR', 'nl_NL',
    'ja_JP', 'ko_KR', 'zh_CN', 'ru_RU', 'pl_PL', 'ar_AE', 'hi_IN', 'tr_TR',
    'cs_CZ', 'sv_SE', 'da_DK', 'fi_FI', 'el_GR', 'he_IL', 'hu_HU', 'nb_NO',
    'ro_RO', 'sk_SK', 'uk_UA', 'vi_VN', 'th_TH', 'id_ID',
]

# Map a 2-letter ISO language code (Deepgram suffix, etc.) to an AudioLanguage.
ISO2_TO_AUDIO_LANGUAGE = {
    'en': 'en_US', 'fr': 'fr_FR', 'de': 'de_DE', 'es': 'es_ES', 'it': 'it_IT',
    'pt': 'pt_BR', 'nl': 'nl_NL', 'ja': 'ja_JP', 'ko': 'ko_KR', 'zh': 'zh_CN',
    'ru': 'ru_RU', 'pl': 'pl_PL', 'ar': 'ar_AE', 'hi': 'hi_IN', 'tr': 'tr_TR',
}

# Map an Azure-style locale (Microsoft prefix) to an AudioLanguage.
LOCALE_TO_AUDIO_LANGUAGE = {
    'en-US': 'en_US', 'es-MX': 'es_ES', 'fr-FR': 'fr_FR', 'de-DE': 'de_DE',
    'en-GB': 'en_GB', 'ja-JP': 'ja_JP', 'ko-KR': 'ko_KR', 'zh-CN': 'zh_CN',
}

# Map Kokoro's 2-letter prefix (gender + language) to language/gender.
# First letter = language family, second letter = f (female) / m (male).
KOKORO_LANG = {
    'a': 'en_US',  # American English
    'b': 'en_GB',  # British English
    'e': 'en_US',  # English (alt)
    'f': 'fr_FR',  # French
    'h': 'hi_IN',  # Hindi
    'i': 'it_IT',  # Italian
    'j': 'ja_JP',  # Japanese
    'p': 'pt_BR',  # Portuguese
    'z': 'zh_CN',  # Chinese
}


def _fetch_speech_models() -> List[dict]:
    with urllib.request.urlopen(OPENROUTER_SPEECH_URL, timeout=30) as resp:
        data = json.load(resp)
    return data.get('data', [])


def _parse_voice(provider: str, voice_id: str) -> Tuple[str, List[str]]:
    """Return (gender, [audio_language_names]) inferred from the voice id.

    ``gender`` is one of 'Male', 'Female', 'Any'. This is a deterministic parser
    per provider's naming convention -- not a curated voice list.
    """
    # Zonos: american_female / british_male / random
    if provider.startswith('zyphra/zonos'):
        if 'female' in voice_id:
            gender = 'Female'
        elif 'male' in voice_id:
            gender = 'Male'
        else:
            gender = 'Any'
        if voice_id.startswith('american'):
            lang = 'en_US'
        elif voice_id.startswith('british'):
            lang = 'en_GB'
        else:
            lang = 'en_US'
        return gender, [lang]

    # Microsoft MAI-Voice: en-US-Harper:MAI-Voice-2
    if provider.startswith('microsoft/mai-voice'):
        locale = voice_id.split('-', 1)[0]
        lang = LOCALE_TO_AUDIO_LANGUAGE.get(locale, 'en_US')
        return 'Any', [lang]

    # Deepgram Aura-2: aura-2-thalia-en  (suffix is a 2-letter ISO code)
    if provider.startswith('deepgram/aura'):
        iso = voice_id.rsplit('-', 1)[-1]
        lang = ISO2_TO_AUDIO_LANGUAGE.get(iso, 'en_US')
        return 'Any', [lang]

    # Kokoro 82M: af_alloy / bm_george / zf_xiaobei
    if provider.startswith('hexgrad/kokoro'):
        prefix = voice_id.split('_', 1)[0]
        if len(prefix) == 2:
            lang = KOKORO_LANG.get(prefix[0], 'en_US')
            gender = 'Female' if prefix[1] == 'f' else 'Male' if prefix[1] == 'm' else 'Any'
            return gender, [lang]
        return 'Any', ['en_US']

    # Grok / Gemini: multilingual, auto-detect; gender not encoded.
    if provider.startswith('x-ai/grok') or provider.startswith('google/gemini'):
        return 'Any', list(MULTILINGUAL)

    # Orpheus / Sesame: English-only models.
    if provider.startswith('canopylabs/orpheus') or provider.startswith('sesame/csm'):
        return 'Any', ['en_US']

    # Unknown provider pattern: safest generic fallback.
    return 'Any', ['en_US']


def build_payload(models: List[dict]) -> dict:
    out_models = []
    skipped = []
    for m in models:
        model_id = m['id']
        voices_raw = m.get('supported_voices')
        if not voices_raw:  # e.g. MiniMax accepts arbitrary ids -> not enumerable
            skipped.append(model_id)
            continue
        parsed_voices = []
        for vid in voices_raw:
            gender, langs = _parse_voice(model_id, vid)
            parsed_voices.append({
                'voice_key': vid,
                'name': vid,
                'gender': gender,
                'audio_languages': langs,
            })
        out_models.append({
            'id': model_id,
            'display_name': m.get('name', model_id),
            'short': m.get('name', model_id).split(':')[-1].strip(),
            'available': True,
            'live_name': m.get('name'),
            'pricing': m.get('pricing'),
            'voices': parsed_voices,
        })

    out_models.sort(key=lambda x: x['id'])
    return {
        'version': 1,
        'source': 'OpenRouter /api/v1/models?output_modalities=speech',
        'note': ('Languages/genders are inferred from each provider voice-id '
                 'naming pattern; models with non-enumerable voices (e.g. '
                 'MiniMax) are omitted.'),
        'voice_options': VOICE_OPTIONS,
        'models': out_models,
        'skipped_models': sorted(skipped),
    }


def main():
    try:
        models = _fetch_speech_models()
    except Exception as exc:  # noqa: BLE001
        print(f'ERROR: could not reach OpenRouter speech API: {exc}', file=sys.stderr)
        sys.exit(1)

    payload = build_payload(models)

    os.makedirs(SERVICES_DIR, exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write('\n')

    total_voices = sum(len(m['voices']) for m in payload['models'])
    print(f'Wrote {OUTPUT_PATH}')
    print(f'  speech models with enumerable voices: {len(payload["models"])}')
    print(f'  skipped (non-enumerable): {payload["skipped_models"]}')
    print(f'  total voices: {total_voices}')


if __name__ == '__main__':
    main()
