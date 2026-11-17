#!/usr/bin/env python3
import gi
import argparse
import sys
from network_service import NetworkService
from ui.main_window import NmwireWindow
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
from ui.styles import StyleManager

# Application version
__version__ = "0.1.0"

class NmwireApp(Gtk.Application):
    """Main application class"""
    
    def __init__(self):
        super().__init__(application_id="com.jmartgraphix.nmwire")
    
    def do_activate(self):
        """Application activation"""
        StyleManager.apply_styles()
        win = self.props.active_window or NmwireWindow(self)
        win.present()

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
        app.run()
    except KeyboardInterrupt:
        print("Application stopped manually.")
    except SystemExit:
        # argparse calls sys.exit() for version/help, let it pass through
        pass
