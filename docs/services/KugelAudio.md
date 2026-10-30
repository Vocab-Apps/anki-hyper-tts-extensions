# KugelAudio

[KugelAudio](https://kugelaudio.com/) is a commercial text-to-speech service with one
multilingual model covering 39 languages. It supports preset and cloned voices, pronunciation
dictionaries, text normalization and expressive generation controls.

## Installation

Follow the instructions for [pointing HyperTTS at a checkout of the extensions
repository](https://github.com/Vocab-Apps/anki-hyper-tts-extensions/tree/main#recommended-point-hypertts-at-a-checkout-of-this-repository),
or [copy `services/service_kugelaudio.py` into the addon
directory](https://github.com/Vocab-Apps/anki-hyper-tts-extensions/tree/main#alternative-copy-the-service-file-into-the-addon-directory).

Then in `Tools` > `HyperTTS: Services Configuration`, enable `KugelAudio` and enter an API key.
The service expects an API key from the [KugelAudio dashboard](https://kugelaudio.com/dashboard).
A key issued in the EU starts with `eu-`; the service strips that prefix and uses the EU endpoint
automatically.

## Voices

The voice list is retrieved from your account with your API key, so new voices and languages
appear without updating the extension. Restart Anki to refresh the list.

KugelAudio voices advertise their languages as BCP-47 tags such as `de-DE` or `en-GB`. The
extension lists each voice under every language it supports. A voice that speaks several languages
appears once under each language, and the selected entry sends the matching language for text
normalization and dictionary selection. This keeps numbers, dates, currencies and pronunciation
rules correct for the language of the text.

Voices without language metadata are listed under English, which is KugelAudio's documented
normalization fallback.

## Languages

KugelAudio text-to-speech supports Arabic, Bengali, Bulgarian, Cantonese, Chinese, Croatian,
Czech, Danish, Dutch, English, Finnish, French, German, Greek, Hebrew, Hindi, Hungarian,
Indonesian, Italian, Japanese, Korean, Malay, Norwegian, Persian, Polish, Portuguese, Romanian,
Russian, Serbian, Slovak, Slovenian, Spanish, Swedish, Tamil, Thai, Turkish, Ukrainian, Urdu and
Vietnamese.

## Options

- `model`: `kugel-3.5` (default) or the previous `kugel-3`.
- `speed`: playback speed from `0.8` to `1.2`. The default is `1.0`; pitch is preserved.
- `cfg_scale`: expressiveness from `1.2` to `2.5`. Higher values produce a more expressive
  delivery; `2.5` is the provider maximum and the default.
- `temperature`: sampling variance from `0.0` to `1.0`, default `0.3`. Higher values add variation
  between takes; it is not an emotion control.
- `normalize`: expand numbers, dates and currencies into spoken words (default `true`).

KugelAudio has no separate emotion parameter. Emotion can be influenced through punctuation,
capitalization and the provider's text tags, such as `<break>` and `<prosody>`.

## Output

HyperTTS receives KugelAudio's raw PCM audio and encodes it with LAME's extreme preset (`-V 0`),
a high-quality variable-bitrate MP3 setting. KugelAudio generates natively at 24 kHz, so the
service requests that rate directly and avoids server-side resampling.
