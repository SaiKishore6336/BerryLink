from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from berrylink.config import Config, GEMINI_MODEL
from berrylink.desktop_tools import ToolResult
from berrylink.gemini_gateway import (
    AIError,
    AskInput,
    ConversationState,
    GeminiGateway,
    LocalRateLimiter,
)


class FakeState:
    def __init__(self, mode: str = "tool") -> None:
        self.mode = mode
        self.posts: list[dict] = []
        self.gets: list[str] = []
        self.headers: list[dict] = []


class FakeHandler(BaseHTTPRequestHandler):
    server: "FakeHttpServer"

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

    def do_GET(self) -> None:  # noqa: N802
        self.server.state.gets.append(self.path)
        self.server.state.headers.append(dict(self.headers.items()))
        self._json(
            200,
            {
                "models": [
                    {"name": "models/gemini-3.8-flash"},
                    {"name": "models/other-model"},
                ]
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        body = json.loads(raw.decode("utf-8"))
        self.server.state.posts.append({"path": self.path, "body": body})
        self.server.state.headers.append(dict(self.headers.items()))
        if self.server.state.mode == "quota":
            self._json(
                429,
                {
                    "error": {
                        "status": "RESOURCE_EXHAUSTED",
                        "message": "Free-tier quota exhausted for AIza" + "x" * 24,
                    }
                },
                {"Retry-After": "17"},
            )
            return
        if self.server.state.mode == "auth":
            self._json(401, {"error": {"status": "UNAUTHENTICATED", "message": "bad key"}})
            return
        if self.server.state.mode == "completed" or len(self.server.state.posts) > 1:
            self._json(
                200,
                {
                    "id": "int_2",
                    "status": "completed",
                    "output_text": "The button is right there.",
                    "usage": {"total_input_tokens": 4, "total_output_tokens": 2},
                },
            )
            return
        self._json(
            200,
            {
                "id": "int_1",
                "status": "requires_action",
                "steps": [
                    {
                        "type": "function_call",
                        "id": "call_1",
                        "name": "point_at_spot",
                        "arguments": {"x": 100, "y": 200, "bubble": "Here"},
                    }
                ],
                "usage": {"total_input_tokens": 7, "total_output_tokens": 3},
            },
        )


class FakeHttpServer(ThreadingHTTPServer):
    state: FakeState

    def __init__(self, address, handler, state: FakeState):
        super().__init__(address, handler)
        self.state = state


class StubTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def tool_declarations(self):
        return [
            {
                "type": "function",
                "name": "point_at_spot",
                "description": "Point at a normalized spot.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "bubble": {"type": "string"},
                    },
                    "required": ["x", "y"],
                },
            }
        ]

    def call(self, name, arguments, *, allow_screenshot=False, allow_tools=True):
        self.calls.append((name, dict(arguments)))
        return ToolResult(text="Pointing at (100,200).", effects=["pointing"])


@pytest.fixture
def fake_gemini():
    servers: list[FakeHttpServer] = []

    def start(mode: str = "tool"):
        state = FakeState(mode)
        server = FakeHttpServer(("127.0.0.1", 0), FakeHandler, state)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}/v1beta", state

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def make_gateway(base_url: str, limiter: LocalRateLimiter | None = None) -> GeminiGateway:
    config = Config(
        display_name="Gemini test",
        http_timeout_seconds=30,
        max_requests_per_minute=10,
        max_requests_per_day=10,
    )
    return GeminiGateway(
        config,
        "test-gemini-key-1234567890",
        base_url=base_url,
        limiter=limiter or LocalRateLimiter(10, 10),
    )


def test_gemini_function_call_round_trip(fake_gemini) -> None:
    base_url, state = fake_gemini("tool")
    gateway = make_gateway(base_url)
    tools = StubTools()
    result = gateway.ask(
        AskInput(text="Point at the send button", screen_text="W1 | word | Send | 100,200"),
        ConversationState(),
        tools,
    )

    assert result.provider == "gemini"
    assert result.model == GEMINI_MODEL
    assert result.text == "The button is right there."
    assert result.tools_used == ["point_at_spot"]
    assert result.effects == ["pointing"]
    assert result.interaction_id == "int_2"
    assert result.input_tokens == 11
    assert result.output_tokens == 5
    assert tools.calls == [("point_at_spot", {"x": 100, "y": 200, "bubble": "Here"})]

    assert len(state.posts) == 2
    first = state.posts[0]
    assert first["path"].startswith("/v1beta/interactions")
    assert first["body"]["model"] == GEMINI_MODEL
    assert first["body"]["store"] is True
    assert first["body"]["tools"][0]["name"] == "point_at_spot"
    assert "previous_interaction_id" not in first["body"]
    assert "Point at the send button" in json.dumps(first["body"])
    assert first["body"]["generation_config"]["thinking_level"] == "low"
    assert {k.lower(): v for k, v in state.headers[0].items()}["x-goog-api-key"] == "test-gemini-key-1234567890"

    second = state.posts[1]["body"]
    assert second["previous_interaction_id"] == "int_1"
    assert second["input"][0]["type"] == "function_result"
    assert second["input"][0]["call_id"] == "call_1"
    assert second["input"][0]["is_error"] is False
    assert "Pointing at" in second["input"][0]["result"][0]["text"]

    # The API key must never be placed in a JSON body or logged response.
    every_body = json.dumps([post["body"] for post in state.posts])
    assert "test-gemini-key" not in every_body


def test_gemini_completed_response_without_tools(fake_gemini) -> None:
    base_url, state = fake_gemini("completed")
    gateway = make_gateway(base_url)
    result = gateway.ask(AskInput(text="hello"), ConversationState())
    assert result.text == "The button is right there."
    assert result.tools_used == []
    assert len(state.posts) == 1
    assert "tools" not in state.posts[0]["body"]


def test_gemini_quota_error_is_mapped_and_secret_is_redacted(fake_gemini, caplog) -> None:
    base_url, _state = fake_gemini("quota")
    gateway = make_gateway(base_url)
    with pytest.raises(AIError) as caught:
        gateway.ask(AskInput(text="hello"), ConversationState())
    assert caught.value.code == "quota_exhausted"
    assert caught.value.retry_after == "17"
    assert "free-tier" in caught.value.message.lower()
    assert "AIza" not in str(caught.value)
    assert "AIza" not in caplog.text


def test_gemini_auth_error_is_clear(fake_gemini) -> None:
    base_url, _state = fake_gemini("auth")
    gateway = make_gateway(base_url)
    with pytest.raises(AIError) as caught:
        gateway.ask(AskInput(text="hello"), ConversationState())
    assert caught.value.code == "auth_failed"


def test_validate_key_checks_model_availability(fake_gemini) -> None:
    base_url, state = fake_gemini("completed")
    gateway = make_gateway(base_url)
    result = gateway.validate_key("some-other-key-1234567890")
    assert result["ok"] is True
    assert result["models_seen"] == 2
    assert GEMINI_MODEL in result["message"]
    assert state.gets and "/models" in state.gets[0]
    assert gateway.api_key == "test-gemini-key-1234567890"


def test_local_rate_limit_stops_before_second_http_call(fake_gemini) -> None:
    base_url, state = fake_gemini("completed")
    gateway = make_gateway(base_url, limiter=LocalRateLimiter(1, 10))
    gateway.ask(AskInput(text="one"), ConversationState())
    with pytest.raises(AIError) as caught:
        gateway.ask(AskInput(text="two"), ConversationState())
    assert caught.value.code == "local_rate_limit"
    assert len(state.posts) == 1
