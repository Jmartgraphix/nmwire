import re

import nmcli
from typing import Literal
from nmcli.data.device import DeviceDetails

EthernetLinkState = Literal[
    "connected",
    "disconnected",
    "connecting",
    "disconnecting",
    "unplugged",
    "failed",
    "unavailable",
]


def _leading_code(value: str | None) -> int | None:
    """Parse the numeric code from an nmcli field such as '100 (connected)'."""
    if not value:
        return None
    token = value.split(" ", 1)[0]
    return int(token) if token.isdigit() else None


def link_state(eth_dev: DeviceDetails) -> EthernetLinkState:
    """Classify a wired device beyond connected and disconnected.

    NetworkManager uses separate states while a link is coming up or has
    failed, and reports an unplugged cable as no carrier rather than as
    a normal disconnect.
    """
    code = _leading_code(eth_dev.get("GENERAL.STATE"))
    reason = _leading_code(eth_dev.get("GENERAL.REASON"))
    carrier = (eth_dev.get("WIRED-PROPERTIES.CARRIER") or "").strip().lower()
    unplugged = carrier == "off" or reason == 40

    if code == 100:
        return "connected"
    if code is not None and 40 <= code < 100:
        return "connecting"
    if code == 110:
        return "disconnecting"
    if code == 120:
        return "failed"
    if unplugged:
        return "unplugged"
    if code == 30:
        return "disconnected"
    return "unavailable"


def format_link_speed(mbps: int | None) -> str:
    """Format a sysfs speed value. Non-positive means the link has no rate."""
    if mbps is None or mbps <= 0:
        return "unavailable"
    if mbps >= 1000:
        return f"{mbps / 1000:g} Gb/s"
    return f"{mbps} Mb/s"


def _link_speed(device: str) -> str:
    if not device or re.fullmatch(r"[A-Za-z0-9._-]+", device) is None:
        return "unavailable"
    try:
        raw = int(open(f"/sys/class/net/{device}/speed").read().strip())
    except (OSError, ValueError):
        return "unavailable"
    return format_link_speed(raw)


def _indexed_values(eth_dev: DeviceDetails, prefix: str) -> list[str]:
    found: list[tuple[int, str]] = []
    marker = prefix + "["
    for key, value in eth_dev.items():
        if not key.startswith(marker) or not key.endswith("]") or not value:
            continue
        index = key[len(marker):-1]
        if index.isdigit():
            found.append((int(index), value))
    found.sort()
    return [value for _, value in found]


def _dns_servers(eth_dev: DeviceDetails) -> str:
    servers = _indexed_values(eth_dev, "IP4.DNS")
    servers.extend(
        server for server in _indexed_values(eth_dev, "IP6.DNS") if server not in servers
    )
    return ", ".join(servers) if servers else "unavailable"


class EthernetDetails:
    device: str
    hwaddr: str
    name: str
    ipaddr: str
    gateway_addr: str
    dns: str
    speed: str
    state: EthernetLinkState

    def __init__(self, eth_dev: DeviceDetails | None = None):
        if eth_dev != None:
            self._parse_data(eth_dev)
        else:
            # No Ethernet device, such as a Wi-Fi-only laptop. Keep the
            # object usable so the window can still open.
            self.device = ""
            self.hwaddr = "unavailable"
            self.name = ""
            self.ipaddr = "unavailable"
            self.gateway_addr = "unavailable"
            self.dns = "unavailable"
            self.speed = "unavailable"
            self.state = "unavailable"

    def _parse_data(self, eth_dev: DeviceDetails) -> None:
        """parses the information from eth_dev and add to properties"""
        self.device = eth_dev.get("GENERAL.DEVICE") or ""
        self.hwaddr = eth_dev.get("GENERAL.HWADDR")
        self.name = eth_dev.get("GENERAL.CONNECTION")
        self.ipaddr = (
            eth_dev.get("IP4.ADDRESS[1]")
            or eth_dev.get("IP6.ADDRESS[1]")
            or "unavailable"
        )
        self.gateway_addr = (
            eth_dev.get("IP4.GATEWAY") or eth_dev.get("IP6.GATEWAY") or "unavailable"
        )
        self.dns = _dns_servers(eth_dev)
        self.speed = _link_speed(self.device)
        self.state = link_state(eth_dev)


class EthernetService:
    @staticmethod
    def get_devices() -> list[DeviceDetails]:
        """Return every wired device, not only the first one."""
        return [
            dev
            for dev in nmcli.device.show_all()
            if dev.get("GENERAL.TYPE") == "ethernet"
        ]

    @staticmethod
    def get_device_details(device: str) -> DeviceDetails | None:
        """Get one wired device by its interface name."""
        for dev in EthernetService.get_devices():
            if dev.get("GENERAL.DEVICE") == device:
                return dev
        return None

    @staticmethod
    def get_ethernet_status(details: EthernetDetails) -> bool:
        """True when this device's link is connected."""
        return details.state == "connected"

    @staticmethod
    def is_ethernet_available(details: EthernetDetails) -> bool:
        """True when this device can be toggled. Different from connected."""
        return bool(details.device) and details.state != "unavailable"

    @staticmethod
    def toggle_ethernet(state: bool, device: str) -> bool:
        """Enable or disable one Ethernet device."""
        if not device:
            return False

        try:
            current = EthernetService.get_device_details(device)
            if current != None and (link_state(current) == "connected") == state:
                return True

            if state:
                nmcli.device.connect(device)
            else:
                nmcli.device.disconnect(device)
            return True
        except Exception as e:
            print(f"Error toggling Ethernet: {e}")
            return False
