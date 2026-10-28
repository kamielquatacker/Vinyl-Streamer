from unittest.mock import Mock

import pytest

from zeroconf import ServiceInfo

from app import discovery
from app.discovery import AirPlayDiscovery, RAOP_SERVICE


def test_discovery_updates_and_removes_devices():
    browser = AirPlayDiscovery()
    name = "000C8A9D57C7@SoundTouch Quatacker." + RAOP_SERVICE
    info = ServiceInfo(RAOP_SERVICE, name, port=5000, parsed_addresses=["192.168.1.20"], properties={b"model": b"Bose"})
    zeroconf = Mock()
    zeroconf.get_service_info.return_value = info
    browser.add_service(zeroconf, RAOP_SERVICE, name)
    browser.update_service(zeroconf, RAOP_SERVICE, name)
    device, = browser.snapshot()
    assert device.friendly_name == "SoundTouch Quatacker"
    assert device.address == "192.168.1.20"
    assert device.properties == {"model": "Bose"}
    zeroconf.get_service_info.return_value = ServiceInfo(RAOP_SERVICE, name, port=5000, parsed_addresses=["192.168.1.21"])
    browser.update_service(zeroconf, RAOP_SERVICE, name)
    assert browser.snapshot()[0].address == "192.168.1.21"
    browser.remove_service(zeroconf, RAOP_SERVICE, name)
    assert browser.snapshot() == []


def test_discovery_accepts_ipv6():
    browser = AirPlayDiscovery()
    name = "Bose." + RAOP_SERVICE
    zeroconf = Mock()
    zeroconf.get_service_info.return_value = ServiceInfo(RAOP_SERVICE, name, port=5000, parsed_addresses=["2001:db8::20"])
    browser.add_service(zeroconf, RAOP_SERVICE, name)
    assert browser.snapshot()[0].address == "2001:db8::20"


def test_browser_start_failure_cleans_up_and_can_be_retried(monkeypatch):
    zeroconf = Mock()
    monkeypatch.setattr(discovery, "Zeroconf", lambda: zeroconf)
    service_browser = Mock(side_effect=OSError("Network offline"))
    monkeypatch.setattr(discovery, "ServiceBrowser", service_browser)
    browser = AirPlayDiscovery()
    with pytest.raises(OSError):
        browser.start()
    zeroconf.close.assert_called_once()
    assert browser.error
    service_browser.side_effect = None
    browser.start()
    assert not browser.error
    browser.stop()
    service_browser.return_value.cancel.assert_called_once()
