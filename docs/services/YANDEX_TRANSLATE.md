# Yandex Translate (TTS)

Free text-to-speech through the same `uniproxy` WebSocket gateway that powers the **listen** button on [Yandex Translate](https://translate.yandex.ru/). No account, API key or other configuration is required.

The service talks to `wss://uniproxy.alice.yandex.net/uni.ws`, sends `TTS.Generate` and concatenates the streamed audio frames. It is implemented with the Python standard library, so it works inside Anki without extra packages.

## Supported languages and voices

| Language | Voice | Gender |
|---|---|---|
| Russian | Oksana | Female |
| Russian | Jane | Female |
| English (US) | David | Male |
| Turkish | Selay | Female |
| Tatar | Rezeda | Female |
| Bashkir | Bashkir | Any |

These are the voices the gateway accepts for the Translate app. Yandex's other languages and voices belong to [Yandex Cloud SpeechKit](https://yandex.cloud/en/services/speechkit), which requires a paid API key and is not covered by this extension.

## Setup

1. In Anki, open `Tools` > `HyperTTS: Services Configuration`.
2. On the `Extensions` tab, enable third party extensions and point them at a checkout of this repository (see the [main README](../../README.md)).
3. On the `Services` tab, `YandexTranslate` is enabled by default. Restart Anki if it is not listed.
4. In a preset's `Voice Selection` tab, filter by service `YandexTranslate` and pick a voice.

## Voice options

| Option | Values | Default | Notes |
|---|---|---|---|
| `speed` | 0.5 – 3.0 | 1.0 | Playback rate applied by Yandex before encoding; values below 0.5 are ignored by the gateway |
| `format` | `mp3`, `ogg_opus` | `mp3` | MP3 is ~64 kbps mono; Ogg Opus is 48 kHz mono |

Both formats are written with the matching file extension, so Anki plays them without conversion.

## Notes and limitations

- This is a private, undocumented endpoint. It can change, throttle, or disappear without notice.
- Requests are free but rate limited by IP. Avoid generating thousands of notes in one batch.
- The whole field is sent as one request. Up to 20,000 characters are accepted; a 15,000-character request took about a minute and produced roughly 60 seconds of audio. Longer text is rejected with a clear error.
- The WebSocket connection is reused across requests and reconnected after 55 seconds of idleness (the gateway closes idle connections at roughly 70–80 seconds).
- The service opens a direct TLS connection to the gateway; HTTP proxies configured for Anki's other services are not used.
- Outside Russia the gateway can take a few seconds to respond; the first request in a session also pays the TLS and WebSocket handshake cost.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `Yandex did not start a speech stream` | The voice was retired or the gateway changed its protocol. Check for an updated version of this extension. |
| `timed out while receiving audio` | Network problem or gateway stall; retry the note. |
| `Service not listed` | Third party extensions are disabled or point at a directory that does not contain `services/service_yandex_translate.py`. |
| `text is too long` | Split the field into several notes or shorten the source text. |

## Credits

Protocol details were reverse engineered from the Yandex Translate web player. This extension is not affiliated with Yandex; use it within the terms of the service.
