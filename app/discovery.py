from __future__ import annotations

import time
from dataclasses import dataclass
from threading import RLock

from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf

RAOP_SERVICE = "_raop._tcp.local."
AIRPLAY_SERVICE = "_airplay._tcp.local."


@dataclass
class AirPlayDevice:
    name: str
    friendly_name: str
    display_name: str
    address: str
    port: int
    service_type: str
    properties: dict[str, str]


def _format_properties(info: ServiceInfo) -> dict[str, str]:
    def decode(value: object) -> str:
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")
    return {decode(key): decode(value) for key, value in info.properties.items()}


class AirPlayDiscovery:
    """One continuous browser; HTTP requests read a thread-safe snapshot."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._lifecycle_lock = RLock()
        self._devices: dict[tuple[str, str], AirPlayDevice] = {}
        self._zeroconf: Zeroconf | None = None
        self._browser: ServiceBrowser | None = None
        self._started_at = 0.0
        self.error: str | None = None

    def start(self) -> None:
        with self._lifecycle_lock:
            self._start()

    def _start(self) -> None:
        if self._zeroconf is not None:
            return
        try:
            self._zeroconf = Zeroconf()
            self._started_at = time.monotonic()
            self._browser = ServiceBrowser(self._zeroconf, [RAOP_SERVICE, AIRPLAY_SERVICE], self)
            self.error = None
        except Exception:
            self.stop()
            self.error = "Netwerkdetectie is niet beschikbaar. Controleer de netwerkverbinding van de Pi."
            raise

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stop()

    def _stop(self) -> None:
        if self._browser is not None:
            self._browser.cancel()
            self._browser = None
        if self._zeroconf is not None:
            self._zeroconf.close()
            self._zeroconf = None
        with self._lock:
            self._devices.clear()

    @property
    def discovering(self) -> bool:
        return self._zeroconf is not None and time.monotonic() - self._started_at < 5

    def snapshot(self) -> list[AirPlayDevice]:
        with self._lock:
            return sorted(self._devices.values(), key=lambda device: (device.friendly_name.casefold(), device.service_type))

    def add_service(self, zeroconf: Zeroconf, service_type: str, name: str) -> None:
        info = zeroconf.get_service_info(service_type, name, timeout=2000)
        if info is None:
            return
        addresses = info.parsed_scoped_addresses()
        if not addresses:
            return
        raw_name = info.name.removesuffix("." + service_type)
        friendly_name = raw_name.split("@", 1)[-1]
        device = AirPlayDevice(
            name=raw_name, friendly_name=friendly_name,
            display_name=f"{friendly_name} ({addresses[0]})",
            address=addresses[0], port=info.port, service_type=service_type,
            properties=_format_properties(info),
        )
        with self._lock:
            self._devices[(service_type, name)] = device

    def update_service(self, zeroconf: Zeroconf, service_type: str, name: str) -> None:
        self.add_service(zeroconf, service_type, name)

    def remove_service(self, zeroconf: Zeroconf, service_type: str, name: str) -> None:
        with self._lock:
            self._devices.pop((service_type, name), None)
