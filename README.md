# Anki HyperTTS Community Contributions

This repository contains community-contributed services for the HyperTTS Anki addon (https://github.com/Vocab-Apps/anki-hyper-tts) as well as documentation. The instructions here tend to require a bit of technical know how. The author of HyperTTS doesn't offer any support for those but you can open issues and we'll try to help.

# How to use the services
## Recommended: point HyperTTS at a checkout of this repository
The easiest way is to get a copy of this repository and tell HyperTTS to load extensions from it. This keeps the services outside the addon directory, so they survive HyperTTS updates and can be updated with a `git pull`.

1. Clone the repository (or download it as a ZIP from the green `Code` button), and store it **outside** your Anki addons folder:
   ```
   git clone https://github.com/Vocab-Apps/anki-hyper-tts-extensions.git
   ```
2. In Anki, go to `Tools` > `HyperTTS: Services Configuration`, open the `Extensions` tab, check `Enable third party extensions`, and use `Browse...` to select the directory you just downloaded. Click `Save` and restart Anki.
3. Go back to `Tools` > `HyperTTS: Services Configuration`, `Services` tab, and enable the services you want. Some of them require additional settings, such as an API key.
4. In a HyperTTS preset, go to the `Voice Selection` tab and use the `Service` filter to pick a voice.

The full walkthrough with screenshots is here: https://www.vocab.ai/tips/hypertts-extensions-community-services

Note that third party services are Python code which HyperTTS runs every time Anki starts, and they are not reviewed by the HyperTTS author.

## Alternative: copy the service file into the addon directory
You can still use any of the services in the [services](services/) directory by downloading them and placing them directly among the HyperTTS service files (which are named `service_<name>.py`). **Files copied there will be overwritten or removed when HyperTTS is updated**, so the approach above is preferred. First look for your Anki profile, then go to the HyperTTS addon directory:
### Windows
`%APPDATA%/Anki2/addons21/111623432/hypertts_addon/services/`
### MacOSX
`~/Library/Application Support/Anki2/addons21/111623432/hypertts_addon/services/`
### Linux
`~/.local/share/Anki2/addons21/111623432/hypertts_addon/services/`

Then go to Anki `Tools` menu, then `HyperTTS: Services Configuration`, locate the service you just added, and enable it. You may need to set some configuration options.

# Creating new services
If you'd like to create new HyperTTS services which interface with a TTS engine, whether local, open source or online, it's very easy, it only requires creating a single python script.
The easiest approach would be to use a coding agent, and point it to the [AGENTS.md](AGENTS.md) file which contains instructions on how to create a new HyperTTS service.

## Example
to create the service [service_replicate_kokoro.py](services/service_replicate_kokoro.py), I used the following prompt:
```
Create a HyperTTS service for Kokoro82m hosted on Replicate. Instructions here: https://replicate.com/jaaari/kokoro-82m/api
```

[Replicate](https://replicate.com/) is a cloud service which lets you run AI models on the cloud with API access. It's very to deploy models such as Kokoro but you'll have to pay for access.

If you are using a web-based AI LLM such as ChatGPT or Claude.Ai, you'll need to paste the contents of [AGENTS.md](AGENTS.md) along with the prompt. If you're using a coding agent such as Open Code, Github Copilot, it will automatically use the instructions.

