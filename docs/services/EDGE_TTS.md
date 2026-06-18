## Edge TTS

[Edge TTS](https://github.com/rany2/edge-tts) uses Microsoft Edge's free online TTS service. It offers 300+ neural voices across many languages with no API key required.

### Prerequisites

You need the `edge-tts` command available in your PATH. The easiest way is via [uv](https://docs.astral.sh/uv/):

```bash
uv tool install edge-tts
```

Or with pip:

```bash
pip install edge-tts
```

Verify it's working:

```bash
edge-tts --list-voices | head
```

### Installation

Copy `service_edge_tts.py` to your HyperTTS services directory (see [README](../../README.md) for paths).

### Usage

1. In Anki, go to `Tools` > `HyperTTS: Services Configuration`
2. Enable **EdgeTTS**
3. No configuration is needed — the service is ready to use

### Voice Options

| Option | Range | Default | Description |
|--------|-------|---------|-------------|
| `rate` | -90% to +200% | 0% | Speech speed |
| `volume` | -90% to +100% | 0% | Speech volume |
| `pitch` | -50Hz to +50Hz | 0Hz | Voice pitch |

### Supported Languages

Edge TTS supports 322 voices across 80+ locales including: English (US/GB/AU/CA/IN), Chinese (Mandarin/Cantonese), Japanese, Korean, French, German, Spanish, Portuguese, Italian, Russian, Arabic, Hindi, and many more.
