# OpenRouter

OpenRouter is a gateway to hundreds of AI models. At the time of this writing,
it provides access to 12 text-to-speech models.

## Installation

Recommended: Follow the instructions for [pointing HyperTTS at a checkout of
the extensions repository](https://github.com/Vocab-Apps/anki-hyper-tts-extensions/tree/main#recommended-point-hypertts-at-a-checkout-of-this-repository).

Alternative: You can [copy the OpenRouter service file into the addon
directory](https://github.com/Vocab-Apps/anki-hyper-tts-extensions/tree/main#alternative-copy-the-service-file-into-the-addon-directory).
But be aware: this OpenRouter service is unique in that it needs **both**
`services/service_openrouter.py` and `services/openrouter_voices.json` to be
placed in the addon directory.

## Automatic Voice Discovery

Since the list of available models, their voices, and their languages changes
frequently, voice information is not hardcoded into the service. Rather, it's
stored in `services/openrouter_voices.json`. The service imports this JSON file
when Anki starts up.

A tool to automatically discover and update the list of voices is provided. You
can run it with Python.

```
python tools/refresh_openrouter_voices.py
```

This will automatically update `services/openrouter_voices.json`.

## Notes

- Although Minimax models do support built-in voices, the voices are not
  returned when requesting speech model metadata from OpenRouter. For that
  reason, Minimax models are not supported by this service.
