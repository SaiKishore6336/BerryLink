# Screenshots

These captures were taken from the real Qt desktop process under Xvfb on
2026-10-21. Xvfb has no compositor, so the overlay screenshots show a black
backdrop; this is a capture-environment artifact, not the app's background on a
normal desktop.

| File | What it shows |
| --- | --- |
| `desktop-control-panel.png` | Screen & control page: local capture/OCR ready, input control off, confirmation enabled, always-visible header STOP |
| `desktop-point-overlay.png` | Desktop cursor tethered to the target, with the speech bubble from the mock ask |
| `desktop-emergency-control-panel.png` | Emergency stop latched: header changes to RESUME, screen awareness off, input disabled |
| `desktop-emergency-overlay.png` | Overlay docked with the lock badge and emergency message |
| `phone-launch-emulator.png` | Earlier pre-face-mode Android 14 launch: animated face shell, speech bubble and pairing controls before pairing |

The phone screenshot is a single launch capture of the **pre-face-mode** build, so
it does not prove the new paired landscape face-only mode, animation timing,
microphone capture, TTS or Android NSD. Those remain for the owner's device test.
The shared emulator was left alone after that one check, and no face-mode runtime
screenshot is claimed.
