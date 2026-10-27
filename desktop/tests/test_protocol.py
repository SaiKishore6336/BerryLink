from __future__ import annotations

import base64
import io
import json
import wave

import pytest

from berrylink.protocol import (
    Envelope,
    ProtocolError,
    decode_audio,
    loads_strict,
    parse,
    safe_message,
    validate_ask,
    validate_method_allowed,
    wav_duration_seconds,
)


def wav(seconds: float, rate: int = 16000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(seconds * rate))
    return out.getvalue()


def test_request_response_and_event_round_trip() -> None:
    request = Envelope.request("ask", {"text": "hello"})
    raw = parse(request.to_json())
    assert raw.kind == "request"
    assert raw.method == "ask"
    assert raw.payload == {"text": "hello"}

    response = Envelope.response(raw, {"reply": "hi"})
    parsed = parse(response.to_json())
    assert parsed.kind == "response"
    assert parsed.reply_to == request.id
    assert parsed.ok is True
    assert parsed.payload["reply"] == "hi"

    failure = Envelope.failure(request, "denied", "No.")
    parsed_failure = parse(failure.to_json())
    assert parsed_failure.ok is False
    assert parsed_failure.error == {"code": "denied", "message": "No."}

    event = Envelope.event("sleep", {})
    assert parse(event.to_json()).method == "sleep"


@pytest.mark.parametrize(
    "payload, code",
    [
        ({"protocol": 2, "id": "x", "kind": "event", "method": "ping"}, "unsupported_protocol"),
        ({"protocol": 1, "id": "x", "kind": "bogus", "method": "ping"}, "bad_envelope"),
        ({"protocol": 1, "id": "", "kind": "event", "method": "ping"}, "bad_id"),
        ({"protocol": 1, "id": "x", "kind": "event"}, "bad_method"),
        ({"protocol": 1, "id": "x", "kind": "request", "method": "Bad Method"}, "bad_method"),
        ({"protocol": 1, "id": "x", "kind": "response", "ok": True}, "bad_id"),
    ],
)
def test_invalid_envelopes_are_rejected(payload: dict, code: str) -> None:
    with pytest.raises(ProtocolError) as caught:
        parse(json.dumps(payload))
    assert caught.value.code == code


def test_duplicate_json_keys_and_non_utf8_are_rejected() -> None:
    with pytest.raises(ProtocolError) as caught:
        loads_strict('{"protocol":1,"protocol":1}')
    assert caught.value.code == "bad_json"
    with pytest.raises(ProtocolError):
        loads_strict(b"\xff\xfe")


def test_oversized_messages_are_rejected_before_json_parsing() -> None:
    with pytest.raises(ProtocolError) as caught:
        loads_strict("{" + " " * (18 * 1024 * 1024) + "}")
    assert caught.value.code == "too_large"


def test_method_allowlists_keep_meeting_and_notes_unreachable() -> None:
    validate_method_allowed("pair.request", False)
    validate_method_allowed("auth", False)
    for method in ("ask", "status.get", "look.screen", "point.text", "ping"):
        validate_method_allowed(method, True)
    with pytest.raises(ProtocolError, match="Authenticate"):
        validate_method_allowed("ask", False)
    for method in ("meeting.start", "meeting.stop", "notes.list", "notes.get", "notes.delete"):
        with pytest.raises(ProtocolError) as caught:
            validate_method_allowed(method, True)
        assert caught.value.code == "unknown_method"


def test_wav_duration_and_decoding(wav_bytes) -> None:
    data = wav_bytes(1.0)
    assert wav_duration_seconds(data) == pytest.approx(1.0)
    assert decode_audio(base64.b64encode(data).decode("ascii")) == data
    assert wav_duration_seconds(b"") is None
    assert wav_duration_seconds(b"RIFF" + b"\x00" * 40) is None
    with pytest.raises(ProtocolError) as caught:
        decode_audio("not base64!!")
    assert caught.value.code == "bad_audio"


def test_validate_ask_accepts_text_and_audio_and_rejects_bad_fields(wav_bytes) -> None:
    tiny = wav_bytes(0.2)
    result = validate_ask(
        {
            "text": "  what is this?  ",
            "audio": base64.b64encode(tiny).decode("ascii"),
            "audio_mime": "audio/wav",
            "include_screen": False,
            "include_screenshot": False,
        },
        12 * 1024 * 1024,
        4000,
    )
    assert result["text"] == "what is this?"
    assert result["audio"] == tiny
    assert result["include_screen"] is False

    with pytest.raises(ProtocolError) as caught:
        validate_ask({}, 12 * 1024 * 1024, 4000)
    assert caught.value.code == "empty_ask"

    with pytest.raises(ProtocolError) as caught:
        validate_ask({"text": "x" * 4001}, 12 * 1024 * 1024, 4000)
    assert caught.value.code == "text_too_long"

    with pytest.raises(ProtocolError) as caught:
        validate_ask({"text": "hi", "include_screen": "yes"}, 12 * 1024 * 1024, 4000)
    assert caught.value.code == "bad_payload"

    with pytest.raises(ProtocolError) as caught:
        validate_ask(
            {
                "audio": base64.b64encode(tiny).decode("ascii"),
                "audio_mime": "audio/mpeg",
            },
            12 * 1024 * 1024,
            4000,
        )
    assert caught.value.code == "bad_audio"


def test_validate_ask_caps_audio_duration(wav_bytes) -> None:
    with pytest.raises(ProtocolError) as caught:
        validate_ask(
            {"audio": base64.b64encode(wav_bytes(62)).decode("ascii")},
            12 * 1024 * 1024,
            4000,
        )
    assert caught.value.code == "audio_too_long"


def test_safe_message_does_not_leak_exception_details() -> None:
    assert safe_message(ProtocolError("bad", "Yes.")) == ("bad", "Yes.")
    code, message = safe_message(RuntimeError("secret token=abc"))
    assert code == "internal_error"
    assert "secret" not in message
