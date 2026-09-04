# Changelog

## 0.3.0

- Add start/stop routing of the PipeWire/PulseAudio system mix to the active
  Sonos room through a temporary LAN MP3 stream.
- Restore the prior default sink and active application streams when routing
  stops or the backend exits.
- Use the documented OmaSonos LAN port range for the stream and present routing
  as a native shell toggle.
- Persist enough temporary routing state to recover the prior output after a
  forced shell restart.
- Send the live HTTP URL unchanged instead of producing a malformed nested
  `x-rincon-mp3radio://http://` Sonos URI.
- Add an idempotent UFW setup/removal helper and report a clear error when a
  speaker cannot connect to the fixed TCP `1499` stream.
- Offer an in-panel, explicitly authorized UFW setup action and retry routing
  automatically after the rules are added.
- Make room changes while system audio is active an explicit fast stop-and-select
  transition, with immediate UI feedback instead of a general media handoff.
- Keep the short controller panel visually centered by hiding its scrollbar;
  wheel, touchpad, drag, and keyboard scrolling remain available.
- Present computer-audio routing as a compact pressed-state icon beside
  Favorites, keeping Sonos playback as the controller's visual focus.
- Keep the Favorites refresh action visually paired by placing computer-audio
  routing first, with an audio-output glyph instead of a display glyph.
- Show immediate connecting/stopping feedback while a routing request is in
  progress.

All notable changes to OmaSonos are documented here.

## [0.2.1] - 2026-08-19

### Fixed

- Preserved command, setup, and degraded-network errors until users can act on them.
- Stopped retrying failed dependency setup in a background loop; retry is now explicit.
- Added keyboard operation and scrolling for long controller panels.
- Aggregated panel-open state across monitors for the shared backend service.
- Validated and installed from a clean staged plugin using Omarchy's official contract.

### Removed

- Removed internal build plans and implementation-review notes from the release tree.

## [0.2.0] - 2026-08-19

### Added

- Event-driven topology, transport, group-volume, and room-volume updates with
  an automatic polling fallback.
- Sonos Favorites playback for direct streams, queueable containers, and saved
  TuneIn podcasts.
- Playback handoff between standalone rooms and richer playback metadata.
- Discovery diagnostics, stale-state handling, and event subscription renewal.

### Changed

- Improved coordinator handoff verification and rollback behavior.
- Added reproducible, hash-locked runtime dependencies.
- Hardened backend restart handling and private state-file permissions.

## [0.1.1] - 2026-08-12

- Added local installation and validation scripts.
- Improved room activity display and audio handoff behavior.

## [0.1.0] - 2026-08-11

- Initial OmaSonos controller, service, and bar widget.
