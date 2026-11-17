import re
import threading

from typing import Literal
from nmcli._device import DeviceControl
from nmcli._system import SystemCommand
from nmcli.data.device import DeviceDetails


class _EnglishCommand(SystemCommand):
    """nmcli for Ethernet, always in English.

    The process environment can set LANGUAGE, which gettext prefers over
    LANG. Pinning that too keeps the carrier value "on" or "off".
    """

    def __init__(self):
        super().__init__()
        self._call_lock = threading.Lock()
        self.disable_use_sudo()
        self.set_lang("C.UTF-8")

    def nmcli(self, parameters):
        with self._call_lock:
            original = self._run

            def run(commands, capture_output, check, env):
                pinned = dict(env)
                pinned["LANG"] = "C.UTF-8"
                pinned["LC_ALL"] = "C.UTF-8"
                pinned["LANGUAGE"] = "C"
                return original(
                    commands, capture_output=capture_output, check=check, env=pinned
                )

            self._run = run
            try:
                return super().nmcli(parameters)
            finally:
                self._run = original


_device = DeviceControl(_EnglishCommand())

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
    a normal disconnect. The carrier word is read in English.
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


def _is_link_local_ipv6(address: str) -> bool:
    """True for fe80::/10. Those addresses only work on the local link."""
    host = address.split("/", 1)[0].split("%", 1)[0].strip().lower()
    first = host.split(":", 1)[0]
    try:
        return 0xFE80 <= int(first, 16) <= 0xFEBF
    except ValueError:
        return False


def _display_address(eth_dev: DeviceDetails) -> str:
    """IPv4 when the port has one, otherwise a global IPv6 address."""
    for raw in _indexed_values(eth_dev, "IP4.ADDRESS"):
        if raw.strip():
            return raw
    for raw in _indexed_values(eth_dev, "IP6.ADDRESS"):
        if raw.strip() and not _is_link_local_ipv6(raw):
            return raw
    return "unavailable"


def _dns_servers(eth_dev: DeviceDetails) -> str:
    servers = _indexed_values(eth_dev, "IP4.DNS")
    servers.extend(
        server for server in _indexed_values(eth_dev, "IP6.DNS") if server not in servers
    )
    return ", ".join(servers) if servers else "unavailable"


def _lowest_metric(routes: list[tuple[int, str]]) -> str:
    if not routes:
        return ""
    routes.sort()
    return routes[0][1]


def ipv4_default_device(lines: list[str]) -> str:
    """Interface with the lowest-metric IPv4 default route."""
    found: list[tuple[int, str]] = []
    for line in lines:
        fields = line.split()
        if len(fields) < 7:
            continue
        iface, destination, _gateway, flags, _ref, _use, metric = fields[:7]
        if destination != "00000000" or not iface:
            continue
        try:
            flag_value = int(flags, 16)
            metric_value = int(metric)
        except ValueError:
            continue
        # RTF_UP. Skip the header and any route that is not usable.
        if flag_value & 0x1 == 0:
            continue
        found.append((metric_value, iface))
    return _lowest_metric(found)


def ipv6_default_device(lines: list[str]) -> str:
    """Interface with the lowest-metric IPv6 default route."""
    found: list[tuple[int, str]] = []
    for line in lines:
        fields = line.split()
        if len(fields) < 10:
            continue
        destination, prefix, _src, _src_prefix, _gateway, metric, _ref, _use, flags, iface = fields[:10]
        if destination != "00000000000000000000000000000000" or prefix != "00" or not iface:
            continue
        try:
            flag_value = int(flags, 16)
            metric_value = int(metric, 16)
        except ValueError:
            continue
        # Ignore down routes and the kernel's unreachable default on lo.
        if flag_value & 0x1 == 0 or flag_value & 0x200:
            continue
        found.append((metric_value, iface))
    return _lowest_metric(found)


def default_route_device() -> str:
    """Interface that currently owns the default route.

    Several wired links can be connected at once. The one with the lowest
    route metric is the link actually carrying traffic.
    """
    try:
        ipv4 = open("/proc/net/route").read().splitlines()
    except OSError:
        ipv4 = []
    device = ipv4_default_device(ipv4)
    if device:
        return device
    try:
        ipv6 = open("/proc/net/ipv6_route").read().splitlines()
    except OSError:
        ipv6 = []
    return ipv6_default_device(ipv6)


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
        self.ipaddr = _display_address(eth_dev)
        self.gateway_addr = (
            eth_dev.get("IP4.GATEWAY") or eth_dev.get("IP6.GATEWAY") or "unavailable"
        )
        self.dns = _dns_servers(eth_dev)
        self.speed = _link_speed(self.device)
        self.state = link_state(eth_dev)


_VIRTUAL_PREFIXES = ("docker", "veth", "virbr", "br-", "tun", "tap", "dummy", "vnet")


def _listed_port(dev: DeviceDetails) -> bool:
    """A physical wired port that NetworkManager is allowed to control.

    State 10 is unmanaged, so it is not a port the user can change here.
    Docker bridges and other virtual interfaces are not physical ports.
    """
    if dev.get("GENERAL.TYPE") != "ethernet":
        return False
    name = dev.get("GENERAL.DEVICE") or ""
    if not name or name.startswith(_VIRTUAL_PREFIXES):
        return False
    return _leading_code(dev.get("GENERAL.STATE")) != 10


class EthernetService:
    @staticmethod
    def get_devices() -> list[DeviceDetails]:
        """Return every physical wired port NetworkManager manages."""
        return [dev for dev in _device.show_all() if _listed_port(dev)]

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
        """True when this device can be toggled.

        An unplugged port has no carrier, so the switch stays off until a
        cable is present. A disconnected port with a cable still toggles.
        """
        return bool(details.device) and details.state not in ("unavailable", "unplugged")

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
                _device.connect(device)
            else:
                _device.disconnect(device)
            return True
        except Exception as e:
            print(f"Error toggling Ethernet: {e}")
            return False
