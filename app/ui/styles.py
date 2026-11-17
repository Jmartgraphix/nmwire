"""CSS styling for the application"""

import os
import gi


def user_style_path(home_path):
    """Path to a user style sheet, if one exists.

    ``~/.config/nmwire/style.css`` wins. The old ``nmgui`` folder is
    still read when the new file is absent.
    """
    for folder in ("nmwire", "nmgui"):
        path = os.path.join(home_path, ".config", folder, "style.css")
        if os.path.isfile(path):
            return path
    return None


gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk

class StyleManager:
    """Handles CSS styling for the application"""
    
    CSS_STYLES = b"""
    #wifi-label, #ethernet-label {
        font-weight: bold;
        font-size: 16px;
    } 

    #wifi-networks-label, #ethernet-name-label {
        font-weight: bold;
        font-size: 14px;
    }

    /* Follow the desktop selection colour instead of a fixed blue. */
    #ethernet-port-title:hover #ethernet-name-label {
        color: @theme_selected_bg_color;
    }

    #wifi-scan-label, #ethernet-scan-label {
        font-size: 14px;
    }

    #wifi-scan-label:hover,
    #ethernet-scan-label:hover {
        color: @theme_selected_bg_color;
    }
    
    #scanning-label {
        font-style: italic;
        color: #888888;
        margin: 10px;
    }
    
    #error-label {
        color: #cc0000;
        margin: 10px;
    }
    
    #no-networks-label {
        font-style: italic;
        color: #888888;
        margin: 10px;
    }

    #network-list-box {
        padding: 5px 0;
    }

    .connected-network {
        background-color: alpha(@theme_selected_bg_color, 0.12);
    }
    
    #wifi-off-box {
        margin: 50px;
    }
    
    #wifi-off-label {
        color: #666666;
        font-size: 14px;
    }
    
    .rescan-in-progress {
        color: @theme_selected_bg_color;
        animation: pulse 1.5s infinite;
    }
    
    @keyframes pulse {
        0% { opacity: 1; }
        50% { opacity: 0.5; }
        100% { opacity: 1; }
    }

    .title-2 {
        font-size: 1.5rem;
        font-weight: 500;
    }
    
    .title-4 {
        font-size: 1.1rem;
        font-weight: 500;
        margin-bottom: 8px;
    }
    
    .dim-label {
        opacity: 0.7;
        font-size: 0.9rem;
    }
    
    scrollbar slider {
        min-width: 6px;
        min-height: 6px;
    }
    """
    
    @classmethod
    def apply_styles(cls):
        """Apply CSS styles to the application"""
        css_provider = Gtk.CssProvider()

        style_path = user_style_path(os.path.expanduser("~"))
        if style_path:
            css_provider.load_from_path(style_path)
        else:
            css_provider.load_from_data(cls.CSS_STYLES)
        
        display = Gdk.Display.get_default()
        Gtk.StyleContext.add_provider_for_display(
            display, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
