# Mistral (Voxtral TTS)

[Voxtral TTS](https://mistral.ai/news/voxtral-tts/) is Mistral AI's text-to-speech model. It
supports English, French, Spanish, German, Italian, Portuguese, Dutch, Hindi and Arabic, and every
voice can speak all of these languages.

## Installation

Follow the instructions for [pointing HyperTTS at a checkout of the extensions
repository](https://github.com/Vocab-Apps/anki-hyper-tts-extensions/tree/main#recommended-point-hypertts-at-a-checkout-of-this-repository),
or [copy `services/service_mistral.py` into the addon
directory](https://github.com/Vocab-Apps/anki-hyper-tts-extensions/tree/main#alternative-copy-the-service-file-into-the-addon-directory).

Then in `Tools` > `HyperTTS: Services Configuration`, enable `Mistral` and enter an API key from
[Mistral AI Studio](https://console.mistral.ai/api-keys). Pricing is listed on the
[Mistral pricing page](https://mistral.ai/pricing#api-pricing).

## Voices

- **Preset voices**: the voices provided by Mistral (Paul, Oliver, Jane, Marie, in different
  emotions).
- **Custom voices**: voices you created in [Mistral AI Studio](https://console.mistral.ai/) or with
  the [voices API](https://docs.mistral.ai/api/endpoint/audio/voices) are retrieved from your
  account with your API key, and show up with a `(custom)` suffix. New voices appear after restarting
  Anki (or within 10 minutes).

## Options

- `model`: the Voxtral TTS model, `voxtral-mini-tts-2603` by default.
- `format`: `mp3` (default) or `ogg_opus`.
