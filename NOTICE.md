# NOTICE

Original code in this repository is MIT-licensed (see LICENSE, Copyright (c) 2026 Sai Kishore).
It is built on the following third-party components. With the exception of the two fonts
bundled inside `android/app/src/main/assets/`, everything below is a build/runtime
dependency installed by the user's own tooling (pip / Gradle) and is **not** distributed
in this repository; the official upstream source and license apply.

## Desktop gateway (Python)

| Component | Purpose | License | Source |
|---|---|---|---|
| PyQt6 | Qt GUI for the desktop companion (window/tray/dialogs) | GPL v3 (or commercial, Riverbank) | https://riverbankcomputing.com/software/pyqt/intro |
| websockets | TLS WebSocket server on the LAN | BSD-3-Clause | https://github.com/python-websockets/websockets |
| Pillow | Screen capture encoding, JPEG conversion | MIT-CMU (HPND variant) | https://github.com/python-pillow/Pillow |
| zeroconf | mDNS discovery/desktop advertisement | LGPL-2.1-or-later | https://github.com/python-zeroconf/python-zeroconf |
| cryptography | TLS identity generation and pairing crypto | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| pynput | Global hotkeys (emergency stop, overlay toggle) | LGPL-3.0 | https://github.com/moses-palmer/pynput |

`pytest` is a development-time test dependency; it is not shipped with the app.

## Android companion (Kotlin)

| Component | Purpose | License | Source |
|---|---|---|---|
| Jetpack Compose / AndroidX (BOM 2024.06.00, activity-compose, lifecycle, core-ktx) | UI framework and runtime libraries | Apache-2.0 | https://android.googlesource.com/platform/frameworks/support |
| kotlinx-coroutines-android 1.8.1 | Concurrency | Apache-2.0 | https://github.com/Kotlin/kotlinx.coroutines |
| kotlinx-serialization-json 1.6.3 | Protocol envelope JSON encoding | Apache-2.0 | https://github.com/Kotlin/kotlinx.serialization |
| OkHttp 4.12.0 | WebSocket client to the desktop | Apache-2.0 | https://github.com/square/okhttp |
| JUnit 4.13.2, kotlinx-coroutines-test, kotlinx-serialization test | Unit tests (not shipped in the APK) | EPL-1.0 / Apache-2.0 | https://github.com/junit-team/junit4 |

## Fonts shipped inside the APK (`android/app/src/main/assets/licenses/`)

| Font | License |
|---|---|
| Fredoka (fredoka.ttf) | SIL Open Font License 1.1 (OFL-Fredoka.txt) |
| IBM Plex Sans (ibm_plex_sans.ttf) | SIL Open Font License 1.1 (OFL-IBMPlex.txt) |

The existing app already ships these OFL texts inside the APK assets; copies of the
files, plus the desktop dependency license texts, live in the top-level `licenses/`
directory.

## AI providers (not bundled code — network services)

BerryLink talks to model APIs you configure yourself. keys never leave the desktop:
they are validated once and stored with file mode 0600 in `~/.config/berrylink/secrets.json`.
The primary provider is Qwen models through an OpenRouter-compatible service (xkiro),
requested with `:free` model ids only; offline mock mode needs no key at all.
