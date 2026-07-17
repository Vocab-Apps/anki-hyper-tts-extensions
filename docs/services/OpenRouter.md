# OpenRouter

OpenRouter is a gateway to hundreds of AI models. At the time of this writing,
it provides access to 12 text-to-speech models.

Since the list of available models, their voices, and their languages changes
frequently, this information is not hardcoded into the service. Rather, it's
stored in `services/openrouter_voices.json`. The service imports this JSON
file at runtime. Therefor, it is necessary.

To install the OpenRouter service to your HyperTTS installation, copy **both**
`services/service_openrouter.py` and `services/openrouter_voices.json` to
your addon directory.

## Automatic Voice Discovery

Due to the frequent updates on OpenRouter, a tool to automatically discover and
update voices is provided. Run it with Python.

```
python tools/refresh_openrouter_voices.py
```

This will automatically update `services/openrouter_voices.json`.
