# Security policy

Context Live Translator is a local desktop application. Translation requests
must go only to the configured `127.0.0.1` llama.cpp server.

The optional OBS HTTP/WebSocket overlay also binds only to `127.0.0.1`. It has
no authentication because it is not reachable from other hosts; do not modify
the bind address for LAN or Internet exposure without adding an appropriate
authentication, authorization, and transport-security design. Other processes
running as the same user may still read localhost captions.

Please report a vulnerability privately through the repository owner's GitHub
security advisory feature. Do not open a public issue containing credentials,
private transcripts, model access tokens, or sensitive local paths.

The project does not distribute model weights. Model provenance, integrity,
license terms, and acceptable-use restrictions remain the user's
responsibility.

Built-in non-localhost network actions are limited to an explicit,
user-confirmed Whisper model download from Hugging Face and a read-only,
anonymous request to GitHub's public Releases API when the About tab is first
opened or the user clicks the refresh button. The update request does not
include audio, transcripts, model paths, or application settings, and it never
downloads or installs a release. Setup and normal application startup do not
download weights. Model downloads are staged and validated before becoming the
configured local model.
