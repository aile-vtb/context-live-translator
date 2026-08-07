# Context Live Translator：第一次安裝

這個 ZIP 是給不使用 Git 的 Windows 使用者。請先把整個 ZIP 解壓縮，再從解壓後的
資料夾執行安裝；不要直接在壓縮檔預覽視窗裡執行。

本專案預設在本機處理音訊、辨識與翻譯，但安裝 Python 套件及下載模型時需要網路。

## 你需要準備的三樣東西

1. Python 3.11.9 x64。
2. 含有 `llama-server.exe` 的 llama.cpp Windows 套件。
3. 一個文字 instruct GGUF；建議先使用 Google 官方 Gemma 3 4B IT Q4_0。

Whisper 模型不必預先手動下載；程式啟動後可在 GUI 中確認並下載。

## 步驟一：安裝 Python 3.11.9 x64

請下載 Python.org 官方的 **Windows installer (64-bit)**：

- 版本頁：<https://www.python.org/downloads/release/python-3119/>
- 64-bit 安裝程式：<https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe>

Python 3.11.9 是 Python 3.11 系列最後一個提供一般 Windows 64-bit installer 的版本；
更新的 3.11 security release 只有原始碼，不是 Windows 使用者應下載的安裝檔。

執行安裝程式時：

1. 勾選 `Add python.exe to PATH`。
2. 保留 Python Launcher，然後按 `Install Now`。
3. 安裝完成後關閉安裝程式。

需要自行確認時，可在 PowerShell 執行：

```powershell
py -3.11 -c "import platform, struct; print(platform.python_version()); print(struct.calcsize('P') * 8, 'bit')"
```

預期會看到 `3.11.9` 和 `64 bit`。

## 步驟二：安裝 Context Live Translator

1. 雙擊 `setup.cmd`。
2. 等待它建立 `.venv` 並安裝鎖定的 Python 依賴。
3. 診斷畫面顯示尚未設定模型是正常的。
4. 安裝完成後雙擊 `run.cmd`。

`setup.cmd` 不會下載 Whisper、Gemma、Qwen 或 llama.cpp，也不會把模型放進專案目錄。

## 步驟三：下載 llama.cpp

本專案的驗證基準是 llama.cpp **build b10181**：

- 官方 Release：<https://github.com/ggml-org/llama.cpp/releases/tag/b10181>

不要下載頁面底部 GitHub 自動產生的 `Source code (zip)`；那不是 Windows 執行檔。

### NVIDIA 顯示卡（建議）

下載以下兩個檔案：

1. [llama-b10181-bin-win-cuda-12.4-x64.zip](https://github.com/ggml-org/llama.cpp/releases/download/b10181/llama-b10181-bin-win-cuda-12.4-x64.zip)
2. [cudart-llama-bin-win-cuda-12.4-x64.zip](https://github.com/ggml-org/llama.cpp/releases/download/b10181/cudart-llama-bin-win-cuda-12.4-x64.zip)

建立例如 `C:\AI\llama-b10181-cuda` 的資料夾，把兩個 ZIP 都解壓到同一個資料夾；
Windows 詢問是否合併資料夾時選擇合併。最後確認裡面有：

```text
C:\AI\llama-b10181-cuda\llama-server.exe
C:\AI\llama-b10181-cuda\cublas64_12.dll
C:\AI\llama-b10181-cuda\cublasLt64_12.dll
C:\AI\llama-b10181-cuda\cudart64_12.dll
```

請勿只把 `llama-server.exe` 單獨移到別處；上面的 DLL 必須留在 exe 的同一資料夾。
v0.3.3 起，程式會自動讓 Whisper 使用這個資料夾內的 CUDA DLL。

### CPU 模式

沒有 NVIDIA GPU 時，下載：

- [llama-b10181-bin-win-cpu-x64.zip](https://github.com/ggml-org/llama.cpp/releases/download/b10181/llama-b10181-bin-win-cpu-x64.zip)

解壓到例如 `C:\AI\llama-b10181-cpu`。CPU 模式可以使用，但不保證即時翻譯速度。

如果翻譯模型使用 CPU 版 llama.cpp，但 Whisper 想使用 NVIDIA GPU，請在執行
`setup.cmd` 後再雙擊 `setup-gpu.cmd`。它會安裝 CUDA 12、cuBLAS 與 cuDNN 9 的
Python runtime，下載約 1 GB。若不需要 Whisper GPU，請略過這個選用步驟。

## 步驟四：下載 Gemma GGUF

建議模型是 Google 官方的 **Gemma 3 4B instruction-tuned QAT Q4_0 GGUF**：

- 模型頁：<https://huggingface.co/google/gemma-3-4b-it-qat-q4_0-gguf>
- 檔案頁：<https://huggingface.co/google/gemma-3-4b-it-qat-q4_0-gguf/blob/main/gemma-3-4b-it-q4_0.gguf>

下載步驟：

1. 登入或註冊 Hugging Face。
2. 在模型頁閱讀並接受 Gemma 使用條款及分享聯絡資料的要求。
3. 下載 `gemma-3-4b-it-q4_0.gguf`，檔案約 3.16 GB。
4. 存到例如 `C:\AI\models\gemma-3-4b-it-q4_0.gguf`。

本程式只做文字翻譯，不需要下載 `mmproj-model-f16-4B.gguf`。Gemma 權重不採用本專案
的 MIT License；使用前請閱讀 [Gemma Terms of Use](https://ai.google.dev/gemma/terms)。

## 步驟五：在 GUI 選擇模型

啟動 `run.cmd` 後，進入「模型與進階」：

1. Whisper：按「下載並安裝到使用者資料夾」，初次建議 `small`。
2. llama-server.exe：選擇步驟三解壓出的 `llama-server.exe`。
3. 翻譯 GGUF：選擇 `gemma-3-4b-it-q4_0.gguf`。
4. NVIDIA 使用者可保留 Auto/CUDA 及 GPU layers `99`。
5. CPU 使用者把 Whisper 運算裝置設為 CPU，並把 GPU layers 設為 `0`。

回到「即時翻譯」選擇目標語言，為每個音訊來源設定裝置與來源語言，就可以開始。

「About」分頁會在開啟時連線 GitHub 公開 Releases 檢查版本，只顯示更新提示，
不會上傳音訊或字幕，也不會自動下載或安裝更新。無法連線不影響離線使用。

完整功能、OBS Browser Source、多裝置監聽與疑難排解請閱讀 [README.md](README.md)。

若看到 `Library cublas64_12.dll is not found or cannot be loaded`，代表 DLL 雖可能
已下載，但 Windows 沒有在 Whisper 的搜尋路徑找到它。請先確認 GUI 選到上述
NVIDIA 資料夾內的 `llama-server.exe`；v0.3.3 會自動加入該資料夾。仍失敗時可
執行 `setup-gpu.cmd`，或先把 Whisper 運算裝置改為 CPU。
