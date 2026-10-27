"""Pairing, device tokens and the desktop's pinned TLS certificate."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .security import (
    atomic_write_text,
    colon_fingerprint,
    normalize_fingerprint,
    secure_dir,
    sha256_hex,
)


class PairingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class PairingWindow:
    code: str
    expires_monotonic: float
    attempts: int = 0


class PairingManager:
    """Stores only hashes of high-entropy device tokens."""

    MAX_ATTEMPTS = 5
    DEFAULT_TTL = 120

    def __init__(
        self,
        devices_file: Path,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self.devices_file = devices_file
        self._clock = clock
        self._wall = wall_clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self._window: PairingWindow | None = None
        self._lock = threading.RLock()
        self._devices: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.devices_file.read_text(encoding="utf-8"))
            devices = raw.get("devices", [])
            if isinstance(devices, list):
                for item in devices:
                    if (
                        isinstance(item, dict)
                        and isinstance(item.get("id"), str)
                        and isinstance(item.get("token_hash"), str)
                    ):
                        self._devices[item["id"]] = item
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            # A corrupt device store fails closed: the user will need to pair again.
            self._devices = {}

    def _save(self) -> None:
        payload = json.dumps(
            {"schema": 1, "devices": sorted(self._devices.values(), key=lambda d: d["created_at"])},
            indent=2,
            sort_keys=True,
        )
        atomic_write_text(self.devices_file, payload + "\n", mode=0o600)

    def begin_pairing(self, ttl_seconds: int = DEFAULT_TTL) -> PairingWindow:
        with self._lock:
            code = f"{secrets.randbelow(1_000_000):06d}"
            self._window = PairingWindow(code=code, expires_monotonic=self._clock() + ttl_seconds)
            return self._window

    def cancel_pairing(self) -> None:
        with self._lock:
            self._window = None

    def pairing_status(self) -> dict[str, Any]:
        with self._lock:
            if not self._window:
                return {"open": False, "expires_in": 0, "attempts_left": self.MAX_ATTEMPTS}
            remaining = max(0, int(self._window.expires_monotonic - self._clock()))
            return {
                "open": remaining > 0,
                "expires_in": remaining,
                "attempts_left": max(0, self.MAX_ATTEMPTS - self._window.attempts),
                "code": self._window.code if remaining > 0 else None,
            }

    def _check_window(self) -> PairingWindow:
        window = self._window
        if window is None or self._clock() >= window.expires_monotonic:
            self._window = None
            raise PairingError("pairing_closed", "Pairing is not open on the desktop.")
        return window

    def mint_device(self, device_name: str) -> tuple[dict[str, Any], str]:
        """Create a new paired phone record without any code check.

        Only called after a confirmation the desktop owner saw and approved
        (the 6-digit code path pairs through `pair`).
        """
        name = " ".join(str(device_name or "Android phone").split())[:64] or "Android phone"
        with self._lock:
            device_id = "dev_" + secrets.token_hex(8)
            token = secrets.token_urlsafe(32)
            device = {
                "id": device_id,
                "name": name,
                "token_hash": sha256_hex(token.encode("utf-8")),
                "created_at": self._wall().replace(microsecond=0).isoformat(),
                "last_seen": None,
            }
            self._devices[device_id] = device
            self._save()
            return self._public_device(device), token

    def pair(self, code: str, device_name: str) -> tuple[dict[str, Any], str]:
        if not isinstance(code, str) or not code.isdigit() or len(code) != 6:
            raise PairingError("pairing_failed", "Enter the 6-digit code shown on the desktop.")
        name = " ".join(str(device_name or "Android phone").split())[:64] or "Android phone"
        with self._lock:
            window = self._check_window()
            if not hmac.compare_digest(window.code, code):
                window.attempts += 1
                attempts_left = max(0, self.MAX_ATTEMPTS - window.attempts)
                if window.attempts >= self.MAX_ATTEMPTS:
                    self._window = None
                    raise PairingError(
                        "pairing_closed",
                        "Too many incorrect codes. Start pairing again on the desktop.",
                    )
                raise PairingError(
                    "pairing_failed",
                    f"That code did not match. {attempts_left} attempts left.",
                )
            # A successful code is single-use.
            self._window = None
        return self.mint_device(name)

    def authenticate(self, device_id: str, token: str) -> dict[str, Any] | None:
        if not isinstance(device_id, str) or not isinstance(token, str):
            return None
        with self._lock:
            device = self._devices.get(device_id)
            if not device:
                return None
            expected = device.get("token_hash", "")
            actual = sha256_hex(token.encode("utf-8"))
            if not hmac.compare_digest(expected, actual):
                return None
            now = self._wall().replace(microsecond=0)
            previous = device.get("last_seen")
            if not previous or (now - dt.datetime.fromisoformat(previous)).total_seconds() > 60:
                device["last_seen"] = now.isoformat()
                self._save()
            return self._public_device(device)

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            existed = self._devices.pop(device_id, None) is not None
            if existed:
                self._save()
            return existed

    def list_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._public_device(d) for d in sorted(self._devices.values(), key=lambda x: x["created_at"])]

    @staticmethod
    def _public_device(device: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": device["id"],
            "name": device["name"],
            "created_at": device["created_at"],
            "last_seen": device.get("last_seen"),
        }


# --------------------------------------------------------------------------- TLS


@dataclass
class TlsIdentity:
    cert_file: Path
    key_file: Path
    fingerprint: str  # uppercase hex SHA-256 of the DER certificate
    subject: str

    @property
    def pretty_fingerprint(self) -> str:
        return colon_fingerprint(self.fingerprint)


def ensure_tls_identity(
    tls_dir: Path,
    display_name: str,
    extra_ips: list[str] | None = None,
) -> TlsIdentity:
    """Reuse a valid self-signed certificate or create a fresh one.

    Android pins the SHA-256 of this exact certificate.  The self-signed leaf is
    never treated as publicly trusted and hostname checks are replaced by an
    exact certificate pin, never disabled in general.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    secure_dir(tls_dir, 0o700)
    cert_file = tls_dir / "server.crt"
    key_file = tls_dir / "server.key"
    if cert_file.exists() and key_file.exists():
        try:
            cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
            now = dt.datetime.now(dt.timezone.utc)
            if cert.not_valid_after_utc - now > dt.timedelta(days=30):
                der = cert.public_bytes(serialization.Encoding.DER)
                return TlsIdentity(
                    cert_file=cert_file,
                    key_file=key_file,
                    fingerprint=sha256_hex(der).upper(),
                    subject=cert.subject.rfc4514_string(),
                )
        except (OSError, ValueError):
            pass

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = dt.datetime.now(dt.timezone.utc)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "BerryLink"),
            x509.NameAttribute(NameOID.COMMON_NAME, "BerryLink local gateway"),
        ]
    )
    host_name = socket.gethostname() or "localhost"
    dns_names = ["localhost"]
    for candidate in (host_name, host_name.split(".")[0], host_name.removesuffix(".local")):
        if candidate and candidate not in dns_names:
            dns_names.append(candidate)
    if not host_name.endswith(".local"):
        local_variant = f"{host_name.removesuffix('.local')}.local"
        if local_variant not in dns_names:
            dns_names.append(local_variant)
    san_entries: list[x509.GeneralName] = [x509.DNSName(value) for value in dns_names]
    san_entries.append(x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1")))
    seen = {"127.0.0.1"}
    for value in extra_ips or []:
        try:
            ip = __import__("ipaddress").ip_address(value)
        except ValueError:
            continue
        if str(ip) not in seen:
            san_entries.append(x509.IPAddress(ip))
            seen.add(str(ip))
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
    from .security import atomic_write_bytes

    atomic_write_bytes(key_file, key_bytes, mode=0o600)
    atomic_write_bytes(cert_file, cert_bytes, mode=0o644)
    der = cert.public_bytes(serialization.Encoding.DER)
    return TlsIdentity(
        cert_file=cert_file,
        key_file=key_file,
        fingerprint=sha256_hex(der).upper(),
        subject=subject.rfc4514_string(),
    )


def local_ipv4_addresses() -> list[str]:
    """Best-effort LAN address discovery, without sending any packets."""
    addresses: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM):
            addr = info[4][0]
            if addr and not addr.startswith("127."):
                addresses.add(addr)
    except OSError:
        pass
    # The UDP connect trick reveals the preferred interface without transmitting.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("192.0.2.1", 9))
            addresses.add(sock.getsockname()[0])
        finally:
            sock.close()
    except OSError:
        pass
    return sorted(a for a in addresses if a and not a.startswith("169.254."))


def fingerprint_matches(expected: str, cert_der: bytes) -> bool:
    return normalize_fingerprint(expected) == sha256_hex(cert_der).upper()
