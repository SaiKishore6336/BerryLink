"""Authenticated TLS WebSocket server for the BerryLink phone companion."""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import re
import ssl
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from . import __version__
from .ai_prompt import (
    ACTION_DISABLED_NOTICE,
    ACTION_INSTRUCTION,
    SCREEN_DESCRIBE_INSTRUCTION,
    SCREEN_OFF_NOTICE,
)
from .config import Config, GEMINI_MODEL, GEMINI_MODEL_VERIFIED
from .desktop_commands import CommandError, run_command
from .desktop_tools import DesktopTools, ToolError
from .gemini_gateway import AIError, AskInput, ConversationState
from .security import redact
from .meeting import MeetingError, MeetingManager

# Input-action rounds: a phrase like "click the Settings button" while the
# owner enabled input control triggers one extra model round that picks a
# screen target, then every executed action passes the Allow dialog.
ACTION_INTENT = re.compile(
    r"\b(click|tap|press|type|write|scroll|drag)\b"
    # A known filename in the sentence ("open the key.txt file") also asks for
    # a screen action — the double-click route opens it, Allow-gated, without
    # inventing any new execution path. App names without extensions
    # ("open brave") keep the untouched launch flow.
    r"|[\w.-]{2,60}\.(?:txt|pdf|jpe?g|png|gif|webp|docx?|xlsx?|pptx?|csv|md|json|mp3|mp4|zip|html?)\b",
    re.IGNORECASE,
)
SERVER_ACTION_TOOLS = frozenset({"click", "type_text", "press_keys", "scroll", "drag"})

# Screen-see questions ("what can you see right now on the screen?"): they get
# the same local OCR round, no execution, no confirmation. False positives are
# harmless — the model merely receives the screen text it was asked about.
SCREEN_QUERY_INTENT = re.compile(
    r"\bwhat\b[^.?!]{0,40}?\b(?:see|seeing|notice|look(?:ing)?\s+at|looking)\b"
    r"|\b(?:describe|read|explain|summar(?:ise|ize)?)\b[^.?!]{0,40}?\b(?:screen|display|monitor|desktop)\b"
    r"|\bwhat\b[^.?!]{0,20}?\bon\b[^.?!]{0,15}?\b(?:my |the )?(?:screen|display|monitor)\b"
    r"|\blook\s+(?:at|to|into)\b[^.?!]{0,20}?\b(?:my |the )?(?:screen|display|monitor|desktop)\b",
    re.IGNORECASE,
)
from .pairing import PairingError, PairingManager, TlsIdentity
from .protocol import (
    Envelope,
    ProtocolError,
    parse,
    safe_message,
    validate_ask,
    validate_method_allowed,
)


class ServerUi(Protocol):
    def confirm(self, title: str, description: str, timeout: float = 90.0) -> bool: ...
    def caption(self, text: str, mood: str = "happy") -> None: ...
    def notify_runtime(self) -> None: ...
    def peers_changed(self, peers: list[dict[str, Any]]) -> None: ...


class ServerStartError(RuntimeError):
    pass


@dataclass
class ClientConnection:
    websocket: ServerConnection
    remote_ip: str
    device_id: str | None = None
    device_name: str | None = None
    authenticated: bool = False
    conversation: ConversationState = field(default_factory=ConversationState)
    message_times: collections.deque[float] = field(default_factory=collections.deque)
    bad_messages: int = 0
    auth_failures: int = 0
    connected_at: float = field(default_factory=time.time)

    def public(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "name": self.device_name,
            "connected": self.authenticated,
            "connected_at": self.connected_at,
            "remote_ip": self.remote_ip,
        }


class BerryLinkServer:
    def __init__(
        self,
        config: Config,
        pairing: PairingManager,
        identity: TlsIdentity,
        ai_getter: Callable[[], Any],
        tools: DesktopTools,
        meeting: MeetingManager,
        ui: ServerUi,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.pairing = pairing
        self.identity = identity
        self.ai_getter = ai_getter
        self.tools = tools
        self.meeting = meeting
        self.ui = ui
        self.log = logger or logging.getLogger("berrylink.server")
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = threading.Event()
        self._start_error: Exception | None = None
        self._server = None
        self._connections: dict[int, ClientConnection] = {}
        self._connections_lock = threading.RLock()
        self._ask_lock: asyncio.Lock | None = None
        self._background_tasks: set[asyncio.Task] = set()
        self._cursor_lock = threading.Lock()
        self._cursor_position: tuple[float, float] | None = None
        self._cursor_dirty = False
        self._cursor_task: asyncio.Task | None = None
        self.port: int | None = None
        self._stopping = threading.Event()

    # ------------------------------------------------------------- lifecycle

    def start(self, port: int | None = None, bind_host: str | None = None) -> int:
        if self._thread and self._thread.is_alive():
            raise ServerStartError("The server is already running.")
        self._stopping.clear()
        self._started.clear()
        self._start_error = None
        with self._connections_lock:
            self._connections.clear()
        target_port = self.config.port if port is None else int(port)
        host = bind_host or self.config.bind_host
        self._thread = threading.Thread(
            target=self._thread_main,
            args=(host, target_port),
            name="berrylink-server",
            daemon=True,
        )
        self._thread.start()
        if not self._started.wait(timeout=15):
            raise ServerStartError("The desktop server did not start in time.")
        if self._start_error:
            raise ServerStartError(str(self._start_error))
        if not self.port:
            raise ServerStartError("The desktop server did not bind a port.")
        return self.port

    def _ssl_context(self) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=str(self.identity.cert_file), keyfile=str(self.identity.key_file))
        # No client certificate: authentication is the device token + exact
        # certificate pin on the phone, both over this encrypted channel.
        context.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM")
        return context

    def _thread_main(self, host: str, port: int) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._start_async(host, port))
        except Exception as exc:
            self._start_error = exc
            self._started.set()
            self.log.error("Server failed to start: %s", type(exc).__name__)
            try:
                loop.close()
            except Exception:
                pass
            return
        self._started.set()
        try:
            loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            try:
                loop.close()
            except Exception:
                pass

    async def _start_async(self, host: str, port: int) -> None:
        context = self._ssl_context()
        self._ask_lock = asyncio.Lock()
        self._server = await serve(
            self._handle_connection,
            host,
            port,
            ssl=context,
            max_size=18 * 1024 * 1024,
            max_queue=8,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            compression=None,
            server_header="BerryLink",
            logger=self.log,
        )
        sockets = getattr(self._server, "sockets", None) or []
        if not sockets:
            raise ServerStartError("No listening socket was created.")
        self.port = sockets[0].getsockname()[1]
        # Cursor samples are pushed from the Qt thread; this loop fans the
        # latest normalized position out to authenticated phones at 30 Hz.
        # It is intentionally independent of request handling so eye
        # tracking never queues behind an ask, screenshot, or OCR job.
        self._cursor_task = asyncio.create_task(self._cursor_loop())
        self.log.info("TLS WebSocket server listening on %s:%s", host, self.port)

    def stop(self, timeout: float = 8.0) -> None:
        if not self._thread or not self._thread.is_alive():
            return
        self._stopping.set()
        loop = self._loop
        if loop and loop.is_running():
            try:
                loop.call_soon_threadsafe(lambda: asyncio.create_task(self._shutdown_async()))
            except RuntimeError:
                pass
        self._thread.join(timeout=timeout)
        self.log.info("Desktop server stopped.")

    async def _shutdown_async(self) -> None:
        cursor_task = self._cursor_task
        self._cursor_task = None
        if cursor_task is not None:
            cursor_task.cancel()
            await asyncio.gather(cursor_task, return_exceptions=True)
        with self._connections_lock:
            connections = list(self._connections.values())
        for conn in connections:
            try:
                await conn.websocket.close(code=1001, reason="Desktop shutting down")
            except Exception:
                pass
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
        loop = asyncio.get_running_loop()
        loop.call_soon(lambda: loop.stop())

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stopping.is_set())

    def peers(self) -> list[dict[str, Any]]:
        with self._connections_lock:
            return [c.public() for c in self._connections.values() if c.authenticated]

    def disconnect_device(self, device_id: str) -> None:
        loop = self._loop

        async def _close() -> None:
            with self._connections_lock:
                targets = [
                    c
                    for c in self._connections.values()
                    if c.device_id == device_id
                ]
            for conn in targets:
                try:
                    await conn.websocket.close(code=1008, reason="Pairing revoked")
                except Exception:
                    pass

        if loop and loop.is_running():
            loop.call_soon_threadsafe(lambda: asyncio.create_task(_close()))

    def set_cursor_position(self, x: float, y: float) -> None:
        """Publish the latest normalized desktop cursor position.

        Called from the Qt GUI thread.  Only authenticated peers can receive
        it, and only the position (never a screenshot or any other data) is
        sent.  Repeated identical samples are dropped so a still pointer does
        not produce continuous Wi-Fi traffic.
        """
        try:
            nx = max(-1.0, min(1.0, float(x)))
            ny = max(-1.0, min(1.0, float(y)))
        except (TypeError, ValueError):
            return
        if not (nx == nx and ny == ny):  # reject NaN
            return
        position = (round(nx, 4), round(ny, 4))
        with self._cursor_lock:
            if position == self._cursor_position:
                return
            self._cursor_position = position
            self._cursor_dirty = True

    def _request_cursor_sync(self) -> None:
        with self._cursor_lock:
            self._cursor_dirty = True

    async def _cursor_loop(self) -> None:
        interval = 1.0 / 30.0
        try:
            while True:
                await asyncio.sleep(interval)
                with self._cursor_lock:
                    dirty = self._cursor_dirty
                    position = self._cursor_position
                    if dirty and position is not None:
                        self._cursor_dirty = False
                if not dirty or position is None:
                    continue
                with self._connections_lock:
                    targets = [
                        conn
                        for conn in self._connections.values()
                        if conn.authenticated
                    ]
                if not targets:
                    continue
                envelope = Envelope.event(
                    "cursor",
                    {"x": position[0], "y": position[1]},
                )
                text = envelope.to_json()
                await asyncio.gather(
                    *(conn.websocket.send(text) for conn in targets),
                    return_exceptions=True,
                )
        except asyncio.CancelledError:
            raise

    def broadcast_event(self, method: str, payload: dict[str, Any]) -> None:
        loop = self._loop
        if not loop or not loop.is_running():
            return
        envelope = Envelope.event(method, payload)
        text = envelope.to_json()

        async def _broadcast() -> None:
            with self._connections_lock:
                targets = [c for c in self._connections.values() if c.authenticated]
            for conn in targets:
                try:
                    await conn.websocket.send(text)
                except Exception:
                    pass

        try:
            loop.call_soon_threadsafe(lambda: self._spawn(_broadcast()))
        except RuntimeError:
            pass

    def _spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    # --------------------------------------------------------------- handler

    async def _handle_connection(self, websocket: ServerConnection) -> None:
        remote = getattr(websocket, "remote_address", None)
        remote_ip = str(remote[0]) if remote and len(remote) >= 1 else "unknown"
        conn = ClientConnection(websocket=websocket, remote_ip=remote_ip)
        with self._connections_lock:
            self._connections[id(websocket)] = conn
        self.log.info("Connection opened from %s", remote_ip)
        try:
            async for raw in websocket:
                if not self._rate_ok(conn):
                    await self._send_failure(conn, "rate_limited", "Too many messages. Slow down.")
                    break
                await self._handle_raw(conn, raw)
                if conn.bad_messages >= 5:
                    await websocket.close(code=1008, reason="Too many protocol errors")
                    break
        except ConnectionClosed:
            pass
        except Exception as exc:
            self.log.warning("Connection handler error: %s", type(exc).__name__)
            try:
                await websocket.close(code=1011, reason="Server error")
            except Exception:
                pass
        finally:
            with self._connections_lock:
                self._connections.pop(id(websocket), None)
            if conn.authenticated:
                self.log.info("Authenticated peer disconnected: %s", conn.device_name or "unknown")
            self._notify_peers()
            self.ui.notify_runtime()

    def _rate_ok(self, conn: ClientConnection) -> bool:
        now = time.monotonic()
        window = conn.message_times
        while window and now - window[0] >= 60:
            window.popleft()
        if len(window) >= 120:
            return False
        window.append(now)
        return True

    async def _handle_raw(self, conn: ClientConnection, raw: str | bytes) -> None:
        try:
            envelope = parse(raw)
        except ProtocolError as exc:
            conn.bad_messages += 1
            await self._send_failure(conn, exc.code, exc.message, request_id=None)
            return
        if envelope.kind != "request":
            conn.bad_messages += 1
            await self._send_failure(conn, "bad_envelope", "Only request envelopes are accepted.", envelope.id)
            return
        conn.bad_messages = 0
        await self._dispatch(conn, envelope)

    async def _send(self, conn: ClientConnection, envelope: Envelope) -> None:
        try:
            await conn.websocket.send(envelope.to_json())
        except Exception:
            pass

    async def _send_failure(
        self,
        conn: ClientConnection,
        code: str,
        message: str,
        request_id: str | None = None,
    ) -> None:
        if request_id:
            response = Envelope.failure(request_id, code, message)
        else:
            response = Envelope(
                kind="response",
                id=uuid.uuid4().hex,
                reply_to="invalid",
                ok=False,
                error={"code": code, "message": message},
            )
        await self._send(conn, response)

    async def _dispatch(self, conn: ClientConnection, env: Envelope) -> None:
        method = env.method or ""
        try:
            validate_method_allowed(method, conn.authenticated)
        except ProtocolError as exc:
            if not conn.authenticated and method not in ("auth", "pair.request"):
                conn.auth_failures += 1
            await self._send(conn, Envelope.failure(env, exc.code, exc.message))
            return
        try:
            if method == "pair.request":
                await self._pair(conn, env)
            elif method == "auth":
                await self._auth(conn, env)
            elif method == "ping":
                await self._send(
                    conn,
                    Envelope.response(env, {"pong": True, "time": int(time.time() * 1000)}),
                )
            elif method == "status.get":
                await self._send(conn, Envelope.response(env, self._status_payload(conn)))
            elif method == "ask":
                await self._ask(conn, env)
            elif method == "session.reset":
                await self._reset_session(conn, env)
            elif method == "notes.list":
                sessions = await asyncio.to_thread(self.meeting.list_sessions)
                await self._send(conn, Envelope.response(env, {"sessions": sessions}))
            elif method == "notes.get":
                await self._notes_get(conn, env)
            elif method == "notes.delete":
                await self._notes_delete(conn, env)
            elif method == "meeting.status":
                await self._send(conn, Envelope.response(env, self.meeting.status()))
            elif method == "meeting.start":
                await self._meeting_start(conn, env)
            elif method == "meeting.stop":
                await self._meeting_stop(conn, env)
            elif method == "look.screen":
                await self._look_screen(conn, env)
            elif method == "point.text":
                await self._point_text(conn, env)
            else:
                await self._send(conn, Envelope.failure(env, "unknown_method", "Unknown method."))
        except AIError as exc:
            await self._send(conn, Envelope.failure(env, exc.code, exc.message))
        except (ProtocolError, MeetingError) as exc:
            await self._send(conn, Envelope.failure(env, exc.code, exc.message))
        except ToolError as exc:
            await self._send(conn, Envelope.failure(env, exc.code, exc.message))
        except asyncio.TimeoutError:
            await self._send(conn, Envelope.failure(env, "timeout", "That request timed out safely."))
        except Exception as exc:
            self.log.warning("Method %s failed: %s", method, type(exc).__name__)
            await self._send(
                conn,
                Envelope.failure(env, "internal_error", "Something went wrong on the desktop."),
            )

    # ------------------------------------------------------------------- auth

    async def _pair(self, conn: ClientConnection, env: Envelope) -> None:
        if conn.authenticated:
            await self._send(conn, Envelope.failure(env, "already_authenticated", "This phone is already paired on this connection."))
            return
        code = env.payload.get("code")
        name = env.payload.get("device_name", "Android phone")
        protocol = env.payload.get("protocol", 1)
        conn.auth_failures += 1  # provisional: reset on success
        if protocol != 1:
            await self._send(conn, Envelope.failure(env, "unsupported_protocol", "Update the Android app to match this desktop."))
            return
        try:
            if code is None and env.payload.get("codeless"):
                device, token = await self._codeless_pair(env, name)
            else:
                device, token = self.pairing.pair(code, name)
        except PairingError as exc:
            await self._send(conn, Envelope.failure(env, exc.code, exc.message))
            if conn.auth_failures >= 6:
                await conn.websocket.close(code=1008, reason="Pairing failed repeatedly")
            return
        conn.authenticated = True
        conn.device_id = device["id"]
        conn.device_name = device["name"]
        conn.auth_failures = 0
        self.log.info("Paired new phone: %s", device["name"])
        await self._send(
            conn,
            Envelope.response(
                env,
                {
                    "device_id": device["id"],
                    "device_name": device["name"],
                    "token": token,
                    "desktop_name": self.config.display_name,
                    "protocol": 1,
                    "certificate_fingerprint": self.identity.pretty_fingerprint,
                },
            ),
        )
        # Send the current cursor immediately on pairing, even if it has not
        # moved since the app started.
        self._request_cursor_sync()
        self._notify_peers()
        self.ui.notify_runtime()

    async def _codeless_pair(self, env: Envelope, name: str) -> tuple[dict[str, Any], str]:
        """One-tap pairing: the desktop owner confirms on the screen.

        Runs `bridge.confirm` in a worker thread so the asyncio loop keeps
        serving other connections while the dialog is open.
        """
        if not self.config.allow_codeless_pairing:
            raise PairingError(
                "pairing_required",
                "This desktop only pairs with the 6-digit code. Open the desktop app's pairing "
                "window or turn on codeless pairing there.",
            )
        pretty_name = " ".join(str(name or "Android phone").split())[:64] or "Android phone"
        approved = await asyncio.to_thread(
            self.ui.confirm,
            "Allow a new phone to connect?",
            f"“{pretty_name}” asked to pair with this desktop with no code.\n\n"
            "Allow once only if this is your phone, within arm's reach.",
            90.0,
        )
        if not approved:
            raise PairingError("pairing_denied", "The desktop declined the connection. Try again and press Allow on the desktop.")
        self.log.info("Codeless pairing approved for %s", pretty_name)
        return self.pairing.mint_device(name)

    async def _auth(self, conn: ClientConnection, env: Envelope) -> None:
        if conn.authenticated:
            await self._send(conn, Envelope.response(env, {"ok": True, "already": True}))
            return
        device_id = env.payload.get("device_id")
        token = env.payload.get("token")
        if not isinstance(device_id, str) or not isinstance(token, str) or len(token) > 200:
            conn.auth_failures += 1
            await self._send(conn, Envelope.failure(env, "auth_failed", "This phone is not paired with the desktop."))
            return
        device = self.pairing.authenticate(device_id, token)
        if not device:
            conn.auth_failures += 1
            self.log.info(
                "Auth rejected for %s (failures: %s)",
                redact(str(device_id)[:24]) or "unknown-device",
                conn.auth_failures,
            )
            await self._send(conn, Envelope.failure(env, "auth_failed", "This phone is not paired with the desktop."))
            if conn.auth_failures >= 5:
                await conn.websocket.close(code=1008, reason="Authentication failed repeatedly")
            return
        conn.authenticated = True
        conn.device_id = device["id"]
        conn.device_name = device["name"]
        conn.auth_failures = 0
        self.log.info("Phone authenticated: %s (%s)", device["name"], device["id"])
        await self._send(
            conn,
            Envelope.response(
                env,
                {
                    "ok": True,
                    "device_id": device["id"],
                    "device_name": device["name"],
                    "desktop_name": self.config.display_name,
                    "protocol": 1,
                    "certificate_fingerprint": self.identity.pretty_fingerprint,
                },
            ),
        )
        self.log.info("Phone authenticated: %s", device["name"])
        self._request_cursor_sync()
        self._notify_peers()
        self.ui.notify_runtime()

    def _notify_peers(self) -> None:
        try:
            self.ui.peers_changed(self.peers())
        except Exception:
            pass

    # -------------------------------------------------------------------- ask

    async def _ask(self, conn: ClientConnection, env: Envelope) -> None:
        if self._ask_lock is None:
            await self._send(conn, Envelope.failure(env, "not_ready", "The desktop is still starting."))
            return
        if self._ask_lock.locked():
            await self._send(conn, Envelope.failure(env, "busy", "I'm already working on something. Give me a moment."))
            return
        request = validate_ask(
            env.payload,
            self.config.max_audio_bytes,
            self.config.max_text_chars,
        )
        async with self._ask_lock:
            screen_text = ""
            screenshot_used = False
            screen_image = None
            screen_note = ""
            # Asks are word-only by default (fast, private). Two read-only
            # exceptions run one local OCR round first: desktop-action phrases
            # (input control on → target list + Allow-gated execution) and
            # screen-see questions (model gets the screen text to describe).
            emergency = self.tools.control.emergency
            ai = self.ai_getter()
            # "wish": the phrase asks for that capability at all; "ready": the
            # matching toggle is on this run. Screen questions ("what can you
            # see on the screen?") get the same one local OCR round the action
            # flow uses — plus the JPEG only when the phone flagged it AND the
            # owner allows screenshots to the provider. Everything else stays a
            # plain word-only chat ask.
            action_wish = (
                bool(request["text"]) and ACTION_INTENT.search(request["text"]) is not None
            )
            action_ready = action_wish and bool(self.tools.control.enabled) and not emergency
            screen_wish = bool(request["text"]) and (
                SCREEN_QUERY_INTENT.search(request["text"]) is not None
            )
            screen_ready = screen_wish and self.tools.control.screen_awareness and not emergency
            look_failed = False
            if action_ready or screen_ready:
                self.ui.caption("Reading your screen…", "thinking")
                capture = bool(request["include_screenshot"]) and bool(
                    self.config.allow_screenshots_to_gemini
                )
                try:
                    look = await asyncio.to_thread(
                        self.tools.call,
                        "look_at_screen",
                        {},
                        allow_screenshot=capture,
                        allow_tools=True,
                    )
                    screen_text = look.text
                    screen_image = look.image_jpeg
                    screenshot_used = bool(look.image_jpeg)
                except ToolError:
                    look_failed = True
                    action_ready = False
                except Exception:
                    look_failed = True
                    action_ready = False
            if action_ready:
                instruction = ACTION_INSTRUCTION
            elif screen_ready and screen_text:
                instruction = SCREEN_DESCRIBE_INSTRUCTION
            elif look_failed:
                instruction = SCREEN_OFF_NOTICE
            elif action_wish:
                instruction = ACTION_DISABLED_NOTICE
            elif screen_wish:
                instruction = SCREEN_OFF_NOTICE
            else:
                instruction = ""
            ask = AskInput(
                text=request["text"],
                audio=request["audio"] or None,
                screen_text=screen_text,
                screen_image_jpeg=screen_image,
                include_screenshot=screenshot_used,
                allow_tools=False,
                action_instruction=instruction,
            )
            screen_log = "off"
            if screen_ready:
                screen_log = "looked" if screen_text else "failed"
            elif screen_wish:
                screen_log = "wish"
            self.log.info(
                "Ask from %s: audio=%s text=%s action=%s screen=%s",
                conn.device_name or "phone",
                bool(ask.audio),
                bool(ask.text),
                "ready" if action_ready else ("wish" if action_wish else "off"),
                screen_log,
            )
            self.ui.caption("Thinking…", "thinking")
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        ai.ask,
                        ask,
                        conn.conversation,
                        self.tools,
                        command_runner=self._command_runner,
                        allow_actions=action_ready,
                    ),
                    timeout=self.config.http_timeout_seconds + 60,
                )
            except asyncio.TimeoutError:
                await self._send(
                    conn,
                    Envelope.failure(env, "timeout", "That took too long. Nothing else was sent to Gemini."),
                )
                return
            if action_ready and result.action:
                proposal = result.action
                result.tools_used = [proposal["name"]]
                try:
                    if proposal["name"] not in SERVER_ACTION_TOOLS:
                        raise ToolError("unknown_tool", "That desktop action isn't available.")
                    outcome = await asyncio.to_thread(
                        self.tools.call,
                        proposal["name"],
                        dict(proposal.get("args") or {}),
                        allow_screenshot=False,
                        allow_tools=True,
                    )
                    result.effects = list(outcome.effects)
                except ToolError as exc:
                    result.mood = "oops"
                    result.text = {
                        "denied": "Okay, I won't touch the screen then.",
                        "control_disabled": "Turn on input control in the desktop app and ask me again.",
                        "screen_disabled": "Screen awareness is off, so I can't find that on the screen.",
                        "emergency_stop": "Emergency stop is active. Resume control in the desktop app first.",
                        "confirmation_unavailable": "I need your confirmation window for that, and none is open.",
                        "tools_disabled": "Input control is off on the desktop.",
                        "bad_arguments": "I couldn't build that action from the screen. Tell me the target once more?",
                        "bad_target": "That screen target is gone. Ask again afterwards.",
                        "stale_target": "That screen target is gone. Ask me again afterwards.",
                    }.get(exc.code, "That desktop action failed safely.")
                except Exception:
                    self.log.exception("Action %s crashed", proposal["name"])
                    result.mood = "oops"
                    result.text = "That desktop action failed safely."
            self.ui.caption(result.text, result.mood)
            self.ui.notify_runtime()
            payload = {
                "reply": result.text,
                "provider": result.provider,
                "model": result.model,
                "mood": result.mood,
                "tools_used": result.tools_used,
                "effects": result.effects,
                "screenshot_used": screenshot_used,
                "screen_context_used": bool(screen_text),
                "screen_note": screen_note,
                "free_tier": result.provider == "gemini",
                "model_verified": GEMINI_MODEL_VERIFIED if result.provider == "gemini" else None,
            }
            await self._send(conn, Envelope.response(env, payload))
            if "sleep" in result.effects:
                await self._send(conn, Envelope.event("sleep", {}))

    # ------------------------------------------------------------- other calls

    def _command_runner(self, command: str) -> tuple[str, bool]:
        """Execute an understood launch command; emergency stop always wins."""
        try:
            if self.tools.control.emergency:
                return ("Emergency stop is active, so I'm not launching anything.", False)
            return run_command(
                command,
                activate_berrylink=self.ui.show_overlay,
                logger=self.log,
            )
        except CommandError as exc:
            return (str(exc), False)
        except Exception:
            # Never let a wiring slip turn into a silent generic reply.
            self.log.exception("Command %s crashed", command)
            return ("That launch didn't go through on this computer.", False)

    async def _reset_session(self, conn: ClientConnection, env: Envelope) -> None:
        previous = conn.conversation.last_interaction_id
        conn.conversation.reset()
        ai = self.ai_getter()
        deleted = False
        if previous and hasattr(ai, "delete_interaction"):
            deleted = await asyncio.to_thread(ai.delete_interaction, previous)
        self.ui.caption("Fresh start.", "happy")
        await self._send(
            conn,
            Envelope.response(env, {"ok": True, "stored_interaction_deleted": deleted}),
        )

    async def _notes_get(self, conn: ClientConnection, env: Envelope) -> None:
        session_id = env.payload.get("id")
        if not isinstance(session_id, str):
            raise ProtocolError("bad_request", "A meeting id is required.")
        detail = await asyncio.to_thread(self.meeting.read_session, session_id)
        detail.pop("audio_files", None)
        await self._send(conn, Envelope.response(env, detail))

    async def _notes_delete(self, conn: ClientConnection, env: Envelope) -> None:
        session_id = env.payload.get("id")
        if not isinstance(session_id, str):
            raise ProtocolError("bad_request", "A meeting id is required.")
        approved = await asyncio.to_thread(
            self.ui.confirm,
            "Delete meeting notes?",
            f"{conn.device_name or 'The phone'} asked to delete meeting {session_id}. "
            "This removes notes.md, session.json, transcript.txt and retained audio permanently.",
            90.0,
        )
        if not approved:
            raise MeetingError("denied", "The desktop user did not approve deleting those notes.")
        await asyncio.to_thread(self.meeting.delete_session, session_id)
        self.broadcast_event("meeting.changed", {"action": "deleted", "id": session_id})
        await self._send(conn, Envelope.response(env, {"ok": True, "id": session_id}))

    async def _meeting_start(self, conn: ClientConnection, env: Envelope) -> None:
        if self.meeting.active:
            raise MeetingError("already_recording", "A meeting recording is already active.")
        approved = await asyncio.to_thread(
            self.ui.confirm,
            "Start meeting recording?",
            f"{conn.device_name or 'The phone'} asked BerryLink to record the desktop microphone.\n\n"
            "Only continue if everyone who may be recorded has consented. "
            f"Transcription with Gemini free tier is currently {'on' if self.config.meeting_transcribe else 'off'}; "
            f"audio retention is {'on' if self.config.meeting_retain_audio else 'off'}.\n\n"
            "The recording indicator remains visible on the desktop.",
            120.0,
        )
        if not approved:
            raise MeetingError("denied", "The desktop user did not start recording.")
        title = env.payload.get("title", "")
        if not isinstance(title, str):
            title = ""
        status = await asyncio.to_thread(
            self.meeting.start,
            consent=True,
            transcribe=self.config.meeting_transcribe,
            retain_audio=self.config.meeting_retain_audio,
            title=title,
        )
        self.broadcast_event("meeting.changed", {"action": "started", "status": status})
        await self._send(conn, Envelope.response(env, status))

    async def _meeting_stop(self, conn: ClientConnection, env: Envelope) -> None:
        status = await asyncio.to_thread(self.meeting.stop)
        self.broadcast_event("meeting.changed", {"action": "stopped", "status": status})
        await self._send(conn, Envelope.response(env, status))

    async def _look_screen(self, conn: ClientConnection, env: Envelope) -> None:
        if self.tools.control.emergency:
            raise ToolError("emergency_stop", "Emergency stop is active.")
        if not self.tools.control.screen_awareness:
            raise ToolError("screen_disabled", "Screen awareness is turned off.")
        snapshot = await asyncio.to_thread(self.tools.screen.get, True)
        await self._send(
            conn,
            Envelope.response(
                env,
                {
                    "snapshot_id": snapshot.id,
                    "width": snapshot.width,
                    "height": snapshot.height,
                    "error": snapshot.error,
                    "context": snapshot.context_text()[:12000],
                    "active_window": snapshot.screenshot.active_window,
                },
            ),
        )

    async def _point_text(self, conn: ClientConnection, env: Envelope) -> None:
        query = env.payload.get("text")
        if not isinstance(query, str) or not query.strip() or len(query) > 200:
            raise ProtocolError("bad_request", "Point text must be 1-200 characters.")
        result = await asyncio.to_thread(self.tools.point_at_text, query.strip())
        await self._send(conn, Envelope.response(env, {"ok": True, "message": result.text}))

    # ------------------------------------------------------------------ status

    def _status_payload(self, conn: ClientConnection | None = None) -> dict[str, Any]:
        ai = self.ai_getter()
        provider = getattr(ai, "provider", "gemini")
        control = self.tools.control.snapshot()
        ai_configured = provider == "gemini"
        return {
            "protocol": 1,
            "desktop_version": __version__,
            "desktop_name": self.config.display_name,
            "phone": {
                "device_id": conn.device_id if conn else None,
                "name": conn.device_name if conn else None,
            },
            "ai": {
                "configured": ai_configured,
                "provider": provider,
                "model": self.config.gemini_model if ai_configured else "local-mock",
                "free_tier": ai_configured,
                "model_verified": GEMINI_MODEL_VERIFIED,
            },
            "control": {
                **control,
                "confirm_actions": self.config.confirm_actions,
            },
            "screen": {
                "capture": self.tools.screen.available().get("capture", False),
                "ocr": self.tools.screen.available().get("ocr", False),
                "screenshots_to_gemini": self.config.allow_screenshots_to_gemini,
            },
            "capabilities": sorted(
                {
                    "ask_audio",
                    "ask_text",
                    "screen_ocr" if self.tools.screen.available().get("ocr") else "screen_capture",
                    "input_control" if control["control_enabled"] else "look_and_point",
                    "mock_ai" if provider == "mock" else "gemini_free_tier",
                }
            ),
            "certificate_fingerprint": self.identity.pretty_fingerprint,
        }

    # ------------------------------------------------------------- ui helpers

    def notify_meeting_changed(self) -> None:
        status = self.meeting.status()
        self.broadcast_event("meeting.changed", {"status": status})
        try:
            self.ui.notify_runtime()
        except Exception:
            pass
