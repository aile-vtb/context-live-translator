# Context Live Translator

<p align="center">
  <img src="src/context_live_translator/static/logo.gif" width="180" alt="Context Live Translator logo">
</p>

Context Live Translator 是一個 Windows 單機桌面程式：從明確選定的麥克風、
音訊介面、虛擬輸入或 Windows 播放端點取得聲音，以本機 Whisper 辨識，
再透過本機 `llama.cpp` 模型翻譯。每句會先快速顯示暫定譯文，後續句出現後，
程式會保守地回看最近上下文，修正可能的辨識錯誤與譯文歧義。

> English summary: A local-first Windows desktop app for live speech
> transcription, single-target translation, and conservative context-aware
> revision, with an optional localhost WebSocket overlay for OBS Browser
> Source. No cloud translation API is used.

目前版本：`0.3.3`（alpha）

## 特色與邊界

- 來源語言：Auto、中文、粵語、英文、日文、韓文。
- 單一目標語言：繁中、簡中、英、日、韓、法、德、西班牙文或自訂語言。
- 麥克風／音訊介面使用 `sounddevice`；Windows 系統播放使用 WASAPI loopback。
- 可同時開啟多個輸入或系統播放裝置；每一路有獨立的標籤、來源語言、
  音量、增益、門檻、VAD 與音訊 buffer，不會在辨識前把不同裝置混音。
- 支援 Gemma、Qwen 及其他可由 `llama.cpp` 提供 OpenAI-compatible chat
  completions 的文字 GGUF。
- 最近三句可依上下文回修；十五秒沒有新內容，或已有三個後續句時鎖定。
- 可選的 OBS Browser Source：本機 HTTP 頁面與 WebSocket 即時更新，回修時
  以相同 segment ID 更新原字幕，不新增重複列。
- 所有處理預設在單機完成；執行期翻譯只連線到 `127.0.0.1`。
- 不包含直播平台 API、單一應用程式音訊擷取、自定義字典、雲端翻譯或
  人工字幕編輯。Browser Source 只負責顯示，不與平台帳號連線。

WASAPI loopback 會擷取指定「播放裝置」正在播放的所有聲音，不會隔離單一
瀏覽器或程式。如果需要隔離，請使用 RME loopback、VB-CABLE 或其他虛擬路由。

## 系統需求

- Windows 10 或 Windows 11，64-bit。
- Python 3.10–3.12；一般 Windows 使用者建議
  [Python 3.11.9 x64](https://www.python.org/downloads/release/python-3119/)。
- 建議 NVIDIA GPU。CPU 模式可以啟動，但不保證達到即時速度。
- 使用者自行準備：
  - 本機 faster-whisper CTranslate2 模型目錄；
  - `llama-server.exe`；
  - 一個相容的文字 GGUF 翻譯模型。

本專案不綁定或散布模型與 `llama.cpp` runtime。GUI 可在使用者確認後下載
Whisper；`setup.ps1` 與一般啟動不會自動下載。

## 安裝

### 一般 Windows 使用者（不需要 Git）

到 GitHub 的 [Releases](https://github.com/aile-vtb/context-live-translator/releases)
下載 `ContextLiveTranslator-v0.3.3-Windows-Setup.zip`，完整解壓後閱讀
[`README_FIRST.md`](README_FIRST.md)，再依序雙擊：

1. `setup.cmd`：建立 Python 環境及安裝依賴；
2. `run.cmd`：啟動程式。

請不要把 GitHub 自動產生的 `Source code (zip)` 當成一般使用者安裝包。

### Git 使用者／開發者

```powershell
git clone https://github.com/aile-vtb/context-live-translator.git
cd context-live-translator
.\setup.cmd
```

`setup.ps1` 只會建立 `.venv`、安裝 Python 依賴與執行環境診斷。它不會下載
Whisper、Gemma、Qwen、其他 GGUF 或 llama.cpp。

安裝完成後直接開啟 GUI，再到「模型與進階」完成設定：

```powershell
.\run.ps1
```

也可以直接執行唯讀診斷：

```powershell
.\.venv\Scripts\context-live-translator.exe --doctor
```

## 模型準備

### 1. Whisper

程式以 `local_files_only=True` 載入 faster-whisper CTranslate2 模型。第一次
開啟時會偵測完整的 Hugging Face cache；如果找到，會直接填入有效的 snapshot
路徑。也可以在「模型與進階」頁明確選擇以下其中一種動作：

- 使用偵測到的既有 cache；
- 下載建議的 `small`（或較大的 `medium`）；
- 選取自行準備的 CTranslate2 模型目錄。

GUI 下載只會在使用者確認後執行，安裝位置為：

```text
%LOCALAPPDATA%\ContextLiveTranslator\models\whisper\<model>
```

下載會先檢查空間，寫入同一磁碟的暫存目錄，驗證 `model.bin`、`config.json`、
`tokenizer.json` 與 `vocabulary.txt` 後才原子移入正式位置；可取消並保留暫存檔
供下次續傳。模型不放在 Git checkout，避免 clone、更新或移動專案時遺失設定。

也可使用 Hugging Face CLI 自行下載，例如：

```powershell
hf download Systran/faster-whisper-small `
  --local-dir H:\models\faster-whisper-small
```

請檢查模型頁面的授權與檔案來源。GitHub repository 不包含模型，也不使用
Git LFS 散布權重。

### 2. llama.cpp

本專案目前的驗證基準是
[llama.cpp build b10181](https://github.com/ggml-org/llama.cpp/releases/tag/b10181)：

- NVIDIA：下載
  [`llama-b10181-bin-win-cuda-12.4-x64.zip`](https://github.com/ggml-org/llama.cpp/releases/download/b10181/llama-b10181-bin-win-cuda-12.4-x64.zip)
  與
  [`cudart-llama-bin-win-cuda-12.4-x64.zip`](https://github.com/ggml-org/llama.cpp/releases/download/b10181/cudart-llama-bin-win-cuda-12.4-x64.zip)，
  解壓到同一資料夾。
- CPU：下載
  [`llama-b10181-bin-win-cpu-x64.zip`](https://github.com/ggml-org/llama.cpp/releases/download/b10181/llama-b10181-bin-win-cpu-x64.zip)。

不要下載 Release 頁底部的 `Source code (zip)`；它不包含 Windows 執行檔。
解壓後在 GUI 選擇其中的 `llama-server.exe`。請勿只把 exe 單獨移走；
NVIDIA 版的 CUDA DLL 必須留在同一資料夾。程式會把這個資料夾同時提供給
Whisper 使用。完整圖解式步驟請看
[`README_FIRST.md`](README_FIRST.md)。

若使用 CPU 版 llama.cpp、但希望 Whisper 使用 NVIDIA GPU，可另外雙擊
`setup-gpu.cmd` 安裝 Whisper 所需的 CUDA 12／cuBLAS／cuDNN 9；下載約 1 GB。
這是選用步驟，一般 `setup.cmd` 不會下載 NVIDIA runtime。

### 3. 翻譯 GGUF

選擇支援 chat template 的文字 instruct GGUF：

- **Gemma**：建議先使用 Google 官方
  [Gemma 3 4B IT QAT Q4_0 GGUF](https://huggingface.co/google/gemma-3-4b-it-qat-q4_0-gguf)，
  下載 `gemma-3-4b-it-q4_0.gguf`（約 3.16 GB）。必須登入 Hugging Face 並先接受
  [Gemma Terms of Use](https://ai.google.dev/gemma/terms)。本程式只做文字翻譯，
  不需要該 repository 的 `mmproj-model-f16-4B.gguf`。程式由檔名辨識 `gemma`，
  直接使用 `json_object`，再於本機驗證所需欄位。
- **Qwen**：程式由檔名辨識 `qwen`，優先要求 JSON Schema；如果 llama.cpp
  回應 HTTP 400，會自動改用 `json_object`。
- **其他模型**：使用 Generic profile，行為與 Qwen 相同。模型仍必須可靠地
  遵從 JSON 輸出指示。

模型名稱只用於選擇相容 profile，不代表本專案背書、散布或授權該模型。
請以實際模型頁面的 license、acceptable-use policy 與 model card 為準。

## 使用方式

1. 在「模型與進階」頁選擇 Whisper 目錄、`llama-server.exe` 和 GGUF。
2. 選擇 Whisper 運算裝置；NVIDIA 使用 Auto/CUDA，CPU 使用 CPU 並將
   llama.cpp GPU layers 設為 `0`。
3. 回到「即時翻譯」，選擇一種目標語言。
4. 每個音訊來源 route 分別設定名稱、來源語言、裝置、增益與門檻；按
   「新增音訊來源」即可同時監聽第二個裝置。
5. 確認每一路即時音量表都有反應，按「開始」。

裝置消失或發生錯誤時，只停止受影響的 route，其他 route 與 session 繼續；
程式絕不偷偷切換到 Windows 預設麥克風。執行期間語言、裝置和模型設定會
鎖定；停止後才能變更。

### 兩個裝置同時翻譯範例

- `自己`：選擇 `ADAT 3+4` input，來源語言設為中文。
- `Discord 朋友`：選擇承載 Discord 的 `ADAT 5+6` input；若 Discord 直接送到
  Windows 播放裝置，則選擇該「Windows 系統播放端點」。endpoint loopback
  不要求音效介面本身另有硬體 Loopback，但會包含該播放端點的所有聲音。

兩路各自分句、各自排入同一個 Whisper 模型 worker，再按時間合併成有 speaker
標籤的對話。即使同時說話，也不會先將兩路波形混成一段音訊。若兩個人已經
混在同一個 mono/stereo stream，則仍需未來的 speaker diarization 才能可靠分離。

### RME、Stereo Mix 與虛擬線路

- RME 使用者可以先在 TotalMix 將瀏覽器／播放器送入 loopback channel，再
  從「麥克風／音訊介面」群組選取該 input。
- 使用 VB-CABLE 等工具時，選擇其 recording/input 端。
- 不需要額外路由時，可直接選「Windows 系統播放端點」群組中的喇叭或耳機。

## OBS Browser Source

OBS 功能預設關閉，不影響純桌面使用：

1. 開啟 GUI 的「OBS Overlay」頁籤，勾選啟用並按「套用／重新啟動」。
2. 按「送出預覽字幕」，再按「瀏覽器預覽」確認樣式。
3. 在 OBS 新增 **Browser Source**，URL 使用 GUI 顯示的網址；預設為：

   ```text
   http://127.0.0.1:8765/overlay
   ```

4. 建議 Browser Source 設為 `1920 × 1080`，背景保持透明。
5. 保持 Context Live Translator 執行；開始聽讀後，初譯會直接出現在 OBS。

Overlay 預設顯示最近三句目標譯文，可切換來源原文、句數、字型、字級、顏色、
背景、位置、對齊與寬度。上下文回修及「已鎖定」事件沿用同一 segment ID，
因此瀏覽器會更新原列。每次 WebSocket 更新帶有單調序號；server 與 Browser
Source 都會拒絕遲到的舊初譯，避免它覆蓋已回修字幕。OBS Browser Source
重新載入或 WebSocket 暫時中斷時，
頁面會自動重連並取得目前快照；按 GUI 的「清除畫面」也會同步清除 Overlay。
多路模式會顯示 route 標籤。要讓某個 Browser Source 只顯示單一路，可在 URL
加入 route ID，例如 `http://127.0.0.1:8765/overlay?route=self`。

HTTP 與 WebSocket 只綁定 `127.0.0.1`，不接受區域網路或網際網路連線。這是
顯示介面，不會隔離直播音訊來源，也不會連接 Twitch、YouTube 或其他平台 API。

## 上下文回修如何運作

1. Whisper 原始辨識永久保存在 `raw_asr_text`。
2. 單句翻譯完成後立刻顯示「暫定」。
3. 新句抵達時，模型收到前一個已鎖定句與最近三個可修改句。
4. 模型只能以相同 ID、相同順序回傳保守修正；過期回應會被丟棄。
5. 字幕收到三個後續句或最後更新超過十五秒後，狀態變成「已鎖定」。

v1 的辨識修正是文字上下文校正，不會重新解碼音訊。GUI tooltip 與 session
事件仍可查到 Whisper 原文。回修失敗不會刪掉初譯，也不會阻斷後續聽讀。

## 資料與隱私

設定存放於：

```text
%LOCALAPPDATA%\ContextLiveTranslator\config.json
```

每次執行的 session 位於：

```text
%LOCALAPPDATA%\ContextLiveTranslator\sessions\<timestamp>\
```

內容包括：

- `events.jsonl`：append-only 初稿、修訂、錯誤和鎖定事件；
- `source.srt`：目前最新來源文字；
- `target.<language>.srt`：目前最新目標譯文；
- `latest.txt`：方便閱讀的雙語文字。

多路 session 另外產生 `source.<route>.srt`、
`target.<language>.<route>.srt` 與 `latest.<route>.txt`；合併版會保留 route
標籤。`events.jsonl` 也會記錄單一路裝置中斷，而不破壞其他字幕。

原子覆寫確保程式異常時盡量保留最後完整輸出。停止 session 時，所有未鎖定
項目會先鎖定再寫出。程式不會自動上傳音訊或文字。啟用 OBS Overlay 時，
字幕會提供給本機 `127.0.0.1` Browser Source；使用者仍須確認自己有權擷取、
處理與播出內容。

## 疑難排解

- **找不到 Whisper model.bin**：到「模型與進階」按「偵測既有模型」，或按
  「下載並安裝到使用者資料夾」；不要選到 `.venv\Lib\site-packages`。
- **`cublas64_12.dll` 找不到**：確認 GUI 選取的是 NVIDIA llama.cpp 資料夾內的
  `llama-server.exe`，而且 exe 旁仍有 `cublas64_12.dll`、`cublasLt64_12.dll`
  與 `cudart64_12.dll`。v0.3.3 起程式會自動加入該 DLL 資料夾；不需複製 DLL。
  若使用 CPU 版 llama.cpp，請執行 `setup-gpu.cmd`，或將 Whisper 改為 CPU。
- **其他 CUDA 無法載入**：Auto 模式會自動改用 CPU；明確選擇 CUDA 時，請依
  錯誤訊息檢查 NVIDIA driver、CUDA 12／cuBLAS 與 cuDNN 9。
- **llama.cpp port 被占用**：關閉其他 `llama-server.exe`，或在進階設定更換
  localhost port。
- **OBS Overlay port 被占用**：關閉仍在背景執行的舊版程式，或在「OBS
  Overlay」頁更換 port 後重新套用。llama.cpp port 與 Overlay port 不可相同。
- **OBS 畫面空白**：先在 GUI 送出預覽字幕；確認 Browser Source URL、程式仍
  在執行，而且 OBS 沒有勾選會在隱藏時關閉來源的選項。
- **系統播放端點沒有聲音**：確認播放程式真的輸出到所選端點；Bluetooth、
  HDMI 或介面切換後請重新掃描。
- **字幕切太碎／不出現**：對照即時音量調低／調高語音門檻，必要時增加增益。
- **模型沒有有效 JSON**：改用遵從指令較穩定的 instruct GGUF；Gemma、Qwen
  profile 只處理結構化輸出相容性，無法補救完全不遵從指令的模型。

## 開發與測試

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q
```

CI 只執行不需要真實 GPU、音訊硬體或模型的 Windows 測試。發版前請依
[`docs/manual-release-checklist.md`](docs/manual-release-checklist.md) 完成實機驗收。
進階的單一 process 擷取、單一裝置的 channel subset/split 與 diarization 規劃
記錄於 [`docs/roadmap.md`](docs/roadmap.md)。

## 授權

本專案程式碼採 [MIT License](LICENSE)。第三方依賴與模型不因此改採 MIT；
請參閱 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
