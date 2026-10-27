# Verification report

**Date:** 2026-10-22 (updated after the OpenRouter + voice-nap + semicircle-face pass, then again after the free-model + on-device-speech pass)  
**Scope:** the assembled MVP in this repository, not a claim that the phone or a
live OpenRouter/Gemini account has been tested.

## What changed in this pass

* **OpenRouter is the default AI provider.** `berrylink/openrouter_gateway.py`
  implements chat completions with tool calling (multi-round agent loop),
  `input_audio` voice parts, key validation via `GET /key` + model-id check via
  `GET /models`, and no paid fallback assumptions. A Gemini key still works as
  a secondary provider. The key is stored per provider by a generalized
  `SecretStore` (label `openrouter-api-key`) and never reaches the phone,
  config.json or logs.
* **Desktop settings UI** gained an "AI provider" dropdown (OpenRouter by
  default), an editable OpenRouter model id (`openrouter/auto` default), a
  provider-neutral key save/clear flow, and provider-aware status pills.
* **Agent chaining:** the shared system prompt (`ai_prompt.py`) instructs
  multi-step desktop tasks (launch app → open URL → look →
  click/type/press/scroll) across up to `tool_round_limit` (default 6) tool
  rounds. `open_url` accepts bare domains (`chatgpt.com` → `https://chatgpt.com`)
  and an optional `app` argument that opens the URL inside a named app such as
  Brave.
* **Voice-driven naps:** holding the face and saying "go to sleep" (or
  goodnight/nap) makes the AI call the `go_to_sleep` tool and/or reply with the
  `sleepy` mood; the phone folds into a new `SLEEPING` face (shut eyes, drifting
  Zzz, slow breath) and shows a "tap him to wake him up" pill. A tap wakes him.
  Moods arrive on every `ask` reply: happy/excited/thinking/sleepy/oops map to
  face activities while text-to-speech continues.
* **True semicircle face:** the phone body is now an exact half-disc
  (`arcTo` of a 2R×2R rect centred on the floor line — never an ellipse), with
  glow, star apex, shine, blush, brows, eyes, mouth and sparkles rebased to
  dome-relative geometry. A later pass made the canvas full-bleed: the dome
  uses the entire screen width.

## Update: free-model wall and on-device speech (same day)

* `openrouter/auto` needs credits (402 on a zero-balance account). The catalog
  was re-scanned and the effective model switched to
  `minimax/minimax-m3.1-flash:free` after a live probe confirmed proper
  OpenAI-format `tool_calls` behaviour ($0 cost).
* OpenRouter's free tier cannot take voice: of the free models with audio
  input, `thinkingmachines/inkling(-small):free` are restricted to approved
  "agentic harness" apps (403) and
  `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` demands at least $0.50
  balance for audio (402) even for a tiny request. Desktop-side free voice is
  therefore not possible.
* The Android hold-to-talk flow now transcribes speech **on the phone** with
  the platform `SpeechRecognizer` (free, no API key) and submits TEXT to the
  desktop, which works with any tool-capable free model. Live partial wording
  shows in the recording pill; the previous WAV-recording path remains as an
  automatic fallback if the device has no recognition service, and a failed
  recognizer mid-hold falls back to the recorder seamlessly.
* Release APK builds but ships unsigned; the distributable artifact remains
  `dist/app-debug.apk` (sha256 `07b6036b14d91ae62d80e5f8ad8b1a4d3f964f2852de69e56e7a3f159855d490`).

## Update 2: simple-and-fast phrase AI (no tool calling, 2026-10-23)

* The agentic loop, screen OCR context, screenshots and DesktopTools wiring
  were removed from the AI path. Every ask is now exactly **one POST** whose
  reply either maps the phrase to a launch command (`COMMAND: open_brave`) or
  is a short chat answer with a mood tag. Latency target ≈ 1–2 s per hold,
  one request per task (the old loop burned 2–4).
* New `berrylink/desktop_commands.py` owns the launchers as common async-safe
  functions (detached `Popen`): open_brave (verified `/usr/bin/brave-browser` +
  default browser), open_tlauncher (detection with an honest not-installed
  reply), open_terminal (`x-terminal-emulator` chain), open_berrylink (overlay
  activation), and kali-undercover on/off (toggle binary verified; state read
  from `~/.local/share/kali-undercover/user-profile.tar.bz2`). Emergency stop
  always blocks launches; `guess_command()` keeps the same phrases working in
  mock/offline mode.
* Free-model resilience: `openrouter_fallback_models` chain in config
  (gemma-4-26b-a4b → laguna-xs → minimax flash) is tried on 404/429/5xx,
  one limiter slot per ask. The old tool-loop pytest was replaced by
  single-shot/command/fallback tests; suite is now **66 passed**.
* Live model probes ($0): nemotron-3.5-lightning and dots/flint/nemotron-super
  are reasoning models that return empty `content`; gemma-4-31b and
  xing4.0 saturated (429); minimax-m3.1-flash deprecated (404) since the
  previous day. Primary model: **`poolside/laguna-s-2.1:free`** (262k context,
  ~1.4 s, followed the COMMAND format exactly).
* Local rate limits raised to **20/min and 500/day** to stop starving free
  quotas. Sleep is now mood-driven only (`[mood: sleepy]`); the `go_to_sleep`
  tool no longer exists. The phone APK from this morning is unchanged and
  compatible.

## Update 3: mock switch, TLauncher via .desktop, pairing UX (2026-10-23 afternoon)

* Removed the Home-page hero berry mascot per user request (sidebar brand mark
  and the pairing-dialog mark stay).

* Sidebar now carries a prominent **“Local mode — no API tokens”** switch
  (synced with the Settings checkbox; state persists via the normal config
  save). ON = fully offline, OFF = cloud AI with the saved key.
* `open_tlauncher` resolves the XDG `.desktop` entry (`Exec=` + `Path=`, field
  codes stripped) — verified live for `/usr/share/applications/tlauncher.desktop`
  (bundled JRE at `/usr/games/tlauncher`), with the old which/jar fallbacks kept.
* Pairing UX (Android): the pairing sheet now shows **“Connect — already
  paired”** for a discovered desktop whose certificate matches the saved
  pairing (`BerryViewModel.connectToDesktop`, honouring fresh discovered
  endpoints); “pair again” with a code remains available for resets. Desktop
  `_auth` now logs `Phone authenticated` / `Auth rejected` to make token
  problems visible next time.
* Forensics (before this change): 9 lifetime pairings with 0 successful
  stored-token authentications and no post-relaunch WS connects — consistent
  with the phone losing (or never reaching) its stored pairing; the
  one-tap-connect path above removes the user-visible pain while logs will pin
  any remaining root cause.
* APK rebuilt: `dist/app-debug.apk`
  sha256 `02c9dd90c8f17cafb1f86048f01a862ba4342badfcbbead18311f710ff4890dd`
  (10,516,038 bytes).
* Launch-command crash fixed (caught live at 13:56): `server._command_runner`
  referenced `self.bridge` but the server's UI port is `self.ui`, so EVERY
  understood launch raised AttributeError in both providers ("that launch
  failed"). Fixed to `self.ui.show_overlay`, runner now logs full tracebacks
  and never degrades to a silent generic reply; verified all four launchers +
  emergency-stop path directly, 66/66 tests pass.
* Emulator-driven pairing verification (2026-10-23 evening):
  Booted AVD `BreakOverlayTest` headless. SwiftShader (`-gpu swiftshader_indirect`)
  crashed the whole emulator (`Killed by SIGSEGV`) ~5–10 s after launching the
  companion app (three repeats); `-gpu host` is stable — keep using it:
  `ANDROID_AVD_HOME=~/.config/.android/avd $ANDROID_HOME/emulator/emulator
  -avd BreakOverlayTest -no-window -gpu host -no-audio -no-boot-anim -no-snapshot`.
  Paired the emulator against the live desktop through mDNS discovery
  (TVS: desktop dialog code via xdotool/import screenshots), then force-stopped
  and relaunched the app: `loadPairing: ok` → `connectSaved … discoveredMatch=true`
  → `Authenticated to BerryLink on kali` in ~1.1 s — **no 6-digit code**.
  Verified again after a second rebuild. Saved prefs inspected via
  `run-as … cat shared_prefs/berrylink_secure.xml` (deviceId/token/host/port/pin all present).
* Companion APK refreshed: `dist/app-debug.apk` sha256
  `2816b9e11acd365e6914bad8ba148fe1dce2baa0361265f949318017ae078722`
  (10,516,038 bytes) — includes tap-to-connect, persistent auto-reconnect and
  new pairing diagnostics: `SecureStore` now logs every load failure reason and
  the offline screen shows a red banner (e.g. "Stored key could not be decrypted
  (device security reset?). Pair once more.") instead of silently acting
  unpaired; orphaned metadata is auto-cleared so the next pairing is clean.
* Forensic expectation for the real LAVA phone: 9 lifetime pairings / 0
  stored-token reconnects matches symmetric keystore/token loss on the phone
  (or an older APK without the persistence fix). The new build will name the
  reason on screen after the first relaunch.

## Result summary

| Area | Result | Evidence |
| --- | --- | --- |
| Desktop unit/integration tests | **61 passed** | `pytest desktop/tests -q` (incl. new `test_openrouter_gateway.py`) |
| Android unit tests | **15 passed** | Gradle `testDebugUnitTest` XML |
| Kotlin/Compose debug build | **Passed** | `assembleDebug` produced a 10,516,038-byte APK (`dist/app-debug.apk`, sha256 `605868412c07855f5cf6e09215daba7e2b192e3dd187819bde7c3fca6233f9bc`) |
| PC cursor stream | **IMPLEMENTED AND TESTED** | Desktop samples the cursor and pushes cursor events only to paired phones |
| Paired eye follow | **COMPILE/TEST VERIFIED; NOT RUNTIME-VERIFIED** | Phone face uses `cursorGaze` and touch override while paired |
| Android lint | **Passed** | `lintDebug`: 0 errors; remaining warnings reviewed |
| APK manifest / package ID | **Passed** | `app.berrylink.companion`, `MainActivity`, minSdk 26 |
| APK signature | **Debug signed, v2 verified** | APK Signature Scheme v2 |
| Real desktop process under Xvfb | **Passed in mock mode** | Local TLS pair, ask, point, overlay, header/sidebar STOP, emergency latch |
| mDNS advertisement | **Passed on this host** | Advertised on port 8765 at [LAN-DESKTOP] |
| Local screen capture / OCR | **Available in the smoke environment** | Xvfb + ImageMagick; bundled Tesseract 5.5.0 |
| Android 14 emulator launch | **Passed (brief, pre-face-mode)** | Base `MainActivity` rendered; no fatal exception |
| Paired face-only landscape mode | **BUILD/LINT VERIFIED; NOT RUNTIME-VERIFIED** | New Compose code compiled; shared AVD left untouched |
| Physical Android app / face animation | **NOT VERIFIED** | No physical phone was connected |
| Phone microphone, TTS, Android NSD | **NOT VERIFIED** | Requires the owner's phone |
| Live OpenRouter / Gemini request | **NOT VERIFIED** | No API key was provided or used |
| Live X11 input automation | **NOT VERIFIED** | Guarded tool tests only; no click/type was sent in the smoke run |

## Environment

```text
Kali GNU/Linux Rolling
Linux 7.1.5+kali-amd64 x86_64
Python 3.14.7
PyQt6 6.11.0
Pillow 12.3.0
websockets 16.0
zeroconf 0.151.5
cryptography 49.0.0
pynput 1.8.2
pytest 9.1.1
Gradle 8.7
Android compileSdk/targetSdk 34, minSdk 26
```

The Android SDK was at `$HOME/Android/Sdk`. No physical phone was connected. A
shared Pixel 6 / Android 14 x86_64 emulator was used for one install-and-launch
check of the **base app before face mode was added**; the owner asked that the
shared AVD be left alone afterwards, so no further emulator interaction was
performed and the face-only build was not launched there.

```text
$ adb devices -l
emulator-5554  device product:sdk_gphone64_x86_64 model:sdk_gphone64_x86_64
```

## Automated tests

### Desktop

Command:

```bash
/tmp/berryvenv/bin/python -m pytest desktop/tests -q --disable-warnings
```

Result:

```text
.............................................................            [100%]
61 passed in 6.5s
```

Coverage includes strict wire parsing, pairing windows and TLS identity,
certificate fingerprints, secret redaction, guarded desktop tools and emergency
stop, mock AI, a fake Gemini Interactions HTTP server, a fake OpenRouter
chat-completions server (tool round-trips, quota/auth/credit error mapping,
key validation, mood-tag parsing, history memory), and a live TLS
WebSocket/pairing/auth/ask flow.

**Test harness note:** on this Python 3.14 environment, the `websockets` 16 sync
client intermittently stalls when opening several TLS 1.3 connections in rapid
succession. The minimal reproducer fails outside BerryLink too. The live-server
test client therefore pins TLS 1.2 to make the transport tests deterministic.
The desktop server itself accepts TLS 1.2 and TLS 1.3; exact pinning is
independent of the TLS version, and the Android client negotiates normally. This
The desktop server itself accepts TLS 1.2 and TLS 1.3; exact pinning is
independent of the TLS version, and the Android client negotiates normally. This
is a test-client limitation, not a production security downgrade.

### PC cursor stream

The desktop samples the real pointer every 33 ms on the Qt GUI thread and
normalizes it against the active screen's virtual geometry. Only authenticated
phones receive the event. The cursor loop is independent of the request path
and fans out the latest sample to all paired phones. The server skips unchanged
samples, so a still pointer does not create idle Wi-Fi traffic.

The paired-phone protocol event is:

```json
{"kind": "event", "method": "cursor", "payload": {"x": 0.56, "y": -0.28}}
```

On the phone `BerryViewModel` stores it as a `GazePoint` in `UiState.cursorGaze`
and clamps it to [-1, 1]. `FaceModeScreen` then uses that as the default gaze;
your finger takes over only while a finger is actually on the face.
`WireMessage.number()` is covered by the new `numberHelpersAcceptNumericPayloadsOnly`
unit test; the Android event whitelist accepts the `cursor` method explicitly.

The new integration test proves a paired phone receives a cursor event. This
does not prove live phone rendering, which still needs the physical phone.

### Android

Command:

```bash
ANDROID_HOME=$HOME/Android/Sdk ANDROID_SDK_ROOT=$HOME/Android/Sdk \
  ./android/gradlew -p android :app:testDebugUnitTest :app:assembleDebug --rerun-tasks
```

Results:

```text
WavWriterTest    3 passed
WireTest         8 passed
FingerprintTest  4 passed
TOTAL           15 tests, 0 failures, 0 errors, 0 skipped
BUILD SUCCESSFUL
```

The new `FaceModeScreen`, `CompanionWindowMode`, interactive `gazeTarget`, the
settings **Ask by typing** action and the pair-success wording were compiled in
this build. `lintDebug` also passes. They are **not** runtime-verified on a phone
or emulator, per the owner's request not to disturb the shared AVD.

The APK was rebuilt and published after the face-mode and cursor-stream changes;
its current checksum is recorded below.

## APK inspection

Artifact:

```text
dist/app-debug.apk
Size     10,516,038 bytes
SHA-256 53bcadf30163a74f58e09e62320e4df03242a1f725584b75d7827b8a46407b53
```

`aapt dump badging`:

```text
package: name='app.berrylink.companion' versionCode='1' versionName='0.1.0'
sdkVersion:'26'
targetSdkVersion:'34'
launchable-activity: name='app.berrylink.companion.MainActivity' label='BerryLink'
uses-permission: INTERNET
uses-permission: ACCESS_NETWORK_STATE
uses-permission: CHANGE_WIFI_MULTICAST_STATE
uses-permission: RECORD_AUDIO
```

`apksigner verify --verbose --print-certs`:

```text
Verifies
Verified using v2 scheme (APK Signature Scheme v2): true
Signer #1 certificate DN: C=US, O=Android, CN=Android Debug
```

This is a debug APK. There is no release keystore, Play Store packaging, or
production signing.

## Android emulator launch check

A pre-face-mode debug APK was installed and `MainActivity` was cold-launched on
the Android 14 emulator at 1080×2400. The animated face, speech bubble, status
chips and pairing controls rendered; logcat showed no fatal exception. The
capture is
[`docs/screenshots/phone-launch-emulator.png`](screenshots/phone-launch-emulator.png).

This proves that the earlier APK installs and the base Compose screen renders on
Android 14. It does **not** cover the new paired face-only mode, landscape lock,
immersive bars, touch-following eyes, tap emotions, hold-the-face recording,
microphone capture, text-to-speech audio, or Android NSD. Those require the
owner's phone (and a real audio route). The shared emulator was not used again.

## Runtime desktop smoke test

The real `BerryLinkController`, Qt window and overlay were started under Xvfb
with temporary config/data/state paths, mock AI and hotkeys disabled. A
simulated phone connected over the pinned TLS WebSocket, paired with the open
six-digit window, and sent an ask.

Evidence in `/tmp/opencode/bl-smoke/`:

```json
// pair-ask.json
{
  "ok": true,
  "pin_match": true,
  "unauth_code": "unauthorized",
  "paired": true,
  "reply": "I'm pointing right at the cursor.",
  "provider": "mock",
  "tools_used": ["point_at_spot"],
  "device_id": "dev_8b72b0042e6195c6"
}
```

```json
// point-state.json
{
  "mode": "point",
  "point_target": [640.0, 400.0],
  "pos": [554.1470097970972, 318.0872724827212],
  "bubble": "I'm pointing right at the cursor.",
  "highlight": null
}
```

After the emergency stop:

```json
{
  "emergency": true,
  "mode": "dock",
  "point_target": null,
  "bubble": "Emergency stop. I won't touch anything until you resume.",
  "control": {
    "control_enabled": false,
    "screen_awareness": false,
    "emergency_stop": true
  }
}
```

The app log recorded the mDNS advertisement and the successful pair/ask:

```text
mDNS advertised as BerryLink on kali._berrylink._tcp.local. on port 8765 ([LAN-DESKTOP])
Paired new phone: Visual test phone
Ask from Visual test phone: audio=False text=True screen=False screenshot=False
tool=point_at_spot ok elapsed=0.00s
```

The same run captured the updated header control: `STOP` is present on the
Screen & control page, and the emergency capture shows the header button changed
to `RESUME` while the sidebar shows `Resume controls`. The one-click header
button calls the same `_emergency_clicked` path as the sidebar and global hotkey.

### Screenshot caveat

The smoke run used Xvfb without a compositor. The full-screen transparent
overlay therefore paints an opaque black backdrop in root captures. The
overlay-window screenshots still show the cursor, tether, bubble and badges, and
the control-panel screenshots were captured by briefly hiding the overlay. They
are evidence for layout/state, not a claim about a composited real desktop. The
current panel images also show the always-visible header STOP/RESUME control.

## What the owner still needs to test on the phone

1. App install, launch, and continuous face animation (blinks, saccades, hops).
2. Pairing through Android NSD, or manual IP + full fingerprint.
3. After pairing: landscape rotation, hidden system bars, keep-screen-on, and
   the face-only layout with its small settings gear.
4. Touch tracking with the eyes, tap-to-smile, hold-to-talk recording, and the
   PC-cursor eye tracking while paired.
5. Release-to-send and Android speech playback.
6. Reconnect after backgrounding or Wi-Fi interruption; typed questions from the
   settings overlay.
7. Any crash, visual glitch, permission error, or unreadable layout.

Live Gemini is separately unverified until a free-tier key is pasted into the
Linux app and a real ask is made. The fake-server test confirms the expected
HTTP request shape but cannot confirm the real service or quota.

## Session 2026-10-24 — six-bug fix round

### Desktop provider switch (OpenRouter → Qwen on xkiro)

- Generalised the OpenAI-compatible gateway to carry both backends. The
  provider is a constructor parameter of `OpenRouterGateway`; xkiro uses
  `https://api.xkiro.com/v1` with the free Qwen catalogue (default
  `qwen/qwen3-omni-flash:free`, `qwen3-vl-plus:free` and friends as fallbacks).
  `build_ai` prefers `config.ai_provider` and falls through xkiro →
  openrouter → gemini → mock based on which keys actually exist locally.
- UI: provider list is now Qwen (xkiro) / OpenRouter / Gemini; pills, hints,
  placeholder, docs links and the model row say xkiro when the desktop uses
  it. `xkiro_api_key` lives in secrets.json (0600) and never leaves the
  desktop. Key validation goes through `GET /v1/models` (no tokens spent).
- Live verified: `build_ai` picks `xkiro https://api.xkiro.com/v1 
  qwen/qwen3-omni-flash:free` when a key exists, `openrouter` when only the
  old key is present, and `mock` otherwise. 66/66 pytest.

### Bug 1 — mock-mode launches

- `guess_command` now strips "hey berry / ok berry / please / could you"
  prefixes and accepts run / start / fire up / bring up as launch verbs;
  "come home", "show yourself", "berrylink come up" raise the desktop panel.
  All 14 phrase probes pass, including "run brave" and "start minecraft",
  which failed before.
- Mock wording is provider-neutral ("Add a free AI key (Qwen via xkiro)…").
  Voice-only asks still cannot be understood offline — that is
  honest product behaviour, not a bug; typed asks launch apps.

### Bug 3 — TLauncher from the menu entry

- `_desktop_exec` now checks `~/.local/share/applications` before
  `/usr/share/applications`, so the user's edited launcher wins. Live result
  for `tlauncher`: `env __NV_PRIME_RENDER_OFFLOAD=1 … java … starter-core.jar`
  with `Path=/usr/games/tlauncher` — exactly what clicking the menu icon runs.

### Bug 4 — undercover mode

- `_launch` builds a child environment with `_session_env()`: when the
  server runs without session vars it reconstructs `XDG_RUNTIME_DIR`
  (`/run/user/<uid>`), `DBUS_SESSION_BUS_ADDRESS` (`unix:path=…/bus`),
  `DISPLAY` (`:0` from `/tmp/.X11-unix`) and `XAUTHORITY`, then hands that
  env to every detached child. Verified by stripping all five variables and
  rebuilding them successfully.
- Live toggle verified on the real Xfce session: ON writes
  `user-profile.tar.bz2` and switches the theme to Windows-10; OFF restores
  `gtk-master` and removes the state file; `undercover_is_on()` tracks both.

### Qwen on xkiro — live connection (2026-10-24)

- Owner supplied the xkiro key and confirmed the id
  `qwen/qwen3.8-omni-flash:free` (1M context, up to 65K output). It is present
  in xkiro's 97-model catalogue (checked via keyless `GET /v1/models`), so it
  became the shipped default (fallbacks: `qwen3.5-omni-flash:free`,
  `qwen3.7-flash:free`, `qwen3-vl-plus:free`).
- Key stored in secrets.json (restricted-file backend, mode 0600) as
  `xkiro_api_key`; live config flipped to `ai_provider: xkiro`,
  `use_mock_ai: false`. Key validated via `/v1/models` (no tokens spent).
- One live ask went end-to-end: prompt 518 tokens → correct clipped reply with
  trailing mood tag parsed (`happy`). A second ask through the real
  `build_ai` chain reported `provider=xkiro`, `https://api.xkiro.com/v1`.
  Free id — no credits consumed.
- Fixed while doing this: the ask log line and `AIResult.provider` always said
  "openrouter"; both now carry the actual provider, so the phone bubble and
  status pills show QWEN/XKIRO correctly.

### What the owner does next

1. Start the desktop app — it loads the xkiro key and provider from config
   with no further setup needed.
2. Install `dist/app-debug.apk`
   (sha256 `93c5533f839d66cf7ed21fe036ee4254a1220589972bad087004ea6fa719d98c`)
   on the Lava phone.
3. Re-test: typed "launch tlauncher" in mock or AI mode (should start the
   menu-version of TLauncher), "undercover on/off", a voice ask (now via
   Qwen), the thinking dots + Try again pill, and the 6-digit-code flow —
   if the red pairing banner appears, report its exact text.

### Bug 5 — phone face, thinking, errors

- Face pulled in by 5% (`faceWidth = maxWidth * 0.95f`).
- Three amber thinking dots now hover above the dome while an ask is in
  flight (the bubble keeps its "Thinking it over…" row).
- Failed typed asks show a crimson Try again pill under the error bubble
  that re-sends the last ask (`UiState.lastAsk` / `viewModel.retryLastAsk`).

### APK

- Debug build succeeded; published `dist/app-debug.apk`,
  sha256 `93c5533f839d66cf7ed21fe036ee4254a1220589972bad087004ea6fa719d98c`.
  Install this build before retesting the 6-digit-code / auto-join flow, and
  report whether the red diagnostics banner appears.

## Session 2026-10-24 (round 2) — voice, knowledge, codeless connect

### Notice removal + knowledge answers

- The mock ask payload no longer carries the "Local mock mode … Add an AI key"
  notice — the phone never shows it now; local-mode fallback replies were
  rewritten as friendly one-liners instead of refusals.
- Berry's persona (shared by every provider) now explicitly says: answer any
  general question — news, tech, games, people, ideas — naturally from what
  you know, like a friend, and say when unsure instead of refusing. Chat
  replies are warm, contracted, 1-3 sentences, speakable, no lists/emoji.
- xkiro/OpenRouter path max_tokens raised 150 → 600 so "tell me about …"
  answers aren't clipped. Gemini already had 1400.
- Tests: mock/server expectations updated (69 total now).

### Human-sounding voice on the phone

- TTS init no longer accepts the engine's default robotic voice: it ranks the
  engine's English voices by quality (VERY_HIGH/ENHANCED network builds first,
  Google "tpd"/"iom" builds preferred) and sets the first that sticks.
- Rate 1.03/pitch 1.12 (the chipmunk settings) → 0.95/1.05 for natural pace.
  Any engine without an enhanced voice falls back to its default gracefully.

### One-tap connect (codeless pairing)

- Desktop: `pair.request` with `codeless: true` pops the proven Allow/Deny
  dialog on the desktop (threaded confirm — the server keeps serving other
  connections while it waits). Allow → the phone is paired with a token
  instantly and auto-authenticates; Deny → "pairing_denied" to the phone.
  Off-switch: "Allow one-tap pairing" checkbox on the desktop home card
  (config `allow_codeless_pairing`, default on; then the old 6-digit code
  still works as before). `pairing.py` gained `mint_device()` shared by both
  paths.
- Phone: a Connect button with the pair sheet ("Connect — the desktop will
  ask you") and a big Connect on the dashboard for every non-connected state:
  paired phones reconnect straight to the stored desktop, fresh phones run a
  ~6 s NSD discovery and one-tap pair with the first BerryLink found. Client
  `pairCodeless` allows two minutes for the owner to reach the desktop.
- Covered by 3 new live-server tests: deny path (dialog raised, nothing
  paired), allow path (paired + token auth works on the next connection), and
  the disabled flag (pairing_required). 69/69.

### APK

- `dist/app-debug.apk` sha256
  `dd398d896d7b9b684fd54f36cc6911e2a41d57dba61b05f16c1038657717301d`.
  Install, then: press Connect (or Pair → Connect) and watch for the Allow
  prompt on the desktop screen.

## Session 2026-10-24 (round 4) — screen actions behind the toggle, per-action Allow

### Tool actions return — strictly gated (Qwen/xkiro desktop path)

- Phrases like "click the Settings button", "type hello in the field",
  "press ctrl+s", "scroll down", "drag L3 to L9" now work again — but ONLY
  when the desktop owner has "Allow input control" enabled AND the phrase
  contains an action verb (`ACTION_INTENT` regex on the request text). Every
  other ask takes the exact same one-shot path as before; audio-only asks
  skip the gate (no transcript on the server).
- Design: two deterministic rounds instead of provider function-calling.
  Round 1 — server reads the screen locally (`look_at_screen`, OCR ids like
  `L12`) and appends `ACTION_INSTRUCTION` to the prompt. Round 2 — the model
  answers `ACTION: <name> {json}` plus a spoken line; `parse_action_reply`
  (ai_prompt.py) splits it. Tools are limited to
  click | type_text | press_keys | scroll | drag; open_app/open_url stay on
  the existing command path. OpenRouterGateway gained an opt-in
  `allow_actions` flag (xkiro Qwen lives there); GeminiGateway/MockAI just
  accept the flag and never propose actions — mock/local mode stays
  hands-off.
- Execution: the server runs the tool in a worker thread through
  `DesktopTools.call(..., allow_tools=True)`, so EVERY executed action rises
  the proven Allow/Deny dialog first (`confirm_actions` defaults True;
  consequential-looking targets are forced even with the confirm toggle
  off). Deny → "Okay, I won't touch the screen then."; screen/emergency/
  control errors map to friendly spoken lines. Unknown tool names from the
  model are rejected server-side (`SERVER_ACTION_TOOLS` allowlist).
- Tests: parser shapes (valid/unknown name/bad JSON/chat text), gateway
  ACTION reply → proposed action + prompt carries instruction + unflagged
  ask stays raw, live-server click ask → Allow dialog raised then denied
  (tool never fires), and the toggle-off case (no OCR round, no dialog,
  chat reply unchanged). **74 passed** (69 → 74).
- Desktop-only change: no APK rebuild needed. To use: flip "Allow input
  control" on the desktop card, then ask "click the Settings button" and
  confirm the Allow dialog.

### Live-check follow-up: the re-locked toggle explained (still 74)

- First live try answered "I can't click buttons for you…": the log showed
  every ask with `action=False` — input control re-locks OFF each desktop
  restart (by design), and the previous session's toggle doesn't survive.
  With control off, "click…" went to Qwen as a plain chat and improvised a
  refusal. The flow itself is fine (OCR round runs regardless of the
  attach-screenshot flag).
- Fix: when the phrase asks for an action but control is off
  (`action=wish` in the log), the ask stays one plain chat round, but the
  prompt carries `ACTION_DISABLED_NOTICE` so Berry answers "enable Allow
  input control on the desktop app and ask again" instead of a fake
  refusal. Non-action asks and mock mode are untouched; the gate variables
  are now wish/ready with `ready` required for OCR + parse + execution.

### "What can you see on the screen?" now answers with eyes (round 4b)

- Screen-see questions (`SCREEN_QUERY_INTENT` in server.py: "what can you see
  right now on the screen?", "what do you see", "describe/read my screen",
  "look at the screen") run the same one local OCR round as the action flow
  and the model receives a `SCREEN_DESCRIBE_INSTRUCTION`: describe what's
  visible in 1–2 warm sentences, never read ids/coords aloud, admit it when
  the read is sparse. No execution, no confirmation — purely a look.
- JPEG attach: only when the phone asked (`include_screenshot`) AND the
  desktop allows screenshots to the provider → Look returns the encoded
  frame and the Qwen ask carries it as an `image_url` part (gateway already
  supported it). Otherwise OCR text only.
- With screen awareness off, the ask stays blind but the prompt carries
  `SCREEN_OFF_NOTICE`: Berry points at "Let BerryLink look and point"
  instead of inventing a view of a blank screen — same honesty pattern as
  the input-control notice.
- Captions/logs: "Reading your screen…" during the look; ask log now ends
  `action=ready|wish|off screen=looked|failed|wish|off`. Tests: see-question
  OCR chain, awareness-off notice, and the JPEG attach chain with a real
  PNG. **77 passed** (74 → 77).

### Double click + "open the key.txt file" (round 4c, still Allow-gated)

- Before: "double click" produced a single click (count unknown to the
  model) and "open <file>" left the action flow entirely (no verb) — both
  dead ends for the user's desktop-file case.
- Click's existing `count: 2` support is now taught in ACTION_INSTRUCTION:
  double-click whenever the user says double click or asks to open a file or
  icon visible on screen (e.g. key.txt on the desktop). `ACTION_INTENT`
  additionally treats a filename with a known extension present in the text
  as an action wish, so "open the key.txt file" runs the same screen round →
  Allow dialog → double click. No new tool, no new execution path (count is
  validated/clamped 1..2 inside `_click`); app launches ("open brave")
  remain the untouched deterministic flow; when the icon isn't on screen the
  model answers honestly. Mock/local mode still never acts.
- Tests: regex coverage (filenames yes, app names/text-file questions no),
  count-2 parse, and a live-server open-file ask proving the Allow dialog
  fires before any execution. **80 passed** (77 → 80).
