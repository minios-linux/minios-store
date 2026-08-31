"""
MiniOS Store GTK3 GUI Installer.

Standalone graphical installer that handles minios-store:// URIs.
Works without the WebSocket daemon.

Usage (via thin launcher bin/minios-store-install):
    minios-store-install "minios-store://install?mode=module&recipes=vlc:auto:zstd&packaging=single"
    minios-store-install --mode module --packaging single --recipes vlc:auto:zstd
"""

import sys
import os
import gettext
import signal
import threading
import argparse
import asyncio

# Internationalization
APP_NAME = "minios-store"
LOCALE_DIR = "/usr/share/locale"
gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
gettext.textdomain(APP_NAME)
_ = gettext.gettext

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib, Pango, Gdk
except (ImportError, ValueError):
    print(_("Error: GTK3 (python3-gi, gir1.2-gtk-3.0) is required"),
          file=sys.stderr)
    sys.exit(1)

from urllib.parse import urlparse, parse_qs

from minios_store.config import get_writable_modules_dir, is_native_system
from minios_store.installer import Installer

# ---------------------------------------------------------------------------
# URI / CLI argument parsing
# ---------------------------------------------------------------------------

def parse_uri(uri):
    """Parse minios-store:// URI and extract parameters.

    Returns dict with keys: recipes, mode, packaging, module_name.
    """
    parsed = urlparse(uri)

    if parsed.scheme != "minios-store":
        raise ValueError(
            _("Invalid scheme: %s (expected minios-store)") % parsed.scheme
        )

    action = parsed.netloc or parsed.path.lstrip("/")
    if action != "install":
        raise ValueError(
            _("Invalid action: %s (expected 'install')") % action
        )

    params = parse_qs(parsed.query)

    recipes_param = params.get("recipes", [""])[0]
    if not recipes_param:
        raise ValueError(_("Missing 'recipes' parameter"))

    recipes = []
    for part in recipes_param.split(","):
        tokens = part.split(":")
        if len(tokens) != 3:
            raise ValueError(_("Invalid recipe format: %s") % part)
        rid, level, compression = tokens
        recipes.append({
            "id": rid,
            "name": rid,
            "method": "apt",
            "level": level,
            "compression": compression,
            "packages": [rid],
        })

    return {
        "recipes": recipes,
        "mode": params.get("mode", ["module"])[0],
        "packaging": params.get("packaging", ["single"])[0],
        "module_name": params.get("moduleName", [""])[0],
    }


def build_cli_parser():
    """Build argparse parser for CLI arguments."""
    parser = argparse.ArgumentParser(description=_("MiniOS Store Installer"))
    parser.add_argument("uri", nargs="?",
                        help=_("minios-store:// URI"))
    parser.add_argument("--mode", choices=["module", "system"],
                        default="module")
    parser.add_argument("--packaging", choices=["single", "separate"],
                        default="single")
    parser.add_argument("--recipes",
                        help=_("Comma-separated id:level:compression"))
    parser.add_argument("--module-name", default="")
    return parser


def resolve_params(args):
    """Return (recipes, mode, packaging, module_name) from parsed args."""
    if args.uri and args.uri.startswith("minios-store://"):
        p = parse_uri(args.uri)
        return p["recipes"], p["mode"], p["packaging"], p["module_name"]
    if args.recipes:
        recipes = []
        for part in args.recipes.split(","):
            tokens = part.strip().split(":")
            if len(tokens) != 3:
                raise ValueError(_("Invalid recipe: %s") % part)
            rid, level, compression = tokens
            recipes.append({
                "id": rid,
                "name": rid,
                "method": "apt",
                "level": level,
                "compression": compression,
                "packages": [rid],
            })
        return recipes, args.mode, args.packaging, args.module_name or ""
    return None, None, None, None


# ---------------------------------------------------------------------------
# GTK3 Installer window
# ---------------------------------------------------------------------------

class InstallerWindow(Gtk.Window):

    def __init__(self, recipes, mode, packaging, module_name):
        Gtk.Window.__init__(self, title=_("MiniOS Store"))
        self.set_default_size(520, -1)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_resizable(False)
        self.set_icon_name("system-software-install")

        self.recipes = recipes
        self.mode = mode
        self.packaging = packaging
        self.module_name = module_name
        self.installer = None
        self.install_thread = None
        self.finished = False

        self._build_ui()

        # Determine modules directory
        self.modules_dir, self.is_fallback = get_writable_modules_dir()

    # -- UI -----------------------------------------------------------------

    def _build_ui(self):
        # HeaderBar (like minios-installer)
        header_bar = Gtk.HeaderBar(show_close_button=True)
        header_bar.props.title = _("MiniOS Store")
        self.set_titlebar(header_bar)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(vbox)

        # Info area: icon + title + subtitle (inside window body)
        info_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=12
        )
        info_box.set_margin_start(16)
        info_box.set_margin_end(16)
        info_box.set_margin_top(16)
        info_box.set_margin_bottom(8)

        icon = Gtk.Image.new_from_icon_name(
            "system-software-install", Gtk.IconSize.DIALOG
        )
        info_box.pack_start(icon, False, False, 0)

        title_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=2
        )
        title_label = Gtk.Label()
        title_label.set_markup(
            "<b><big>%s</big></b>" % GLib.markup_escape_text(_("MiniOS Store"))
        )
        title_label.set_halign(Gtk.Align.START)
        title_box.pack_start(title_label, False, False, 0)

        subtitle = Gtk.Label()
        recipe_names = ", ".join(r["id"] for r in self.recipes)
        subtitle.set_markup(
            "<small>%s: %s</small>" % (
                self._mode_label(),
                GLib.markup_escape_text(recipe_names),
            )
        )
        subtitle.set_halign(Gtk.Align.START)
        subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        title_box.pack_start(subtitle, False, False, 0)
        info_box.pack_start(title_box, True, True, 0)
        vbox.pack_start(info_box, False, False, 0)

        # Progress area
        progress_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8
        )
        progress_box.set_margin_start(16)
        progress_box.set_margin_end(16)
        progress_box.set_margin_top(12)

        self.status_label = Gtk.Label(label=_("Preparing..."))
        self.status_label.set_halign(Gtk.Align.START)
        self.status_label.set_ellipsize(Pango.EllipsizeMode.END)
        progress_box.pack_start(self.status_label, False, False, 0)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(False)
        progress_box.pack_start(self.progress_bar, False, False, 0)

        vbox.pack_start(progress_box, False, False, 0)

        # Log toggle button
        self.log_toggle = Gtk.ToggleButton(
            label="\u25b6 %s" % _("Installation Log")
        )
        self.log_toggle.set_relief(Gtk.ReliefStyle.NONE)
        self.log_toggle.set_halign(Gtk.Align.START)
        self.log_toggle.set_margin_start(16)
        self.log_toggle.set_margin_top(8)
        self.log_toggle.connect("toggled", self._on_log_toggled)
        vbox.pack_start(self.log_toggle, False, False, 0)

        # Log scrolled window (hidden initially)
        self.log_sw = Gtk.ScrolledWindow()
        self.log_sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.log_sw.set_size_request(-1, 200)
        self.log_sw.set_margin_start(16)
        self.log_sw.set_margin_end(16)
        self.log_sw.set_margin_bottom(8)

        self.log_buffer = Gtk.TextBuffer()
        self.log_view = Gtk.TextView(buffer=self.log_buffer)
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.log_view.set_monospace(True)

        # Create tags for coloring
        self.log_buffer.create_tag("info", foreground="#4a9eff")
        self.log_buffer.create_tag("error", foreground="#ff4444")
        self.log_buffer.create_tag("success", foreground="#44bb44")
        self.log_buffer.create_tag("warning", foreground="#ffaa00")
        self.log_buffer.create_tag("output", foreground="#999999")

        self.log_sw.add(self.log_view)
        vbox.pack_start(self.log_sw, False, False, 0)

        # Bottom buttons
        self.button_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8
        )
        self.button_box.set_margin_start(16)
        self.button_box.set_margin_end(16)
        self.button_box.set_margin_bottom(16)
        self.button_box.set_margin_top(4)

        # Left: Cancel Installation (shown during install)
        self.cancel_btn = Gtk.Button(label=_("Cancel Installation"))
        self.cancel_btn.get_style_context().add_class("destructive-action")
        self.cancel_btn.connect("clicked", self._on_cancel)
        self.button_box.pack_start(self.cancel_btn, False, False, 0)

        # Spacer
        self.button_box.pack_start(Gtk.Box(), True, True, 0)

        # Right: Open Folder button (hidden initially)
        self.open_folder_btn = Gtk.Button(label=_("Open Folder"))
        self.open_folder_btn.set_no_show_all(True)
        self.open_folder_btn.connect("clicked", self._on_open_folder)
        self.button_box.pack_start(self.open_folder_btn, False, False, 6)

        # Right: Done button (hidden initially, shown after completion) - rightmost
        self.done_btn = Gtk.Button(label=_("Done"))
        self.done_btn.get_style_context().add_class("suggested-action")
        self.done_btn.set_no_show_all(True)
        self.done_btn.connect("clicked", self._on_done)
        self.button_box.pack_start(self.done_btn, False, False, 0)

        vbox.pack_start(self.button_box, False, False, 0)

        self.connect("delete-event", self._on_delete)

    def _mode_label(self):
        if self.mode == "system":
            return _("System install")
        if self.packaging == "separate":
            return _("Separate modules")
        return _("Single module")

    # -- Logging ------------------------------------------------------------

    def _log(self, text, tag=None):
        """Append text to log view (must be called from main thread)."""
        end = self.log_buffer.get_end_iter()
        if tag:
            self.log_buffer.insert_with_tags_by_name(
                end, text + "\n", tag
            )
        else:
            self.log_buffer.insert(end, text + "\n")
        # Auto-scroll
        end_mark = self.log_buffer.create_mark(
            None, self.log_buffer.get_end_iter(), False
        )
        self.log_view.scroll_to_mark(end_mark, 0.0, False, 0.0, 0.0)
        self.log_buffer.delete_mark(end_mark)

    def _log_threadsafe(self, text, tag=None):
        GLib.idle_add(self._log, text, tag)

    # -- Installation -------------------------------------------------------

    def _on_install(self, _btn):
        self.finished = False

        self._log(_("Starting installation..."), "info")
        self._log(
            _("Mode: %s | Packaging: %s") % (self.mode, self.packaging),
            "info",
        )
        self._log(
            _("Packages: %s") % ", ".join(r["id"] for r in self.recipes),
            "info",
        )
        self._log(_("Target: %s") % self.modules_dir, "info")
        if self.is_fallback:
            self._log(_("Warning: using fallback directory"), "warning")
        self._log("")

        self.progress_bar.set_fraction(0.0)
        GLib.idle_add(self._set_status, _("Installing..."))
        GLib.idle_add(self.progress_bar.pulse)

        self.installer = Installer(self.modules_dir, self.is_fallback)
        self.install_thread = threading.Thread(
            target=self._install_worker, daemon=True
        )
        self.install_thread.start()

        # Pulse the progress bar while installing
        self._pulse_id = GLib.timeout_add(120, self._pulse_progress)

    def _pulse_progress(self):
        if self.finished:
            return False
        self.progress_bar.pulse()
        return True

    def _install_worker(self):
        """Run installation in a background thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            successful, failed = loop.run_until_complete(
                self.installer.install_batch(
                    self.recipes,
                    message_callback=self._async_message_cb,
                    mode=self.mode,
                    packaging=self.packaging,
                    module_name=self.module_name,
                )
            )
            GLib.idle_add(self._on_install_complete, successful, failed)
        except Exception as e:
            GLib.idle_add(self._on_install_error, str(e))
        finally:
            loop.close()

    async def _async_message_cb(self, msg):
        """Receive progress messages from Installer."""
        msg_type = msg.get("type", "")

        if msg_type == "install_start":
            total = msg.get("total", 0)
            self._log_threadsafe(
                _("Installing %d package(s)...") % total, "info"
            )

        elif msg_type == "install_progress":
            name = msg.get("recipeName", msg.get("recipeId", ""))
            step = msg.get("step", "")
            current = msg.get("current", 0)
            total = msg.get("total", 1)
            if total > 0:
                frac = float(current) / float(total)
                GLib.idle_add(self.progress_bar.set_fraction, frac)
            GLib.idle_add(
                self._set_status,
                _("%s - %s (%d/%d)") % (name, step, current, total),
            )

        elif msg_type == "log":
            level = msg.get("level", "info")
            text = msg.get("message", "")
            tag_map = {
                "info": "info",
                "warn": "warning",
                "error": "error",
            }
            self._log_threadsafe(text, tag_map.get(level, "info"))

        elif msg_type == "output":
            text = msg.get("text", "").rstrip()
            if text:
                self._log_threadsafe(text, "output")

        elif msg_type == "install_error":
            error = msg.get("error", _("Unknown error"))
            self._log_threadsafe(_("Error: %s") % error, "error")

    def _on_install_complete(self, successful, failed):
        self.finished = True
        self.progress_bar.set_fraction(1.0 if not failed else 0.0)

        if successful:
            self._log("")
            self._log(
                _("Successfully installed: %s") % ", ".join(successful),
                "success",
            )
            if (self.mode == "module"
                    and self.installer.last_module_filename):
                self._log(
                    _("Module: %s") % self.installer.last_module_filename,
                    "success",
                )
                self._log(
                    _("Location: %s") % self.modules_dir, "success"
                )
            if not failed:
                self._set_status(_("Installation complete"))
            if self.mode == "module" and not failed:
                self.open_folder_btn.set_visible(True)
                self.open_folder_btn.set_sensitive(True)

        if failed:
            self._log("")
            self._log(_("Failed: %s") % ", ".join(failed), "error")
            self._set_status(_("Installation failed"))

        self.cancel_btn.set_visible(False)
        self.done_btn.set_visible(True)

    def _on_install_error(self, error_text):
        self.finished = True
        self.progress_bar.set_fraction(0.0)
        self._log("")
        self._log(_("Fatal error: %s") % error_text, "error")
        self._set_status(_("Installation failed"))
        self.cancel_btn.set_visible(False)
        self.done_btn.set_visible(True)

    # -- Actions ------------------------------------------------------------

    def _set_status(self, text):
        self.status_label.set_text(text)

    def _on_log_toggled(self, btn):
        if btn.get_active():
            btn.set_label("\u25bc %s" % _("Installation Log"))
            self.set_resizable(True)
            self.log_sw.show_all()
        else:
            btn.set_label("\u25b6 %s" % _("Installation Log"))
            self.log_sw.hide()
            self.set_resizable(False)

    def _on_done(self, _btn):
        Gtk.main_quit()

    def _on_cancel(self, _btn):
        if self.install_thread and self.install_thread.is_alive():
            if self.installer:
                self.installer.cancel()
            self._log(_("Cancelling..."), "warning")
            self._set_status(_("Cancelling..."))
        else:
            Gtk.main_quit()

    def _on_open_folder(self, _btn):
        import subprocess as sp
        try:
            sp.Popen(
                ["xdg-open", self.modules_dir], start_new_session=True
            )
        except OSError:
            pass

    def _on_delete(self, _widget, _event):
        if self.install_thread and self.install_thread.is_alive():
            if self.installer:
                self.installer.cancel()
        Gtk.main_quit()
        return False


# ---------------------------------------------------------------------------
# CSS theming
# ---------------------------------------------------------------------------

CSS = b"""
window {
    background-color: @theme_bg_color;
}
textview {
    font-size: 11px;
}
textview text {
    background-color: shade(@theme_bg_color, 0.95);
    color: @theme_fg_color;
    padding: 6px;
}
"""


def _apply_css():
    screen = Gdk.Screen.get_default()
    if screen is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        screen,
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Main entry point for the GTK3 installer."""
    # Require root privileges. Escalation is handled externally
    # by pkexec via the .desktop file, not by self-re-exec.
    if os.geteuid() != 0:
        try:
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk as _Gtk
            dlg = _Gtk.MessageDialog(
                modal=True,
                destroy_with_parent=False,
                message_type=_Gtk.MessageType.ERROR,
                buttons=_Gtk.ButtonsType.OK,
                text=_("Root Privileges Required"),
            )
            dlg.format_secondary_text(
                _("This installer must be run as root.\n"
                  "Use the MiniOS Store URI handler or run with pkexec.")
            )
            dlg.run()
            dlg.destroy()
        except Exception:
            print(
                _("Error: root privileges required. "
                  "Run via pkexec or the URI handler."),
                file=sys.stderr,
            )
        sys.exit(1)

    parser = build_cli_parser()
    args = parser.parse_args()

    try:
        recipes, mode, packaging, module_name = resolve_params(args)
    except ValueError as e:
        print(_("Error: %s") % e, file=sys.stderr)
        sys.exit(1)

    if recipes is None:
        parser.print_help()
        sys.exit(1)

    if is_native_system():
        mode = "system"
        packaging = "single"
        module_name = ""

    # Allow Ctrl-C to work
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    _apply_css()
    win = InstallerWindow(recipes, mode, packaging, module_name)
    win.show_all()
    win.log_sw.hide()

    # Auto-start installation
    GLib.idle_add(win._on_install, None)

    Gtk.main()
