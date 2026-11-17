"""Data models for the network manager application"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

class WiFiState(Enum):
    """Enum for WiFi states"""
    OFF = "off"
    ON = "on"
    SCANNING = "scanning"
    CONNECTING = "connecting"

@dataclass
class NetworkInfo:
    """Data class for network information"""
    ssid: str
    signal: int
    requires_password: bool
    is_connected: bool = False
    bssid: Optional[str] = None
    frequency: Optional[int] = None
    channel: Optional[int] = None
    rate: Optional[int] = None
    mode: Optional[str] = None
    security: Optional[str] = None
    
    @classmethod
    def from_wifi_device(cls, wifi_device):
        """Create NetworkInfo from nmcli wifi device"""
        return cls(
            ssid=wifi_device.ssid,
            signal=wifi_device.signal,
            requires_password=bool(wifi_device.security),
            is_connected=wifi_device.in_use,
            bssid=wifi_device.bssid,
            frequency=wifi_device.freq,
            channel=wifi_device.chan,
            rate=wifi_device.rate,
            mode=wifi_device.mode,
            security=wifi_device.security
        )


@dataclass
class NetworkGroup:
    """Access points that share an SSID and security."""

    nodes: list[NetworkInfo]

    @property
    def ssid(self) -> str:
        return self.nodes[0].ssid

    @property
    def security(self) -> str:
        return self.nodes[0].security or ""

    @property
    def is_connected(self) -> bool:
        return any(node.is_connected for node in self.nodes)

    @property
    def representative(self) -> NetworkInfo:
        """Strongest access point. The list row uses its signal."""
        return max(self.nodes, key=lambda node: node.signal)

    @property
    def connected_node(self) -> NetworkInfo | None:
        """The access point currently in use, when this group is connected."""
        connected = [node for node in self.nodes if node.is_connected]
        if not connected:
            return None
        return max(connected, key=lambda node: node.signal)

    @property
    def display_node(self) -> NetworkInfo:
        """The radio this row describes.

        A connected row shows the link in use. Any other row shows the
        strongest radio you could join.
        """
        return self.connected_node or self.representative


def group_networks(networks: list[NetworkInfo]) -> list[NetworkGroup]:
    """Collapse access points that advertise the same name and security.

    A different security type stays separate, since it is not the same network.
    """
    buckets: dict[tuple[str, str], list[NetworkInfo]] = {}
    order: list[tuple[str, str]] = []
    for network in networks:
        key = (network.ssid, network.security or "")
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(network)

    groups: list[NetworkGroup] = []
    for key in order:
        nodes = sorted(
            buckets[key],
            key=lambda node: (not node.is_connected, -node.signal, node.bssid or ""),
        )
        groups.append(NetworkGroup(nodes))
    groups.sort(
        key=lambda group: (
            not group.is_connected,
            -group.representative.signal,
            group.ssid,
        )
    )
    return groups
