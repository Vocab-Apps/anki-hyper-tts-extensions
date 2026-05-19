Contributed by @snorthman

## Getting Started 

[VOICEVOX](https://voicevox.hiroshiba.jp/) is a free, mid-quality text-to-speech and singing voice synthesis software.

To run [VOICEVOX](https://hub.docker.com/r/voicevox/voicevox_engine), you first need Docker installed on your computer.

### 1. Install Docker Desktop

Choose your operating system:

* **Windows / macOS**
  Install [Docker Desktop](https://www.docker.com/products/docker-desktop)

* **Linux**
  Install [Docker Engine](https://docs.docker.com/engine/install)

After installation, make sure Docker is running before continuing.

---

### 2. Choose Version

Run the commands below in a terminal application.

#### CPU 

Works on almost all systems.

```bash
docker pull voicevox/voicevox_engine:cpu-latest
docker run --detach --name voicevox_cpu -p '127.0.0.1:50021:50021' voicevox/voicevox_engine:cpu-latest
```

#### GPU (NVIDIA)

Requires:

* An NVIDIA GPU
* Recent NVIDIA drivers
* NVIDIA Container Toolkit support (usually handled automatically by Docker Desktop on Windows)

```bash
docker pull voicevox/voicevox_engine:nvidia-latest
docker run --detach --name voicevox_gpu --gpus all -p '127.0.0.1:50021:50021' voicevox/voicevox_engine:nvidia-latest
```

---

### 3. Verify

You can verify everything runs correctly. After starting the container, open this URL in your browser: your local [VOICEVOX API](http://127.0.0.1:50021). 
If the engine is running correctly, the API will respond. 
You can also verify the container status in [Docker Desktop](https://www.docker.com/products/docker-desktop/?utm_source=chatgpt.com).
