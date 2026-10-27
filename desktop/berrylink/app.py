"""BerryLink desktop entry point and service wiring."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .audio_recorder import recorder_backend
from .config import Config, ConfigError, GEMINI_MODEL
from .desktop_tools import ControlState, DesktopTools
from .gemini_gateway import AIError, AskInput, ConversationState, GeminiGateway, build_ai
from .hotkeys import HotkeyManager
from .mdns import MdnsAdvertiser
from .meeting import MeetingError, MeetingManager, MeetingStore
from .openrouter_gateway import OpenRouterGateway
from .overlay import BerryOverlay
from .pairing import PairingManager, ensure_tls_identity, local_ipv4_addresses
from .paths import AppPaths
from .screen import ScreenAwareness
from .security import (
    SecretStore,
    configure_logging,
    redact,
    register_secret,
)
from .server import BerryLinkServer, ServerStartError
from .ui import MainWindow, THEME, UiBridge, load_fonts, make_app_icon


APP_ID = "app.berrylink.desktop"


class AIHolder:
    """Holds the current provider and the desktop-only keys in memory."""

    def __init__(
        self,
        config: Config,
        gemini_key: str | None,
        openrouter_key: str | None,
        xkiro_key: str | None,
        logger,
    ) -> None:
        self.config = config
        self.log = logger
        self._lock = threading.RLock()
        self._gemini_key = gemini_key or None
        self._openrouter_key = openrouter_key or None
        self._xkiro_key = xkiro_key or None
        for key in (self._gemini_key, self._openrouter_key, self._xkiro_key):
            if key:
                register_secret(key)
        self.rebuild()

    @property
    def has_key(self) -> bool:
        with self._lock:
            return bool(self._gemini_key or self._openrouter_key or self._xkiro_key)

    def has_key_for(self, provider: str) -> bool:
        return self.get_key_for(provider) is not None

    def get_key_for(self, provider: str) -> str | None:
        with self._lock:
            if provider == "gemini":
                return self._gemini_key
            if provider == "openrouter":
                return self._openrouter_key
            if provider == "xkiro":
                return self._xkiro_key
            return None

    def get(self):
        with self._lock:
            return self._ai

    def configure(
        self,
        gemini_key: str | None,
        openrouter_key: str | None = None,
        xkiro_key: str | None = None,
        *,
        use_mock: bool | None = None,
    ) -> None:
        with self._lock:
            self._gemini_key = gemini_key or None
            self._openrouter_key = openrouter_key or None
            self._xkiro_key = xkiro_key or None
            if use_mock is not None:
                self.config.use_mock_ai = bool(use_mock)
            for key in (self._gemini_key, self._openrouter_key, self._xkiro_key):
                if key:
                    register_secret(key)
            self.rebuild()

    def refresh(self) -> None:
        with self._lock:
            self.rebuild()

    def rebuild(self) -> None:
        self._ai = build_ai(
            self.config,
            self._gemini_key,
            self._openrouter_key,
            xkiro_key=self._xkiro_key,
            logger=self.log,
        )


class BerryLinkController(QObject):
    def __init__(self, paths: AppPaths, config: Config, *, no_hotkeys: bool = False, logger=None) -> None:
        super().__init__()
        self.paths = paths
        self.config = config
        self.log = logger or logging.getLogger("berrylink")
        self._config_lock = threading.RLock()
        self._cleanup_lock = threading.Lock()
        self._cleaned = False
        self._quitting = False
        self.no_hotkeys = no_hotkeys

        self.secret_store = SecretStore(paths)
        gemini_key = self.secret_store.get_key("gemini")
        openrouter_key = self.secret_store.get_key("openrouter")
        xkiro_key = self.secret_store.get_key("xkiro")
        if gemini_key:
            register_secret(gemini_key)
        if openrouter_key:
            register_secret(openrouter_key)
        if xkiro_key:
            register_secret(xkiro_key)
        self.ai_holder = AIHolder(config, gemini_key, openrouter_key, xkiro_key, self.log)
        self.identity = ensure_tls_identity(
            paths.tls_dir,
            config.display_name,
            local_ipv4_addresses(),
        )
        self.pairing = PairingManager(paths.devices_file)
        self.control = ControlState(
            enabled=False,  # input control is always re-locked at startup
            screen_awareness=config.screen_awareness_enabled,
        )
        self.bridge = UiBridge(self.control)
        self.bridge.set_emergency_callback(self._emergency_side_effects)
        self.screen = ScreenAwareness(
            hide_overlay=self.bridge.hide_overlay,
            show_overlay=self.bridge.show_overlay,
        )
        self.tools = DesktopTools(
            config,
            self.screen,
            self.bridge,
            self.control,
            confirm=self.bridge.confirm,
            logger=self.log,
        )
        self.meeting_store = MeetingStore(paths.notes_dir, self.log)
        recovered = self.meeting_store.recover_interrupted()
        if recovered:
            self.log.info("Marked %s interrupted meeting session(s).", recovered)
        self.meeting = MeetingManager(
            config,
            self.meeting_store,
            self.ai_holder.get,
            on_change=self._meeting_changed,
            logger=self.log,
        )
        self.server = BerryLinkServer(
            config,
            self.pairing,
            self.identity,
            self.ai_holder.get,
            self.tools,
            self.meeting,
            self.bridge,
            self.log,
        )
        self.hotkeys = HotkeyManager(self.log)
        self.mdns: MdnsAdvertiser | None = None
        self._server_running = False
        self.overlay = BerryOverlay()
        self.bridge.attach_overlay(self.overlay)
        self.bridge.recording_changed.connect(self.overlay.set_recording)
        self.bridge.hotkey_toggle_requested.connect(self._hotkey_toggle_overlay)
        self.window = MainWindow(self, self.bridge)
        self._server_error: str | None = None
        self._configure_overlay()
        self.overlay.show_after_capture()
        self.overlay.set_visible_preference(config.overlay_visible)
        if config.overlay_visible:
            self.overlay.show()
            self.overlay.raise_()
        QTimer.singleShot(120, self._start_services)
        QTimer.singleShot(350, self._startup_greeting)

    # --------------------------------------------------------------- lifecycle

    def _start_services(self) -> None:
        self._start_server()
        if not self.no_hotkeys:
            self._start_hotkeys()
        self.bridge.notify_runtime()
        if self._server_error:
            QTimer.singleShot(100, self._show_server_error)

    def _show_server_error(self) -> None:
        if not self._server_error:
            return
        QMessageBox.warning(
            self.window,
            "Desktop server is offline",
            self._server_error
            + "\n\nBerryLink still runs locally. Change the port in Settings and use Restart server, "
            "or close the app occupying the port.",
        )

    def _startup_greeting(self) -> None:
        if self.config.overlay_visible:
            provider = getattr(self.ai_holder.get(), "provider", "mock")
            if provider == "openrouter":
                text = "Hi! Hold the button on your phone and ask. I can look, point, and run desktop tasks."
            elif provider == "gemini":
                text = "Hi! Hold the button on your phone and ask. I can point things out on this screen."
            else:
                text = "Hi! I'm in local mock mode. Pair your phone, then ask me to point at something here."
            self.bridge.caption(text, "happy")

    def _start_server(self) -> bool:
        try:
            port = self.server.start()
            self._server_running = True
            self._start_mdns(port)
            self.log.info("BerryLink desktop ready on port %s", port)
            return True
        except ServerStartError as exc:
            self._server_running = False
            self._server_error = str(exc)
            self.log.warning("Server startup failed: %s", redact(str(exc)))
            return False
        except Exception as exc:
            self._server_running = False
            self._server_error = f"The desktop server could not start ({type(exc).__name__})."
            self.log.warning("Server startup failed: %s", type(exc).__name__)
            return False

    def _start_mdns(self, port: int) -> None:
        if self.mdns:
            self.mdns.stop()
        self.mdns = MdnsAdvertiser(
            self.config.display_name,
            port,
            self.identity.fingerprint,
            __version__,
            self.log,
        )
        if not self.mdns.start():
            self.log.info("Manual IP pairing will be required.")

    def restart_server(self) -> dict[str, Any]:
        self.log.info("Restarting desktop server")
        self._server_running = False
        if self.mdns:
            self.mdns.stop()
            self.mdns = None
        try:
            self.server.stop()
        except Exception:
            pass
        # The running server's port may differ from the edited config.
        if not self._start_server():
            raise ServerStartError(self._server_error or "The server could not restart.")
        self.bridge.notify_runtime()
        return {"port": self.server.port, "running": True}

    def _start_hotkeys(self) -> bool:
        ok = self.hotkeys.start(
            emergency=self.config.emergency_hotkey,
            toggle_overlay=self.config.overlay_hotkey,
            demo_point=self.config.point_hotkey,
            on_emergency=self.emergency_stop,
            on_toggle_overlay=lambda: self.bridge.hotkey_toggle_requested.emit(),
            on_demo_point=lambda: self.bridge.hotkey_demo_point_requested.emit(),
        )
        self.bridge.notify_runtime()
        return ok

    def _configure_overlay(self) -> None:
        self.overlay.set_visible_preference(bool(self.config.overlay_visible))
        # The desktop cursor is intentionally not tied to the PC pointer.
        # overlay_follow_pointer is kept only so older config files still load.
        self.overlay.set_emergency(self.control.emergency)

    def _toggle_overlay_hotkey(self) -> None:
        self.set_overlay_visible(not bool(self.config.overlay_visible))

    def _hotkey_toggle_overlay(self) -> None:
        self.set_overlay_visible(not bool(self.config.overlay_visible))

    def emergency_stop(self) -> None:
        self.log.warning("Emergency stop activated")
        self.bridge.trigger_emergency()

    def _emergency_side_effects(self) -> None:
        self.bridge.set_emergency(True)
        try:
            self.server.broadcast_event(
                "control.changed",
                {
                    "emergency_stop": True,
                    "control_enabled": False,
                    "screen_awareness": False,
                    "message": "Emergency stop is active. All screen and input tools are blocked.",
                },
            )
            self.server.broadcast_event(
                "emergency",
                {"active": True, "message": "Emergency stop was pressed on the desktop."},
            )
        except Exception:
            pass
        self.bridge.notify_runtime()

    def resume_controls(self) -> None:
        self.bridge.resume_controls()
        self.overlay.set_emergency(False)
        try:
            self.server.broadcast_event(
                "control.changed",
                {
                    "emergency_stop": False,
                    "control_enabled": False,
                    "screen_awareness": bool(self.config.screen_awareness_enabled),
                    "message": "Emergency stop cleared. Input control stays off until explicitly enabled.",
                },
            )
            self.server.broadcast_event("emergency", {"active": False})
        except Exception:
            pass
        self.log.info("Emergency stop cleared; input control remains off")
        self.bridge.notify_runtime()

    def _meeting_changed(self) -> None:
        try:
            self.server.notify_meeting_changed()
        except Exception:
            pass
        self.bridge.notify_runtime()

    # ------------------------------------------------------------------ status

    @property
    def server_running(self) -> bool:
        return bool(self._server_running and self.server.running)

    def ai_configured(self) -> bool:
        return getattr(self.ai_holder.get(), "provider", "mock") in ("gemini", "openrouter")

    def active_model(self) -> str:
        provider = getattr(self.ai_holder.get(), "provider", "mock")
        if provider == "openrouter":
            return self.config.openrouter_model
        if provider == "gemini":
            return self.config.gemini_model
        return "local-mock"

    def network_addresses(self, port: int | None = None) -> list[str]:
        use_port = port or (self.server.port if self.server.port else self.config.port)
        addresses = local_ipv4_addresses()
        return [f"{address}:{use_port}" for address in addresses]

    def status_snapshot(self) -> dict[str, Any]:
        ai = self.ai_holder.get()
        provider = getattr(ai, "provider", "mock")
        meeting_status = self.meeting.status()
        try:
            notes = self.meeting.list_sessions()
        except Exception:
            notes = []
        devices = self.pairing.list_devices()
        capture = self.screen.available()
        hotkeys = self.hotkeys.status()
        mdns_status = self.mdns.status() if self.mdns else {
            "running": False,
            "addresses": [],
            "error": "mDNS has not started.",
        }
        try:
            peers = self.server.peers()
        except Exception:
            peers = []
        return {
            "server_running": self.server_running,
            "port": self.server.port if self.server.port else None,
            "bind_host": self.config.bind_host,
            "provider": provider,
            "model": self.active_model(),
            "ai_provider_setting": self.config.ai_provider,
            "ai_configured": provider in ("gemini", "openrouter"),
            "has_key": self.ai_holder.has_key,
            "has_openrouter_key": self.ai_holder.has_key_for("openrouter"),
            "has_gemini_key": self.ai_holder.has_key_for("gemini"),
            "has_xkiro_key": self.ai_holder.has_key_for("xkiro"),
            "openrouter_model": self.config.openrouter_model,
            "control_enabled": self.control.enabled,
            "screen_awareness": self.control.screen_awareness,
            "emergency": self.control.emergency,
            "confirm_actions": bool(self.config.confirm_actions),
            "allow_screenshots": bool(self.config.allow_screenshots_to_gemini),
            "overlay_visible": bool(self.config.overlay_visible),
            "devices": devices,
            "peers": peers,
            "notes_count": len(notes),
            "meeting": meeting_status,
            "mdns": mdns_status,
            "hotkeys": hotkeys,
            "emergency_hotkey": self.config.emergency_hotkey,
            "screen_capture": capture.get("capture", False),
            "ocr_detail": capture.get("ocr_detail", "unavailable"),
            "recorder": recorder_backend()[1],
            "server_error": self._server_error,
        }

    # -------------------------------------------------------------- settings

    def _save_config(self) -> None:
        with self._config_lock:
            self.config.save(self.paths)

    def start_pairing(self) -> dict[str, Any]:
        self.pairing.begin_pairing(120)
        self.log.info("Pairing window opened for 120 seconds")
        self.bridge.notify_runtime()
        return self.pairing.pairing_status()

    def set_screen_awareness(self, value: bool) -> None:
        self.config.screen_awareness_enabled = bool(value)
        self.control.set_screen_awareness(bool(value))
        if not value:
            self.bridge.stop_pointing()
        self._save_config()
        try:
            self.server.broadcast_event(
                "control.changed",
                {
                    "emergency_stop": self.control.emergency,
                    "control_enabled": self.control.enabled,
                    "screen_awareness": self.control.screen_awareness,
                },
            )
        except Exception:
            pass
        self.bridge.notify_runtime()

    def set_input_control(self, value: bool) -> None:
        if value and self.control.emergency:
            return
        self.control.set_enabled(bool(value))
        self.log.info("Input control %s", "enabled for this run" if value else "disabled")
        try:
            self.server.broadcast_event(
                "control.changed",
                {
                    "emergency_stop": self.control.emergency,
                    "control_enabled": self.control.enabled,
                    "screen_awareness": self.control.screen_awareness,
                },
            )
        except Exception:
            pass
        self.bridge.notify_runtime()

    def set_confirm_actions(self, value: bool) -> None:
        self.config.confirm_actions = bool(value)
        self._save_config()
        self.bridge.notify_runtime()

    def set_allow_codeless_pairing(self, value: bool) -> None:
        self.config.allow_codeless_pairing = bool(value)
        self._save_config()
        self.bridge.notify_runtime()

    def set_allow_screenshots(self, value: bool) -> None:
        self.config.allow_screenshots_to_gemini = bool(value)
        self._save_config()
        self.bridge.notify_runtime()

    def set_overlay_visible(self, visible: bool) -> None:
        self.config.overlay_visible = bool(visible)
        self._save_config()
        self.overlay.set_visible_preference(bool(visible))
        if visible:
            self.overlay.raise_()
        self.bridge.notify_runtime()

    def set_mock_mode(self, value: bool) -> None:
        self.config.use_mock_ai = bool(value)
        self.ai_holder.refresh()
        self._save_config()
        self.bridge.notify_runtime()

    def save_meeting_preferences(self, transcribe: bool, retain_audio: bool) -> None:
        self.config.meeting_transcribe = bool(transcribe)
        self.config.meeting_retain_audio = bool(retain_audio)
        self._save_config()
        self.bridge.notify_runtime()

    def save_network_settings(self, display_name: str, port: int) -> dict[str, Any]:
        name = " ".join((display_name or "").split())
        if not name or len(name) > 80:
            raise ValueError("Display name must be 1-80 characters.")
        if not 1 <= int(port) <= 65535:
            raise ValueError("Port must be between 1 and 65535.")
        old_port = self.config.port
        self.config.display_name = name
        self.config.port = int(port)
        self._save_config()
        if self.mdns and self._server_running:
            self._start_mdns(self.server.port or old_port)
        self.bridge.notify_runtime()
        return {"restart_required": self.server.port is not None and int(port) != int(self.server.port)}

    def save_hotkeys(self, emergency: str, overlay: str, point: str) -> None:
        if not emergency.strip():
            raise ValueError("Emergency hotkey may not be empty.")
        old = (self.config.emergency_hotkey, self.config.overlay_hotkey, self.config.point_hotkey)
        self.config.emergency_hotkey = emergency.strip()
        self.config.overlay_hotkey = overlay.strip()
        self.config.point_hotkey = point.strip()
        self._save_config()
        if self.no_hotkeys:
            return
        if not self._start_hotkeys():
            self.config.emergency_hotkey, self.config.overlay_hotkey, self.config.point_hotkey = old
            self._save_config()
            self._start_hotkeys()
            raise ValueError(self.hotkeys.error or "The hotkeys could not be registered.")
        self.bridge.notify_runtime()

    def save_gemini_key(self, key: str) -> dict[str, Any]:
        candidate = (key or "").strip()
        if not candidate:
            return {"ok": False, "message": "No key was supplied."}
        candidate_gateway = GeminiGateway(self.config, candidate, logger=self.log)
        result = candidate_gateway.validate_key()
        if not result.get("ok"):
            return result
        backend = self.secret_store.set_key(candidate, provider="gemini")
        self.config.use_mock_ai = False
        self.config.ai_provider = "gemini"
        self.ai_holder.configure(candidate, self.ai_holder.get_key_for("openrouter"),
                                  self.ai_holder.get_key_for("xkiro"))
        self._save_config()
        self.log.info("Gemini key validated and stored using %s", backend)
        result["backend"] = backend
        result["message"] = result.get("message", "Key valid.") + f" Stored with {backend}."
        self.bridge.notify_runtime()
        return result

    def has_provider_key(self, provider: str) -> bool:
        return self.ai_holder.has_key_for(provider)

    def save_openrouter_key(self, key: str) -> dict[str, Any]:
        candidate = (key or "").strip()
        if not candidate:
            return {"ok": False, "message": "No key was supplied."}
        candidate_gateway = OpenRouterGateway(self.config, candidate, logger=self.log)
        result = candidate_gateway.validate_key()
        if not result.get("ok"):
            return result
        backend = self.secret_store.set_key(candidate, provider="openrouter")
        self.config.use_mock_ai = False
        self.config.ai_provider = "openrouter"
        self.ai_holder.configure(self.ai_holder.get_key_for("gemini"), candidate,
                                  self.ai_holder.get_key_for("xkiro"))
        self._save_config()
        self.log.info("OpenRouter key validated and stored using %s", backend)
        result["backend"] = backend
        result["message"] = result.get("message", "Key valid.") + f" Stored with {backend}."
        self.bridge.notify_runtime()
        return result

    def save_openrouter_model(self, model: str) -> dict[str, Any]:
        candidate = " ".join((model or "").split())
        if not candidate or len(candidate) > 120 or any(c.isspace() for c in candidate):
            raise ValueError("That does not look like an OpenRouter model id.")
        old_model = self.config.openrouter_model
        old_model = self.config.openrouter_model
        old_provider = self.config.ai_provider
        self.config.openrouter_model = candidate
        self.config.ai_provider = "openrouter"
        self.ai_holder.refresh()
        self._save_config()
        self.bridge.notify_runtime()
        return {"model": candidate, "previous_model": old_model, "previous_provider": old_provider}

    def save_xkiro_key(self, key: str) -> dict[str, Any]:
        candidate = (key or "").strip()
        if not candidate:
            return {"ok": False, "message": "No key was supplied."}
        candidate_gateway = OpenRouterGateway(self.config, candidate, provider="xkiro", logger=self.log)
        result = candidate_gateway.validate_key()
        if not result.get("ok"):
            return result
        backend = self.secret_store.set_key(candidate, provider="xkiro")
        self.config.use_mock_ai = False
        self.config.ai_provider = "xkiro"
        self.ai_holder.configure(
            self.ai_holder.get_key_for("gemini"),
            self.ai_holder.get_key_for("openrouter"),
            candidate,
        )
        self._save_config()
        self.log.info("xkiro key validated and stored using %s", backend)
        result["backend"] = backend
        result["message"] = result.get("message", "Key valid.") + f" Stored with {backend}."
        self.bridge.notify_runtime()
        return result

    def save_xkiro_model(self, model: str) -> dict[str, Any]:
        candidate = " ".join((model or "").split())
        if not candidate or len(candidate) > 120 or any(c.isspace() for c in candidate):
            raise ValueError("That does not look like an xkiro model id.")
        old_model = self.config.xkiro_model
        old_provider = self.config.ai_provider
        self.config.xkiro_model = candidate
        self.config.ai_provider = "xkiro"
        self.ai_holder.refresh()
        self._save_config()
        self.bridge.notify_runtime()
        return {"model": candidate, "previous_model": old_model, "previous_provider": old_provider}

    def set_ai_provider(self, provider: str) -> dict[str, Any]:
        if provider not in ("xkiro", "openrouter", "gemini"):
            raise ValueError("Provider must be xkiro, openrouter or gemini.")
        self.config.ai_provider = provider
        self.ai_holder.refresh()
        self._save_config()
        self.bridge.notify_runtime()
        return {"provider": getattr(self.ai_holder.get(), "provider", "mock")}

    def clear_xkiro_key(self) -> None:
        self.secret_store.clear_key("xkiro")
        self.ai_holder.configure(
            self.ai_holder.get_key_for("gemini"),
            self.ai_holder.get_key_for("openrouter"),
            None,
        )
        self._save_config()
        self.log.info("xkiro key removed")
        self.bridge.notify_runtime()

    def clear_gemini_key(self) -> None:
        self.secret_store.clear_key("gemini")
        self.ai_holder.configure(None, self.ai_holder.get_key_for("openrouter"),
                                  self.ai_holder.get_key_for("xkiro"))
        self._save_config()
        self.log.info("Gemini key removed")
        self.bridge.notify_runtime()

    def clear_openrouter_key(self) -> None:
        self.secret_store.clear_key("openrouter")
        self.ai_holder.configure(self.ai_holder.get_key_for("gemini"), None,
                                  self.ai_holder.get_key_for("xkiro"))
        self._save_config()
        self.log.info("OpenRouter key removed")
        self.bridge.notify_runtime()

    def revoke_device(self, device_id: str) -> bool:
        revoked = self.pairing.revoke(device_id)
        if revoked:
            self.server.disconnect_device(device_id)
            self.log.info("Paired device revoked")
        self.bridge.notify_runtime()
        return revoked

    # ------------------------------------------------------------------ local UI helpers

    def read_screen_for_test(self) -> str:
        if not self.config.screen_awareness_enabled:
            raise RuntimeError("Turn on screen awareness first. This test captures your screen locally.")
        snapshot = self.screen.get(force=True)
        return (
            f"Snapshot {snapshot.id} · {snapshot.width}x{snapshot.height}\n"
            f"Active window: {snapshot.screenshot.active_window or '(unknown)'}\n"
            f"OCR: {snapshot.error or 'ok'}\n\n" + snapshot.context_text()
        )

    def meeting_started_elapsed(self) -> float:
        status = self.meeting.status()
        session = status.get("session") or {}
        started = session.get("started_at")
        if not started or not status.get("recording"):
            return 0.0
        try:
            value = dt.datetime.fromisoformat(str(started).replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.replace(tzinfo=dt.timezone.utc)
            return max(0.0, (dt.datetime.now(dt.timezone.utc) - value).total_seconds())
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def session_duration(session: dict[str, Any]) -> float:
        duration = 0.0
        for chunk in session.get("chunks", []):
            try:
                duration = max(
                    duration,
                    float(chunk.get("start_offset", 0)) + float(chunk.get("duration", 0)),
                )
            except (TypeError, ValueError):
                pass
        return duration

    def notes_folder_for(self, session_id: str):
        try:
            return self.meeting_store.folder_path(session_id)
        except Exception:
            return None

    def refresh_notes_signal(self) -> None:
        try:
            self.window.notes_changed.emit()
        except Exception:
            pass

    # ------------------------------------------------------------------ shutdown

    def request_quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        try:
            status = self.meeting.status()
            if status.get("recording"):
                self.log.info("Stopping meeting recording for app quit")
                self.meeting.stop()
        except Exception:
            self.log.warning("Could not finalise the meeting during quit")
        try:
            self._cleanup()
        finally:
            QApplication.quit()

    def _cleanup(self) -> None:
        with self._cleanup_lock:
            if self._cleaned:
                return
            self._cleaned = True
        self._server_running = False
        try:
            if self.mdns:
                self.mdns.stop()
        except Exception:
            pass
        try:
            if self.hotkeys:
                self.hotkeys.stop()
        except Exception:
            pass
        try:
            self.server.stop()
        except Exception:
            pass
        try:
            self._save_config()
        except Exception:
            pass
        try:
            if getattr(self.window, "tray", None):
                self.window.tray.hide()
        except Exception:
            pass
        try:
            self.overlay.close()
        except Exception:
            pass
        self.log.info("BerryLink shut down")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BerryLink desktop companion")
    parser.add_argument("--mock", action="store_true", help="force local mock AI even if a key is saved")
    parser.add_argument("--no-hotkeys", action="store_true", help="do not grab global hotkeys")
    parser.add_argument("--minimized", action="store_true", help="start with the settings window hidden")
    parser.add_argument("--verbose", action="store_true", help="verbose logging")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    app = QApplication(sys.argv[:1] if argv is None else ["berrylink", *argv])
    app.setApplicationName("BerryLink")
    app.setApplicationDisplayName("BerryLink")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("BerryLink")
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)
    QGuiApplication.setDesktopFileName(APP_ID)
    app.setWindowIcon(make_app_icon())

    paths = AppPaths.default()
    try:
        paths.ensure()
        logger = configure_logging(paths.log_file, verbose=args.verbose)
        config = Config.load(paths)
    except (ConfigError, OSError) as exc:
        QMessageBox.critical(None, "BerryLink could not start", str(exc))
        return 2
    if args.mock:
        config.use_mock_ai = True

    assets = Path(os.environ.get("BERRYLINK_ASSETS", Path(__file__).resolve().parent.parent / "assets"))
    load_fonts(str(assets / "fonts"))
    app.setStyleSheet(THEME)

    logger.info("BerryLink %s starting (desktop id %s)", __version__, APP_ID)
    logger.info("Config: %s; notes: %s", paths.config_dir, paths.notes_dir)
    controller = BerryLinkController(paths, config, no_hotkeys=args.no_hotkeys, logger=logger)
    app.aboutToQuit.connect(controller._cleanup)
    if args.minimized and getattr(controller.window, "tray_available", False):
        controller.window.hide()
    else:
        controller.window.show()
    controller.window.raise_()
    code = app.exec()
    controller._cleanup()
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
