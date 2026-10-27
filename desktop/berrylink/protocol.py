"""Versioned JSON envelope used between the Android companion and this gateway.

All messages are small JSON objects except opt-in ask requests, which may carry
one bounded WAV recording.  Nothing is trusted before validation.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from . import PROTOCOL_VERSION

MAX_ENVELOPE_BYTES = 17 * 1024 * 1024  # 12 MiB audio -> 16 MiB base64 + envelope overhead
MAX_AUDIO_BYTES = 12 * 1024 * 1024
MAX_TEXT_CHARS = 4000
ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
METHOD_RE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")

PREAUTH_METHODS = {"auth", "pair.request"}
AUTH_METHODS = {
    "ask",
    "status.get",
    "session.reset",
    "look.screen",
    "point.text",
    "ping",
}
# Meeting recording/notes remain in the codebase but are intentionally not
# reachable from the phone in this first MVP.  They can be re-enabled as a
# reviewed protocol addition later.


class ProtocolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("bad_json", "Duplicate JSON keys are not allowed.")
        result[key] = value
    return result


def loads_strict(data: str | bytes) -> Any:
    if isinstance(data, bytes):
        if len(data) > MAX_ENVELOPE_BYTES:
            raise ProtocolError("too_large", "Message is too large.")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("bad_json", "Message is not UTF-8.") from exc
    else:
        text = data
        if len(text.encode("utf-8")) > MAX_ENVELOPE_BYTES:
            raise ProtocolError("too_large", "Message is too large.")
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except ProtocolError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ProtocolError("bad_json", "Message is not valid JSON.") from exc


@dataclass
class Envelope:
    kind: str
    id: str
    method: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    reply_to: str | None = None
    ok: bool | None = None
    error: dict[str, Any] | None = None

    @classmethod
    def request(cls, method: str, payload: Mapping[str, Any] | None = None) -> "Envelope":
        return cls(kind="request", id=uuid.uuid4().hex, method=method, payload=dict(payload or {}))

    @classmethod
    def response(cls, request: "Envelope", payload: Mapping[str, Any] | None = None) -> "Envelope":
        return cls(
            kind="response",
            id=uuid.uuid4().hex,
            reply_to=request.id,
            ok=True,
            payload=dict(payload or {}),
        )

    @classmethod
    def failure(cls, request: "Envelope" | str, code: str, message: str) -> "Envelope":
        request_id = request.id if isinstance(request, Envelope) else request
        return cls(
            kind="response",
            id=uuid.uuid4().hex,
            reply_to=request_id,
            ok=False,
            error={"code": code, "message": message},
        )

    @classmethod
    def event(cls, method: str, payload: Mapping[str, Any] | None = None) -> "Envelope":
        return cls(kind="event", id=uuid.uuid4().hex, method=method, payload=dict(payload or {}))

    def to_dict(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "protocol": PROTOCOL_VERSION,
            "id": self.id,
            "kind": self.kind,
        }
        if self.kind == "request":
            base["method"] = self.method
            base["payload"] = self.payload
            base["ts"] = int(time.time() * 1000)
        elif self.kind == "event":
            base["method"] = self.method
            base["payload"] = self.payload
            base["ts"] = int(time.time() * 1000)
        elif self.kind == "response":
            base["reply_to"] = self.reply_to
            base["ok"] = bool(self.ok)
            if self.ok:
                base["payload"] = self.payload
            else:
                base["error"] = self.error or {
                    "code": "error",
                    "message": "Unknown error.",
                }
        else:
            raise ProtocolError("bad_envelope", "Unknown envelope kind.")
        self.validate()
        return base

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), ensure_ascii=False)

    def validate(self) -> None:
        if self.kind not in ("request", "response", "event"):
            raise ProtocolError("bad_envelope", "Unknown envelope kind.")
        if not ID_RE.fullmatch(self.id):
            raise ProtocolError("bad_id", "Invalid message id.")
        if self.kind in ("request", "event"):
            if not self.method or not METHOD_RE.fullmatch(self.method):
                raise ProtocolError("bad_method", "Invalid method.")
            if not isinstance(self.payload, dict):
                raise ProtocolError("bad_payload", "Payload must be an object.")
        if self.kind == "response":
            if not self.reply_to or not ID_RE.fullmatch(self.reply_to):
                raise ProtocolError("bad_id", "Invalid reply_to.")
            if self.ok is None:
                raise ProtocolError("bad_envelope", "Response needs ok.")
            if self.ok and not isinstance(self.payload, dict):
                raise ProtocolError("bad_payload", "Payload must be an object.")
            if not self.ok:
                if not isinstance(self.error, dict):
                    raise ProtocolError("bad_error", "Error must be an object.")
                if not isinstance(self.error.get("code"), str) or not isinstance(
                    self.error.get("message"), str
                ):
                    raise ProtocolError("bad_error", "Error needs code and message.")

    @classmethod
    def from_dict(cls, raw: Any) -> "Envelope":
        if not isinstance(raw, dict):
            raise ProtocolError("bad_envelope", "Envelope must be an object.")
        if raw.get("protocol") != PROTOCOL_VERSION:
            raise ProtocolError("unsupported_protocol", "Unsupported protocol version.")
        kind = raw.get("kind")
        env = cls(
            kind=kind if isinstance(kind, str) else "",
            id=raw.get("id") if isinstance(raw.get("id"), str) else "",
            method=raw.get("method") if isinstance(raw.get("method"), str) else None,
            payload=raw.get("payload") if isinstance(raw.get("payload"), dict) else {},
            reply_to=raw.get("reply_to") if isinstance(raw.get("reply_to"), str) else None,
            ok=raw.get("ok") if isinstance(raw.get("ok"), bool) else None,
            error=raw.get("error") if isinstance(raw.get("error"), dict) else None,
        )
        env.validate()
        return env


def parse(data: str | bytes) -> Envelope:
    raw = loads_strict(data)
    return Envelope.from_dict(raw)


def validate_method_allowed(method: str, authenticated: bool) -> None:
    if not authenticated and method not in PREAUTH_METHODS:
        raise ProtocolError("unauthorized", "Authenticate before using this method.")
    if authenticated and method not in AUTH_METHODS:
        raise ProtocolError("unknown_method", "Unknown method.")


def decode_audio(data: str, max_bytes: int = MAX_AUDIO_BYTES) -> bytes:
    if not isinstance(data, str) or not data:
        raise ProtocolError("bad_audio", "No audio data was supplied.")
    # Base64 expands by 4/3. Reject before decoding something huge.
    if len(data) > ((max_bytes + 2) // 3) * 4 + 8:
        raise ProtocolError("too_large", "Audio recording is too large.")
    try:
        decoded = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProtocolError("bad_audio", "Audio data is not valid base64.") from exc
    if len(decoded) > max_bytes:
        raise ProtocolError("too_large", "Audio recording is too large.")
    if len(decoded) < 44:
        raise ProtocolError("bad_audio", "Audio recording is empty.")
    return decoded


def wav_duration_seconds(data: bytes) -> float | None:
    """Read a PCM WAV duration without trusting the header's size blindly."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    # Find fmt and data chunks. PCM only is enough for the Android recorder.
    pos = 12
    byte_rate = 0
    data_size = 0
    while pos + 8 <= len(data):
        chunk_id = data[pos : pos + 4]
        chunk_size = int.from_bytes(data[pos + 4 : pos + 8], "little")
        body = pos + 8
        if chunk_id == b"fmt ":
            if body + 16 > len(data):
                return None
            byte_rate = int.from_bytes(data[body + 8 : body + 12], "little")
        elif chunk_id == b"data":
            data_size = min(chunk_size, max(0, len(data) - body))
            break
        pos = body + chunk_size + (chunk_size & 1)
    if byte_rate <= 0 or data_size <= 0:
        return None
    return data_size / byte_rate


def validate_ask(payload: Mapping[str, Any], max_audio_bytes: int, max_text_chars: int) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ProtocolError("bad_payload", "Ask payload must be an object.")
    text = payload.get("text", "")
    if text is None:
        text = ""
    if not isinstance(text, str):
        raise ProtocolError("bad_text", "Text must be a string.")
    text = text.strip()
    if len(text) > max_text_chars:
        raise ProtocolError("text_too_long", f"Text is limited to {max_text_chars} characters.")
    audio_b64 = payload.get("audio")
    audio = b""
    if audio_b64 not in (None, ""):
        audio = decode_audio(audio_b64, max_audio_bytes)
        duration = wav_duration_seconds(audio)
        if duration is not None and duration > 61:
            raise ProtocolError("audio_too_long", "Voice asks are limited to 60 seconds.")
    mime = payload.get("audio_mime", "audio/wav")
    if audio and mime not in ("audio/wav", "audio/x-wav", "audio/wave"):
        raise ProtocolError("bad_audio", "Only WAV recordings are accepted.")
    include_screen = payload.get("include_screen", True)
    include_screenshot = payload.get("include_screenshot", False)
    if not isinstance(include_screen, bool) or not isinstance(include_screenshot, bool):
        raise ProtocolError("bad_payload", "Screen flags must be booleans.")
    if not text and not audio:
        raise ProtocolError("empty_ask", "Say something or type a question.")
    return {
        "text": text,
        "audio": audio,
        "include_screen": include_screen,
        "include_screenshot": include_screenshot,
    }


def safe_message(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, ProtocolError):
        return exc.code, exc.message
    return "internal_error", "Something went wrong on the desktop."
