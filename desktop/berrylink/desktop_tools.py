"""Guarded local computer-control tools for the BerryLink character.

Design constraints:
* No shell strings, ever.  Every command is an argv list.
* Input control is off unless the user explicitly enabled it this run.
* Risky actions require a fresh human confirmation.
* Password-manager windows and password-looking fields are refused for typing.
* The emergency stop blocks every screen/input tool immediately.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .config import Config
from .screen import ScreenAwareness, ScreenSnapshot, Target
from .security import is_password_manager, looks_sensitive_label, safe_text_preview

DANGEROUS_LABEL = re.compile(
    r"(?i)\b(send|submit|delete|remove|purchase|buy|pay|checkout|post|publish|"
    r"confirm|logout|log out|sign out|shutdown|restart|format|unsubscribe|"
    r"transfer|allow|grant|install|uninstall)\b"
)
HOTKEY_RESERVED = {
    ("ctrl", "alt", "s"),
    ("ctrl", "alt", "h"),
    ("ctrl", "alt", "p"),
    ("ctrl", "alt", "delete"),
}
ALLOWED_KEYS = {
    "return",
    "enter",
    "tab",
    "escape",
    "backspace",
    "delete",
    "home",
    "end",
    "page_up",
    "page_down",
    "up",
    "down",
    "left",
    "right",
    "space",
    "minus",
    "equal",
    "comma",
    "period",
    "slash",
    "semicolon",
    "apostrophe",
    "bracketleft",
    "bracketright",
    "backslash",
    "grave",
} | {chr(c) for c in range(ord("a"), ord("z") + 1)} | {str(d) for d in range(10)} | {
    f"f{n}" for n in range(1, 13)
}
ALLOWED_MODIFIERS = {"ctrl", "control", "alt", "shift"}
FORBIDDEN_COMBO_PARTS = {"sysrq", "print", "pause"}
# Bare hostname with a dot, e.g. "chatgpt.com" or "docs.example.com/path".
_BARE_DOMAIN = re.compile(
    r"^[a-z0-9][a-z0-9-]*(\.[a-z0-9-]+)+(:\d{1,5})?(/[^\s]*)?$",
    re.IGNORECASE,
)


class ToolError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ToolResult:
    text: str
    image_jpeg: bytes | None = None
    effects: list[str] = field(default_factory=list)


class OverlayPort(Protocol):
    def point_at(self, x: int, y: int, label: str, bubble: str = "", rect: tuple[int, int, int, int] | None = None) -> None: ...
    def stop_pointing(self) -> None: ...
    def sleep(self) -> None: ...
    def show_action(self, label: str) -> None: ...
    def clear_action(self) -> None: ...
    def caption(self, text: str, mood: str = "happy") -> None: ...


class ControlState:
    def __init__(self, *, enabled: bool = False, screen_awareness: bool = True) -> None:
        self._lock = threading.RLock()
        self._enabled = bool(enabled)
        self._emergency = False
        self._screen = bool(screen_awareness)

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled and not self._emergency

    @property
    def screen_awareness(self) -> bool:
        with self._lock:
            return self._screen and not self._emergency

    @property
    def emergency(self) -> bool:
        with self._lock:
            return self._emergency

    def set_enabled(self, value: bool) -> None:
        with self._lock:
            self._enabled = bool(value)
            if value:
                # Enabling input is an explicit action; it clears only the
                # emergency latch after a separate Resume action in the UI.
                pass

    def set_screen_awareness(self, value: bool) -> None:
        with self._lock:
            self._screen = bool(value)

    def trigger_emergency_stop(self) -> None:
        with self._lock:
            self._emergency = True
            self._enabled = False

    def resume(self) -> None:
        with self._lock:
            self._emergency = False

    def snapshot(self) -> dict[str, bool]:
        with self._lock:
            return {
                "control_enabled": self._enabled and not self._emergency,
                "screen_awareness": self._screen and not self._emergency,
                "emergency_stop": self._emergency,
            }


SCREEN_TOOLS = {"look_at_screen", "point_at", "point_at_spot", "stop_pointing", "go_to_sleep"}
INPUT_TOOLS = {"click", "type_text", "press_keys", "scroll", "drag", "open_app", "open_url"}


class DesktopTools:
    def __init__(
        self,
        config: Config,
        screen: ScreenAwareness,
        overlay: OverlayPort,
        control: ControlState,
        confirm: Callable[[str, str], bool] | None = None,
        logger=None,
    ) -> None:
        self.config = config
        self.screen = screen
        self.overlay = overlay
        self.control = control
        self.confirm = confirm
        self.log = logger
        self._action_lock = threading.Lock()
        self._last_snapshot: ScreenSnapshot | None = None

    # ---------------------------------------------------------------- schema

    def tool_declarations(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        if self.control.screen_awareness:
            tools.extend(
                [
                    self._fn(
                        "look_at_screen",
                        "Capture the user's screen and OCR readable text. Use this when you need a fresh view, then refer to target IDs from the result.",
                        {},
                    ),
                    self._fn(
                        "point_at",
                        "Move the little BerryLink cursor overlay to an on-screen target from the most recent look_at_screen result, and show a short speech bubble. This never moves the real mouse pointer.",
                        {
                            "target_id": {"type": "string", "description": "Target ID such as L12 or W12_3."},
                            "bubble": {"type": "string", "description": "Optional short bubble text."},
                        },
                        ["target_id"],
                    ),
                    self._fn(
                        "point_at_spot",
                        "Point the visual cursor at a normalized spot on the whole screen. Coordinates are x,y from 0 to 1000.",
                        {
                            "x": {"type": "integer", "minimum": 0, "maximum": 1000},
                            "y": {"type": "integer", "minimum": 0, "maximum": 1000},
                            "bubble": {"type": "string"},
                        },
                        ["x", "y"],
                    ),
                    self._fn(
                        "stop_pointing",
                        "Stop pointing and return the visual cursor to its idle position.",
                        {},
                    ),
                    self._fn(
                        "go_to_sleep",
                        "Put the phone companion to sleep and return the desktop cursor to rest.",
                        {},
                    ),
                ]
            )
        if self.control.enabled:
            tools.extend(
                [
                    self._fn(
                        "click",
                        "Click a target from the most recent screen snapshot. Requires input control and, normally, human confirmation.",
                        {
                            "target_id": {"type": "string"},
                            "button": {"type": "integer", "minimum": 1, "maximum": 3},
                            "count": {"type": "integer", "minimum": 1, "maximum": 2},
                        },
                        ["target_id"],
                    ),
                    self._fn(
                        "type_text",
                        "Type text into the currently focused field using xdotool. Never use this for passwords, API keys, recovery codes, or other secrets. Requires input control and confirmation.",
                        {
                            "text": {"type": "string"},
                            "submit": {"type": "boolean", "description": "Press Return after typing."},
                        },
                        ["text"],
                    ),
                    self._fn(
                        "press_keys",
                        "Press a limited keyboard shortcut, for example ctrl+l or alt+tab. Dangerous system shortcuts and shell execution are rejected.",
                        {"keys": {"type": "string", "description": "Keys joined by +, e.g. ctrl+l."}},
                        ["keys"],
                    ),
                    self._fn(
                        "scroll",
                        "Scroll at a target or the current pointer. Positive amount scrolls down, negative scrolls up.",
                        {
                            "target_id": {"type": "string"},
                            "amount": {"type": "integer", "minimum": -20, "maximum": 20},
                        },
                        ["amount"],
                    ),
                    self._fn(
                        "drag",
                        "Drag from one normalized screen point to another. Use only for a clearly identified drag the user requested.",
                        {
                            "from_x": {"type": "integer", "minimum": 0, "maximum": 1000},
                            "from_y": {"type": "integer", "minimum": 0, "maximum": 1000},
                            "to_x": {"type": "integer", "minimum": 0, "maximum": 1000},
                            "to_y": {"type": "integer", "minimum": 0, "maximum": 1000},
                        },
                        ["from_x", "from_y", "to_x", "to_y"],
                    ),
                    self._fn(
                        "open_app",
                        "Launch an installed desktop application by name, e.g. open_app('Brave') to start the Brave browser. Part of multi-step tasks: launch the app first, then use open_url or click/type_text inside it.",
                        {"name": {"type": "string", "description": "Application name, e.g. Brave or Files."}},
                        ["name"],
                    ),
                    self._fn(
                        "open_url",
                        "Open a website. With no app given the default browser handles it; with 'app' given the URL opens inside that application, e.g. open_url('chatgpt.com', app='Brave'). Bare domains are upgraded to https automatically.",
                        {
                            "url": {"type": "string", "description": "Domain like chatgpt.com or full https URL."},
                            "app": {"type": "string", "description": "Optional installed app to open the URL in, e.g. Brave."},
                        },
                        ["url"],
                    ),
                ]
            )
        return tools

    @staticmethod
    def _fn(
        name: str,
        description: str,
        properties: dict[str, Any],
        required: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "function",
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        }

    # ------------------------------------------------------------------ calls

    def call(
        self,
        name: str,
        arguments: Mapping[str, Any] | None,
        *,
        allow_screenshot: bool = False,
        allow_tools: bool = True,
    ) -> ToolResult:
        args = dict(arguments or {})
        if not allow_tools:
            raise ToolError("tools_disabled", "Tools are disabled for this request.")
        if self.control.emergency:
            raise ToolError(
                "emergency_stop",
                "Emergency stop is active. Resume control in the desktop app before I do anything.",
            )
        handlers: dict[str, Callable[..., ToolResult]] = {
            "look_at_screen": lambda: self._look_at_screen(allow_screenshot=allow_screenshot),
            "point_at": lambda: self._point_at(args),
            "point_at_spot": lambda: self._point_at_spot(args),
            "stop_pointing": self._stop_pointing,
            "go_to_sleep": self._go_to_sleep,
            "click": lambda: self._click(args),
            "type_text": lambda: self._type_text(args),
            "press_keys": lambda: self._press_keys(args),
            "scroll": lambda: self._scroll(args),
            "drag": lambda: self._drag(args),
            "open_app": lambda: self._open_app(args),
            "open_url": lambda: self._open_url(args),
        }
        handler = handlers.get(name)
        if handler is None:
            raise ToolError("unknown_tool", f"Unknown tool: {name}")
        if name in SCREEN_TOOLS and not self.control.screen_awareness:
            raise ToolError("screen_disabled", "Screen awareness is turned off.")
        if name in INPUT_TOOLS:
            self._ensure_input_control()
        started = time.monotonic()
        try:
            result = handler()
            if self.log:
                self.log.info(
                    "tool=%s ok elapsed=%.2fs effects=%s",
                    name,
                    time.monotonic() - started,
                    ",".join(result.effects) or "-",
                )
            return result
        except ToolError as exc:
            if self.log:
                self.log.warning("tool=%s refused=%s", name, exc.code)
            raise
        except Exception as exc:
            if self.log:
                self.log.warning("tool=%s failed=%s", name, type(exc).__name__)
            raise ToolError("tool_failed", "That desktop action failed safely.") from exc

    def _ensure_input_control(self) -> None:
        if not self.control.enabled:
            raise ToolError(
                "control_disabled",
                "Input control is off. The user must enable it in BerryLink on the desktop.",
            )

    def _snapshot(self, force: bool = False) -> ScreenSnapshot:
        snapshot = self.screen.get(force=force)
        self._last_snapshot = snapshot
        return snapshot

    def _resolve_target(self, target_id: str, force_refresh_on_miss: bool = True) -> tuple[ScreenSnapshot, Target]:
        if not isinstance(target_id, str) or not target_id.strip():
            raise ToolError("bad_target", "A target ID is required.")
        snapshot = self._snapshot()
        target = snapshot.target(target_id)
        if target is None and force_refresh_on_miss:
            snapshot = self._snapshot(force=True)
            target = snapshot.target(target_id)
        if target is None:
            raise ToolError(
                "stale_target",
                "That screen target is no longer available. Ask me to look at the screen again.",
            )
        return snapshot, target

    def _bubble(self, args: Mapping[str, Any], default: str = "") -> str:
        value = args.get("bubble", default)
        if value is None:
            return default
        if not isinstance(value, str):
            raise ToolError("bad_arguments", "Bubble must be text.")
        return " ".join(value.split())[:240]

    # ------------------------------------------------------------- screen/point

    def _look_at_screen(self, allow_screenshot: bool = False) -> ToolResult:
        snapshot = self._snapshot(force=True)
        text = snapshot.context_text()
        text += (
            "\nTo point at a target, call point_at with that ID. "
            "Coordinates in this list are normalized for point_at_spot."
        )
        image = None
        if allow_screenshot and self.config.allow_screenshots_to_gemini:
            try:
                image = snapshot.screenshot.jpeg()
            except Exception:
                image = None
        return ToolResult(text=text, image_jpeg=image)

    def _point_at(self, args: Mapping[str, Any]) -> ToolResult:
        snapshot, target = self._resolve_target(args.get("target_id", ""))
        bubble = self._bubble(args, target.text[:120])
        x, y = target.center
        self.overlay.point_at(
            x,
            y,
            target.text[:80],
            bubble,
            rect=(target.left, target.top, target.width, target.height),
        )
        return ToolResult(
            text=f"Pointing at {target.id} ({target.text!r}) at ({x},{y}) in snapshot {snapshot.id}."
        )

    def point_at_text(self, query: str, bubble: str = "") -> ToolResult:
        """Local helper for mock mode and simple phone-side point commands."""
        if not self.control.screen_awareness:
            raise ToolError("screen_disabled", "Screen awareness is turned off.")
        snapshot = self.screen.get(force=True)
        target = snapshot.find_text(query)
        if target is None:
            raise ToolError("target_not_found", f"I couldn't find {query!r} on the screen.")
        x, y = target.center
        self.overlay.point_at(
            x,
            y,
            target.text[:80],
            (bubble or target.text)[:240],
            rect=(target.left, target.top, target.width, target.height),
        )
        return ToolResult(text=f"Pointing at {target.text!r}.")

    def _point_at_spot(self, args: Mapping[str, Any]) -> ToolResult:
        x = _int_arg(args, "x", 0, 1000)
        y = _int_arg(args, "y", 0, 1000)
        snapshot = self._snapshot()
        px, py = self.screen.normalized_to_pixels(x, y, snapshot.width, snapshot.height)
        bubble = self._bubble(args)
        self.overlay.point_at(px, py, bubble or "right here", bubble)
        return ToolResult(text=f"Pointing at screen spot ({px},{py}) (normalized {x},{y}).")

    def _stop_pointing(self) -> ToolResult:
        self.overlay.stop_pointing()
        return ToolResult(text="Stopped pointing.")

    def _go_to_sleep(self) -> ToolResult:
        self.overlay.sleep()
        return ToolResult(text="Going to sleep.", effects=["sleep"])

    # ------------------------------------------------------------------ actions

    def _authorize(self, action: str, description: str, force: bool = False) -> bool:
        if self.control.emergency:
            raise ToolError("emergency_stop", "Emergency stop is active.")
        must_ask = force or self.config.confirm_actions
        if not must_ask:
            return True
        if self.confirm is None:
            raise ToolError(
                "confirmation_unavailable",
                "This action needs human confirmation, but no confirmation window is available.",
            )
        approved = bool(self.confirm(action, description))
        if self.control.emergency:
            raise ToolError("emergency_stop", "Emergency stop was pressed.")
        if not approved:
            raise ToolError("denied", "The user did not approve that action.")
        return True

    def _mark_action(self, label: str) -> None:
        self.overlay.show_action(label)

    def _clear_action(self) -> None:
        self.overlay.clear_action()

    def _click(self, args: Mapping[str, Any]) -> ToolResult:
        target_id = args.get("target_id")
        if not isinstance(target_id, str) or not target_id:
            raise ToolError("bad_arguments", "Click needs a target_id.")
        snapshot, target = self._resolve_target(target_id)
        button = _int_arg(args, "button", 1, 3, default=1)
        count = _int_arg(args, "count", 1, 2, default=1)
        risky = bool(DANGEROUS_LABEL.search(target.text))
        description = (
            f'Click {target.text!r} ({target.id}) at {target.center[0]},{target.center[1]}'
            f"{' — this looks consequential' if risky else ''}."
        )
        self._authorize("click", description, force=risky)
        self._mark_action("CLICK")
        saved = self._pointer_position()
        try:
            self._run(
                [
                    "xdotool",
                    "mousemove",
                    "--sync",
                    str(target.center[0]),
                    str(target.center[1]),
                    "click",
                    "--clearmodifiers",
                    "--repeat",
                    str(count),
                    "--delay",
                    "80",
                    str(button),
                ]
            )
        finally:
            if saved:
                self._restore_pointer(saved)
            self._clear_action()
        return ToolResult(text=f"Clicked {target.id} ({target.text[:80]!r}).")

    def _refresh_active_window(self) -> tuple[ScreenSnapshot, str, str]:
        # A fresh capture is needed here: typing into the wrong window is not
        # reversible, so do not rely on a stale title.
        snapshot = self._snapshot(force=True)
        return snapshot, snapshot.screenshot.active_window, snapshot.screenshot.active_class

    def _type_text(self, args: Mapping[str, Any]) -> ToolResult:
        text = args.get("text")
        if not isinstance(text, str) or not text:
            raise ToolError("bad_arguments", "Nothing to type.")
        if len(text) > 2000:
            raise ToolError("too_long", "Typed text is limited to 2000 characters.")
        submit = bool(args.get("submit", False))
        snapshot, window_title, window_class = self._refresh_active_window()
        if is_password_manager(window_class, window_title) or looks_sensitive_label(window_title):
            raise ToolError(
                "sensitive_window",
                "I won't type into a password or secret window. Please do that yourself.",
            )
        # Refuse obvious password-field context from OCR as well.
        for line in snapshot.lines:
            if looks_sensitive_label(line.text) and any(
                w.text.strip() in ("|", ":", "=") for w in line.words
            ):
                raise ToolError(
                    "sensitive_window",
                    "A password-like field is focused. I won't type there.",
                )
        preview = safe_text_preview(text, 120)
        description = f'Type "{preview}"' + (" and press Return" if submit else "") + f" in {window_title or 'the active window'}."
        self._authorize("type_text", description, force=submit)
        self._mark_action("TYPE")
        try:
            proc = self._run(
                ["xdotool", "type", "--clearmodifiers", "--delay", "12", "--file", "-"],
                input_bytes=text.encode("utf-8"),
                timeout=30,
            )
            if proc.returncode != 0:
                raise ToolError("type_failed", "The text could not be typed.")
            if submit:
                self._run(["xdotool", "key", "--clearmodifiers", "Return"])
        finally:
            self._clear_action()
        return ToolResult(text=f"Typed {len(text)} characters into {window_title or 'the active window'}.")

    def _press_keys(self, args: Mapping[str, Any]) -> ToolResult:
        raw = args.get("keys")
        if not isinstance(raw, str):
            raise ToolError("bad_arguments", "Keys must be text.")
        tokens = [t.strip().lower() for t in raw.split("+") if t.strip()]
        if not 1 <= len(tokens) <= 5:
            raise ToolError("bad_keys", "Use between one and five keys.")
        if any(token in FORBIDDEN_COMBO_PARTS for token in tokens):
            raise ToolError("bad_keys", "That system key is not allowed.")
        modifiers = [t for t in tokens if t in ALLOWED_MODIFIERS]
        keys = [t.replace("control", "ctrl") for t in tokens if t not in ALLOWED_MODIFIERS]
        if len(keys) != 1:
            raise ToolError("bad_keys", "A shortcut must contain exactly one non-modifier key.")
        key = keys[0]
        if key not in ALLOWED_KEYS:
            raise ToolError("bad_keys", "That key is not in the allowlist.")
        modifier_set = {m if m != "control" else "ctrl" for m in modifiers}
        reserved = {frozenset(combo) for combo in HOTKEY_RESERVED}
        if frozenset(modifier_set | {key}) in reserved or (
            modifier_set >= {"ctrl", "alt"} and key.startswith("f")
        ):
            raise ToolError("bad_keys", "That shortcut is reserved or unsafe.")
        pretty = "+".join(list(dict.fromkeys(m.replace("control", "ctrl") for m in modifiers)) + [key])
        self._authorize("press_keys", f"Press the keyboard shortcut {pretty}.")
        self._mark_action("KEYS")
        try:
            proc = self._run(["xdotool", "key", "--clearmodifiers", pretty])
            if proc.returncode != 0:
                raise ToolError("keys_failed", "The key shortcut could not be sent.")
        finally:
            self._clear_action()
        return ToolResult(text=f"Pressed {pretty}.")

    def _scroll(self, args: Mapping[str, Any]) -> ToolResult:
        amount = _int_arg(args, "amount", -20, 20)
        if amount == 0:
            raise ToolError("bad_arguments", "Scroll amount cannot be zero.")
        target_id = args.get("target_id")
        snapshot = self._snapshot()
        if isinstance(target_id, str) and target_id:
            _snapshot, target = self._resolve_target(target_id)
            x, y = target.center
            label = target.text[:60]
        else:
            x, y = snapshot.screenshot.pointer_x, snapshot.screenshot.pointer_y
            label = "pointer"
        # Scrolling is reversible; it does not need a modal confirmation, but
        # the visible AUTO badge still shows that an action is happening.
        self._mark_action("SCROLL")
        saved = self._pointer_position()
        button = "5" if amount > 0 else "4"
        try:
            self._run(
                ["xdotool", "mousemove", "--sync", str(x), str(y)]
            )
            for _ in range(abs(amount)):
                self._run(["xdotool", "click", "--clearmodifiers", button], timeout=3)
                if self.control.emergency:
                    raise ToolError("emergency_stop", "Emergency stop was pressed.")
                time.sleep(0.025)
        finally:
            if saved:
                self._restore_pointer(saved)
            self._clear_action()
        return ToolResult(text=f"Scrolled {abs(amount)} steps {'down' if amount > 0 else 'up'} at {label!r}.")

    def _drag(self, args: Mapping[str, Any]) -> ToolResult:
        snapshot = self._snapshot()
        from_x = _int_arg(args, "from_x", 0, 1000)
        from_y = _int_arg(args, "from_y", 0, 1000)
        to_x = _int_arg(args, "to_x", 0, 1000)
        to_y = _int_arg(args, "to_y", 0, 1000)
        sx, sy = self.screen.normalized_to_pixels(from_x, from_y, snapshot.width, snapshot.height)
        tx, ty = self.screen.normalized_to_pixels(to_x, to_y, snapshot.width, snapshot.height)
        self._authorize("drag", f"Drag from ({sx},{sy}) to ({tx},{ty}).", force=True)
        self._mark_action("DRAG")
        saved = self._pointer_position()
        try:
            self._run(["xdotool", "mousemove", "--sync", str(sx), str(sy)])
            self._run(["xdotool", "mousedown", "1"])
            try:
                for step in range(1, 13):
                    if self.control.emergency:
                        raise ToolError("emergency_stop", "Emergency stop was pressed.")
                    x = round(sx + (tx - sx) * step / 12)
                    y = round(sy + (ty - sy) * step / 12)
                    self._run(["xdotool", "mousemove", "--sync", str(x), str(y)], timeout=3)
                    time.sleep(0.03)
            finally:
                self._run(["xdotool", "mouseup", "1"], timeout=3)
        finally:
            if saved:
                self._restore_pointer(saved)
            self._clear_action()
        return ToolResult(text=f"Dragged from ({sx},{sy}) to ({tx},{ty}).")

    def _open_app(self, args: Mapping[str, Any]) -> ToolResult:
        name = args.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ToolError("bad_arguments", "Which application?")
        entry = find_desktop_app(name)
        if entry is None:
            raise ToolError("app_not_found", "No installed application matched that name.")
        self._authorize("open_app", f"Open the application {entry['name']!r}.")
        self._mark_action("OPEN APP")
        try:
            launch_desktop_app(entry)
        finally:
            self._clear_action()
        return ToolResult(text=f"Opened {entry['name']}.")

    def _open_url(self, args: Mapping[str, Any]) -> ToolResult:
        url = args.get("url")
        if not isinstance(url, str):
            raise ToolError("bad_arguments", "URL must be text.")
        url = url.strip()
        if len(url) > 2048:
            raise ToolError("bad_url", "URL is too long.")
        # The user asks with natural language ("go to chatgpt.com"), so a bare
        # domain is upgraded to https automatically; nothing else is accepted.
        if "://" not in url and _BARE_DOMAIN.match(url):
            url = "https://" + url
        try:
            parsed = urllib.parse.urlsplit(url)
        except ValueError as exc:
            raise ToolError("bad_url", "That URL is not valid.") from exc
        if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            raise ToolError(
                "bad_url",
                "Only http(s) URLs are allowed, e.g. https://chatgpt.com.",
            )
        if parsed.username or parsed.password:
            raise ToolError("bad_url", "URLs with embedded credentials are not allowed.")
        if any(ord(c) < 32 for c in url):
            raise ToolError("bad_url", "URL contains control characters.")
        app_query = args.get("app")
        if isinstance(app_query, str) and app_query.strip():
            entry = find_desktop_app(app_query)
            if entry is None:
                raise ToolError("app_not_found", f"No installed app matched {app_query!r}.")
            self._authorize("open_url", f"Open this URL in {entry['name']}:\n{url}")
            self._mark_action("OPEN URL")
            try:
                launch_desktop_app(entry, arguments=[url])
            finally:
                self._clear_action()
            return ToolResult(text=f"Opened {url} in {entry['name']}.")
        self._authorize("open_url", f"Open this URL in the default browser:\n{url}")
        self._mark_action("OPEN URL")
        try:
            self._run(["xdg-open", url], timeout=8)
        except Exception:
            try:
                self._run(["gio", "open", url], timeout=8)
            except Exception as exc:
                raise ToolError("open_url_failed", "No browser opener was available.") from exc
        finally:
            self._clear_action()
        return ToolResult(text=f"Opened {url}.")

    # ----------------------------------------------------------------- helpers

    def _run(
        self,
        argv: list[str],
        *,
        input_bytes: bytes | None = None,
        timeout: float = 12,
    ) -> subprocess.CompletedProcess:
        if self.control.emergency:
            raise ToolError("emergency_stop", "Emergency stop is active.")
        if not argv or not all(isinstance(a, str) and "\x00" not in a for a in argv):
            raise ToolError("bad_command", "Unsafe command rejected.")
        try:
            return subprocess.run(
                argv,
                input=input_bytes,
                capture_output=True,
                timeout=timeout,
                check=False,
                env=os.environ.copy(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.last_command_error = str(exc)
            raise ToolError("command_failed", "A safe desktop command failed.") from exc

    def _pointer_position(self) -> tuple[int, int] | None:
        try:
            proc = self._run(["xdotool", "getmouselocation", "--shell"], timeout=3)
            x = y = None
            for line in proc.stdout.decode("utf-8", "replace").splitlines():
                if line.startswith("X="):
                    x = int(line.split("=", 1)[1])
                elif line.startswith("Y="):
                    y = int(line.split("=", 1)[1])
            if x is not None and y is not None:
                return x, y
        except (ToolError, ValueError):
            pass
        return None

    def _restore_pointer(self, position: tuple[int, int]) -> None:
        try:
            self._run(["xdotool", "mousemove", "--sync", str(position[0]), str(position[1])], timeout=3)
        except ToolError:
            pass


def _int_arg(args: Mapping[str, Any], name: str, minimum: int, maximum: int, default: int | None = None) -> int:
    value = args.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError("bad_arguments", f"{name} must be an integer.")
    if not minimum <= value <= maximum:
        raise ToolError("bad_arguments", f"{name} must be between {minimum} and {maximum}.")
    return value


def _desktop_roots() -> list[Path]:
    home = Path.home()
    roots = [home / ".local" / "share" / "applications", Path("/usr/share/applications")]
    xdg = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    for part in xdg.split(":"):
        if part:
            roots.append(Path(part) / "applications")
    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def desktop_app_catalog() -> list[dict[str, str]]:
    apps: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for root in _desktop_roots():
        try:
            entries = sorted(root.glob("*.desktop"))
        except OSError:
            continue
        for path in entries:
            if path.name in seen_ids:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            values: dict[str, str] = {}
            for line in text.splitlines():
                if line.startswith("[") and line.strip() != "[Desktop Entry]":
                    break
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    values.setdefault(key.strip(), value.strip())
            if values.get("Type") != "Application":
                continue
            if values.get("NoDisplay", "false").lower() == "true" or values.get("Hidden", "false").lower() == "true":
                continue
            name = values.get("Name", "")
            if not name:
                continue
            desktop_id = path.name
            seen_ids.add(desktop_id)
            apps.append(
                {
                    "id": desktop_id,
                    "name": name,
                    "generic": values.get("GenericName", ""),
                    "path": str(path),
                }
            )
    return apps


def find_desktop_app(query: str) -> dict[str, str] | None:
    q = " ".join(query.split()).casefold()
    if not q:
        return None
    apps = desktop_app_catalog()
    for app in apps:
        if q in (app["name"].casefold(), app["id"].removesuffix(".desktop").casefold()):
            return app
    for app in apps:
        if q in app["name"].casefold() or q in app["generic"].casefold():
            return app
    return None


def launch_desktop_app(entry: Mapping[str, str], arguments: list[str] | None = None) -> None:
    desktop_id = entry.get("id", "")
    if not re.fullmatch(r"[A-Za-z0-9_.+-]+\.desktop", desktop_id):
        raise ToolError("bad_app", "Unsafe desktop entry id.")
    extra = [_restore_safe_arg(a) for a in (arguments or [])]
    try:
        if shutil.which("gtk-launch"):
            proc = subprocess.run(
                ["gtk-launch", desktop_id.removesuffix(".desktop"), *extra],
                capture_output=True,
                timeout=12,
                check=False,
            )
            if proc.returncode == 0:
                return
        path = entry.get("path", "")
        if path and shutil.which("gio"):
            proc = subprocess.run(
                ["gio", "launch", path, *extra],
                capture_output=True,
                timeout=12,
                check=False,
            )
            if proc.returncode == 0:
                return
    except (OSError, subprocess.SubprocessError) as exc:
        raise ToolError("open_app_failed", "The application could not be launched.") from exc
    raise ToolError("open_app_failed", "The application could not be launched.")


def _restore_safe_arg(value: str) -> str:
    """Arguments are joined to a validated argv list; reject control bytes."""
    if any(ord(c) < 32 for c in value):
        raise ToolError("bad_arguments", "Unsafe argument for the launcher.")
    return value
