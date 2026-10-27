"""Global X11 hotkeys via pynput.

The emergency stop is intentionally handled by a global listener, not a Qt
shortcut: it must work even when another application has focus.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable


class HotkeyManager:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.log = logger or logging.getLogger("berrylink.hotkeys")
        self._listener = None
        self._lock = threading.RLock()
        self.error: str | None = None
        self.bound: dict[str, str] = {}

    def start(
        self,
        *,
        emergency: str,
        toggle_overlay: str = "",
        demo_point: str = "",
        on_emergency: Callable[[], None] | None = None,
        on_toggle_overlay: Callable[[], None] | None = None,
        on_demo_point: Callable[[], None] | None = None,
    ) -> bool:
        self.stop()
        mapping: dict[str, Callable[[], None]] = {}
        labels: dict[str, str] = {}
        if emergency and on_emergency:
            mapping[emergency] = on_emergency
            labels[emergency] = "emergency stop"
        if toggle_overlay and on_toggle_overlay:
            mapping[toggle_overlay] = on_toggle_overlay
            labels[toggle_overlay] = "toggle overlay"
        if demo_point and on_demo_point:
            mapping[demo_point] = on_demo_point
            labels[demo_point] = "demo point"
        if not mapping:
            self.error = "No hotkeys configured."
            return False
        try:
            from pynput import keyboard

            listener = keyboard.GlobalHotKeys(mapping)
            listener.daemon = True
            listener.start()
            # pynput's listener.start() is asynchronous; wait() is available on
            # the X11 backend and confirms that the grab succeeded.
            wait = getattr(listener, "wait", None)
            if callable(wait):
                try:
                    wait(2.0)
                except TypeError:
                    wait()
            if not getattr(listener, "running", False):
                raise RuntimeError("Global hotkey listener did not start.")
            with self._lock:
                self._listener = listener
                self.bound = labels
                self.error = None
            self.log.info("Global hotkeys active: %s", ", ".join(f"{k} ({v})" for k, v in labels.items()))
            return True
        except Exception as exc:
            self.error = (
                "Global hotkeys are unavailable. On X11 install python3-pynput; "
                "use the on-screen Emergency Stop button instead."
            )
            self.log.warning("Global hotkeys unavailable: %s", type(exc).__name__)
            return False

    def stop(self) -> None:
        with self._lock:
            listener = self._listener
            self._listener = None
            self.bound = {}
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass

    def status(self) -> dict[str, object]:
        return {
            "active": self._listener is not None and bool(getattr(self._listener, "running", False)),
            "bound": dict(self.bound),
            "error": self.error,
        }
