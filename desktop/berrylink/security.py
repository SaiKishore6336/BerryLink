"""Small security utilities: secrets, redaction, file modes and hashes."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

_KEY_PATTERN = re.compile(r"((?:AIza[0-9A-Za-z_\-]{15,})|(?:sk-or-)?[0-9a-zA-Z._\-]{15,})")
_BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)[0-9a-zA-Z._\-]{16,}")
_SECRETISH = re.compile(
    r"(?i)(api[_-]?key|token|secret|authorization)(\s*[:=]\s*)[^\s,;\"']{8,}"
)

_SECRETS: set[str] = set()


def register_secret(value: str | None) -> None:
    """Remember a secret so logging filters can redact it everywhere."""
    if value and len(value) >= 8:
        _SECRETS.add(value)


def redact(text: str) -> str:
    out = _KEY_PATTERN.sub("[REDACTED]", text)
    out = _BEARER_PATTERN.sub(r"\1[REDACTED]", out)
    out = _SECRETISH.sub(r"\1\2[REDACTED]", out)
    for secret in sorted(_SECRETS, key=len, reverse=True):
        out = out.replace(secret, "[REDACTED]")
    return out


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            message = record.getMessage()
        except Exception:
            return True
        record.msg = redact(message)
        record.args = ()
        if record.exc_info:
            # Never persist an exception traceback that may contain request data.
            exc_type = record.exc_info[0]
            record.exc_text = None
            if exc_type is not None:
                record.msg = f"{record.msg} [exception: {exc_type.__name__}]"
            record.exc_info = None
        return True


def configure_logging(log_file: Path | None, verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("berrylink")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    stream.addFilter(RedactionFilter())
    logger.addHandler(stream)
    if log_file is not None:
        try:
            secure_dir(log_file.parent)
            handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=1_500_000, backupCount=3, encoding="utf-8"
            )
            try:
                os.chmod(log_file, 0o600)
            except OSError:
                pass
            handler.setFormatter(formatter)
            handler.addFilter(RedactionFilter())
            logger.addHandler(handler)
        except OSError:
            pass
    return logger


# logging.handlers is a separate module; importing here keeps the public API small.
import logging.handlers  # noqa: E402  (after logging import)


def secure_dir(path: Path, mode: int = 0o700) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def atomic_write_text(path: Path, text: str, mode: int = 0o600) -> None:
    secure_dir(path.parent)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass


def atomic_write_bytes(path: Path, data: bytes, mode: int = 0o600) -> None:
    secure_dir(path.parent)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass


def file_mode(path: Path) -> int | None:
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def colon_fingerprint(hex_digest: str) -> str:
    clean = re.sub(r"[^0-9A-Fa-f]", "", hex_digest).upper()
    return ":".join(clean[i : i + 2] for i in range(0, len(clean), 2))


def normalize_fingerprint(value: str) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", value).upper()


def is_password_manager(window_class: str, window_title: str) -> bool:
    haystack = f"{window_class} {window_title}".lower()
    markers = (
        "keepass",
        "bitwarden",
        "1password",
        "lastpass",
        "enpass",
        "password store",
        "passwords and keys",
        "seahorse",
        "wallet",
    )
    return any(marker in haystack for marker in markers)


def looks_sensitive_label(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        word in lowered
        for word in (
            "password",
            "passphrase",
            "secret",
            "api key",
            "recovery code",
            "verification code",
        )
    )


def safe_text_preview(value: str, limit: int = 80) -> str:
    one_line = " ".join(str(value).split())
    if len(one_line) > limit:
        one_line = one_line[: limit - 1] + "…"
    return one_line


class SecretStore:
    """Prefer the OS secret service; fall back to a mode-0600 file.

    The file fallback is deliberate and disclosed in the UI: on a system
    without libsecret there is no safe unattended secret service to use.
    Keys are stored per provider (gemini | openrouter) and never leave this
    desktop: they are never written into config.json or sent to the phone.
    """

    SERVICE = "app.berrylink.desktop"
    ACCOUNTS = {
        "gemini": "gemini-api-key",
        "openrouter": "openrouter-api-key",
        "xkiro": "xkiro-api-key",
    }
    FILE_FIELDS = {
        "gemini": "gemini_api_key",
        "openrouter": "openrouter_api_key",
        "xkiro": "xkiro_api_key",
    }
    LABELS = {
        "gemini": "BerryLink Gemini API key",
        "openrouter": "BerryLink OpenRouter API key",
        "xkiro": "BerryLink xkiro API key",
    }

    def __init__(self, paths) -> None:  # AppPaths, kept duck-typed for tests
        self.paths = paths

    def _secret_tool(self) -> str | None:
        return shutil.which("secret-tool")

    def _file_load_all(self) -> dict[str, str]:
        try:
            data = json.loads(self.paths.secrets_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(data, dict):
            return {}
        result: dict[str, str] = {}
        for provider, field_name in self.FILE_FIELDS.items():
            value = data.get(field_name)
            if isinstance(value, str) and value.strip():
                result[provider] = value
        return result

    def _file_load(self, provider: str = "gemini") -> str | None:
        return self._file_load_all().get(provider)

    def _file_store(self, provider: str, value: str | None) -> None:
        if provider not in self.FILE_FIELDS:
            raise ValueError(f"Unknown AI provider: {provider}")
        if value is None:
            merged = self._file_load_all()
            merged.pop(provider, None)
            if merged:
                payload = {self.FILE_FIELDS[p]: v for p, v in merged.items()}
                atomic_write_text(
                    self.paths.secrets_file,
                    json.dumps(payload, indent=2) + "\n",
                    mode=0o600,
                )
            else:
                try:
                    self.paths.secrets_file.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
            return
        merged = self._file_load_all()
        merged[provider] = value
        payload = {self.FILE_FIELDS[p]: v for p, v in merged.items()}
        atomic_write_text(
            self.paths.secrets_file,
            json.dumps(payload, indent=2) + "\n",
            mode=0o600,
        )

    def get_key(self, provider: str = "gemini") -> str | None:
        if provider not in self.ACCOUNTS:
            raise ValueError(f"Unknown AI provider: {provider}")
        tool = self._secret_tool()
        if tool:
            try:
                proc = subprocess.run(
                    [tool, "lookup", "service", self.SERVICE, "account", self.ACCOUNTS[provider]],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                value = proc.stdout.strip()
                if proc.returncode == 0 and value:
                    register_secret(value)
                    return value
            except (OSError, subprocess.SubprocessError):
                pass
        value = self._file_load(provider)
        if value:
            register_secret(value)
        return value

    def set_key(self, value: str, provider: str = "gemini") -> str:
        if provider not in self.ACCOUNTS:
            raise ValueError(f"Unknown AI provider: {provider}")
        value = value.strip()
        if not 20 <= len(value) <= 256 or any(c.isspace() for c in value):
            raise ValueError("That does not look like an API key.")
        tool = self._secret_tool()
        if tool:
            try:
                proc = subprocess.run(
                    [
                        "store",
                        f"--label={self.LABELS[provider]}",
                        "service",
                        self.SERVICE,
                        "account",
                        self.ACCOUNTS[provider],
                    ],
                    input=value,
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                if proc.returncode == 0:
                    register_secret(value)
                    self._file_store(provider, None)
                    return "secret-tool"
            except (OSError, subprocess.SubprocessError):
                pass
        self._file_store(provider, value)
        register_secret(value)
        return "restricted-file"

    def clear_key(self, provider: str = "gemini") -> None:
        if provider not in self.ACCOUNTS:
            raise ValueError(f"Unknown AI provider: {provider}")
        tool = self._secret_tool()
        if tool:
            try:
                subprocess.run(
                    [tool, "clear", "service", self.SERVICE, "account", self.ACCOUNTS[provider]],
                    capture_output=True,
                    timeout=5,
                )
            except (OSError, subprocess.SubprocessError):
                pass
        self._file_store(provider, None)

    def backend(self) -> str:
        return "OS secret service" if self._secret_tool() else "restricted file (mode 600)"

    def has_key(self, provider: str = "gemini") -> bool:
        return bool(self.get_key(provider))


def remove_tree_under(root: Path, target: Path) -> None:
    """Delete target only if it is a direct child of root (defence in depth)."""
    root = root.resolve()
    target = target.resolve()
    if target.parent != root:
        raise ValueError("refusing to delete a path outside the notes root")
    if target == root:
        raise ValueError("refusing to delete the notes root")
    shutil.rmtree(target)
