"""Understood-phrase launchers.

The AI is only a tiny phrase mapper: when it answers `COMMAND: open_brave` the
desktop runs one of the common functions below. Every launch is detached
(`subprocess.Popen` with a fresh session) so the question never blocks the
phone, the server, or the desktop while the target app starts up.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

HOME = Path.home()

TERMINAL_CANDIDATES = (
    "x-terminal-emulator",
    "qterminal",
    "xfce4-terminal",
    "gnome-terminal",
    "konsole",
    "xterm",
    "kitty",
    "alacritty",
)

UNDERCOVER_STATE_FILE = HOME / ".local/share/kali-undercover/user-profile.tar.bz2"

COMMAND_SAYINGS = {
    "open_brave": "Opening Brave for you.",
    "open_tlauncher": "Launching TLauncher!",
    "open_terminal": "Opening a terminal.",
    "open_berrylink": "Bringing the BerryLink desktop up.",
    "undercover_on": "Switching Kali Undercover on.",
    "undercover_off": "Back to the normal Kali desktop.",
}


class CommandError(RuntimeError):
    """Raised with a speakable message when a command cannot run."""


def _session_env() -> dict:
    """A child environment that can actually open apps on the user's desktop.

    BerryLink may run from systemd, SSH or a terminal that lacks the graphical
    session's variables. GUI apps (and kali-undercover, which talks to xfconfd
    over D-Bus) then fail silently. Fill the well-known gaps: X11/Wayland
    display, XDG_RUNTIME_DIR, the user session's D-Bus address and Xauthority.
    """
    env = dict(os.environ)
    uid = os.getuid()
    runtime_dir = env.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    if Path(runtime_dir).is_dir():
        env.setdefault("XDG_RUNTIME_DIR", runtime_dir)
        bus = env.get("DBUS_SESSION_BUS_ADDRESS")
        if not bus and (Path(runtime_dir) / "bus").exists():
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime_dir}/bus"
        if not env.get("WAYLAND_DISPLAY") and (Path(runtime_dir) / "wayland-0").exists():
            env["WAYLAND_DISPLAY"] = "wayland-0"
    if not env.get("DISPLAY"):
        sockets = sorted(Path("/tmp/.X11-unix").glob("X*")) if Path("/tmp/.X11-unix").is_dir() else []
        if sockets:
            env["DISPLAY"] = f":{sockets[0].name.lstrip('X')}"
    if not env.get("XAUTHORITY"):
        candidate = HOME / ".Xauthority"
        if candidate.exists():
            env["XAUTHORITY"] = str(candidate)
    return env


_ENV_LOCK = threading.Lock()
_ENV_CACHE: dict | None = None


def _launch(
    cmd: list[str],
    logger: logging.Logger | None = None,
    cwd: str | None = None,
) -> None:
    global _ENV_CACHE
    log = logger or logging.getLogger("berrylink.commands")
    log.info("launching %s", cmd[0])
    with _ENV_LOCK:
        if _ENV_CACHE is None:
            _ENV_CACHE = _session_env()
    try:
        subprocess.Popen(
            cmd,
            cwd=cwd,
            env=_ENV_CACHE,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # detached: this call returns immediately
        )
    except OSError as exc:
        raise CommandError(f"I couldn't start {cmd[0]}: {exc}") from exc


def _which(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


_DESKTOP_CODE_FIELDS = re.compile(r"%[a-zA-Z]")


def _desktop_exec(desktop_id: str) -> tuple[list[str], str | None] | None:
    """Resolve an installed app from its XDG .desktop entry.

    Returns (argv, working_directory) so apps like TLauncher — which ship
    only as tlauncher.desktop — can start exactly like the desktop menu does.
    """
    import shlex

    # The user's own menu entries (~/.local/share/applications) win: Kali lets
    # you edit launchers (GPU env, flags) and the menu runs those. Checking
    # them first reproduces exactly what clicking the menu icon does.
    for base in (HOME / ".local/share/applications", Path("/usr/share/applications")):
        path = base / f"{desktop_id}.desktop"
        if not path.exists():
            continue
        exec_line = ""
        working_dir: str | None = None
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Exec="):
                    exec_line = line[5:].strip()
                elif line.startswith("Path="):
                    candidate = line[5:].strip()
                    if candidate and Path(candidate).is_dir():
                        working_dir = candidate
            if not exec_line:
                continue
            argv = []
            for token in shlex.split(exec_line):
                if _DESKTOP_CODE_FIELDS.fullmatch(token):
                    continue  # %f %u etc. need no argument for a plain launch
                token = _DESKTOP_CODE_FIELDS.sub("", token)
                if token:
                    argv.append(token)
            if argv:
                return argv, working_dir
        except OSError:
            continue
    return None


def _undercover_active() -> bool:
    return UNDERCOVER_STATE_FILE.exists()


def undercover_is_on() -> bool:
    return _undercover_active()


_LAUNCH_VERBS = ("open", "launch", "start", "run", "fire up", "bring up", "bring")


def _sayings(text: str) -> list[str]:
    """Text variants to match against: raw plus the filler-stripped one.

    Voice and chat messages usually start with 'hey berry…', 'ok berry…',
    'please…' — stripping those still leaves honest keyword matching.
    """
    lowered = (text or "").casefold()
    cleaned = lowered.strip(" !.,'\"")
    for filler in ("hey berry", "ok berry", "okay berry", "hi berry", "berry", "please", "could you", "can you", "would you"):
        if cleaned.startswith(filler):
            cleaned = cleaned[len(filler):].lstrip(" ,-':")
    return [cleaned for cleaned in (cleaned, lowered) if cleaned]


def guess_command(text: str) -> str | None:
    """Local keyword fallback so the same phrases work even in mock mode."""
    variants = _sayings(text)
    if not variants:
        return None
    wants_off = any(
        word in variant
        for variant in variants
        for word in ("off", "normal", "back", "turn off", "disable")
    )
    undercover = any(
        word in variant
        for variant in variants
        for word in ("undercover", "windows look", "windows disguise")
    )
    if undercover:
        return "undercover_off" if wants_off else "undercover_on"
    # Bring the desktop app up under its casual names, before browser matching
    # (so 'berry open brave' still hits brave, guarded by the berrylink words).
    for variant in variants:
        if "berrylink" in variant and any(word in variant for word in _LAUNCH_VERBS):
            return "open_berrylink"
        if variant.endswith("open berry"):
            return "open_berrylink"
    for variant in variants:
        if (
            "come home" in variant
            or "show yourself" in variant
            or "come back" in variant
            or "come up" in variant
        ) and "brave" not in variant:
            return "open_berrylink"
    for variant in variants:
        if any(word in variant for word in ("brave", "browser", "chrome", "web", "internet")) and any(
            word in variant for word in _LAUNCH_VERBS
        ):
            return "open_brave"
    for variant in variants:
        if any(word in variant for word in ("tlauncher", "minecraft")) and any(
            word in variant for word in (*_LAUNCH_VERBS, "play")
        ):
            return "open_tlauncher"
    for variant in variants:
        if any(word in variant for word in _LAUNCH_VERBS) and any(
            word in variant for word in ("terminal", "console", "shell", "command line")
        ):
            return "open_terminal"
    return None


def run_command(
    command: str,
    *,
    activate_berrylink=None,
    logger: logging.Logger | None = None,
) -> tuple[str, bool]:
    """Run one launcher and return (spoken_line, ok)."""
    command = (command or "").strip()
    if command == "open_brave":
        program = _which("brave-browser", "brave")
        if program:
            _launch([program], logger)
            return COMMAND_SAYINGS[command], True
        default = _which("xdg-open")
        if default:
            _launch([default, "about:blank"], logger)
            return "Opening your default web browser.", True
        raise CommandError("I couldn't find a browser on this computer.")

    if command == "open_tlauncher":
        desktop = _desktop_exec("tlauncher")
        if desktop:
            _launch(desktop[0], logger, cwd=desktop[1])
            return COMMAND_SAYINGS[command], True
        program = _which("tlauncher", "TLauncher")
        if program:
            _launch([program], logger)
            return COMMAND_SAYINGS[command], True
        jar = HOME / "TLauncher" / "TLauncher.jar"
        java = shutil.which("java")
        if jar.exists() and java:
            _launch([java, "-jar", str(jar)], logger)
            return COMMAND_SAYINGS[command], True
        raise CommandError("TLauncher doesn't seem to be installed on this computer yet.")

    if command == "open_terminal":
        program = _which(*TERMINAL_CANDIDATES)
        if program:
            _launch([program], logger)
            return COMMAND_SAYINGS[command], True
        raise CommandError("I couldn't find a terminal on this computer.")

    if command == "open_berrylink":
        if activate_berrylink is not None:
            try:
                activate_berrylink()
            except Exception:  # overlay activation failing must never crash the ask
                logging.getLogger("berrylink.commands").exception("berrylink activation failed")
        return COMMAND_SAYINGS[command], True

    if command in ("undercover_on", "undercover_off"):
        toggle = _which("kali-undercover")
        if not toggle:
            raise CommandError("Kali Undercover isn't available on this computer.")
        active = _undercover_active()
        if command == "undercover_on":
            if active:
                return "Kali Undercover is already on.", True
            _launch([toggle], logger)
            return COMMAND_SAYINGS[command], True
        if not active:
            return "Kali Undercover is already off.", True
        _launch([toggle], logger)
        return COMMAND_SAYINGS[command], True

    raise CommandError(f"Unknown command: {command}")
