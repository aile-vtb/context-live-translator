# Manual release checklist

Run this checklist on a clean Windows 10 or Windows 11 x64 machine before
tagging a release.

## Installation and privacy

- Clone the repository into a path containing spaces and non-ASCII characters.
- Run `setup.ps1` with Python 3.11 x64.
- Confirm setup installs dependencies but does not download any model or
  llama.cpp runtime.
- Confirm `.gitignore` excludes local config, sessions, logs, runtimes, and
  model weights.
- Run `context-live-translator --doctor` before and after configuring models.
- With an empty model path, confirm the GUI detects an existing complete
  Hugging Face cache without downloading anything.
- In a clean Windows user profile, explicitly download `small`; confirm source,
  size, free space and destination are shown, cancellation is safe, and the
  final managed directory passes diagnostics.

## Audio

- Select and monitor a normal microphone.
- Select and monitor an RME or comparable multichannel audio-interface input.
- Select a Windows WASAPI speaker/headphone loopback endpoint.
- Open two routes simultaneously (for example ADAT 3+4 mic and ADAT 5+6
  Discord/input or a Windows playback endpoint) and confirm both meters move.
- Speak over both routes and confirm their independent buffers produce labelled
  segments rather than a pre-ASR mix.
- Unplug or disable one selected endpoint and confirm only that route stops,
  the other continues, and neither falls back to the Windows default microphone.

## Recognition and translation

- Test manual English, Japanese, and Korean source modes.
- Test Auto mode and confirm low-confidence language detection is marked.
- Test Traditional Chinese and one custom target language.
- Test a Gemma GGUF (`json_object`) and a Qwen GGUF (JSON Schema with fallback).
- Test NVIDIA CUDA and CPU fallback (`GPU layers = 0`).

## Revision and persistence

- Confirm the initial translation appears without waiting for a following
  sentence.
- Confirm context revision updates the existing row and preserves its ID.
- Confirm an old revision response cannot overwrite a newer generation.
- Confirm a segment locks after three following segments or the configured
  idle timeout.
- Force a revision error and confirm the provisional translation remains.
- Stop mid-session and confirm `events.jsonl`, both SRT files, and `latest.txt`
  contain the latest complete state.
- For two routes, confirm combined outputs include labels and each
  `source.<route>.srt`, `target.<language>.<route>.srt`, and
  `latest.<route>.txt` contains only that route.

## OBS Browser Source

- Enable the Overlay and confirm it binds only to `127.0.0.1`.
- Add `http://127.0.0.1:8765/overlay` as a 1920×1080 OBS Browser Source.
- Confirm preview, clear, recent-line count, source toggle, position, colors, and
  font sizes update without restarting the translation session.
- Confirm an initial translation appears immediately and a later context
  revision updates the same visible segment instead of adding a duplicate.
- Reload the Browser Source and confirm the current snapshot returns.
- Add `?route=<route-id>` to a second Browser Source and confirm it displays only
  that speaker while the default URL remains combined.
- Disable the Overlay and confirm the port is released while desktop
  transcription and session output continue to work.
- Occupy the configured port and confirm the GUI reports the conflict without
  stopping audio, Whisper, translation, or session persistence.
