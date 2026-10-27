from __future__ import annotations

import json
import stat

import pytest

from berrylink.security import (
    SecretStore,
    is_password_manager,
    looks_sensitive_label,
    normalize_fingerprint,
    redact,
    register_secret,
    remove_tree_under,
    safe_text_preview,
)


def test_redacts_google_keys_bearers_and_registered_secrets() -> None:
    google = "AIza" + "a" * 24
    secret = "unique-secret-" + "x" * 20
    register_secret(secret)
    text = f"key={google} Authorization: Bearer {'b' * 24} token={secret} api_key=abc12345678"
    cleaned = redact(text)
    assert google not in cleaned
    assert secret not in cleaned
    assert "b" * 24 not in cleaned
    assert "abc12345678" not in cleaned
    assert "[REDACTED]" in cleaned


def test_sensitive_window_and_label_helpers() -> None:
    assert is_password_manager("keepassxc", "Vault")
    assert is_password_manager("firefox", "Bitwarden — vault")
    assert not is_password_manager("firefox", "Recipe")
    for label in ("Password:", "Recovery code", "API key", "Verification code"):
        assert looks_sensitive_label(label)
    assert not looks_sensitive_label("Search the web")


def test_secret_store_file_fallback_is_mode_600(tmp_path, data_paths, monkeypatch) -> None:
    store = SecretStore(data_paths)
    monkeypatch.setattr(store, "_secret_tool", lambda: None)
    key = "test-key-" + "a" * 24
    assert store.set_key(key) == "restricted-file"
    assert store.get_key() == key
    assert stat.S_IMODE(data_paths.secrets_file.stat().st_mode) == 0o600
    payload = json.loads(data_paths.secrets_file.read_text(encoding="utf-8"))
    assert payload == {"gemini_api_key": key}
    assert store.backend().startswith("restricted file")
    assert store.has_key() is True
    store.clear_key()
    assert store.get_key() is None


def test_secret_store_rejects_bad_keys(tmp_path, data_paths, monkeypatch) -> None:
    store = SecretStore(data_paths)
    monkeypatch.setattr(store, "_secret_tool", lambda: None)
    for value in ("short", "has space " + "a" * 30, "a" * 300):
        with pytest.raises(ValueError):
            store.set_key(value)


def test_fingerprint_normalization_and_preview() -> None:
    assert normalize_fingerprint("aa:bb:cc") == "AABBCC"
    assert safe_text_preview("  a   b  ", 3) == "a b"
    assert safe_text_preview("abcdef", 5) == "abcd…"


def test_remove_tree_under_only_direct_children(tmp_path) -> None:
    root = tmp_path / "notes"
    child = root / "one"
    nested = root / "two" / "inner"
    nested.mkdir(parents=True)
    child.mkdir()
    remove_tree_under(root, child)
    assert not child.exists()
    with pytest.raises(ValueError):
        remove_tree_under(root, nested)
    with pytest.raises(ValueError):
        remove_tree_under(root, root)
