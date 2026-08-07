# Context Live Translator v0.3.6 - Audio Source Hotfix

This alpha hotfix fixes a regression introduced in v0.3.5.

## Fixed

- Fixed `tr() got multiple values for argument 'source'` when opening any
  microphone, audio-interface input, virtual input, or Windows playback source.
- Added regression coverage for the real audio-route monitoring status path and
  translation placeholders named `source`.

No model, configuration, or session migration is required. Users of v0.3.5
should replace it with this release.

Use the attached `ContextLiveTranslator-v0.3.6-Windows-Setup.zip`; do not use
GitHub's automatically generated source archive as the Windows setup package.
