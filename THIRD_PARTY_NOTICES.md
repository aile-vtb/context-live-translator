# Third-party notices

Context Live Translator's own source code is provided under the MIT License.
That license does not grant rights to model weights, model output, voices,
livestream content, or other third-party material.

The application depends on, or can interoperate with, the following projects:

| Project | Role | Upstream license |
| --- | --- | --- |
| [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/) | Desktop GUI | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Whisper inference | MIT |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | Transformer runtime | MIT |
| [python-sounddevice](https://python-sounddevice.readthedocs.io/) | Microphone and audio-interface capture | MIT |
| [SoundCard](https://soundcard.readthedocs.io/) | Windows WASAPI loopback capture | BSD-3-Clause |
| [webrtcvad-wheels](https://github.com/daanzu/py-webrtcvad-wheels) | Voice activity detection | MIT |
| [NumPy](https://numpy.org/) | Numeric arrays | BSD-3-Clause |
| [SciPy](https://scipy.org/) | Audio resampling | BSD-3-Clause |
| [HTTPX](https://www.python-httpx.org/) | localhost HTTP client | BSD-3-Clause |
| [OpenCC](https://github.com/BYVoid/OpenCC) | Chinese conversion data and algorithms | Apache-2.0 |
| [FastAPI](https://github.com/fastapi/fastapi) | Local overlay HTTP/WebSocket application | MIT |
| [Uvicorn](https://github.com/Kludex/uvicorn) | Local ASGI server | BSD-3-Clause |
| [Starlette](https://github.com/Kludex/starlette) | ASGI and WebSocket framework | BSD-3-Clause |
| [websockets](https://github.com/python-websockets/websockets) | WebSocket protocol implementation | BSD-3-Clause |
| [huggingface_hub](https://github.com/huggingface/huggingface_hub) | Explicit Whisper model discovery/download | Apache-2.0 |
| [tqdm](https://github.com/tqdm/tqdm) | Model download progress | MPL-2.0 AND MIT |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | Optional local translation server | MIT |

No `llama.cpp` binary, Whisper model, GGUF model, or other model weight is
distributed in this repository. Users must obtain those files separately and
review the exact terms supplied by the model publisher. In particular, Gemma
weights are subject to the [Gemma Terms of Use](https://ai.google.dev/gemma/terms),
and Qwen model licenses can differ by model and publisher.

This notice is informational and is not legal advice. Consult each upstream
project and model card for the authoritative, current terms.
