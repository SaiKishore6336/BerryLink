from __future__ import annotations

import hashlib
import json
import ssl
from typing import Any

import pytest
from websockets.sync.client import connect

from berrylink.config import Config
from berrylink.desktop_tools import ControlState, DesktopTools
from berrylink.gemini_gateway import AIError, AIResult, AskInput, ConversationState
from berrylink.mock_ai import MockAI
from berrylink.pairing import PairingManager, ensure_tls_identity
from berrylink.protocol import Envelope, parse
from berrylink.screen import OcrLine, OcrWord, Screenshot, ScreenSnapshot
from berrylink.server import BerryLinkServer


class FakeOverlay:
    def __init__(self) -> None:
        self.points: list[dict[str, Any]] = []
        self.stopped = 0
        self.slept = 0

    def point_at(self, x, y, label, bubble="", rect=None) -> None:
        self.points.append({"x": x, "y": y, "label": label, "bubble": bubble, "rect": rect})

    def stop_pointing(self) -> None:
        self.stopped += 1

    def sleep(self) -> None:
        self.slept += 1

    def show_action(self, label: str) -> None:
        pass

    def clear_action(self) -> None:
        pass

    def caption(self, text: str, mood: str = "happy") -> None:
        pass


class FakeScreen:
    hide_overlay = None

    def __init__(self) -> None:
        word = OcrWord("W1", "Settings", 100, 200, 80, 20, 95.0)
        line = OcrLine("L1", "Settings", 50, 180, 200, 60, [word])
        shot = Screenshot(
            png=b"",
            width=1000,
            height=800,
            pointer_x=500,
            pointer_y=400,
            active_window="Notes",
            active_class="gedit",
        )
        self.snapshot = ScreenSnapshot(id="snap-1", screenshot=shot, lines=[line])

    def get(self, force: bool = False, hide_overlay: bool = True) -> ScreenSnapshot:
        return self.snapshot

    def available(self) -> dict[str, Any]:
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


class DummyMeeting:
    active = False

    def status(self) -> dict[str, Any]:
        return {"recording": False}


class DummyUi:
    def __init__(self) -> None:
        self.captions: list[tuple[str, str]] = []
        self.peers: list[dict[str, Any]] = []
        self.confirmations: list[tuple[str, str]] = []

    def confirm(self, title: str, description: str, timeout: float = 90.0) -> bool:
        self.confirmations.append((title, description))
        return False

    def caption(self, text: str, mood: str = "happy") -> None:
        self.captions.append((text, mood))

    def notify_runtime(self) -> None:
        pass

    def peers_changed(self, peers) -> None:
        self.peers = list(peers)


@pytest.fixture
def live_server(data_paths):
    config = Config(
        display_name="BerryLink integration test",
        confirm_actions=True,
        screen_awareness_enabled=True,
        max_requests_per_minute=20,
        max_requests_per_day=200,
    )
    identity = ensure_tls_identity(data_paths.tls_dir, config.display_name, ["127.0.0.1"])
    pairing = PairingManager(data_paths.devices_file)
    screen = FakeScreen()
    overlay = FakeOverlay()
    control = ControlState(enabled=False, screen_awareness=True)
    ui = DummyUi()
    tools = DesktopTools(config, screen, overlay, control, confirm=ui.confirm)
    ai = MockAI(config)
    server = BerryLinkServer(
        config,
        pairing,
        identity,
        lambda: ai,
        tools,
        DummyMeeting(),
        ui,
    )
    port = server.start(port=0, bind_host="127.0.0.1")
    try:
        yield server, port, identity, pairing, overlay, ui
    finally:
        server.stop()
        assert server.running is False


def pin_for(port: int) -> str:
    pem = ssl.get_server_certificate(("127.0.0.1", port))
    der = ssl.PEM_cert_to_DER_cert(pem)
    return hashlib.sha256(der).hexdigest().upper()


def client(port: int):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    # The websockets sync client on Python 3.14 can intermittently stall when
    # opening several TLS 1.3 connections in quick succession.  The server
    # supports TLS 1.2 and 1.3; use 1.2 here so this transport test exercises
    # BerryLink's protocol reliably.  Android negotiates TLS 1.3 normally.
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    return connect(
        f"wss://127.0.0.1:{port}",
        ssl=context,
        server_hostname="127.0.0.1",
        proxy=None,
        open_timeout=10,
        close_timeout=5,
    )


def send_request(ws, method: str, payload: dict | None = None) -> Any:
    envelope = Envelope.request(method, payload or {})
    ws.send(envelope.to_json())
    # Server-initiated events (cursor updates, control changes) can interleave
    # with the response; read until the matching response envelope arrives.
    while True:
        response = parse(ws.recv(timeout=15))
        assert response.kind == "response"
        assert response.reply_to == envelope.id
        return response


def test_live_tls_pin_matches_identity(live_server) -> None:
    _server, port, identity, _pairing, _overlay, _ui = live_server
    assert pin_for(port) == identity.fingerprint


def test_untrusted_self_signed_certificate_fails_default_verification(live_server) -> None:
    _server, port, _identity, _pairing, _overlay, _ui = live_server
    context = ssl.create_default_context()
    with pytest.raises(ssl.SSLError):
        with connect(
            f"wss://127.0.0.1:{port}",
            ssl=context,
            server_hostname="127.0.0.1",
            proxy=None,
            open_timeout=5,
        ):
            pass


def test_pair_auth_status_ask_and_meeting_blocked(live_server) -> None:
    _server, port, identity, pairing, overlay, _ui = live_server
    with client(port) as ws:
        denied = send_request(ws, "status.get")
        assert denied.ok is False
        assert denied.error["code"] == "unauthorized"

        window = pairing.begin_pairing()
        paired = send_request(
            ws,
            "pair.request",
            {"code": window.code, "device_name": "Test phone", "protocol": 1},
        )
        assert paired.ok is True
        payload = paired.payload
        token = payload["token"]
        device_id = payload["device_id"]
        assert payload["certificate_fingerprint"] == identity.pretty_fingerprint
        assert payload["desktop_name"] == "BerryLink integration test"

        status = send_request(ws, "status.get")
        assert status.ok is True
        assert status.payload["protocol"] == 1
        assert status.payload["ai"]["provider"] == "mock"
        assert status.payload["certificate_fingerprint"] == identity.pretty_fingerprint
        assert "meeting" not in " ".join(status.payload["capabilities"]).lower()

        blocked = send_request(ws, "meeting.start", {})
        assert blocked.ok is False
        assert blocked.error["code"] == "unknown_method"
        blocked = send_request(ws, "notes.list", {})
        assert blocked.ok is False
        assert blocked.error["code"] == "unknown_method"

        looked = send_request(ws, "look.screen", {})
        assert looked.ok is True
        assert "Settings" in looked.payload["context"]

        pointed = send_request(ws, "point.text", {"text": "Settings"})
        assert pointed.ok is True
        assert "Pointing at" in pointed.payload["message"]
        assert overlay.points[-1]["label"] == "Settings"

        asked = send_request(
            ws,
            "ask",
            {"text": "point at Settings", "include_screen": False},
        )
        assert asked.ok is True
        assert asked.payload["provider"] == "mock"
        assert "point_at" in asked.payload["tools_used"]
        assert not asked.payload.get("notice")

        empty = send_request(ws, "ask", {"text": ""})
        assert empty.ok is False
        assert empty.error["code"] == "empty_ask"
        reset = send_request(ws, "session.reset", {})
        assert reset.ok is True

    # A fresh connection must authenticate with the token before doing anything.
    with client(port) as ws:
        bad = send_request(ws, "auth", {"device_id": device_id, "token": "wrong"})
        assert bad.ok is False
        assert bad.error["code"] == "auth_failed"
    with client(port) as ws:
        auth = send_request(ws, "auth", {"device_id": device_id, "token": token})
        assert auth.ok is True
        assert auth.payload["device_id"] == device_id
        again = send_request(ws, "status.get")
        assert again.ok is True
        assert again.payload["phone"]["device_id"] == device_id


def test_cursor_position_streams_to_authenticated_phone(live_server) -> None:
    server, port, _identity, pairing, _overlay, _ui = live_server
    window = pairing.begin_pairing()
    with client(port) as ws:
        paired = send_request(
            ws,
            "pair.request",
            {"code": window.code, "device_name": "Cursor phone", "protocol": 1},
        )
        assert paired.ok is True

        # Any post-auth sync can arrive before this ping; the request helper
        # skips server events and this call confirms the link is usable.
        ping = send_request(ws, "ping")
        assert ping.ok is True

        server.set_cursor_position(0.56, -0.28)
        event = parse(ws.recv(timeout=5))
        assert event.kind == "event"
        assert event.method == "cursor"
        assert event.payload == {"x": 0.56, "y": -0.28}


def test_pairing_rejects_unknown_code_but_keeps_connection(live_server) -> None:
    _server, port, _identity, pairing, _overlay, _ui = live_server
    window = pairing.begin_pairing()
    wrong = "000000" if window.code != "000000" else "111111"
    with client(port) as ws:
        failed = send_request(
            ws,
            "pair.request",
            {"code": wrong, "device_name": "Phone", "protocol": 1},
        )
        assert failed.ok is False
        assert failed.error["code"] == "pairing_failed"
        # The connection remains usable and can retry with the right code.
        paired = send_request(
            ws,
            "pair.request",
            {"code": window.code, "device_name": "Phone", "protocol": 1},
        )
        assert paired.ok is True


def test_codeless_pairing_denied_without_desktop_allow(live_server) -> None:
    _server, port, _identity, pairing, _overlay, ui = live_server
    assert len(pairing.list_devices()) == 0
    with client(port) as ws:
        denied = send_request(
            ws,
            "pair.request",
            {"codeless": True, "device_name": "Lava test", "protocol": 1},
        )
        assert denied.ok is False
        assert denied.error["code"] == "pairing_denied"
    # The dialog was actually raised on the desktop.
    assert ui.confirmations and ui.confirmations[-1][0] == "Allow a new phone to connect?"
    # Nothing was paired through a denial.
    assert pairing.list_devices() == []


def test_codeless_pairing_allowed_by_desktop_owner(live_server) -> None:
    _server, port, _identity, pairing, _overlay, ui = live_server
    with client(port) as ws:
        ui.confirm = lambda *args, **kwargs: True  # the owner pressed Allow once
        paired = send_request(
            ws,
            "pair.request",
            {"codeless": True, "device_name": "Lava test", "protocol": 1},
        )
        assert paired.ok is True
        payload = json.loads(json.dumps(paired.payload))
        assert payload["token"]
        assert payload["device_name"] == "Lava test"
        assert payload["certificate_fingerprint"]
    devices = pairing.list_devices()
    assert devices and devices[-1]["name"] == "Lava test"
    # The phone's token authenticates straight away (auto-join).
    with client(port) as ws:
        auth = send_request(
            ws,
            "auth",
            {"device_id": devices[-1]["id"], "token": payload["token"], "name": "Lava test"},
        )
        assert auth.ok is True


def test_codeless_pairing_respects_disabled_flag(live_server) -> None:
    server, port, _identity, pairing, _overlay, _ui = live_server
    server.config.allow_codeless_pairing = False
    with client(port) as ws:
        rejected = send_request(
            ws,
            "pair.request",
            {"codeless": True, "device_name": "Lava test", "protocol": 1},
        )
        assert rejected.ok is False
        assert rejected.error["code"] == "pairing_required"
        assert pairing.list_devices() == []


class ActionStubAI:
    provider = "stub"
    model = "stub-action"

    def ask(self, request, state, tools=None, *, command_runner=None, allow_actions=False):
        self.seen = {
            "allow_actions": allow_actions,
            "instruction": request.action_instruction,
            "screen_text": request.screen_text,
            "text": request.text,
        }
        state.turns += 1
        if allow_actions:
            assert "Desktop actions" in request.action_instruction
            assert "Settings" in request.screen_text
            return AIResult(
                text="Doing it now.",
                provider="stub",
                model="stub-action",
                mood="happy",
                tools_used=["click"],
                action={"name": "click", "args": {"target_id": "L1"}},
            )
        assert not request.action_instruction or "disabled" in request.action_instruction
        return AIResult(text="Chatting as usual.", provider="stub", model="stub-action")


def _pair_window(ws, pairing) -> None:
    window = pairing.begin_pairing()
    response = send_request(
        ws,
        "pair.request",
        {"code": window.code, "device_name": "Action phone", "protocol": 1},
    )
    assert response.ok is True


def test_click_ask_asks_the_desktop_owner_before_anything(live_server) -> None:
    server, port, _identity, pairing, _overlay, ui = live_server
    server.ai_getter = lambda: ActionStubAI()
    server.tools.control.set_enabled(True)  # the owner flipped "Allow input control" on
    with client(port) as ws:
        _pair_window(ws, pairing)
        reply = send_request(
            ws,
            "ask",
            {"text": "click the Settings button", "include_screen": False},
        )
        assert reply.ok is True
        payload = reply.payload
        # The action was proposed, routed to the Allow dialog, and denied —
        # the tool never executed because DummyUi.confirm returns False.
        assert payload["tools_used"] == ["click"]
        assert payload["mood"] == "oops"
        assert "won't touch the screen" in payload["reply"]
        assert ui.confirmations and "click" in ui.confirmations[-1][0]
    # The screen OCR round happened only because the phrase asked for a click.
    assert "Settings" in server.tools._last_snapshot.context_text()


def test_click_ask_ignored_when_input_control_is_off(live_server) -> None:
    server, port, _identity, pairing, _overlay, ui = live_server
    stub = ActionStubAI()
    server.ai_getter = lambda: stub  # fixtures start with control disabled
    with client(port) as ws:
        _pair_window(ws, pairing)
        reply = send_request(
            ws,
            "ask",
            {"text": "type hello in the field", "include_screen": False},
        )
        assert reply.ok is True
        assert reply.payload["reply"] == "Chatting as usual."
        assert reply.payload["tools_used"] == []
        # No screen round, no dialog — but the AI was told to point the owner
        # at the "Allow input control" toggle instead of improvising.
        assert stub.seen["allow_actions"] is False
        assert "disabled" in stub.seen["instruction"]
        assert ui.confirmations == []  # no dialog was ever raised


class ScreenStubAI:
    provider = "stub"
    model = "stub-screen"

    def __init__(self) -> None:
        self.seen: dict[str, Any] = {}

    def ask(self, request, state, tools=None, *, command_runner=None, allow_actions=False):
        self.seen = {
            "screen_text": request.screen_text,
            "instruction": request.action_instruction,
            "jpeg": request.screen_image_jpeg,
            "include_screenshot": request.include_screenshot,
            "allow_actions": allow_actions,
        }
        state.turns += 1
        return AIResult(text="Describing as usual.", provider="stub", model="stub-screen")


def test_what_do_you_see_reads_the_screen(live_server) -> None:
    server, port, _identity, pairing, _overlay, ui = live_server
    stub = ScreenStubAI()
    server.ai_getter = lambda: stub
    with client(port) as ws:
        _pair_window(ws, pairing)
        reply = send_request(
            ws,
            "ask",
            {"text": "what can you see right now on the screen?", "include_screen": False},
        )
        assert reply.ok is True
        assert reply.payload["reply"] == "Describing as usual."
        assert reply.payload["tools_used"] == []
        assert reply.payload["screen_context_used"] is True
        # The phrase asked for a look, so the OCR round attached the screen —
        # read-only: no actions, no confirmation dialogs.
        assert "Settings" in stub.seen["screen_text"]
        assert "what you can see" in stub.seen["instruction"].lower()
        assert stub.seen["allow_actions"] is False
        assert ui.confirmations == []


def test_see_question_without_screen_awareness_gets_the_on_switch_hint(live_server) -> None:
    server, port, _identity, pairing, _overlay, _ui = live_server
    server.tools.control.set_screen_awareness(False)
    stub = ScreenStubAI()
    server.ai_getter = lambda: stub
    with client(port) as ws:
        _pair_window(ws, pairing)
        reply = send_request(
            ws,
            "ask",
            {"text": "what can you see right now on the screen?", "include_screen": False},
        )
        assert reply.ok is True
        assert reply.payload["reply"] == "Describing as usual."
        assert stub.seen["screen_text"] == ""  # no OCR was even attempted
        assert "cannot read" in stub.seen["instruction"].lower()
        assert "look and point" in stub.seen["instruction"].lower()


def test_see_question_with_screenshot_opt_in_attaches_the_jpeg(live_server) -> None:
    import io

    from PIL import Image as PILImage
    from berrylink.screen import OcrLine, OcrWord, ScreenSnapshot, Screenshot

    server, port, _identity, pairing, _overlay, _ui = live_server
    buf = io.BytesIO()
    PILImage.new("RGB", (6, 4), "white").save(buf, format="PNG")
    server.tools.screen.snapshot = ScreenSnapshot(
        id="snap-real",
        screenshot=Screenshot(
            png=buf.getvalue(),
            width=6,
            height=4,
            pointer_x=1,
            pointer_y=1,
            active_window="Notes",
            active_class="gedit",
        ),
        lines=[
            OcrLine(
                "L1",
                "Settings",
                50,
                180,
                200,
                60,
                [OcrWord("W1", "Settings", 100, 200, 80, 20, 95.0)],
            )
        ],
    )
    server.config.allow_screenshots_to_gemini = True  # the owner opted in
    stub = ScreenStubAI()
    server.ai_getter = lambda: stub
    with client(port) as ws:
        _pair_window(ws, pairing)
        reply = send_request(
            ws,
            "ask",
            {
                "text": "what can you see right now on the screen?",
                "include_screen": False,
                "include_screenshot": True,
            },
        )
        assert reply.ok is True
        assert stub.seen["include_screenshot"] is True
        assert stub.seen["jpeg"] is not None and stub.seen["jpeg"][:2] == b"\xff\xd8"
        assert "Settings" in stub.seen["screen_text"]


def test_action_intent_covers_double_click_and_file_names() -> None:
    from berrylink.ai_prompt import ACTION_INSTRUCTION
    from berrylink.server import ACTION_INTENT, SCREEN_QUERY_INTENT

    assert ACTION_INTENT.search("double click the Settings button")
    assert ACTION_INTENT.search("open the key.txt file")
    assert ACTION_INTENT.search("delete report.pdf")
    # App launches and plain chat keep their untouched fast path.
    assert not ACTION_INTENT.search("open brave")
    assert not ACTION_INTENT.search("what is a text file")
    assert not SCREEN_QUERY_INTENT.search("ellipsis")
    # The model is actually taught the double-click shape.
    assert "count" in ACTION_INSTRUCTION and "double" in ACTION_INSTRUCTION


def test_open_file_ask_double_clicks_through_the_allow_dialog(live_server) -> None:
    class DoubleClickStubAI:
        provider = "stub"
        model = "stub-doubleclick"

        def ask(self, request, state, tools=None, *, command_runner=None, allow_actions=False):
            assert allow_actions is True
            assert "count" in request.action_instruction
            assert "key.txt" in request.text
            state.turns += 1
            return AIResult(
                text="Doing it now.",
                provider="stub",
                model="stub-doubleclick",
                mood="happy",
                tools_used=["click"],
                action={"name": "click", "args": {"target_id": "L1", "count": 2}},
            )

    server, port, _identity, pairing, _overlay, ui = live_server
    server.ai_getter = lambda: DoubleClickStubAI()
    server.tools.control.set_enabled(True)
    with client(port) as ws:
        _pair_window(ws, pairing)
        reply = send_request(
            ws,
            "ask",
            {"text": "open the key.txt file", "include_screen": False},
        )
        assert reply.ok is True
        # The tool resolved the icon, popped the Allow dialog, and stopped at
        # the denial — no execution without the owner.
        assert reply.payload["tools_used"] == ["click"]
        assert "won't touch the screen" in reply.payload["reply"]
        assert ui.confirmations and "Settings" in ui.confirmations[-1][1]
