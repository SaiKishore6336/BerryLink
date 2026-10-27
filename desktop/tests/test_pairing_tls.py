from __future__ import annotations

import datetime as dt
import hashlib
import json
import stat

import pytest
from cryptography import x509

from berrylink.pairing import (
    PairingError,
    PairingManager,
    ensure_tls_identity,
    fingerprint_matches,
    local_ipv4_addresses,
)
from berrylink.security import colon_fingerprint, normalize_fingerprint


def test_pairing_rejects_wrong_code_and_expires(tmp_path) -> None:
    now = [100.0]
    manager = PairingManager(tmp_path / "devices.json", clock=lambda: now[0])
    window = manager.begin_pairing(ttl_seconds=60)
    assert len(window.code) == 6 and window.code.isdigit()
    assert manager.pairing_status()["open"] is True

    wrong = "000000" if window.code != "000000" else "111111"
    with pytest.raises(PairingError) as caught:
        manager.pair("wrong", "phone")
    assert caught.value.code == "pairing_failed"
    with pytest.raises(PairingError) as caught:
        manager.pair(wrong, "phone")
    assert caught.value.code == "pairing_failed"
    assert "4 attempts left" in caught.value.message

    manager.cancel_pairing()
    with pytest.raises(PairingError) as caught:
        manager.pair(window.code, "phone")
    assert caught.value.code == "pairing_closed"

    window = manager.begin_pairing(ttl_seconds=30)
    now[0] += 31
    status = manager.pairing_status()
    assert status["open"] is False
    assert status["code"] is None
    with pytest.raises(PairingError) as caught:
        manager.pair(window.code, "phone")
    assert caught.value.code == "pairing_closed"


def test_wrong_codes_close_after_five_attempts(tmp_path) -> None:
    manager = PairingManager(tmp_path / "devices.json")
    window = manager.begin_pairing()
    wrong = "000000" if window.code != "000000" else "111111"
    codes = []
    for _ in range(5):
        with pytest.raises(PairingError) as caught:
            manager.pair(wrong, "phone")
        codes.append(caught.value.code)
    assert codes[-1] == "pairing_closed"
    assert manager.pairing_status()["open"] is False


def test_successful_pairing_is_single_use_and_token_is_hashed(tmp_path) -> None:
    path = tmp_path / "devices.json"
    manager = PairingManager(
        path,
        wall_clock=lambda: dt.datetime(2026, 10, 21, 12, 0, tzinfo=dt.timezone.utc),
    )
    window = manager.begin_pairing()
    device, token = manager.pair(window.code, "  My   Pixel  ")
    assert device["name"] == "My Pixel"
    assert device["id"].startswith("dev_")
    assert len(token) > 30
    assert token not in path.read_text(encoding="utf-8")
    stored = json.loads(path.read_text(encoding="utf-8"))["devices"][0]
    assert stored["token_hash"] == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    with pytest.raises(PairingError) as caught:
        manager.pair(window.code, "Again")
    assert caught.value.code == "pairing_closed"

    reloaded = PairingManager(path)
    assert reloaded.authenticate(device["id"], token)["id"] == device["id"]
    assert reloaded.authenticate(device["id"], token + "x") is None
    assert reloaded.authenticate("missing", token) is None
    assert reloaded.list_devices()[0]["last_seen"] is not None
    assert reloaded.revoke(device["id"]) is True
    assert reloaded.revoke(device["id"]) is False


def test_pairing_store_corruption_fails_closed(tmp_path) -> None:
    path = tmp_path / "devices.json"
    path.write_text("{not json", encoding="utf-8")
    manager = PairingManager(path)
    assert manager.list_devices() == []


def test_tls_identity_is_exact_and_reused(tmp_path) -> None:
    identity = ensure_tls_identity(tmp_path / "tls", "BerryLink test", ["192.168.1.50"])
    cert = x509.load_pem_x509_certificate(identity.cert_file.read_bytes())
    der = cert.public_bytes(__import__("cryptography").hazmat.primitives.serialization.Encoding.DER)
    digest = hashlib.sha256(der).hexdigest().upper()
    assert identity.fingerprint == digest
    assert identity.pretty_fingerprint == colon_fingerprint(digest)
    assert normalize_fingerprint(identity.pretty_fingerprint) == digest
    assert fingerprint_matches(identity.pretty_fingerprint, der)
    assert not fingerprint_matches("AA:BB", der)
    assert "CN=BerryLink local gateway" in identity.subject

    # Key material is private; the public cert is readable.
    assert stat.S_IMODE(identity.key_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(identity.cert_file.stat().st_mode) == 0o644

    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "127.0.0.1" in [str(value) for value in san.get_values_for_type(x509.IPAddress)]
    assert "192.168.1.50" in [str(value) for value in san.get_values_for_type(x509.IPAddress)]
    assert "localhost" in san.get_values_for_type(x509.DNSName)

    again = ensure_tls_identity(tmp_path / "tls", "BerryLink test")
    assert again.fingerprint == identity.fingerprint
    assert again.cert_file.read_bytes() == identity.cert_file.read_bytes()


def test_local_addresses_are_not_loopback() -> None:
    for address in local_ipv4_addresses():
        assert not address.startswith("127.")
        assert not address.startswith("169.254.")
