"""Deterministic, clearly-labelled local fallback used without any AI key.

Mock mode is intentionally honest: it cannot understand speech offline and it
cannot be a cloud brain. It keeps the local manual helpers (point at text,
look at the screen, stop pointing) and the phrase → command launcher, so a
fresh install without a key still shows a working, responsive companion.
"""

from __future__ import annotations

import re

from .config import Config
from .desktop_commands import COMMAND_SAYINGS, guess_command
from .gemini_gateway import AIResult, AskInput, ConversationState

_SLEEPY_WORDS = ("sleep", "goodnight", "good night", "nap")
_INPUT_WORDS = ("click", "type ", "press ", "drag")


class MockAI:
    provider = "mock"

    def __init__(self, config: Config) -> None:
        self.config = config

    def ask(
        self,
        request: AskInput,
        state: ConversationState,
        tools: object = None,
        *,
        command_runner=None,
        allow_actions: bool = False,
    ) -> AIResult:
        state.turns += 1
        text = " ".join((request.text or "").split())
        lowered = text.casefold()

        if request.audio and not text:
            return self._reply(
                "I can't listen while in local mode, but typed app launches work. "
                "Turn off Local mode on the desktop for real voice questions.",
                "oops",
            )
        if not text:
            return self._reply(
                "I'm awake in local mock mode. Typed app launches work — say 'open brave'.",
                "happy",
            )
        if any(word in lowered for word in _SLEEPY_WORDS):
            return self._reply("Goodnight! I'll be right here napping.", "sleepy")
        if tools and any(phrase in lowered for phrase in ("stop pointing", "stop point")):
            tools.call("stop_pointing", {})
            return self._reply("Okay, I'll stop pointing.", "happy", ["stop_pointing"])
        if tools and ("point here" in lowered or "point at the cursor" in lowered):
            snapshot = tools.screen.get()
            x = round(snapshot.screenshot.pointer_x / max(1, snapshot.width) * 1000)
            y = round(snapshot.screenshot.pointer_y / max(1, snapshot.height) * 1000)
            tools.call("point_at_spot", {"x": x, "y": y, "bubble": "Right here!"})
            return self._reply("I'm pointing right at the cursor.", "happy", ["point_at_spot"])
        if tools and re.search(r"\bpoint (?:at|to) (?:the )?(.+)$", text, re.IGNORECASE):
            query = re.search(r"\bpoint (?:at|to) (?:the )?(.+)$", text, re.IGNORECASE).group(1).strip(" .?!")
            result = tools.point_at_text(query)
            return self._reply(result.text, "happy", ["point_at"])
        if tools and any(
            phrase in lowered
            for phrase in ("look at my screen", "look at the screen", "what's on my screen", "read my screen")
        ):
            result = tools.call("look_at_screen", {}, allow_screenshot=False)
            lines = []
            for line in result.text.splitlines():
                if " | line | " in line:
                    lines.append(line.split(" | line | ", 1)[1].split(" | ", 1)[0])
            visible = "; ".join(lines[:5])
            return self._reply(
                "Local OCR can read this on screen: " + visible if visible else "I looked, but I couldn't read any text clearly.",
                "happy",
                ["look_at_screen"],
            )

        command = guess_command(text)
        if command is not None:
            if command_runner is not None:
                try:
                    spoken, ok = command_runner(command)
                except Exception:
                    spoken, ok = "That launch failed on this computer.", False
                return self._reply(spoken, "excited" if ok else "oops", [command])
            return self._reply(
                "I understood that, but no launcher is wired here right now.", "oops", [command]
            )

        if any(word in lowered for word in _INPUT_WORDS):
            return self._reply(
                "I stay hands-off while in local mode. "
                "I can still launch apps — say 'open brave', 'run terminal', 'open tlauncher' or similar.",
                "happy",
            )
        return self._reply(
            "Local mode keeps me offline, but app launches work — say 'open brave' or 'run terminal'. "
            "Turn off Local mode on the desktop for real answers.",
            "happy",
        )

    @staticmethod
    def _reply(text: str, mood: str, tools_used: list[str] | None = None) -> AIResult:
        return AIResult(
            text=text[:2000],
            provider="mock",
            model="local-mock",
            mood=mood,
            tools_used=list(tools_used or []),
            effects=[],
        )
