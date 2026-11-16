from typing import Callable, Optional
import threading
import gi

from ui.utils import UIUtils
from ethernet_service import EthernetService, EthernetDetails

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib


def port_title(details: EthernetDetails) -> str:
    if not details.device:
        return "Not Connected"
    if details.name and details.name != details.device:
        return f"{details.name} ({details.device})"
    return details.device


class EthernetPortRow(Gtk.Box):
    """Switch and details for a single wired port."""

    def __init__(self, section: "EthernetSection", details: EthernetDetails):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        self.section = section
        self.device = details.device
        self.details = details
        self._syncing = False
        self._fingerprint_value = None
        self.allows_toggle = EthernetService.is_ethernet_available(details)

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.name_label = Gtk.Label(xalign=0, name="ethernet-name-label")
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.append(self.name_label)
        header.append(Gtk.Box(hexpand=True))
        header.append(self.switch)
        self.append(header)
        self.append(self.content)

        self._show(details, self._switch_on(details))
        self.switch.connect("state-set", self._on_toggled)

    def _switch_on(self, details: EthernetDetails) -> bool:
        return details.state in ("connected", "connecting")

    def _fingerprint(self, details: EthernetDetails) -> tuple:
        return (
            port_title(details),
            details.state,
            details.ipaddr,
            details.gateway_addr,
            details.dns,
            details.speed,
            details.hwaddr,
            self._switch_on(details),
        )

    def apply_if_changed(self, details: EthernetDetails):
        """Update this port when a background poll sees new information."""
        if self._fingerprint(details) == self._fingerprint_value:
            return
        self.device = details.device
        self._show(details, self._switch_on(details))

    def _on_toggled(self, switch, state):
        """Start the link change without committing the switch yet."""
        if self._syncing:
            return True

        self.section.set_busy(True)

        def toggle_thread():
            success = EthernetService.toggle_ethernet(state, self.device)
            refreshed = None
            try:
                device = EthernetService.get_device_details(self.device)
                if device != None:
                    refreshed = EthernetDetails(device)
            except Exception as e:
                print(f"Error reading Ethernet device {self.device}: {e}")
            GLib.idle_add(self._finish_toggle, state, success, refreshed)

        thread = threading.Thread(target=toggle_thread)
        thread.daemon = True
        thread.start()
        # GTK commits the switch when this returns false. Keep the old
        # underlying state so a failed connect can move the slider back.
        return True

    def _finish_toggle(self, requested: bool, success: bool, details: Optional[EthernetDetails]):
        # A failed connect or disconnect puts the slider back. The status
        # text still shows whatever NetworkManager reported for this port.
        if not success or details is None:
            switch_on = not requested
        elif requested:
            switch_on = details.state in ("connected", "connecting")
        else:
            switch_on = details.state == "connected"

        self._show(details or self.details, switch_on)
        self.section.set_busy(False)
        return False

    def _show(self, details: EthernetDetails, switch_on: bool):
        self.details = details
        self.allows_toggle = EthernetService.is_ethernet_available(details)
        self.name_label.set_label(port_title(details))
        self._clear_content()
        if details.device:
            self._add_row(
                "Network Status",
                details.state.title(),
                "network-transmit-receive-symbolic",
            )
            self._add_row("IP Address", details.ipaddr, "network-workgroup-symbolic")
            self._add_row("Gateway", details.gateway_addr, "network-transmit-symbolic")
            self._add_row("DNS", details.dns, "network-server-symbolic")
            self._add_row("Link Speed", details.speed, "network-wired-symbolic")
            self._add_row("MAC Address", details.hwaddr, "network-wired-symbolic")
        self._fingerprint_value = self._fingerprint(details)

        self._syncing = True
        self.switch.set_state(switch_on)
        self.switch.set_active(switch_on)
        self.switch.set_sensitive(self.allows_toggle and not self.section.busy)
        self._syncing = False

    def _add_row(self, label: str, value: str, icon_name: str):
        self.content.append(
            UIUtils.create_detail_row(label, value or "unavailable", icon_name)
        )

    def _clear_content(self):
        child = self.content.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.content.remove(child)
            child = next_child


class EthernetSection(Gtk.Box):
    """Every wired port, refreshed in the background."""

    POLL_INTERVAL_SECONDS = 1

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        self.busy = False
        self._polling = False
        self._generation = 0
        self._poll_id = 0
        self.ports: list[EthernetPortRow] = []
        self.ports_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        self.spinner = Gtk.Spinner()
        self.spinner.set_size_request(20, 20)
        self.refresh_label = Gtk.Label(label="Refresh", name="ethernet-scan-label")
        self.refresh_label.set_cursor_from_name("pointer")
        self.refresh_label.add_controller(self._click(self.update))

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.append(Gtk.Label(label="Ethernet", xalign=0, name="ethernet-label"))
        header.append(Gtk.Box(hexpand=True))
        header.append(self.spinner)
        header.append(self.refresh_label)

        self.append(header)
        self.append(self.ports_box)
        details, _failed = self._load_details()
        self._rebuild(details or [EthernetDetails()])
        self._poll_id = GLib.timeout_add_seconds(self.POLL_INTERVAL_SECONDS, self._poll)

    def do_unroot(self):
        if self._poll_id:
            GLib.source_remove(self._poll_id)
            self._poll_id = 0
        Gtk.Box.do_unroot(self)

    def _load_details(self) -> tuple[list[EthernetDetails], bool]:
        try:
            devices = EthernetService.get_devices()
        except Exception as e:
            print(f"Error listing Ethernet devices: {e}")
            return [], True
        details = [EthernetDetails(device) for device in devices]
        return details or [EthernetDetails()], False

    def _click(self, callback: Callable):
        controller = Gtk.GestureClick()
        controller.set_button(0)
        controller.connect("pressed", lambda *args: callback())
        return controller

    def set_busy(self, busy: bool):
        self.busy = busy
        self.refresh_label.set_sensitive(not busy)
        if busy:
            self.spinner.start()
            self.refresh_label.add_css_class("rescan-in-progress")
        else:
            self.spinner.stop()
            self.refresh_label.remove_css_class("rescan-in-progress")

        for port in self.ports:
            port.switch.set_sensitive(port.allows_toggle and not busy)

    def update(self):
        """Reload every wired port on a background thread."""
        if self.busy:
            return False

        self.set_busy(True)
        self._start_fetch(manual=True)
        return False

    def _poll(self):
        """Pick up link, address, DNS, and speed changes without Refresh."""
        if self._poll_id == 0:
            return False
        if not self.busy and not self._polling:
            self._polling = True
            self._start_fetch(manual=False)
        return True

    def _start_fetch(self, manual: bool):
        self._generation += 1
        generation = self._generation

        def refresh_thread():
            details, failed = self._load_details()
            GLib.idle_add(self._apply_fetched, details, manual, generation, failed)

        thread = threading.Thread(target=refresh_thread)
        thread.daemon = True
        thread.start()

    def _apply_fetched(
        self,
        details: list[EthernetDetails],
        manual: bool,
        generation: int,
        failed: bool,
    ):
        if generation != self._generation:
            return False

        self._polling = False
        if failed or (self.busy and not manual):
            if manual:
                self.set_busy(False)
            return False

        current = [port.device for port in self.ports]
        names = [item.device for item in details]
        if names != current:
            self._rebuild(details)
        else:
            for port, item in zip(self.ports, details):
                port.apply_if_changed(item)

        if manual:
            self.set_busy(False)
        return False

    def _rebuild(self, details: list[EthernetDetails]):
        child = self.ports_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.ports_box.remove(child)
            child = next_child

        self.ports = []
        for item in details:
            row = EthernetPortRow(self, item)
            self.ports.append(row)
            self.ports_box.append(row)
        return False
