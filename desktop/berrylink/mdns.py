"""mDNS/DNS-SD advertisement for Android NSD discovery."""

from __future__ import annotations

import logging
import socket
from typing import Any

from .pairing import local_ipv4_addresses

SERVICE_TYPE = "_berrylink._tcp.local."


class MdnsAdvertiser:
    def __init__(
        self,
        display_name: str,
        port: int,
        fingerprint: str,
        version: str = "0.1.0",
        logger: logging.Logger | None = None,
    ) -> None:
        self.display_name = display_name
        self.port = port
        self.fingerprint = fingerprint.upper().replace(":", "")
        self.version = version
        self.log = logger or logging.getLogger("berrylink.mdns")
        self._zeroconf = None
        self._info = None
        self.addresses: list[str] = []
        self.error: str | None = None

    @property
    def name(self) -> str:
        host = socket.gethostname().replace(".local", "") or "berrylink"
        return f"BerryLink on {host}"

    def start(self) -> bool:
        try:
            from zeroconf import ServiceInfo, Zeroconf

            self.addresses = local_ipv4_addresses()
            if not self.addresses:
                self.error = "No LAN IPv4 address was found; use manual IP entry on the phone."
                self.log.warning(self.error)
                return False
            properties = {
                "proto": "1",
                "name": self.display_name,
                "fp": self.fingerprint,
                "version": self.version,
                "app": "BerryLink",
            }
            info = ServiceInfo(
                SERVICE_TYPE,
                f"{self.name}.{SERVICE_TYPE}",
                addresses=[socket.inet_aton(address) for address in self.addresses],
                port=self.port,
                properties=properties,
                server=f"{socket.gethostname().split('.')[0] or 'berrylink'}.local.",
            )
            zeroconf = Zeroconf()
            zeroconf.register_service(info, allow_name_change=True)
            self._zeroconf = zeroconf
            self._info = info
            self.error = None
            self.log.info(
                "mDNS advertised as %s on port %s (%s)",
                info.name,
                self.port,
                ", ".join(self.addresses),
            )
            return True
        except Exception as exc:
            self.error = "mDNS discovery could not start; use manual IP entry on the phone."
            self.log.warning("mDNS failed: %s", type(exc).__name__)
            self.stop()
            return False

    def stop(self) -> None:
        try:
            if self._zeroconf is not None and self._info is not None:
                self._zeroconf.unregister_service(self._info)
        except Exception:
            pass
        try:
            if self._zeroconf is not None:
                self._zeroconf.close()
        except Exception:
            pass
        self._zeroconf = None
        self._info = None

    def status(self) -> dict[str, Any]:
        return {
            "running": self._zeroconf is not None,
            "name": self.name,
            "addresses": list(self.addresses),
            "port": self.port,
            "error": self.error,
        }
