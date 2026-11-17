import time
import threading
from dataclasses import replace
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Pango
from typing import List, Callable

from models import NetworkGroup, NetworkInfo, group_networks
from network_service import NetworkService

class NetworkListWidget(Gtk.Box):
    """Widget for displaying network list with visual rescan feedback"""
    
    def __init__(self, on_network_selected: Callable, on_network_details: Callable):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.on_network_selected = on_network_selected
        self.on_network_details = on_network_details
        self.is_scanning = False
        self.scan_start_time = None

        self._create_header()
        self._create_network_list()
    
    def _create_header(self):
        """Create the header with refresh button and spinner"""
        self.scan_label = Gtk.Label(label="Refresh", name="wifi-scan-label")
        self.scan_label.set_cursor_from_name("pointer")
        self.scan_label.add_controller(self._create_click_controller(self._on_refresh_clicked))
        
        self.spinner = Gtk.Spinner()
        self.spinner.set_size_request(20, 20)
        
        networks_label = Gtk.Label(label="Wi-Fi Networks", xalign=0, name="wifi-networks-label")
        
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header_box.append(networks_label)
        header_box.append(Gtk.Box(hexpand=True))  # Spacer
        header_box.append(self.spinner)
        header_box.append(self.scan_label)
        
        self.append(header_box)
    
    def _create_network_list(self):
        """Create the network list. The window scrolls this with the rest of the page."""
        self.network_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.network_list_box.set_name("network-list-box")
        self.append(self.network_list_box)
    
    def _create_click_controller(self, callback: Callable):
        """Create a click controller for a label"""
        controller = Gtk.GestureClick()
        controller.set_button(0)
        controller.connect("pressed", lambda *args: callback())
        return controller
    
    def _on_refresh_clicked(self):
        """Handle refresh button click with visual feedback"""
        if not self.is_scanning:
            self.start_scan(rescan=True)
    
    def start_scan(self, rescan: bool = False):
        """List networks. Only an explicit refresh asks NetworkManager to scan."""
        if self.is_scanning:
            return
        
        self.is_scanning = True
        self.scan_start_time = time.time()
        
        # Update UI for scanning state
        self.spinner.start()
        self.scan_label.set_sensitive(False)
        self.scan_label.add_css_class("rescan-in-progress")
        
        # Clear existing networks
        self._clear_network_list()
        
        # Show scanning message
        scanning_label = Gtk.Label(
            label="Scanning for networks..." if rescan else "Loading networks..."
        )
        scanning_label.set_margin_top(64)
        scanning_label.set_name("scanning-label")
        self.network_list_box.append(scanning_label)
        
        # Start background scan
        thread = threading.Thread(target=self._background_scan, args=(rescan,))
        thread.daemon = True
        thread.start()
    
    def _background_scan(self, rescan: bool):
        """Background network scanning"""
        try:
            networks, scan_allowed = NetworkService.scan_networks(rescan=rescan)
            scan_duration = time.time() - self.scan_start_time if self.scan_start_time else 0
            
            GLib.idle_add(self._update_network_list, networks, scan_duration, scan_allowed)
            
        except Exception as e:
            print(f"Error during background scan: {e}")
            GLib.idle_add(self._show_scan_error)
        finally:
            GLib.idle_add(self._scan_complete)
    
    def _update_network_list(self, networks: List[NetworkInfo], scan_duration: float, scan_allowed: bool = True):
        """Update the network list UI with scan results"""
        self._clear_network_list()
        
        if not networks:
            no_networks_label = Gtk.Label(label="No networks found", xalign=0.5)
            no_networks_label.set_name("no-networks-label")
            self.network_list_box.append(no_networks_label)
        else:
            for group in group_networks(networks):
                self.network_list_box.append(self._create_group_row(group))
        if not scan_allowed:
            note = Gtk.Label(label="Showing recent networks (scan not permitted)", xalign=0.5)
            note.add_css_class("dim-label")
            note.set_name("scanning-label")
            self.network_list_box.append(note)
        
        return False

    def _create_group_row(self, group: NetworkGroup) -> Gtk.Box:
        """One row per SSID. Connected rows show the link in use."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        shown = replace(group.display_node, is_connected=group.is_connected)
        network_button = self._create_network_button(shown)
        network_button.set_hexpand(True)
        row.append(network_button)
        row.append(self._create_details_button(group.display_node))
        return row

    def _create_details_button(self, network: NetworkInfo) -> Gtk.Button:
        more_button = Gtk.Button()
        more_button.set_icon_name("go-next-symbolic")
        more_button.set_tooltip_text("More Details")
        more_button.set_css_classes(["more-details-button"])
        more_button.connect("clicked", lambda _button, chosen=network: self.on_network_details(chosen))
        return more_button
    
    def _create_network_button(self, network: NetworkInfo) -> Gtk.Button:
        """Create a button for a network"""
        network_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        network_box.set_margin_top(2)
        network_box.set_margin_bottom(2)

        # Signal strength
        signal_icon = self._get_signal_icon(network.signal)
        network_box.append(signal_icon)

        # Network name
        network_label = Gtk.Label(label=network.ssid, xalign=0, hexpand=True)
        network_label.set_ellipsize(Pango.EllipsizeMode.END)
        network_label.set_name("network-ssid")
        network_box.append(network_label)

        strength = Gtk.Label(label=f"{network.signal}%")
        strength.add_css_class("dim-label")
        strength.set_name("network-signal")
        network_box.append(strength)

        # Connected indicator
        if network.is_connected:
            check_icon = Gtk.Image.new_from_icon_name("object-select-symbolic")
            check_icon.set_pixel_size(16)
            check_icon.set_margin_start(5)
            check_icon.set_name("connected-icon")
            network_box.append(check_icon)
        
        # Security indicator
        if network.requires_password:
            lock_icon = Gtk.Image.new_from_icon_name("system-lock-screen-symbolic")
            lock_icon.set_pixel_size(16)
            network_box.append(lock_icon)

        # Create button
        button = Gtk.Button()
        button.set_name("network-button")
        button.set_child(network_box) 

        if network.is_connected:
            button.set_sensitive(False)
            button.add_css_class("connected-network")
        else:
            button.connect("clicked", lambda b, n=network: self.on_network_selected(n))
        
        return button

    def _get_signal_icon(self, signal: int) -> Gtk.Image:
        """Get signal strength icon based on signal level"""
        if signal < 20:
            icon_name = "network-wireless-signal-weak-symbolic"
        elif signal < 40:
            icon_name = "network-wireless-signal-ok-symbolic"
        elif signal < 60:
            icon_name = "network-wireless-signal-good-symbolic"
        else:
            icon_name = "network-wireless-signal-excellent-symbolic"
        
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(16)
        return icon
    
    def _show_scan_error(self):
        """Show scan error message"""
        self._clear_network_list()
        error_label = Gtk.Label(label="Error scanning networks. Try again.", xalign=0.5)
        error_label.set_name("error-label")
        self.network_list_box.append(error_label)
        return False
    
    def _scan_complete(self):
        """Clean up after scan completes"""
        self.spinner.stop()
        self.scan_label.set_sensitive(True)
        self.scan_label.remove_css_class("rescan-in-progress")
        self.is_scanning = False
        
        return False
    
    def _clear_network_list(self):
        """Clear all networks from the list"""
        child = self.network_list_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.network_list_box.remove(child)
            child = next_child
