from __future__ import annotations

from berrylink.config import Config
from berrylink.desktop_tools import ControlState, DesktopTools
from berrylink.gemini_gateway import AskInput, ConversationState, build_ai
from berrylink.mock_ai import MockAI

from test_desktop_tools import FakeOverlay, FakeScreen, make_snapshot


def make_tools() -> tuple[MockAI, DesktopTools, FakeOverlay, Config]:
    config = Config(display_name="Mock test", screen_awareness_enabled=True)
    overlay = FakeOverlay()
    screen = FakeScreen(make_snapshot())
    control = ControlState(enabled=False, screen_awareness=True)
    tools = DesktopTools(config, screen, overlay, control)
    return MockAI(config), tools, overlay, config


def test_without_a_key_build_ai_stays_local() -> None:
    config = Config(display_name="No key")
    assert build_ai(config, None).provider == "mock"


def test_mock_voice_does_not_pretend_to_understand() -> None:
    ai, tools, overlay, _ = make_tools()
    state = ConversationState()
    result = ai.ask(AskInput(audio=b"fake-wav"), state, tools)
    assert result.provider == "mock"
    assert "can't listen while in local mode" in result.text
    assert result.tools_used == []
    assert overlay.points == []
    assert state.turns == 1


def test_mock_points_at_local_ocr_text() -> None:
    ai, tools, overlay, _ = make_tools()
    state = ConversationState()
    result = ai.ask(AskInput(text="Please point at Settings"), state, tools)
    assert "Pointing at" in result.text
    assert result.tools_used == ["point_at"]
    assert overlay.points[-1]["label"] == "Settings"
    assert overlay.points[-1]["x"] == 140


def test_mock_looks_at_screen_and_reports_text() -> None:
    ai, tools, overlay, _ = make_tools()
    result = ai.ask(AskInput(text="what's on my screen?"), ConversationState(), tools)
    assert result.tools_used == ["look_at_screen"]
    assert "Settings" in result.text
    assert overlay.points == []


def test_mock_stops_pointing_and_sleeps_by_mood() -> None:
    ai, tools, overlay, _ = make_tools()
    result = ai.ask(AskInput(text="stop pointing"), ConversationState(), tools)
    assert result.tools_used == ["stop_pointing"]
    assert overlay.stopped == 1

    result = ai.ask(AskInput(text="goodnight"), ConversationState())
    assert result.tools_used == []
    assert result.effects == []
    assert result.mood == "sleepy"


def test_mock_maps_launch_phrases_to_commands() -> None:
    ai, _tools, _overlay, _ = make_tools()
    ran: list[str] = []

    def runner(command: str) -> tuple[str, bool]:
        ran.append(command)
        return "Opening Brave for you.", True

    with_brave = ai.ask(
        AskInput(text="open brave browser please"), ConversationState(), None, command_runner=runner
    )
    assert ran == ["open_brave"]
    assert with_brave.tools_used == ["open_brave"]
    assert with_brave.mood == "excited"
    assert with_brave.text == "Opening Brave for you."

    without_runner = ai.ask(AskInput(text="open the terminal"), ConversationState())
    assert without_runner.tools_used == ["open_terminal"]
    assert without_runner.mood == "oops"


def test_mock_refuses_input_actions_without_control() -> None:
    ai, tools, _overlay, _ = make_tools()
    result = ai.ask(AskInput(text="click the delete button"), ConversationState(), tools)
    assert "hands-off while in local mode" in result.text
    assert result.tools_used == []


def test_mock_empty_ask_is_honest() -> None:
    ai, tools, _overlay, _ = make_tools()
    result = ai.ask(AskInput(), ConversationState(), tools)
    assert "local mock mode" in result.text
    assert result.provider == "mock"
