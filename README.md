# Anki HyperTTS Community Contributions

This repository contains community-contributed services for the HyperTTS Anki addon (https://github.com/Vocab-Apps/anki-hyper-tts) as well as documentation. The instructions here tend to require a bit of technical know how. The author of HyperTTS doesn't offer any support for those but you can open issues and we'll try to help.

# How to use the services
## Download the service file
You can use any of the services in the [services](services/) directory by simply downloading them and placing them in the correct directory. First look for your Anki profile, then go to the HyperTTS addon directory, and place the downloaded service among other services python files (which should be named `service_<name>.py`)
### Windows
`%APPDATA%/Anki2/addons21/111623432/hypertts_addon/services/`
### MacOSX
`~/Library/Application Support/Anki2/addons21/111623432/hypertts_addon/services/`
### Linux
`~/.local/share/Anki2/addons21/111623432/hypertts_addon/services/`
## Enable the service in HyperTTS
go to Anki `Tools` menu, then `HyperTTS: Services Configuration`, locate the service you just added, and enable it. You may need to set some configuration files.

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

