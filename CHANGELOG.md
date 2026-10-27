# Changelog

All notable changes to BerryLink are documented here.

## 0.1.0 — 2026-10-27

First public release. Local-first AI companion: an Android "face" phone and a
Kali Linux (X11) desktop gateway talking over a pinned TLS WebSocket with
per-device tokens.

### Phone companion (Android, Kotlin/Compose)
- Face-only immersive companion: animated berry face, landscape lock, eyes
  follow the cursor/finger, tap to smile.
- Hold-to-talk voice: on-device speech-to-text sends the recognized question;
  answers are spoken on the phone with a human-sounding TTS voice picker
  (quality-ranked voices, natural rate/pitch).
- One-tap codeless pairing: press Connect on the phone, Allow on the desktop —
  mDNS discovery plus a signed pairing request, no codes to type. Legacy
  6-digit code pairing still works when the codeless toggle is off.
- Typed asks and reconnect/unpair controls in a minimal settings panel.

### Desktop gateway (Python, PyQt6)
- mDNS-advertised TLS server (default port 8765), per-device token auth,
  codeless pairing with the proven Allow/Deny dialog.
- AI providers: Qwen models via an OpenRouter-compatible service (xkiro) as
  the primary path — free `:free` model ids only, key validated before use and
  stored at `~/.config/berrylink/secrets.json` (0600), redacted in logs.
  Offline mock mode for keyless local demos; Gemini/OpenRouter code paths
  remain available but were not exercised for this release.
- Screen awareness: local OCR reads targets (ids like `L12`) for point/look;
  screenshots attach to an ask only when the phone flags it AND the owner has
  "Allow screenshots to the AI provider" enabled.
- Screen questions ("what can you see right now on the screen?") run one local
  OCR round and the answer describes the real screen — never an invented one.
- Input control (off by default, re-locked on every app start): click (incl.
  double-click), type, key shortcuts, scroll, drag. Every executed action
  passes a per-action Allow/Deny dialog; consequential-looking targets are
  forced to confirm. A filename in the sentence (e.g. "open the key.txt
  file") routes to a double-click of the on-screen item. App launches keep
  their separate deterministic path.
- Own pointing overlay: labeled pointer/bubble at the target, click-through,
  plus automation badges while tools act.
- Emergency stop (Ctrl+Alt+S) latches all input off; resume is deliberate.
- Persona/personality: warm one-liner chat, mood tags, 600-token default
  response cap.

### Compliance
- MIT for the original code; NOTICE.md plus full third-party texts under
  `licenses/`; OFL font notices also ship inside the APK assets.

### Verification
- Desktop: 80 tests passing (protocol, pairing incl. codeless, tools,
  gateways incl. action parsing, live-server ask flows).
- Android: unit tests pass and the debug APK builds in one command via
  `scripts/build-android.sh`; the dist APK is that same flow's build. A
  release-signed APK builds with `scripts/build-release.sh` using the
  maintainer's private local keystore (gitignored, in-project); the GitHub
  release ships exactly one APK — `BerryLink-<version>.apk` — and version
  bumps replace it in place on the same release page.
