"""Immediate launch feedback for the browser-based MiniOS Store."""

import argparse
import gettext
import os
import subprocess
import time
from urllib.request import Request, urlopen

APP_NAME = "minios-store"
LOCALE_DIR = "/usr/share/locale"
STORE_URL = os.environ.get("MINIOS_STORE_URL", "https://store.minios.dev")
MINIMUM_CHECK_SECONDS = 1.0
LAUNCHER_CSS_PATH = "/usr/share/minios-store/launcher.css"
LAUNCH_OPENED = "opened"
LAUNCH_UNAVAILABLE = "unavailable"
LAUNCH_BROWSER_ERROR = "browser-error"

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


def load_gtk3():
    import gi
    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, GLib, Gtk
    return Gdk, GLib, Gtk


def load_minios_gui():
    from minios_gui import (
        BackgroundTask, OperationView, apply_minios_css, new_header_bar,
        new_icon,
    )
    return (
        BackgroundTask, OperationView, apply_minios_css, new_header_bar,
        new_icon,
    )


def main():
    args = build_parser().parse_args()
    _Gdk, GLib, Gtk = load_gtk3()
    (BackgroundTask, OperationView, apply_minios_css, new_header_bar,
     new_icon) = load_minios_gui()
    apply_minios_css(LAUNCHER_CSS_PATH)

    class LauncherWindow(Gtk.Window):
        def __init__(self):
            Gtk.Window.__init__(self, title=_("MiniOS Store"))
            self.set_default_size(400, 165)
            self.set_position(Gtk.WindowPosition.CENTER)
            self.set_resizable(False)
            self.set_keep_above(True)
            self.set_icon_name("system-software-install")
            self._destroyed = False
            self._pulse_source_id = None
            self._finish_source_id = None
            self.connect("destroy", self._on_destroy)
            self.connect("destroy", Gtk.main_quit)

            self.set_titlebar(new_header_bar(_("MiniOS Store")))

            surface = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            surface.set_border_width(10)
            self.add(surface)

            card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            card.get_style_context().add_class("launcher-card")
            surface.pack_start(card, True, True, 0)

            icon_box = Gtk.EventBox()
            icon_box.get_style_context().add_class("launcher-icon-box")
            icon_box.set_valign(Gtk.Align.CENTER)
            self.icon = new_icon(
                "system-software-install", Gtk.IconSize.DIALOG,
                accessible_name=_("MiniOS Store"),
            )
            self.icon.set_pixel_size(42)
            icon_box.add(self.icon)
            card.pack_start(icon_box, False, False, 0)

            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
            content.set_valign(Gtk.Align.CENTER)
            card.pack_start(content, True, True, 0)

            title = Gtk.Label(label=_("MiniOS Store"))
            title.set_halign(Gtk.Align.START)
            title.get_style_context().add_class("launcher-title")
            content.pack_start(title, False, False, 0)

            self.operation_view = OperationView(
                status=_("Starting MiniOS Store..."),
                show_log=False,
                cancellable=False,
            )
            self.operation_view.status_label.set_max_width_chars(36)
            self.operation_view.status_label.get_style_context().add_class(
                "dim-label"
            )
            self.operation_view.progress_bar.set_pulse_step(0.16)
            content.pack_start(self.operation_view, False, False, 0)

            self.buttons = Gtk.ButtonBox(orientation=Gtk.Orientation.HORIZONTAL)
            self.buttons.set_layout(Gtk.ButtonBoxStyle.END)
            self.buttons.set_spacing(8)
            self.buttons.get_style_context().add_class("launcher-footer")
            surface.pack_start(self.buttons, False, False, 0)

            self.retry_button = Gtk.Button(label=_("Retry"))
            self.retry_button.connect("clicked", self._start)
            self.retry_button.get_style_context().add_class("suggested-action")
            self.buttons.add(self.retry_button)

            close_button = Gtk.Button(label=_("Close"))
            close_button.connect("clicked", lambda _button: self.destroy())
            self.buttons.add(close_button)

            self.loading = False
            self.task = None
            self._pulse_source_id = GLib.timeout_add(100, self._pulse)
            self.show_all()
            self.buttons.hide()
            self._start()

        def _pulse(self):
            if self._destroyed:
                return False
            if self.loading:
                self.operation_view.progress_bar.pulse()
            return True

        def _set_status(self, text):
            if self._destroyed:
                return False
            self.operation_view.set_status(text)
            return False

        def _start(self, _button=None):
            if self._destroyed:
                return
            self.buttons.hide()
            self.loading = True
            self.operation_view.set_progress(0.0)
            self.operation_view.set_state("running")
            self.icon.set_from_icon_name("system-software-install", Gtk.IconSize.DIALOG)
            self.icon.set_pixel_size(42)
            context = self.operation_view.status_label.get_style_context()
            context.remove_class("inline-error")
            context.add_class("dim-label")
            self._set_status(_("Connecting to MiniOS Store..."))
            started_at = time.monotonic()
            self.task = BackgroundTask(
                lambda token: self._launch(token, started_at),
                finished_callback=self._on_launch_finished,
                owner=self,
            ).start()

        def _launch(self, token, started_at):
            if not website_available(args.url):
                wait_for_minimum_check(started_at)
                token.raise_if_cancelled()
                return LAUNCH_UNAVAILABLE

            wait_for_minimum_check(started_at)
            token.raise_if_cancelled()
            try:
                open_browser(args.url)
            except OSError:
                return LAUNCH_BROWSER_ERROR
            return LAUNCH_OPENED

        def _on_launch_finished(self, outcome):
            self.task = None
            if self._destroyed or outcome.cancelled:
                return
            if outcome.error is not None:
                self._show_error(str(outcome.error))
            elif outcome.value == LAUNCH_UNAVAILABLE:
                self._show_error(
                    _("MiniOS Store is unavailable. Check your network connection.")
                )
            elif outcome.value == LAUNCH_BROWSER_ERROR:
                self._show_error(_("Could not open the default browser."))
            else:
                self._set_status(_("Opening the browser..."))
                self._finish_source_id = GLib.timeout_add_seconds(2, self._finish)

        def _show_error(self, message):
            if self._destroyed:
                return False
            self.loading = False
            self.operation_view.set_progress(None)
            self.icon.set_from_icon_name("dialog-error", Gtk.IconSize.DIALOG)
            self.icon.set_pixel_size(42)
            context = self.operation_view.status_label.get_style_context()
            context.remove_class("dim-label")
            context.add_class("inline-error")
            self.operation_view.set_state("error", message)
            self.buttons.show_all()
            return False

        def _finish(self):
            self._finish_source_id = None
            if not self._destroyed:
                self.destroy()
            return False

        def _on_destroy(self, *_args):
            if self._destroyed:
                return
            self._destroyed = True
            self.loading = False
            if self.task is not None:
                self.task.cancel()
                self.task = None
            for source_attr in ("_pulse_source_id", "_finish_source_id"):
                source_id = getattr(self, source_attr)
                if source_id is not None:
                    GLib.source_remove(source_id)
                    setattr(self, source_attr, None)

    window = LauncherWindow()
    Gtk.main()
    return window


if __name__ == "__main__":
    main()
