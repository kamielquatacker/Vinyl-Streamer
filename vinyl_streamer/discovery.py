from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from typing import Dict, List

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
    properties: Dict[str, str]


def _friendly_name(raw_name: str) -> str:
    if "@" in raw_name:
        return raw_name.split("@", 1)[1]
    return raw_name


def _format_properties(info: ServiceInfo) -> Dict[str, str]:
    if not info.properties:
        return {}
    formatted: Dict[str, str] = {}
    for key, value in info.properties.items():
        key_text = key.decode("utf-8", errors="ignore") if isinstance(key, bytes) else str(key)
        if isinstance(value, bytes):
            value_text = value.decode("utf-8", errors="ignore")
        else:
            value_text = str(value)
        formatted[key_text] = value_text
    return formatted


class _Collector:
    def __init__(self, zeroconf: Zeroconf, service_type: str, results: List[AirPlayDevice]):
        self.zeroconf = zeroconf
        self.service_type = service_type
        self.results = results

    def add_service(self, zeroconf: Zeroconf, service_type: str, name: str) -> None:
        info = zeroconf.get_service_info(service_type, name)
        if not info:
            return
        address = socket.inet_ntoa(info.addresses[0]) if info.addresses else "unknown"
        device = AirPlayDevice(
            name=info.name.replace(service_type, "").strip("."),
            friendly_name=_friendly_name(info.name.replace(service_type, "").strip(".")),
            display_name="",
            address=address,
            port=info.port,
            service_type=service_type,
            properties=_format_properties(info),
        )
        device.display_name = f"{device.friendly_name} ({device.address})"
        self.results.append(device)

    def update_service(self, zeroconf: Zeroconf, service_type: str, name: str) -> None:
        return


def discover(duration: float = 3.0) -> List[AirPlayDevice]:
    zeroconf = Zeroconf()
    results: List[AirPlayDevice] = []
    collectors = [
        _Collector(zeroconf, RAOP_SERVICE, results),
        _Collector(zeroconf, AIRPLAY_SERVICE, results),
    ]
    browsers = [
        ServiceBrowser(zeroconf, RAOP_SERVICE, collectors[0]),
        ServiceBrowser(zeroconf, AIRPLAY_SERVICE, collectors[1]),
    ]
    try:
        time.sleep(duration)
    finally:
        for browser in browsers:
            browser.cancel()
        zeroconf.close()
    return results
