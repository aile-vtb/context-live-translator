# Context Live Translator v0.3.4 - About and Update Check

This alpha release adds a non-blocking About page and an opt-in-by-navigation
GitHub Release check.

## Added

- An About tab displaying the application logo, author/maintainer, installed
  version, latest public GitHub Release, project link, and license summary.
- The first visit to About checks public GitHub Releases in the background.
- A manual refresh button and a direct link to GitHub Releases.
- Clear states for update available, current, local development version, and
  offline/API errors.

## Privacy and update behavior

- Audio, transcripts, model paths, and settings are never included in the
  update request.
- The request is anonymous and only reads the repository's public Release list.
- The app does not automatically download, replace, or install any update.
- Failure to reach GitHub does not affect offline transcription or translation.

Use the attached `ContextLiveTranslator-v0.3.4-Windows-Setup.zip`; do not use
GitHub's automatically generated source archive as the Windows setup package.
