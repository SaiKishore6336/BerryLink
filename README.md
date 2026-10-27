# BerryLink

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/SaiKishore6336/BerryLink.svg)](https://github.com/SaiKishore6336/BerryLink/releases/latest)
[![Platform: Linux + Android](https://img.shields.io/badge/platform-Linux%20%7C%20Android-blueviolet.svg)](#install)
[![Python](https://img.shields.io/badge/desktop-Python%20%2B%20Qt-blue.svg)](desktop/berrylink)
[![Kotlin](https://img.shields.io/badge/android-Kotlin%20%2B%20Compose-green.svg)](android/app)

**BerryLink turns an Android phone into a living, talking Berry companion for a Kali Linux (X11) desktop — the phone is the face and voice, the desktop is the hands and the eyes.**

BerryLink is a local-first pair of apps: a Kotlin/Compose phone app showing an animated berry face with hold-to-talk, and a Python/Qt desktop gateway that listens over your LAN, answers questions out loud, reads the screen locally, points at things with its own overlay, and can click/type/scroll on your desktop — but only through explicit Allow prompts, with input control off by default. AI traffic goes to Qwen models (free tiers only) through an OpenRouter-compatible service you configure once; API keys stay on the desktop, and everything works key-free in offline mock mode.

One note before the marketing-free details list: the AI provider side runs Qwen through xkiro. Keys are validated against the provider and stored under `~/.config/berrylink/secrets.json` (0600) on the desktop app — never on the phone, never in this repository, and never sent anywhere except the provider call.

```text
Android phone (face, mic, TTS) ── LAN/Wi-Fi ──► Kali desktop gateway (Qt tray app)
        held talk button ── speech-to-text            │ pinned TLS WebSocket, per-device token
        streamed answer ── TTS voice picker           │ local OCR screen reader + target ids
                                                      │ opt-in screenshots + guarded X11 tools
                                                      │ per-action Allow/Deny prompts
```

## Highlights

- **Face-only phone companion.** Locks to landscape, hides system chrome, eyes
  track the cursor or your finger; a tap makes Berry smile; holding the face
  starts a question.
- **Real voice loop.** On-device speech recognition on the phone → answer from
  the model → spoken reply with a human-sounding TTS voice picked for quality
  (`tts-quality` ranked, natural pace).
- **Codeless pairing.** Press Connect on the phone, then Allow once on the
  desktop.BerryLink finds the desktop over mDNS and pairs with a fresh token.
  The 6-digit code path still works if you turn one-tap pairing off.
- **Screen questions get eyes.** "What can you see right now on the screen?"
  runs one local OCR round and the answer describes actual windows and
  elements — ids and coordinates are never spoken aloud.
- **Input control you have to hand over.** Click, type, key shortcuts, scroll
  and drag are gated behind an "Allow input control" toggle that re-locks
  every app start, and every executed action needs its own Allow prompt.
  Critical-looking targets always ask, even with per-action confirmations
  relaxed.
- **Honest double-click/file opening.** "Double click the Settings button" or
  "open the key.txt file" resolves the on-screen item and double-clicks it —
  through the same Allow prompt. App launches ("open Brave") keep a separate
  deterministic path.
- **Local mock mode.** No API key needed to demo: the desktop answers locally
  and can point, look and read the screen. Mock mode provably never performs
  input actions.
- **Pairing and operational safety.** Session certificates are pinned; device
  tokens authenticate each phone; the emergency-stop hotkey (Ctrl+Alt+S)
  latches every input tool off until you resume deliberately; log output
  redacts anything key-shaped.

## What is intentionally not here

- Meeting recording is absent from this MVP, by design.
- No cloud service, no accounts, no telemetry. BerryLink talks only to the AI
  provider you configured and to your own desktop.

## Install

- **APK (Android 8.0+, 10.5 MB, debug-signed testing build):** download the
  latest release from https://github.com/SaiKishore6336/BerryLink/releases/latest
  and install it:

  ```bash
  adb install BerryLink-0.1.0-debug.apk
  ```

  Package id: `app.berrylink.companion` (single build variant — the debug build
  IS the release; see project structure below). The exact file checksum is in
  each release's `SHA256SUMS.txt`.

- **Desktop (Kali Linux or another X11 desktop, Python 3.10+):**

  ```bash
  python3 -m venv .venv
  .venv/bin/pip install -r desktop/requirements.txt
  scripts/run-desktop.sh          # picks .venv if present, else system python3
  ```

  The gateway advertises mDNS on port 8765 and shows a settings window plus
  quick-control checkboxes. Pair your phone with Connect on the phone.

## Usage examples

Pair once, then just talk or type:

- *"What can you see right now on the screen?"* — Berry reads the desktop and
  describes it.
- *"Point at the Settings button"* — Berry's own overlay pointer lands on it.
- *"Open Brave"* / *"Open the terminal"* — deterministic app launches.
- *"Double click the Settings button"*, *"type hello in the field"*,
  *"press ctrl+s"*, *"scroll down"*, *"open the key.txt file"* — input control:
  the "Allow input control" toggle must be on, the screen is read for target
  ids, the AI proposes one action, and the dialog asks before anything moves.
- Hold the berry face to speak; release and the answer comes back spoken.

## Building from source

- **Desktop** (inside `desktop/`): `python3 -m pytest tests -q` — the suite is
  protocol, pairing, tools, and gateway coverage. The gateway runs with
  `python3 -m berrylink.app` (or `scripts/run-desktop.sh`).
- **Android** (from the repo root): `scripts/build-android.sh` runs the unit
  tests, builds the debug APK, and publishes it to `dist/app-debug.apk` with a
  `sha256` file. Needs `ANDROID_HOME` (buildSdk 34, minSdk 26, Java 17).
- The desktop entry script installs a `.desktop` launcher when you ask it to;
  see `packaging/`.

## Signing

The published APK is **debug-key signed** and is labeled a testing build in
the release notes. Only debug builds currently exist; there is no release
variant. Use a private keystore before distributing outside development, and
keep the app package id and release/debug signing separate if/when that
happens.

## Limit and notes

Real limits, stated plainly:

- **Desktop is X11 only.** Wayland screen reading and global hotkeys are not
  supported. Tested on Kali Linux.
- **Free-tier models only.** Configured provider endpoints list `:free` model
  ids only; rate limits apply, and a fallback try happens when a model is
  throttled or dead — all within the key configured on the desktop.
- **Input control restarts off.** The safety-by-default state is restored on
  every desktop app start; the toggle is deliberately re-flipped each session.
- **Voice requests in mock mode return an honest refusal** (mock AI cannot
  listen to audio), while text asks work fully offline.
- **Screenshots are opt-in twice**: the phone has to flag them AND the desktop
  has to allow screenshots to the provider; OCR text is always local-first.
- **No meeting recording**; legacy meeting code is intentionally inert in
  this MVP.
- The Android emulator shipped upstream (face-facing rendering of the face)
  was exercised early but some phone-only flows (hold-to-talk hardware,
  TTS voice quality picking on real speaker) still want an owner's phone.
  Pair, connect, voice and asks have run live between the phone and desktop.

## Project layout

```
berrylink/
├── android/            Kotlin Compose phone app (face, pairing, voice)
│   └── app/…
├── desktop/            Python Qt gateway
│   ├── berrylink/      app, server, desktop tools, AI gateways, protocol
│   └── tests/          80-test suite
├── dist/               built APK output (release binaries → releases)
├── docs/VERIFICATION.md        live verification walkthrough
├── docs/screenshots/           capture evidence screenshots
├── packaging/          .desktop launcher + icon + install script
├── scripts/            helper entrypoints (build-android, run-desktop)
└── licenses/           full third-party license texts (see NOTICE.md)
```

## License

This project is [MIT](LICENSE) — © 2026 Sai Kishore. Third-party parts are
covered by their own licenses; the summary table is in
[NOTICE.md](NOTICE.md) and full texts live under [licenses/](licenses/).
The OFL font notices additionally ship inside the APK at
`android/app/src/main/assets/licenses/`.

## Verification trail

[docs/VERIFICATION.md](docs/VERIFICATION.md) documents what was tested at
every working round: pairing (six-digit and codeless), ask flows, action
Allow-gating, screenshot/OCR behavior, and the current tally of desktop tests
(80 passing).
