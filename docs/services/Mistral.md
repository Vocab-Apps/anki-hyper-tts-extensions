# Mistral (Voxtral TTS 3)

[Voxtral TTS 3](https://mistral.ai/news/voxtral-tts/) is Mistral AI's current text-to-speech
model (`voxtral-mini-tts-3-0`). It supports 35 languages with 50+ regional dialects, preset and
cloned voices, and keeps the older Voxtral 2 preset voices usable.

## Installation

Follow the instructions for [pointing HyperTTS at a checkout of the extensions
repository](https://github.com/Vocab-Apps/anki-hyper-tts-extensions/tree/main#recommended-point-hypertts-at-a-checkout-of-this-repository),
or [copy `services/service_mistral.py` into the addon
directory](https://github.com/Vocab-Apps/anki-hyper-tts-extensions/tree/main#alternative-copy-the-service-file-into-the-addon-directory).

Then in `Tools` > `HyperTTS: Services Configuration`, enable `Mistral` and enter an API key from
[Mistral AI Studio](https://console.mistral.ai/api-keys). Pricing is listed on the
[Mistral pricing page](https://mistral.ai/pricing#api-pricing).

## Voices

The voices and Voxtral 3 models are retrieved from your Mistral account with your API key, so new
voices, languages and Voxtral 3 model versions released by Mistral show up without updating the
extension. New voices and models appear after restarting Anki.

- **Preset voices**: Mistral's voices, including the Voxtral 3 voices and the older Voxtral 2
  presets (still accepted by Voxtral 3). Voxtral 3 adds native voices for Arabic, Catalan,
  Chinese, Dutch, English (UK and US), French, German, Hindi, Hungarian, Italian, Japanese,
  Korean, Norwegian, Polish, Portuguese, Romanian, Russian, Spanish, Turkish, Ukrainian and
  Vietnamese.
- **Custom voices**: voices you created in [Mistral AI Studio](https://console.mistral.ai/) or with
  the [voices API](https://docs.mistral.ai/api/endpoint/audio/voices), shown with a `(custom)`
  suffix.

Each voice has its own native language and accent, so the extension lists it under that language
only. Choose the voice listed under the language and locale you are learning; for example, select
an English voice under **English (UK)** or **English (US)** for the matching accent, or choose a
native voice under the target language for other languages. A voice reading text in another
language keeps its own accent, and there is no separate accent setting in the speech request.

Custom voices are listed under the languages you assigned in Mistral AI Studio. If a custom voice
has no language metadata, it is listed under the documented preset languages and any languages
found on other voices in your account.

## Options

- `model`: the Voxtral TTS model. `voxtral-mini-tts-3-0` (default) is the explicit Voxtral 3
  model. Other Voxtral 3 models available on your account are listed too.
  `voxtral-mini-tts-latest` is intentionally not listed: it can still resolve to Voxtral 2, which
  rejects Voxtral 3 voices with `voice is not supported for speech v1`.
- `format`: `mp3` (default) or `ogg_opus`. MP3 requests raw PCM from Mistral and is encoded
  locally with LAME's extreme preset (`-V 0`, high-quality VBR). Ogg Opus uses Mistral's Opus
  response directly.
- `expressiveness`: how strongly the delivery follows the voice, text and emotion tags, from
  `1.0` to `5.0` (default `1.2`). Higher values trade voice similarity and stability for
  stronger delivery; lower them if the speech sounds forced.

## Upgrading from an older version

Existing presets that saved `voxtral-mini-tts-latest` (or an old Voxtral 2 model) are upgraded to
`voxtral-mini-tts-3-0` automatically when audio is generated. If a saved preset uses a voice whose
native language does not match the text, reselect a voice under the target language and locale to
get the matching accent.
