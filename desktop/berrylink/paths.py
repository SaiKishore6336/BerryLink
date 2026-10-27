"""Filesystem locations used by BerryLink.

Every path can be overridden with an environment variable, which keeps the
test suite from touching a real user's notes or credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _home() -> Path:
    return Path(os.path.expanduser("~"))


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    state_dir: Path
    notes_dir: Path
    log_dir: Path
    vendor_dir: Path

    @classmethod
    def default(cls) -> "AppPaths":
        home = _home()
        config_dir = Path(
            os.environ.get("BERRYLINK_CONFIG_DIR", home / ".config" / "berrylink")
        ).expanduser()
        data_dir = Path(
            os.environ.get(
                "BERRYLINK_DATA_DIR", home / ".local" / "share" / "berrylink"
            )
        ).expanduser()
        state_dir = Path(
            os.environ.get("BERRYLINK_STATE_DIR", home / ".local" / "state" / "berrylink")
        ).expanduser()
        notes_dir = Path(
            os.environ.get(
                "BERRYLINK_NOTES_DIR", home / "Documents" / "BerryLink Notes"
            )
        ).expanduser()
        pad = os.environ.get("XDG_DATA_HOME")
        if pad and "BERRYLINK_DATA_DIR" not in os.environ:
            data_dir = Path(pad).expanduser() / "berrylink"
        vendor_dir = Path(
            os.environ.get("BERRYLINK_VENDOR_DIR", data_dir / "vendor")
        ).expanduser()
        return cls(config_dir, data_dir, state_dir, notes_dir, log_dir=state_dir, vendor_dir=vendor_dir)

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def secrets_file(self) -> Path:
        return self.config_dir / "secrets.json"

    @property
    def devices_file(self) -> Path:
        return self.config_dir / "devices.json"

    @property
    def tls_dir(self) -> Path:
        return self.config_dir / "tls"

    @property
    def cert_file(self) -> Path:
        return self.tls_dir / "server.crt"

    @property
    def key_file(self) -> Path:
        return self.tls_dir / "server.key"

    @property
    def log_file(self) -> Path:
        return self.log_dir / "berrylink.log"

    @property
    def vendor_tesseract(self) -> Path:
        return self.vendor_dir / "tesseract" / "bin" / "tesseract"

    @property
    def vendor_tessdata(self) -> Path:
        return self.vendor_dir / "tesseract" / "tessdata"

    def ensure(self) -> None:
        from .security import secure_dir

        for directory in (
            self.config_dir,
            self.data_dir,
            self.state_dir,
            self.notes_dir,
            self.tls_dir,
        ):
            secure_dir(directory)
