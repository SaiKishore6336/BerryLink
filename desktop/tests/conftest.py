from __future__ import annotations

import io
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop"
if str(DESKTOP) not in sys.path:
    sys.path.insert(0, str(DESKTOP))


@pytest.fixture
def wav_bytes():
    def make(seconds: float = 1.0, rate: int = 16000) -> bytes:
        out = io.BytesIO()
        with wave.open(out, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            frames = int(seconds * rate)
            handle.writeframes(b"\x00\x00" * frames)
        return out.getvalue()

    return make


@pytest.fixture
def data_paths(tmp_path):
    from berrylink.paths import AppPaths

    paths = AppPaths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        state_dir=tmp_path / "state",
        notes_dir=tmp_path / "notes",
        log_dir=tmp_path / "state",
        vendor_dir=tmp_path / "data" / "vendor",
    )
    paths.ensure()
    return paths
