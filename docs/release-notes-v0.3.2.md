# Context Live Translator v0.3.2 - Public Alpha

第一個公開測試版本。這是一個 Windows 本機即時語音翻譯工具，可同時監聽多個
音訊來源，分別指定來源語言，翻譯為一個共同目標語言，並把上下文回修同步顯示在
桌面 GUI 與 OBS Browser Source。

## 一般使用者下載

請下載 Release Assets 中的：

```text
ContextLiveTranslator-v0.3.2-Windows-Setup.zip
```

解壓後先閱讀 `README_FIRST.md`，再雙擊 `setup.cmd`。請不要下載 GitHub 自動產生的
`Source code (zip)` 當作一般使用者安裝包。

## 重要需求

- Windows 10/11 x64。
- Python 3.11.9 x64。
- 自行下載 llama.cpp Windows build。
- 自行取得並接受授權條款的 Gemma／Qwen／其他相容文字 GGUF。
- NVIDIA GPU 是主要驗證環境；CPU 模式不保證即時速度。

安裝包不包含 Python、Whisper、llama.cpp、CUDA DLL 或 GGUF 權重。GUI 可在使用者
確認後下載 Whisper；其他 runtime 與模型的官方下載步驟已寫在 `README_FIRST.md`。

## 主要功能

- 麥克風、音訊介面及 Windows WASAPI 播放端點。
- 多裝置同時監聽，每路獨立來源語言、VAD 與字幕標籤。
- faster-whisper 本機辨識。
- Gemma、Qwen 與 Generic llama.cpp 翻譯 profile。
- 初譯立即顯示，最近上下文可保守回修並更新原字幕。
- GUI 字幕時間軸、session JSONL/SRT/TXT 輸出。
- localhost OBS Browser Source 與 WebSocket 修訂同步。
- 視窗標題列與 Windows 工作列使用 Context Live Translator logo。

這是 alpha 版本。發布前後仍建議依 repository 中的
`docs/manual-release-checklist.md` 完成實機驗證並回報硬體相容性問題。
