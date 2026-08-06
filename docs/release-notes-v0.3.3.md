# Context Live Translator v0.3.3 - CUDA Hotfix

This alpha hotfix addresses first-install Whisper GPU failures on Windows.

## Fixed

- The app now registers the selected `llama-server.exe` directory as a Windows
  DLL search directory before loading faster-whisper. CUDA builds of llama.cpp
  can therefore provide their adjacent `cublas64_12.dll`, `cublasLt64_12.dll`,
  and `cudart64_12.dll` to CTranslate2 without copying files.
- Whisper Auto mode falls back to CPU when the CUDA runtime cannot be loaded.
- Explicit CUDA mode now reports actionable setup guidance instead of only the
  underlying DLL-loader error.
- `--doctor` reports missing cuBLAS/cuDNN libraries.

## Optional GPU runtime

Users who combine CPU llama.cpp with Whisper GPU mode can run
`setup-gpu.cmd`. This explicitly installs pinned NVIDIA CUDA 12, cuBLAS, and
cuDNN 9 Python runtime packages. The download is approximately 1 GB and remains
optional.

Use the attached `ContextLiveTranslator-v0.3.3-Windows-Setup.zip`; do not use
GitHub's automatically generated source archive as the Windows setup package.
