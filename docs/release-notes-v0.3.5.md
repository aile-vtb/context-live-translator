# Context Live Translator v0.3.5 - Multilingual Interface

This alpha release adds live interface switching for Traditional Chinese,
English, and Japanese.

## Added

- A top-right interface language selector on the Live Translation tab.
- 中文, English, and 日本語 options, with Traditional Chinese as the default.
- Immediate retranslation of every tab, control, route card, subtitle status,
  warning, update state, model-download state, and diagnostic result.
- Persistent interface language selection in the local application config.

## Behavior

- Interface language is independent of each audio route's source language and
  the shared subtitle target language.
- Switching the interface does not restart capture, Whisper, llama-server, the
  current session, or OBS Overlay.
- User-entered route names, model paths, and translated subtitle content are
  never rewritten by the interface language selector.

Use the attached `ContextLiveTranslator-v0.3.5-Windows-Setup.zip`; do not use
GitHub's automatically generated source archive as the Windows setup package.
