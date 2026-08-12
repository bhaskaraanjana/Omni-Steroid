# Cross-platform port — Linux (0.2.0) and macOS (later)

## Decision (2026-08-11)
0.1.0 ships **Windows only**. The release matrix and `bundle.targets` are scoped to
`nsis`/`msi`. Rationale: provider API keys are stored through **Windows DPAPI only**, so a
mac or Linux bundle produces an app in which a user can never save a key — the Ask, note
enhancement, and agent features are all inert. Shipping such a bundle would be shipping a
product that cannot be configured.

Verified directly on Ubuntu 24.04 (WSL):

```
dpapi_protect(b"test") -> DpapiUnavailableError: DPAPI is only available on Windows
```

The failure is graceful — `provider_keys_command_dispatcher` catches it and replies
`"the key could not be saved"` — but the message never explains that it is a platform
limitation, so a Linux user would read it as a bug in their setup.

## What is already cross-platform (do not rebuild these)

| Layer | State |
|---|---|
| Rust / Tauri crate | Already `cfg`-guarded. `windows-sys` sits under `[target.'cfg(windows)'.dependencies]`, so it is not pulled on mac/Linux. `#[cfg(not(windows))]` fallbacks exist in `dictation_injection_win32.rs:215`, `dictation_pill_window.rs:95`, `engine_sidecar.rs`. |
| Audio capture | `engine/audio/sounddevice_capture_backend.py` is a **real 186-line implementation**, not a stub. `_find_loopback_device_index()` already matches PulseAudio/PipeWire `"monitor of"` sources and macOS `blackhole`/`soundflower`/`loopback` devices. `capture_backend_factory.py` already routes darwin/linux to it. |
| Engine process | Boots and serves `/health` on Linux — proven by the ubuntu release job and again under WSL. |
| Tray, global hotkey | Cross-platform Tauri plugins (`tauri-plugin-global-shortcut`, `tray-icon`). |
| Detection modules | `microphone_in_use_detector.py` and `windows_desktop_snapshot_via_ctypes.py` already carry non-Windows stubs. |

`engine/audio/pipewire_capture_backend.py` and `engine/audio/macos_loopback_backend.py` are
17-line stubs ("implement in Phase 6 hardware pass"). They are for a **native** path; the
sounddevice backend is the working fallback, so they are an optimisation, not a blocker.

## The one true blocker: key custody

DPAPI has exactly **6 call sites across 3 files** — a clean seam:

- `engine/security/provider_key_store.py:24,128,137`
- `engine/google/dpapi_google_token_store.py:26,156,165`
- `engine/microsoft/dpapi_microsoft_token_store.py:11,113,121`

**Work:** introduce a platform-dispatching secret store exposing the same
`protect(bytes) -> bytes` / `unprotect(bytes) -> bytes` contract, routing to DPAPI on
Windows, Keychain on macOS, and Secret Service/libsecret on Linux (the `keyring` package
covers all three; it is **not** currently a dependency). Then change 3 imports and 6 calls.

Keep the fail-closed behaviour exactly as it is: a missing or tampered store must still
refuse rather than fall back to plaintext. The three Windows-gated DPAPI test modules need
cross-platform equivalents.

## Estimates

**Linux — roughly 2 to 4 days**
1. Secret-store abstraction (~1 day incl. tests)
2. Validate capture against real PipeWire monitor sources (~1 day) — the code exists but has
   never been exercised on hardware
3. Restore `ubuntu-latest` to the release matrix, re-add `deb`/`appimage` targets, CI job (~1 day)

**macOS — roughly 1 to 2 weeks**, and most of the variance is not code:
1. Shares the secret-store work
2. `.transparent(true)` (4 call sites) needs the `macos-private-api` Cargo feature **paired
   with** `"macOSPrivateApi": true` in `tauri.conf.json`. Adding the feature **alone breaks
   `tauri-build`'s manifest check on every platform, including Windows** — they are a matched
   pair. Needs a Mac to compile-verify; do not land it blind.
3. System audio: either depend on the user installing BlackHole (poor UX) or implement the
   Core Audio / ScreenCaptureKit tap that `macos_loopback_backend.py` stubs out. This is the
   multi-day item.
4. **Apple signing and notarization.** `bundle.macOS` is currently `{}` — nothing configured.
   Historically the largest hidden cost.

## Accepted feature loss on both platforms

**Text injection** (dictation typing into other apps) is Windows-only and honestly stubbed:
`"text injection is only available on Windows"`. mac/Linux would need AXUIElement and
ydotool/xdotool respectively. Dictation still works in note mode; only injection into a
foreground app is lost.

## Retained in the workflow for 0.2.0
`.github/workflows/release.yml` keeps two OS-guarded steps that are inert while the matrix is
Windows-only — the Linux Tauri system-dependency install and the non-Windows smoke test. They
are correct code for the Linux milestone, so they are kept rather than deleted and re-derived.
