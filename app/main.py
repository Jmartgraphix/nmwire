#!/usr/bin/env python3
import gi
import argparse
import signal
import sys
from network_service import NetworkService
from ui.main_window import NmwireWindow
gi.require_version("Gtk", "4.0")
gi.require_version("GLibUnix", "2.0")
from gi.repository import GLib, GLibUnix, Gtk
from ui.styles import StyleManager

# Application version
__version__ = "0.1.0"

class NmwireApp(Gtk.Application):
    """Main application class"""
    
    def __init__(self):
        super().__init__(application_id="com.jmartgraphix.nmwire")
    
    def do_activate(self):
        """Application activation"""
        win = self.props.active_window
        if win is None:
            StyleManager.apply_styles()
            win = NmwireWindow(self)
        win.present()

    def do_shutdown(self):
        """Stop Ethernet monitors when the process exits without closing."""
        for window in self.get_windows():
            section = getattr(window, "ethernet_section", None)
            if section is not None:
                section._stop_monitor()
        Gtk.Application.do_shutdown(self)

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="nmwire - A GTK4 NetworkManager panel",
        prog="nmwire"
    )
    
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {__version__}"
    )
    
    return parser.parse_args()

if __name__ == "__main__":
    try:
        # Parse command line arguments first
        args = parse_arguments()
        
        # Check if NetworkManager is available before starting the app
        if not NetworkService.check_networkmanager():
            sys.exit(1)
        
        # If we get here, NetworkManager is available, so start the app
        app = NmwireApp()
        # SIGTERM skips Python's interrupt handler, so quit through GLib.
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: app.quit() or GLib.SOURCE_REMOVE)
        app.run()
    except KeyboardInterrupt:
        print("Application stopped manually.")
