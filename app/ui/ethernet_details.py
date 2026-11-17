from typing import Callable, Optional
import subprocess
import threading
import gi

from ui.utils import UIUtils
from ethernet_service import EthernetService, EthernetDetails, default_route_device

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Pango


def port_title(details: EthernetDetails) -> str:
    if not details.device:
        return "No wired ports"
    if details.name and details.name != details.device:
        return f"{details.name} ({details.device})"
    return details.device


def status_text(details: EthernetDetails, expanded: bool) -> str:
    """State for the row. A closed connected port also shows its address."""
    if not details.device:
        return ""
    label = details.state.title()
    if (
        not expanded
        and details.state == "connected"
        and details.ipaddr
        and details.ipaddr != "unavailable"
    ):
        return f"{label} · {details.ipaddr}"
    return label


class EthernetPortRow(Gtk.Box):
    """One wired port. Details stay behind the disclosure triangle."""

    def __init__(self, section: "EthernetSection", details: EthernetDetails):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.section = section
        self.device = details.device
        self.details = details
        self._syncing = False
        self._fingerprint_value = None
        self.allows_toggle = EthernetService.is_ethernet_available(details)

        self.arrow = Gtk.Image.new_from_icon_name("pan-end-symbolic")
        self.arrow.set_pixel_size(16)
        self.name_label = Gtk.Label(xalign=0, name="ethernet-name-label")
        self.name_label.set_hexpand(True)
        self.name_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.status_label = Gtk.Label(xalign=1)
        self.status_label.add_css_class("dim-label")
        self.status_label.set_margin_start(12)
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)

        self.title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.title_box.set_hexpand(True)
        self.title_box.set_name("ethernet-port-title")
        self.title_box.append(self.arrow)
        self.title_box.append(self.name_label)
        self.title_box.append(self.status_label)
        disclose = Gtk.GestureClick()
        disclose.set_button(1)
        disclose.connect("pressed", self._on_disclose)
        self.title_box.add_controller(disclose)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.append(self.title_box)
        header.append(self.switch)

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.content.set_margin_top(8)
        self.content.set_margin_start(24)
        self.content.set_margin_bottom(4)
        self.revealer = Gtk.Revealer()
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.revealer.set_child(self.content)

        self.append(header)
        self.append(self.revealer)

        self._show(details, self._switch_on(details), section.expanded_for(details))
        self.switch.connect("state-set", self._on_toggled)

    def _switch_on(self, details: EthernetDetails) -> bool:
        return details.state in ("connected", "connecting")

    def _fingerprint(self, details: EthernetDetails, expanded: bool) -> tuple:
        return (
            port_title(details),
            status_text(details, expanded),
            details.state,
            details.ipaddr,
            details.gateway_addr,
            details.dns,
            details.speed,
            details.hwaddr,
            self._switch_on(details),
            expanded,
        )

    def apply_if_changed(self, details: EthernetDetails):
        """Update this port when a background poll sees new information."""
        expanded = self.section.expanded_for(details)
        if self._fingerprint(details, expanded) == self._fingerprint_value:
            return
        self.device = details.device
        self._show(details, self._switch_on(details), expanded)

    def _on_disclose(self, *_args):
        if not self.device:
            return
        expanded = not self.revealer.get_reveal_child()
        self.section.remember_expansion(self.device, expanded)
        self._set_expanded(self.details, expanded)
        self._fingerprint_value = self._fingerprint(self.details, expanded)

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
            route_device = default_route_device()
            GLib.idle_add(self._finish_toggle, state, success, refreshed, route_device)

        thread = threading.Thread(target=toggle_thread)
        thread.daemon = True
        thread.start()
        # GTK commits the switch when this returns false. Keep the old
        # underlying state so a failed connect can move the slider back.
        return True

    def _finish_toggle(
        self,
        requested: bool,
        success: bool,
        details: Optional[EthernetDetails],
        route_device: str,
    ):
        # A failed connect or disconnect puts the slider back. The status
        # text still shows whatever NetworkManager reported for this port.
        if not success or details is None:
            switch_on = not requested
        elif requested:
            switch_on = details.state in ("connected", "connecting")
        else:
            switch_on = details.state == "connected"

        self.section.note_default_route(route_device)
        shown = details or self.details
        self._show(shown, switch_on, self.section.expanded_for(shown))
        for port in self.section.ports:
            if port is not self:
                port.apply_if_changed(port.details)
        self.section.set_busy(False)
        return False

    def _show(self, details: EthernetDetails, switch_on: bool, expanded: bool):
        self.details = details
        self.allows_toggle = EthernetService.is_ethernet_available(details)
        self.name_label.set_label(port_title(details))
        self._clear_content()
        if details.device:
            self._add_row("IP Address", details.ipaddr, "network-workgroup-symbolic")
            self._add_row("Gateway", details.gateway_addr, "network-transmit-symbolic")
            self._add_row("DNS", details.dns, "network-server-symbolic")
            self._add_row("Link Speed", details.speed, "network-wired-symbolic")
            self._add_row("MAC Address", details.hwaddr, "network-wired-symbolic")
        self._set_expanded(details, expanded)
        self._fingerprint_value = self._fingerprint(details, expanded)

        self._syncing = True
        self.switch.set_state(switch_on)
        self.switch.set_active(switch_on)
        self.switch.set_sensitive(self.allows_toggle and not self.section.busy)
        self._syncing = False

    def _set_expanded(self, details: EthernetDetails, expanded: bool):
        show_details = bool(details.device)
        self.arrow.set_visible(show_details)
        self.revealer.set_reveal_child(expanded and show_details)
        self.arrow.set_from_icon_name(
            "pan-down-symbolic" if expanded and show_details else "pan-end-symbolic"
        )
        self.status_label.set_label(status_text(details, expanded))
        if show_details:
            self.title_box.set_cursor_from_name("pointer")
        else:
            self.title_box.set_cursor(None)

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
    """Every wired port, refreshed when NetworkManager reports a change."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        self.busy = False
        self._polling = False
        self._pending_refresh = False
        self._closed = False
        self._generation = 0
        self._monitor_proc: subprocess.Popen | None = None
        self._monitor_refresh_id = 0
        self._default_device = ""
        self._expansion_choice: dict[str, bool] = {}
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
        self.connect("unrealize", self._on_unrealize)
        # The first device listing waits on nmcli, so it stays off this thread.
        self._start_fetch(manual=False)
        self._start_monitor()

    def remember_expansion(self, device: str, expanded: bool):
        """Keep a row where someone put it across refreshes."""
        if device:
            self._expansion_choice[device] = expanded

    def note_default_route(self, device: str):
        self._default_device = device

    def expanded_for(self, details: EthernetDetails) -> bool:
        """Open the default-route port until someone opens or closes a row."""
        if not details.device:
            return False
        choice = self._expansion_choice.get(details.device)
        if choice is not None:
            return choice
        return details.device == self._default_device

    def _on_unrealize(self, *_args):
        self._stop_monitor()

    def do_unroot(self):
        self._stop_monitor()
        Gtk.Box.do_unroot(self)

    def _start_monitor(self):
        """Watch NetworkManager and reload only when it reports a change."""
        try:
            self._monitor_proc = subprocess.Popen(
                ["nmcli", "monitor"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError as error:
            print(f"Error starting nmcli monitor: {error}")
            return
        threading.Thread(target=self._read_monitor, daemon=True).start()

    def _read_monitor(self):
        proc = self._monitor_proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                if self._closed:
                    break
                if line.strip():
                    GLib.idle_add(self._on_network_changed)
        except Exception as error:
            if not self._closed:
                print(f"Error reading nmcli monitor: {error}")

    def _on_network_changed(self):
        """Coalesce a burst of monitor lines into one reload."""
        if self._closed or self._monitor_refresh_id:
            return False
        self._monitor_refresh_id = GLib.timeout_add(250, self._refresh_after_change)
        return False

    def _refresh_after_change(self):
        self._monitor_refresh_id = 0
        if self._closed:
            return False
        if self.busy or self._polling:
            self._pending_refresh = True
            return False
        self._polling = True
        self._start_fetch(manual=False)
        return False

    def _run_pending_refresh(self):
        if not self._pending_refresh or self.busy or self._polling or self._closed:
            return
        self._pending_refresh = False
        self._polling = True
        self._start_fetch(manual=False)

    def _stop_monitor(self):
        """Stop nmcli monitor so closing the window does not leave it running."""
        self._closed = True
        if self._monitor_refresh_id:
            GLib.source_remove(self._monitor_refresh_id)
            self._monitor_refresh_id = 0
        proc = self._monitor_proc
        self._monitor_proc = None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    def _load_details(self) -> tuple[list[EthernetDetails], bool, str]:
        try:
            devices = EthernetService.get_devices()
            route_device = default_route_device()
        except Exception as e:
            print(f"Error listing Ethernet devices: {e}")
            return [], True, ""
        details = [EthernetDetails(device) for device in devices]
        return details or [EthernetDetails()], False, route_device

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
        if not busy:
            self._run_pending_refresh()

    def update(self):
        """Reload every wired port on a background thread."""
        if self.busy:
            return False

        self.set_busy(True)
        self._start_fetch(manual=True)
        return False

    def _start_fetch(self, manual: bool):
        self._generation += 1
        generation = self._generation
        if not manual:
            self._polling = True

        def refresh_thread():
            details, failed, route_device = self._load_details()
            GLib.idle_add(
                self._apply_fetched, details, manual, generation, failed, route_device
            )

        thread = threading.Thread(target=refresh_thread)
        thread.daemon = True
        thread.start()

    def _apply_fetched(
        self,
        details: list[EthernetDetails],
        manual: bool,
        generation: int,
        failed: bool,
        route_device: str,
    ):
        if self._closed or generation != self._generation:
            return False

        self._polling = False
        if failed or (self.busy and not manual):
            if not self.ports:
                self._rebuild([EthernetDetails()])
            if manual:
                self.set_busy(False)
            else:
                self._run_pending_refresh()
            return False

        self._default_device = route_device
        current = [port.device for port in self.ports]
        names = [item.device for item in details]
        if names != current:
            self._rebuild(details)
        else:
            for port, item in zip(self.ports, details):
                port.apply_if_changed(item)

        if manual:
            self.set_busy(False)
        else:
            self._run_pending_refresh()
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
