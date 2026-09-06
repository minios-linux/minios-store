"""Tests for the GTK installer's pure URI / CLI argument parsing helpers.

The GTK window itself needs a display and is not exercised here, but
parse_uri / resolve_params / build_cli_parser are plain logic and are
fully testable.
"""

import base64
import json

import pytest

# gui.py imports GTK (gi) at module import time and calls sys.exit(1) when it
# is unavailable. Skip the whole module gracefully on headless machines.
try:
    from minios_store import gui
except (SystemExit, ImportError, ValueError):  # pragma: no cover
    pytest.skip("GTK (python3-gi / gir1.2-gtk-3.0) not available",
                 allow_module_level=True)


def _require_gtk_display():
    initialized = gui.Gtk.init_check([])
    if isinstance(initialized, tuple):
        initialized = initialized[0]
    if not initialized:
        pytest.skip("GTK display is unavailable")


def test_installer_uses_public_minios_gui_api():
    assert gui.OperationView.__module__ == "minios_gui.widgets"
    assert gui.apply_minios_css.__module__ == "minios_gui.style"
    assert gui.new_header_bar.__module__ == "minios_gui.widgets"
    assert gui.new_icon.__module__ == "minios_gui.style"


def test_installer_has_no_local_generic_css_or_hard_coded_log_colors():
    with open(gui.__file__, encoding="utf-8") as stream:
        source = stream.read()

    assert "Gtk.CssProvider" not in source
    assert "foreground=" not in source
    assert "self.operation_view.feed(text + \"\\n\", level=level)" in source
    assert "#4a9eff" not in source
    assert "#ff4444" not in source


def test_installer_composes_operation_view(monkeypatch):
    _require_gtk_display()
    monkeypatch.setattr(gui, "get_writable_modules_dir", lambda: ("/tmp", False))
    window = gui.InstallerWindow(
        [{"id": "vlc"}], "module", "single", ""
    )
    try:
        assert isinstance(window.operation_view, gui.OperationView)
        assert (window.operation_view.log_expander.get_label()
                == "Installation Log")
        assert (window.operation_view.cancel_button.get_label()
                == "Cancel Installation")

        window._log("failed", "error")
        tags = window.operation_view.log_view.text_buffer.get_tag_table()
        assert tags.lookup("log-level-error") is not None
    finally:
        window.destroy()


def test_installer_operation_cancel_reaches_async_installer(monkeypatch):
    _require_gtk_display()
    monkeypatch.setattr(gui, "get_writable_modules_dir", lambda: ("/tmp", False))
    window = gui.InstallerWindow(
        [{"id": "vlc"}], "module", "single", ""
    )

    class RunningThread:
        def is_alive(self):
            return True

    class CancellableInstaller:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    try:
        window.install_thread = RunningThread()
        window.installer = CancellableInstaller()
        window.operation_view.emit("cancel-requested")

        assert window.installer.cancelled
        assert window.operation_view.status_label.get_text() == "Cancelling..."
    finally:
        window.destroy()


# ---------------------------------------------------------------------------
# parse_uri
# ---------------------------------------------------------------------------

def test_parse_uri_single_recipe():
    result = gui.parse_uri(
        "minios-store://install?recipes=vlc:auto:zstd&mode=module&packaging=single"
    )
    assert result["mode"] == "module"
    assert result["packaging"] == "single"
    assert result["module_name"] == ""
    assert result["recipes"] == [{
        "id": "vlc",
        "name": "vlc",
        "method": "apt",
        "level": "auto",
        "compression": "zstd",
        "packages": ["vlc"],
    }]


def test_parse_uri_multiple_recipes_and_module_name():
    result = gui.parse_uri(
        "minios-store://install?recipes=vlc:05:zstd,gimp:auto:xz"
        "&packaging=separate&moduleName=bundle"
    )
    ids = [r["id"] for r in result["recipes"]]
    assert ids == ["vlc", "gimp"]
    assert result["recipes"][0]["level"] == "05"
    assert result["recipes"][1]["compression"] == "xz"
    assert result["packaging"] == "separate"
    assert result["module_name"] == "bundle"


def test_parse_uri_defaults_mode_and_packaging():
    result = gui.parse_uri("minios-store://install?recipes=vlc:auto:zstd")
    assert result["mode"] == "module"
    assert result["packaging"] == "single"


def test_parse_uri_invalid_scheme():
    with pytest.raises(ValueError):
        gui.parse_uri("https://install?recipes=vlc:auto:zstd")


def test_parse_uri_invalid_action():
    with pytest.raises(ValueError):
        gui.parse_uri("minios-store://remove?recipes=vlc:auto:zstd")


def test_parse_uri_missing_recipes():
    with pytest.raises(ValueError):
        gui.parse_uri("minios-store://install?mode=module")


def test_parse_uri_bad_recipe_format():
    with pytest.raises(ValueError):
        gui.parse_uri("minios-store://install?recipes=vlc:auto")


def _payload(value):
    raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_parse_uri_full_script_payload_with_license_acceptance():
    recipe = {
        "id": "virtualbox-extpack",
        "name": "VirtualBox + Extension Pack",
        "method": "script",
        "level": "auto",
        "compression": "zstd",
        "script": "#!/bin/bash\necho ok",
        "license": {
            "id": "virtualbox-puel",
            "name": "Oracle PUEL",
            "url": "https://example.org/license",
            "requiresAcceptance": True,
        },
    }
    uri = (
        "minios-store://install?mode=module&packaging=single"
        "&recipes=virtualbox-extpack:auto:zstd&payload=%s"
        "&acceptedLicenses=virtualbox-puel" % _payload([recipe])
    )
    result = gui.parse_uri(uri)
    assert result["recipes"][0]["method"] == "script"
    assert result["recipes"][0]["script"].endswith("echo ok")
    assert result["accepted_licenses"] == ["virtualbox-puel"]


def test_parse_uri_rejects_unaccepted_required_license():
    recipe = {
        "id": "demo", "name": "Demo", "method": "script",
        "level": "auto", "compression": "zstd", "script": "echo ok",
        "license": {
            "id": "demo-license", "name": "Demo License",
            "url": "https://example.org/license", "requiresAcceptance": True,
        },
    }
    uri = (
        "minios-store://install?recipes=demo:auto:zstd&payload=%s"
        % _payload([recipe])
    )
    with pytest.raises(ValueError, match="License acceptance is required"):
        gui.parse_uri(uri)


# ---------------------------------------------------------------------------
# build_cli_parser / resolve_params
# ---------------------------------------------------------------------------

def test_build_cli_parser_defaults():
    parser = gui.build_cli_parser()
    args = parser.parse_args(["--recipes", "vlc:auto:zstd"])
    assert args.mode == "module"
    assert args.packaging == "single"
    assert args.recipes == "vlc:auto:zstd"


def test_resolve_params_from_uri():
    parser = gui.build_cli_parser()
    args = parser.parse_args(["minios-store://install?recipes=vlc:auto:zstd"])
    recipes, mode, packaging, module_name, accepted = gui.resolve_params(args)
    assert recipes[0]["id"] == "vlc"
    assert mode == "module"
    assert packaging == "single"


def test_resolve_params_from_cli_flags():
    parser = gui.build_cli_parser()
    args = parser.parse_args([
        "--mode", "system",
        "--packaging", "separate",
        "--recipes", "vlc:auto:zstd,gimp:05:xz",
        "--module-name", "bundle",
    ])
    recipes, mode, packaging, module_name, accepted = gui.resolve_params(args)
    assert [r["id"] for r in recipes] == ["vlc", "gimp"]
    assert mode == "system"
    assert packaging == "separate"
    assert module_name == "bundle"


def test_resolve_params_none_when_no_input():
    parser = gui.build_cli_parser()
    args = parser.parse_args([])
    assert gui.resolve_params(args) == (None, None, None, None, None)


def test_resolve_params_bad_cli_recipe_raises():
    parser = gui.build_cli_parser()
    args = parser.parse_args(["--recipes", "vlc:auto"])
    with pytest.raises(ValueError):
        gui.resolve_params(args)
