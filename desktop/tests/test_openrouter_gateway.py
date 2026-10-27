from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from berrylink.ai_prompt import (
    ACTION_INSTRUCTION,
    parse_action_reply,
    parse_command_reply,
    parse_mood_reply,
    system_instruction,
)
from berrylink.config import Config
from berrylink.gemini_gateway import AIError, AskInput, ConversationState, LocalRateLimiter
from berrylink.openrouter_gateway import OpenRouterGateway


class FakeState:
    def __init__(self, mode: str = "chat") -> None:
        self.mode = mode
        self.next_mood: str | None = None
        self.posts: list[dict] = []
        self.gets: list[str] = []
        self.headers: list[dict] = []


class FakeHandler(BaseHTTPRequestHandler):
    server: FakeHttpServer

    def log_message(self, format, *args):  # noqa: A003
        return

    def _json(self, status: int, payload: dict, extra_headers: dict | None = None) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": {"code": status, "message": message}})

    def _chat(self, content: str) -> None:
        self._json(
            200,
            {
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 4},
            },
        )

    def do_GET(self) -> None:  # noqa: N802
        self.server.state.gets.append(self.path)
        self.server.state.headers.append(dict(self.headers.items()))
        if self.path.endswith("/key"):
            self._json(
                200,
                {"data": {"label": "berrylink-test", "usage": {"limit": {"is_free_tier": False}}}},
            )
        else:
            self._json(
                200,
                {"data": [{"id": "openrouter/auto"}, {"id": "some/free-model:free"}]},
            )

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.state.posts.append({"path": self.path, "body": body})
        self.server.state.headers.append(dict(self.headers.items()))
        state = self.server.state
        if state.mode == "quota":
            self._json(429, {"error": {"code": 429, "message": "Rate limit exceeded"}})
            return
        if state.mode == "auth":
            self._error(401, "Invalid key")
            return
        if state.mode == "credits":
            self._error(402, "Not enough credits for this model")
            return
        if state.mode == "deadmodel" and len(state.posts) == 1:
            self._json(
                404,
                {"error": {"code": 404, "message": "No endpoints found for your request"}},
            )
            return
        if state.mode == "command":
            self._chat("COMMAND: open_brave\nOpening Brave up now. [mood: happy]")
            return
        if state.mode == "action":
            self._chat('ACTION: click {"target_id": "L12"}\nDoing it now. [mood: excited]')
            return
        if state.next_mood is not None:
            content = f"Done. [mood: {state.next_mood}]"
            state.next_mood = None
            self._chat(content)
            return
        self._chat("It is open right there. [mood: happy]")


class FakeHttpServer(ThreadingHTTPServer):
    state: FakeState

    def __init__(self, address, handler, state: FakeState) -> None:
        self.state = state
        super().__init__(address, handler, True)


@pytest.fixture
def fake_openrouter():
    servers: list[FakeHttpServer] = []

    def start(mode: str = "chat"):
        state = FakeState(mode)
        server = FakeHttpServer(("127.0.0.1", 0), FakeHandler, state)
        servers.append(server)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return f"http://127.0.0.1:{server.server_address[1]}/api/v1", state

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def make_config(**overrides) -> Config:
    values = dict(
        display_name="OpenRouter test",
        ai_provider="openrouter",
        openrouter_model="openrouter/auto",
        openrouter_fallback_models="",
        http_timeout_seconds=30,
        max_requests_per_minute=10,
        max_requests_per_day=10,
    )
    values.update(overrides)
    return Config(**values)


def make_gateway(
    base_url: str,
    config: Config | None = None,
    limiter: LocalRateLimiter | None = None,
) -> OpenRouterGateway:
    return OpenRouterGateway(
        config or make_config(),
        "sk-or-test-key-1234567890",
        base_url=base_url,
        limiter=limiter or LocalRateLimiter(10, 10),
    )


def test_openrouter_one_shot_with_command_reply(fake_openrouter) -> None:
    base_url, state = fake_openrouter("command")
    ran: list[str] = []

    def runner(command: str) -> tuple[str, bool]:
        ran.append(command)
        return "Opening Brave for you.", True

    conv = ConversationState()
    result = make_gateway(base_url).ask(
        AskInput(text="open my default browser please"),
        conv,
        None,
        command_runner=runner,
    )

    assert result.provider == "openrouter"
    assert result.model == "openrouter/auto"
    assert result.tools_used == ["open_brave"]
    assert result.effects == []
    assert result.mood == "excited"
    assert result.text == "Opening Brave for you."
    assert ran == ["open_brave"]

    # One phrase = exactly one POST, and never a tools body.
    assert len(state.posts) == 1
    only = state.posts[0]
    assert only["path"].endswith("chat/completions")
    assert "tools" not in only["body"]
    assert only["body"]["stream"] is False
    assert only["body"]["temperature"] == 0.2

    headers = {k.lower(): v for k, v in state.headers[0].items()}
    assert headers["authorization"].startswith("Bearer sk-or-test-key")
    assert "sk-or-test-key" not in json.dumps([p["body"] for p in state.posts])

    # Each ask is remembered as one compact user/assistant turn.
    make_gateway(base_url).ask(AskInput(text="second question"), conv, None)
    assert [m["role"] for m in conv.messages] == ["user", "assistant", "user", "assistant"]
    assert "second question" in conv.messages[2]["content"]
    assert conv.messages[-1]["role"] == "assistant"


def test_openrouter_chat_reply_keeps_mood_and_history(fake_openrouter) -> None:
    base_url, state = fake_openrouter("chat")
    conv = ConversationState()
    result = make_gateway(base_url).ask(AskInput(text="hello"), conv, None)
    assert result.tools_used == []
    assert result.text == "It is open right there."
    assert result.mood == "happy"


def test_command_without_runner_is_honest(fake_openrouter) -> None:
    base_url, _ = fake_openrouter("command")
    result = make_gateway(base_url).ask(AskInput(text="open brave"), ConversationState(), None)
    assert result.tools_used == ["open_brave"]
    assert result.mood == "oops"
    assert "isn't letting me run commands" in result.text


def test_fallback_chain_tries_next_model(fake_openrouter) -> None:
    base_url, state = fake_openrouter("deadmodel")
    config = make_config(openrouter_fallback_models="some/free-model:free")
    result = make_gateway(base_url, config).ask(AskInput(text="hello"), ConversationState(), None)
    assert result.text == "It is open right there."
    assert result.mood == "happy"
    assert [p["body"]["model"] for p in state.posts] == ["openrouter/auto", "some/free-model:free"]


def test_openrouter_rate_limit_error_is_mapped(fake_openrouter, caplog) -> None:
    base_url, _ = fake_openrouter("quota")
    gateway = make_gateway(base_url)
    with pytest.raises(AIError) as caught:
        gateway.ask(AskInput(text="hello"), ConversationState())
    assert caught.value.code == "quota_exhausted"
    assert "sk-or-test-key" not in str(caught.value)
    assert "sk-or-test-key" not in caplog.text


def test_openrouter_auth_error_is_clear(fake_openrouter) -> None:
    base_url, _ = fake_openrouter("auth")
    with pytest.raises(AIError) as caught:
        make_gateway(base_url).ask(AskInput(text="hello"), ConversationState())
    assert caught.value.code == "auth_failed"


def test_openrouter_missing_credits_has_clear_hint(fake_openrouter) -> None:
    base_url, _ = fake_openrouter("credits")
    with pytest.raises(AIError) as caught:
        make_gateway(base_url).ask(AskInput(text="hello"), ConversationState())
    assert caught.value.code == "no_credits"
    assert ":free" in caught.value.message


def test_openrouter_model_gone_maps_to_unavailable(fake_openrouter) -> None:
    base_url, _ = fake_openrouter("deadmodel")
    with pytest.raises(AIError) as caught:
        make_gateway(base_url).ask(AskInput(text="hello"), ConversationState())
    assert caught.value.code == "model_unavailable"


def test_openrouter_validate_key_checks_model(fake_openrouter) -> None:
    base_url, state = fake_openrouter("chat")
    gateway = make_gateway(base_url)
    result = gateway.validate_key("sk-or-other-key-9876543210")
    assert result["ok"] is True
    assert result["models_seen"] == 2
    assert "openrouter/auto" in result["message"]
    gets = "\n".join(state.gets)
    assert "/key" in gets and "/models" in gets
    assert gateway.api_key == "sk-or-test-key-1234567890"


def test_mood_tag_is_stripped_from_reply() -> None:
    clean, mood = parse_mood_reply("All done! [mood: sleepy]")
    assert clean == "All done!"
    assert mood == "sleepy"
    clean, mood = parse_mood_reply("No tag here", default="thinking")
    assert mood == "thinking"
    assert mood != ""


def test_command_reply_parsing() -> None:
    command, spoken, mood = parse_command_reply("COMMAND: open_terminal\nHere you go. [mood: happy]")
    assert command == "open_terminal"
    assert spoken == "Here you go."
    assert mood == "happy"
    command, spoken, mood = parse_command_reply("command: undercover-off")
    assert command is None
    assert spoken == "command: undercover-off"[-len("command: undercover-off"):]
    command, spoken, mood = parse_command_reply("COMMAND: none ... [mood: sleepy]")
    assert command is None
    assert mood == "sleepy"
    command, spoken, mood = parse_command_reply("")
    assert command is None
    assert spoken == ""
    assert mood == "happy"


def test_system_prompt_contains_command_and_mood_contract() -> None:
    text = system_instruction()
    assert "COMMAND: <id>" in text
    assert "open_brave" in text and "undercover_off" in text
    assert "mood: happy" in text
    assert "Never output a COMMAND for anything else" in text


def test_parse_action_reply_shapes() -> None:
    name, args, rest = parse_action_reply(
        'ACTION: click {"target_id": "L12"}\nDoing it now. [mood: excited]'
    )
    assert name == "click"
    assert args == {"target_id": "L12"}
    assert rest == "Doing it now. [mood: excited]"
    assert parse_action_reply("just a chat reply")[0] is None
    assert parse_action_reply("ACTION: evil_tool {}")[0] is None
    assert parse_action_reply("ACTION: click not-json")[0] is None
    assert parse_action_reply("")[0] is None


def test_action_reply_becomes_a_proposed_action(fake_openrouter) -> None:
    base_url, state = fake_openrouter("action")
    gateway = make_gateway(base_url)
    request = AskInput(
        text="Click the Run button on screen",
        screen_text="On-screen targets (id | kind | text | center):",
        action_instruction=ACTION_INSTRUCTION,
    )
    result = gateway.ask(request, ConversationState(), None, allow_actions=True)
    assert result.action == {"name": "click", "args": {"target_id": "L12"}}
    assert result.mood == "excited"
    assert result.tools_used == ["click"]
    assert result.text == "Doing it now."
    # The instruction and the screen context rode along in the prompt.
    body = json.dumps(state.posts[0]["body"])
    assert "Desktop actions" in body and "target_id" in body


def test_action_reply_stays_raw_without_the_flag(fake_openrouter) -> None:
    base_url, _state = fake_openrouter("action")
    gateway = make_gateway(base_url)
    result = gateway.ask(AskInput(text="hello"), ConversationState())
    assert result.action is None
    assert "ACTION: click" in result.text


def test_action_parse_supports_double_click_count() -> None:
    assert parse_action_reply('ACTION: click {"target_id": "L3", "count": 2}')[1] == {
        "target_id": "L3",
        "count": 2,
    }
