from __future__ import annotations

import subprocess

import pytest

from berrylink.config import Config
from berrylink.desktop_tools import ControlState, DesktopTools, ToolError
from berrylink.screen import OcrLine, OcrWord, Screenshot, ScreenSnapshot


class FakeOverlay:
    def __init__(self) -> None:
        self.points: list[dict] = []
        self.stopped = 0
        self.slept = 0
        self.actions: list[str] = []
        self.captions: list[tuple[str, str]] = []

    def point_at(self, x, y, label, bubble="", rect=None) -> None:
        self.points.append(
            {"x": x, "y": y, "label": label, "bubble": bubble, "rect": rect}
        )

    def stop_pointing(self) -> None:
        self.stopped += 1

    def sleep(self) -> None:
        self.slept += 1

    def show_action(self, label: str) -> None:
        self.actions.append(label)

    def clear_action(self) -> None:
        pass

    def caption(self, text: str, mood: str = "happy") -> None:
        self.captions.append((text, mood))


class FakeScreen:
    hide_overlay = None

    def __init__(self, snapshot: ScreenSnapshot) -> None:
        self.snapshot = snapshot
        self.get_calls: list[bool] = []

    def get(self, force: bool = False, hide_overlay: bool = True) -> ScreenSnapshot:
        self.get_calls.append(force)
        return self.snapshot

    def available(self) -> dict[str, bool | str]:
        return {
            "capture": True,
            "capture_detail": "fake",
            "ocr": True,
            "ocr_detail": "fake",
        }

    @staticmethod
    def normalized_to_pixels(x: int, y: int, width: int, height: int) -> tuple[int, int]:
        return (
            round((max(0, min(1000, x)) / 1000) * (width - 1)),
            round((max(0, min(1000, y)) / 1000) * (height - 1)),
        )


def make_snapshot(active_window: str = "Notes", active_class: str = "gedit") -> ScreenSnapshot:
    word = OcrWord("W1", "Settings", 100, 200, 80, 20, 95.0)
    word2 = OcrWord("W2", "Delete file", 400, 300, 100, 20, 95.0)
    line = OcrLine(
        "L1",
        "Settings and Delete file",
        50,
        180,
        500,
        60,
        [word, word2],
    )
    shot = Screenshot(
        png=b"",
        width=1000,
        height=800,
        pointer_x=500,
        pointer_y=400,
        active_window=active_window,
        active_class=active_class,
    )
    return ScreenSnapshot(id="snap-1", screenshot=shot, lines=[line])


@pytest.fixture
def config() -> Config:
    return Config(
        display_name="BerryLink tests",
        confirm_actions=True,
        screen_awareness_enabled=True,
    )


@pytest.fixture
def tools(config: Config):
    screen = FakeScreen(make_snapshot())
    overlay = FakeOverlay()
    control = ControlState(enabled=False, screen_awareness=True)
    return DesktopTools(config, screen, overlay, control, confirm=lambda title, detail: False), screen, overlay, control


def test_tool_declarations_follow_control_state(tools) -> None:
    tool, _screen, _overlay, control = tools
    names = {d["name"] for d in tool.tool_declarations()}
    assert {"look_at_screen", "point_at", "point_at_spot", "stop_pointing", "go_to_sleep"} <= names
    assert "click" not in names
    control.set_enabled(True)
    names = {d["name"] for d in tool.tool_declarations()}
    assert {"click", "type_text", "press_keys", "scroll", "drag", "open_app", "open_url"} <= names


def test_look_and_point_stay_local_and_never_need_input_control(tools) -> None:
    tool, screen, overlay, _control = tools
    result = tool.call("look_at_screen", {})
    assert "Settings" in result.text
    assert "W1" in result.text

    result = tool.call("point_at", {"target_id": "W1", "bubble": "That one"})
    assert "W1" in result.text
    assert overlay.points == [
        {
            "x": 140,
            "y": 210,
            "label": "Settings",
            "bubble": "That one",
            "rect": (100, 200, 80, 20),
        }
    ]
    assert screen.get_calls

    result = tool.point_at_text("Settings")
    assert "Settings" in result.text
    assert overlay.points[-1]["x"] == 140

    result = tool.call("point_at_spot", {"x": 500, "y": 500, "bubble": "middle"})
    assert "normalized 500,500" in result.text
    assert overlay.points[-1]["x"] == 500
    assert overlay.points[-1]["y"] == 400


def test_stale_target_and_input_lock(tools) -> None:
    tool, _screen, _overlay, control = tools
    with pytest.raises(ToolError) as caught:
        tool.call("point_at", {"target_id": "NOPE"})
    assert caught.value.code == "stale_target"

    with pytest.raises(ToolError) as caught:
        tool.call("click", {"target_id": "W1"})
    assert caught.value.code == "control_disabled"

    control.set_enabled(True)
    with pytest.raises(ToolError) as caught:
        tool.call("click", {"target_id": "W1"})
    assert caught.value.code == "denied"


def test_screen_switch_and_emergency_stop_block_screen_tools(tools) -> None:
    tool, _screen, _overlay, control = tools
    control.set_screen_awareness(False)
    with pytest.raises(ToolError) as caught:
        tool.call("look_at_screen", {})
    assert caught.value.code == "screen_disabled"
    control.set_screen_awareness(True)

    control.trigger_emergency_stop()
    assert control.snapshot()["emergency_stop"] is True
    assert control.enabled is False
    with pytest.raises(ToolError) as caught:
        tool.call("point_at_spot", {"x": 1, "y": 1})
    assert caught.value.code == "emergency_stop"
    control.resume()
    assert control.snapshot()["control_enabled"] is False


def test_type_text_refuses_secret_windows_and_missing_confirmation(tools) -> None:
    tool, screen, _overlay, control = tools
    control.set_enabled(True)
    screen.snapshot = make_snapshot(active_window="KeePassXC", active_class="keepassxc")
    with pytest.raises(ToolError) as caught:
        tool.call("type_text", {"text": "hello"})
    assert caught.value.code == "sensitive_window"

    screen.snapshot = make_snapshot(active_window="Notes", active_class="gedit")
    tool.confirm = None
    with pytest.raises(ToolError) as caught:
        tool.call("type_text", {"text": "hello"})
    assert caught.value.code == "confirmation_unavailable"


def test_consequential_click_always_asks_even_when_confirmation_is_off(config, tools) -> None:
    _tool, _screen, _overlay, control = tools
    config.confirm_actions = False
    confirmations: list[tuple[str, str]] = []
    tool = DesktopTools(
        config,
        _screen,
        _overlay,
        control,
        confirm=lambda action, description: confirmations.append((action, description)) or False,
    )
    control.set_enabled(True)
    with pytest.raises(ToolError) as caught:
        tool.call("click", {"target_id": "W2"})
    assert caught.value.code == "denied"
    assert confirmations and confirmations[0][0] == "click"
    assert "consequential" in confirmations[0][1]


def test_url_and_key_allowlists_reject_dangerous_input(tools, monkeypatch) -> None:
    tool, _screen, _overlay, control = tools
    config = tool.config
    control.set_enabled(True)
    config.confirm_actions = False

    for url in ("file:///etc/passwd", "javascript:alert(1)", "https://user:pass@example.com"):
        with pytest.raises(ToolError) as caught:
            tool.call("open_url", {"url": url})
        assert caught.value.code == "bad_url"

    for keys in ("ctrl+alt+s", "alt+control+delete", "ctrl+alt+F4", "super+l", "a+b"):
        with pytest.raises(ToolError) as caught:
            tool.call("press_keys", {"keys": keys})
        assert caught.value.code == "bad_keys"

    with pytest.raises(ToolError) as caught:
        tool._run(["echo", "bad\x00arg"])
    assert caught.value.code == "bad_command"


def test_valid_url_uses_argv_without_a_shell(tools, monkeypatch) -> None:
    tool, _screen, _overlay, control = tools
    control.set_enabled(True)
    tool.config.confirm_actions = False
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(tool, "_run", fake_run)
    result = tool.call("open_url", {"url": "https://example.com/a?b=1"})
    assert "Opened" in result.text
    assert calls == [["xdg-open", "https://example.com/a?b=1"]]


def test_allow_tools_false_blocks_everything(tools) -> None:
    tool, _screen, _overlay, _control = tools
    with pytest.raises(ToolError) as caught:
        tool.call("look_at_screen", {}, allow_tools=False)
    assert caught.value.code == "tools_disabled"
