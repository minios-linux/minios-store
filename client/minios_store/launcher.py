"""Immediate launch feedback for the browser-based MiniOS Store."""

import argparse
import gettext
import os
import subprocess
import threading
import time
from urllib.request import Request, urlopen

APP_NAME = "minios-store"
LOCALE_DIR = "/usr/share/locale"
STORE_URL = os.environ.get("MINIOS_STORE_URL", "https://store.minios.dev")
MINIMUM_CHECK_SECONDS = 1.0

LAUNCHER_CSS = b"""
headerbar.minios-headerbar {
    min-height: 34px;
    padding-top: 0;
    padding-bottom: 0;
}

.launcher-surface {
    background-color: shade(@theme_bg_color, 0.98);
}

.launcher-card {
    padding: 12px;
}

.launcher-icon-box {
    padding: 2px;
}

.launcher-title {
    font-size: 17px;
    font-weight: 700;
}

.launcher-status {
    opacity: 0.76;
}

.launcher-error {
    color: #d33b45;
    opacity: 1;
}

.launcher-progress trough {
    min-height: 6px;
    border-radius: 3px;
}

.launcher-progress progress {
    min-height: 6px;
    border-radius: 3px;
}

.launcher-footer {
    padding-top: 8px;
}

button.launcher-button {
    min-height: 30px;
    min-width: 88px;
    padding: 0 12px;
    border-radius: 4px;
}

button.suggested-action {
    background-image: linear-gradient(to bottom, #6bb5ff, #4a90d9);
    color: #ffffff;
    border: 1px solid #1c71d8;
    box-shadow: none;
    text-shadow: none;
}

button.suggested-action:hover {
    background-image: linear-gradient(to bottom, #7fc3ff, #5ba0e9);
    color: #ffffff;
    border-color: #1a5fb4;
}

button.suggested-action:active {
    background-image: none;
    background-color: #1a5fb4;
}
"""

gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
gettext.textdomain(APP_NAME)
_ = gettext.gettext


def website_available(url=STORE_URL, timeout=4.0):
    try:
        request = Request(url, headers={"User-Agent": "MiniOS-Store-Launcher/1.0"})
        response = urlopen(request, timeout=timeout)
        response.close()
        return True
    except (OSError, ValueError):
        return False


def wait_for_minimum_check(started_at, minimum=MINIMUM_CHECK_SECONDS):
    remaining = minimum - (time.monotonic() - started_at)
    if remaining > 0:
        time.sleep(remaining)


def open_browser(url=STORE_URL):
    return subprocess.Popen(
        ["xdg-open", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def build_parser():
    parser = argparse.ArgumentParser(description=_("Launch MiniOS Store"))
    parser.add_argument("--url", default=STORE_URL, help=argparse.SUPPRESS)
    return parser


def main():
    args = build_parser().parse_args()

    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, GLib, Gtk

    provider = Gtk.CssProvider()
    provider.load_from_data(LAUNCHER_CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )

    class LauncherWindow(Gtk.Window):
        def __init__(self):
            Gtk.Window.__init__(self, title="MiniOS Store")
            self.set_default_size(400, 165)
            self.set_position(Gtk.WindowPosition.CENTER)
            self.set_resizable(False)
            self.set_keep_above(True)
            self.set_icon_name("system-software-install")
            self.connect("destroy", Gtk.main_quit)

            header = Gtk.HeaderBar(show_close_button=True)
            header.props.title = "MiniOS Store"
            header.get_style_context().add_class("minios-headerbar")
            self.set_titlebar(header)

            surface = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            surface.set_border_width(10)
            surface.get_style_context().add_class("launcher-surface")
            self.add(surface)

            card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            card.get_style_context().add_class("launcher-card")
            surface.pack_start(card, True, True, 0)

            icon_box = Gtk.EventBox()
            icon_box.get_style_context().add_class("launcher-icon-box")
            icon_box.set_valign(Gtk.Align.CENTER)
            self.icon = Gtk.Image.new_from_icon_name(
                "system-software-install", Gtk.IconSize.DIALOG
            )
            self.icon.set_pixel_size(42)
            icon_box.add(self.icon)
            card.pack_start(icon_box, False, False, 0)

            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
            content.set_valign(Gtk.Align.CENTER)
            card.pack_start(content, True, True, 0)

            title = Gtk.Label(label="MiniOS Store")
            title.set_halign(Gtk.Align.START)
            title.get_style_context().add_class("launcher-title")
            content.pack_start(title, False, False, 0)

            self.status = Gtk.Label(label=_("Starting MiniOS Store..."))
            self.status.set_halign(Gtk.Align.START)
            self.status.set_line_wrap(True)
            self.status.set_max_width_chars(36)
            self.status.get_style_context().add_class("launcher-status")
            content.pack_start(self.status, False, False, 0)

            self.progress = Gtk.ProgressBar()
            self.progress.set_pulse_step(0.16)
            self.progress.get_style_context().add_class("launcher-progress")
            content.pack_start(self.progress, False, False, 0)

            self.buttons = Gtk.ButtonBox(orientation=Gtk.Orientation.HORIZONTAL)
            self.buttons.set_layout(Gtk.ButtonBoxStyle.END)
            self.buttons.set_spacing(8)
            self.buttons.get_style_context().add_class("launcher-footer")
            surface.pack_start(self.buttons, False, False, 0)

            self.retry_button = Gtk.Button(label=_("Retry"))
            self.retry_button.connect("clicked", self._start)
            self.retry_button.get_style_context().add_class("launcher-button")
            self.retry_button.get_style_context().add_class("suggested-action")
            self.buttons.add(self.retry_button)

            close_button = Gtk.Button(label=_("Close"))
            close_button.connect("clicked", lambda _button: self.destroy())
            close_button.get_style_context().add_class("launcher-button")
            self.buttons.add(close_button)

            self.loading = False
            GLib.timeout_add(100, self._pulse)
            self.show_all()
            self.buttons.hide()
            self._start()

        def _pulse(self):
            if self.loading:
                self.progress.pulse()
            return True

        def _set_status(self, text):
            self.status.set_text(text)
            return False

        def _start(self, _button=None):
            self.buttons.hide()
            self.loading = True
            self.progress.show()
            self.icon.set_from_icon_name("system-software-install", Gtk.IconSize.DIALOG)
            self.icon.set_pixel_size(42)
            self.status.get_style_context().remove_class("launcher-error")
            self._set_status(_("Connecting to MiniOS Store..."))
            threading.Thread(
                target=self._launch,
                args=(time.monotonic(),),
                daemon=True,
            ).start()

        def _launch(self, started_at):
            GLib.idle_add(self._set_status, _("Connecting to MiniOS Store..."))
            if not website_available(args.url):
                wait_for_minimum_check(started_at)
                GLib.idle_add(
                    self._show_error,
                    _("MiniOS Store is unavailable. Check your network connection."),
                )
                return

            wait_for_minimum_check(started_at)
            GLib.idle_add(self._set_status, _("Opening the browser..."))
            try:
                open_browser(args.url)
            except OSError:
                GLib.idle_add(self._show_error, _("Could not open the default browser."))
                return
            GLib.timeout_add_seconds(2, self._finish)

        def _show_error(self, message):
            self.loading = False
            self.progress.hide()
            self.icon.set_from_icon_name("dialog-error", Gtk.IconSize.DIALOG)
            self.icon.set_pixel_size(42)
            self.status.get_style_context().add_class("launcher-error")
            self._set_status(message)
            self.buttons.show_all()
            return False

        def _finish(self):
            self.destroy()
            return False

    window = LauncherWindow()
    Gtk.main()
    return window


if __name__ == "__main__":
    main()
