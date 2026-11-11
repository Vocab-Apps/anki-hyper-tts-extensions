# Cartesia

[Cartesia](https://cartesia.ai/) is a commercial text-to-speech service. Sonic 3.6 supports
44 languages, preset and cloned voices, multilingual voices with native accents, and
request-level controls for speed, volume, emotion and text normalization.

## Installation

Follow the instructions for [pointing HyperTTS at a checkout of the extensions
repository](https://github.com/Vocab-Apps/anki-hyper-tts-extensions/tree/main#recommended-point-hypertts-at-a-checkout-of-this-repository),
or [copy `services/service_cartesia.py` into the addon
directory](https://github.com/Vocab-Apps/anki-hyper-tts-extensions/tree/main#alternative-copy-the-service-file-into-the-addon-directory).

Then in `Tools` > `HyperTTS: Services Configuration`, enable `Cartesia` and enter an API key
from the [Cartesia playground](https://play.cartesia.ai/keys). Pricing is listed on the
[Cartesia pricing page](https://cartesia.ai/pricing).

## Voices

The voice list is retrieved from your account with your API key, so new public voices,
cloned voices and accent updates appear after restarting Anki. Voice entries owned by your
organization have a `(custom)` suffix.

Cartesia voices advertise an `accents` array. Every item in that array is an accent the voice
speaks natively; `is_native` only marks the accent the voice was originally recorded in. The
extension lists each voice under every accent locale it supports. A multilingual voice
therefore appears once under each of its native languages and locales, and the selected entry
sends the matching locale to Cartesia. This makes numbers, dates, units and pronunciation
follow the target language and region, while Cartesia selects the matching native accent.

Voices without accent metadata are listed under their deprecated `language` field, or under
English when no language is available. A voice can also speak languages it has no native
accent for, but those fallback voices are not listed; select a voice with a native accent for
the target language instead.

## Languages

Cartesia text-to-speech supports Arabic, Bengali, Bulgarian, Chinese, Croatian, Czech, Danish,
Dutch, English, Finnish, French, Georgian, German, Greek, Gujarati, Hebrew, Hindi, Hungarian,
Indonesian, Italian, Japanese, Kannada, Korean, Malay, Malayalam, Marathi, Norwegian, Odia,
Punjabi, Polish, Portuguese, Romanian, Russian, Slovak, Spanish, Swedish, Tagalog, Tamil,
Telugu, Thai, Turkish, Ukrainian, Urdu and Vietnamese.

## Options

- `model`: `sonic-3.6` (default), `sonic-3.5` or `sonic-3`. Sonic 3.6 receives the regional
  locale in `locale`. The older models receive it in the older `language` field, which
  accepts the same language and regional locale codes. The older models do not support Odia
  or Urdu.
- `speed`: speed guidance from `0.6` to `1.5`. The default is `1.0`.
- `volume`: volume guidance from `0.5` to `2.0`. The default is `1.0`.
- `emotion`: optional emotion guidance, default `auto`. With `auto`, the model interprets the
  emotional subtext of the transcript. Selecting an emotion sends it in
  `generation_config.emotion`; Cartesia currently documents emotion guidance for English.
- `normalization`: `auto` (default) normalizes dates, times, numbers and units using the
  request locale, or `off` for a transcript you have already written out the way it should be
  spoken.

## Output

The service requests lossless WAV audio (`pcm_s16le`, 44.1 kHz) and encodes it with LAME's
extreme preset (`-V 0`, high-quality VBR). Cartesia's own MP3 output supports at most
192 kbps, so local encoding keeps the quality higher. HyperTTS stores the result as a normal
MP3 file.
