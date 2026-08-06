# Roadmap

This roadmap records what shipped in `0.3.0` and the audio-routing work that
remains. Implementation preserves local-first operation, stable segment IDs,
recoverable sessions, and explicit user control.

## 0.3 — First-run setup and multi-device audio (shipped)

### P0: Whisper model onboarding — shipped

Model weights remain outside Git, while the GUI now makes local setup
discoverable.

- Store managed downloads under
  `%LOCALAPPDATA%\ContextLiveTranslator\models\whisper\<model>` rather than in
  the Git checkout.
- When no valid model is configured, offer three explicit actions:
  - use a detected, complete Hugging Face cache entry;
  - download the recommended `faster-whisper-small` model;
  - select an existing CTranslate2 model directory.
- Never download during `setup.ps1` or application startup without a deliberate
  user action.
- Before downloading, show the model source, license, approximate size, free
  disk-space requirement, destination, and CPU/GPU performance guidance.
- Download into a temporary directory, support progress and cancellation, then
  validate `model.bin`, `config.json`, tokenizer data, and vocabulary before an
  atomic move into the managed model directory.
- Recommend `small` for live use. Keep larger models such as `medium` behind an
  advanced choice.
- Continue ignoring `models/`, weight files, incomplete downloads, and caches in
  Git. Do not use Git LFS to publish third-party model weights.
- Add diagnostics, offline error messages, persistence tests, and first-run GUI
  smoke tests.

### P1: Simultaneous audio sources and route configuration — core shipped

The application can now keep multiple normal capture inputs and Windows WASAPI
render-endpoint loopbacks open simultaneously. WASAPI endpoint loopback does
not require a hardware interface to provide its own loopback channel. Routes
retain independent capture/VAD settings and explicit speaker labels.

A primary acceptance scenario is a two-person Discord conversation:

- route `self`: `ADAT (3+4)` capture input containing the local microphone;
- route `friend`: `ADAT (5+6)` Windows playback-endpoint loopback containing
  Discord output;
- both routes are captured at the same time, use Chinese source recognition,
  retain separate VAD/audio buffers and speaker labels, and feed one translated
  conversation timeline.

Do not mix these routes before VAD or ASR. Independent capture preserves
overlapping speech and route identity. They may be merged chronologically only
after route-tagged transcript segments exist.

#### Source types

- **Input device:** microphone, audio-interface input, virtual recording input,
  ASIO/WASAPI input, or similar capture endpoint.
- **Windows playback endpoint:** the complete mix currently played through a
  selected speaker, headphone, HDMI, S/PDIF, or interface output. Keep the
  existing SoundCard/WASAPI backend and clearly label that all applications on
  that endpoint are included.
- **Application/process output (not yet implemented):** investigate native Windows
  process-loopback capture for a selected process tree, such as Discord,
  without requiring a virtual cable or separate playback endpoint. Gate this
  backend to supported Windows builds and keep endpoint loopback as the stable
  fallback. Windows builds below `20348`, including the observed Windows 10
  `19045` development machine, must disable this option with an explanation.

Replace the single long device combo box with a source-type selector followed
by a filtered device list. Input devices, Windows playback endpoints, and any
supported process sources must be visually separate, with a live test meter
and a short explanation of what each choice captures.

Device loss must stop only the affected route, retain subtitles and session
events, and never switch silently to another microphone or playback endpoint.

#### Capture manager

Replace the single-source `AudioEngine` ownership model with an
`AudioCaptureManager` that owns multiple concurrent route workers.

- Each route opens and closes its own input stream or endpoint-loopback worker.
- Each route maintains an independent ring buffer, sample-rate conversion,
  meter, gain, threshold, VAD state, utterance timestamps, and error state.
- Timestamp route events against one monotonic application clock so utterances
  from different device clocks can be merged consistently.
- Capture and VAD on one route must continue while another route is undergoing
  Whisper inference, reconnecting, or reporting device loss.
- A route that disappears stops only itself. The session and unaffected routes
  continue, with a recorded route-error event.
- Detect likely duplicated audio across routes and warn rather than silently
  emitting duplicate subtitles; do not discard audio solely from a heuristic.

#### Route model

Introduce an `AudioRoute` with a stable route ID and at least:

- source fingerprint and source type;
- route/speaker label;
- selected channel indices and channel mode;
- source-language setting;
- gain, threshold, VAD, and enabled state;
- context-group ID for either a shared conversation or independent content.

Persist routes as configuration data. Add `route_id`, source label, and channel
metadata to new transcript/session events while treating old sessions as a
single `main` route for backward compatibility.

#### Channel modes (not yet implemented)

Channel selection is secondary to simultaneous devices. It defines how one
route reads its selected device; it does not replace the ability to run several
routes at once.

- **Mixdown (default):** use for ordinary stereo program audio, livestreams,
  videos, games, and Discord output where both channels contain the same mixed
  conversation. Preserve the current dominant-channel protection so a mono mic
  carried on one side is not averaged into silence.
- **Split routes:** use only when channels really contain isolated speakers or
  sources, for example speaker A on channel 1 and speaker B on channel 2. Each
  selected channel gets an independent meter, gain/threshold, VAD state,
  language setting, queue, and route label.
- **Selected-channel mix:** allow an interface with many channels to select a
  subset such as `1+2` or `3+4`, rather than opening and mixing every advertised
  channel.

Splitting left/right does not separate speakers that are already mixed into
both channels. That requires speaker diarization and remains a separate future
feature. Simultaneous speech in one mixed stream cannot be recovered reliably
by the channel router.

#### Recognition, context, and output

- Use one shared Whisper model service with bounded per-route queues and fair
  scheduling. Do not load one model copy per device or channel by default,
  because that unnecessarily duplicates GPU memory. When two people overlap,
  preserve both completed route utterances even if inference must process them
  sequentially.
- Never let a busy route block audio capture or VAD on another route. Surface
  backlog and dropped-work warnings per route.
- Maintain stable segment IDs and latest-wins context revision across all
  routes.
- For a conversation context group, supply recent interleaved turns with route
  labels so translation can understand dialogue, but allow revisions only for
  the exact mutable segment IDs.
- For unrelated sources, maintain independent context groups so one stream
  cannot rewrite or bias another.
- Merge GUI and default OBS output chronologically with a visible route/speaker
  label. Also provide route-filtered Browser Source URLs so users can place each
  speaker independently in OBS.
- Export a combined timeline plus per-route source/target SRT and text outputs.

#### Acceptance coverage

- Normal microphone input and existing RME inputs remain compatible.
- `ADAT (3+4)` microphone input and `ADAT (5+6)` Discord playback loopback can
  run simultaneously, retain `self`/`friend` labels, and survive overlapping
  speech without mixing their audio buffers.
- A Windows playback endpoint works without hardware loopback support.
- Discord routed to a dedicated playback endpoint can be captured without
  other endpoint audio.
- [Future] Experimental process capture isolates a selected Discord process tree on a
  supported Windows build, with a clear fallback when unavailable.
- [Future] Windows 10 build 19045 hides or disables process capture and directs the user
  to endpoint loopback, a dedicated playback endpoint, or a virtual audio cable.
- Stereo program audio uses mixdown without duplicate subtitles.
- Two isolated devices produce separately labelled transcripts and translations.
- [Future] Two isolated channels within one device produce separately
  labelled transcripts and translations, including overlapping speech.
- Pulling one route does not silently replace it or stop unaffected routes.
- Revisions update the same route/segment row and OBS element.
- Session reconstruction preserves route identity and final corrected text.

## Later candidates

- Speaker diarization for multiple people already mixed into one mono/stereo
  stream.
- More than one simultaneous target language.
- Manual correction and manual segment locking.
- Optional custom dictionaries or terminology profiles.

## Technical references

- [Microsoft WASAPI loopback recording](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording)
- [Microsoft application-loopback sample](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/)
- [SoundCard loopback API](https://soundcard.readthedocs.io/en/stable/)
