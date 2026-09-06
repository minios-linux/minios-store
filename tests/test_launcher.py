import ast
import inspect
import os
import sys
import threading
from unittest.mock import Mock, patch

import pytest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))

from minios_store import launcher


def test_website_available_closes_response():
    response = Mock()
    with patch("minios_store.launcher.urlopen", return_value=response):
        assert launcher.website_available("https://store.minios.dev")

    response.close.assert_called_once_with()


def test_website_available_handles_network_error():
    with patch("minios_store.launcher.urlopen", side_effect=OSError):
        assert not launcher.website_available("https://store.minios.dev")


def test_website_available_handles_invalid_url():
    assert not launcher.website_available("not-a-url")


def test_check_state_is_visible_for_minimum_duration():
    with patch("minios_store.launcher.time.monotonic", return_value=10.25), \
            patch("minios_store.launcher.time.sleep") as sleep:
        launcher.wait_for_minimum_check(10.0, minimum=1.0)

    sleep.assert_called_once_with(0.75)


def test_open_browser_uses_xdg_open():
    with patch("minios_store.launcher.subprocess.Popen") as popen:
        launcher.open_browser("https://store.minios.dev")

    assert popen.call_args[0][0] == ["xdg-open", "https://store.minios.dev"]


def test_launcher_pins_gtk3_namespaces():
    Gdk, _GLib, Gtk = launcher.load_gtk3()

    assert Gdk._version == "3.0"
    assert Gtk._version == "3.0"


def test_website_available_sends_user_agent_header():
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["ua"] = request.headers.get("User-agent")
        response = Mock()
        return response

    with patch("minios_store.launcher.urlopen", side_effect=fake_urlopen):
        assert launcher.website_available("https://store.minios.dev")

    assert "MiniOS-Store-Launcher" in captured["ua"]


def test_launcher_loads_public_minios_gui_api():
    (BackgroundTask, OperationView, apply_minios_css, new_header_bar,
     new_icon) = launcher.load_minios_gui()

    assert BackgroundTask.__module__ == "minios_gui.task"
    assert OperationView.__module__ == "minios_gui.widgets"
    assert apply_minios_css.__module__ == "minios_gui.style"
    assert new_header_bar.__module__ == "minios_gui.widgets"
    assert new_icon.__module__ == "minios_gui.style"


def test_launcher_css_only_contains_app_specific_layout():
    css_path = os.path.join(os.path.dirname(__file__), "..", "share", "launcher.css")
    with open(css_path, encoding="ascii") as stream:
        css = stream.read()

    assert ".launcher-card" in css
    assert "headerbar" not in css
    assert "suggested-action" not in css
    assert "min-height" not in css
    assert "#" not in css
    assert launcher.LAUNCHER_CSS_PATH == "/usr/share/minios-store/launcher.css"


def test_minios_gui_runtime_and_build_dependencies_are_declared():
    root = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(root, "debian", "control"), encoding="ascii") as stream:
        control = stream.read()
    with open(os.path.join(root, "debian", "rules"), encoding="ascii") as stream:
        rules = stream.read()

    assert control.count("python3-minios-gui (>= 1.4.0)") == 3
    assert "cp share/launcher.css debian/minios-store/usr/share/minios-store/" in rules


def test_launcher_worker_returns_data_without_direct_gtk_dispatch():
    tree = ast.parse(inspect.getsource(launcher.main))
    worker = next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_launch"
    )

    assert not any(
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in ("GLib", "Gtk")
        for node in ast.walk(worker)
    )

    task_call = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "BackgroundTask"
    )
    owner = next(keyword.value for keyword in task_call.keywords
                 if keyword.arg == "owner")
    assert isinstance(owner, ast.Name) and owner.id == "self"


def test_launcher_does_not_update_widgets_after_destroy(monkeypatch):
    _Gdk, GLib, Gtk = launcher.load_gtk3()
    initialized, _args = Gtk.init_check([])
    if not initialized:
        pytest.skip("GTK display is not available")

    (BackgroundTask, OperationView, apply_minios_css, new_header_bar,
     new_icon) = launcher.load_minios_gui()
    release_worker = threading.Event()
    calls = []
    tasks = []

    class RecordingTask(BackgroundTask):
        def __init__(self, *args, **kwargs):
            BackgroundTask.__init__(self, *args, **kwargs)
            tasks.append(self)

    monkeypatch.setattr(
        launcher, "load_minios_gui",
        lambda: (RecordingTask, OperationView, apply_minios_css,
                 new_header_bar, new_icon),
    )

    def record(method_name, original):
        def wrapper(self, *args, **kwargs):
            calls.append(method_name)
            return original(self, *args, **kwargs)
        return wrapper

    for method_name in ("set_status", "set_progress", "set_state"):
        original = getattr(OperationView, method_name)
        monkeypatch.setattr(
            OperationView, method_name, record(method_name, original)
        )

    original_pulse = Gtk.ProgressBar.pulse
    monkeypatch.setattr(
        Gtk.ProgressBar, "pulse", record("pulse", original_pulse)
    )
    monkeypatch.setattr(launcher, "website_available",
                        lambda _url: release_worker.wait(2.0) or True)
    monkeypatch.setattr(launcher, "wait_for_minimum_check",
                        lambda _started_at: None)
    monkeypatch.setattr(launcher, "open_browser", Mock())
    monkeypatch.setattr(sys, "argv", ["minios-store-launcher"])

    def destroy_launcher():
        for window in Gtk.Window.list_toplevels():
            if window.get_title() == "MiniOS Store":
                window.destroy()
        return False

    GLib.timeout_add(20, destroy_launcher)
    launcher.main()
    calls[:] = []
    release_worker.set()
    assert len(tasks) == 1
    assert tasks[0].wait(1.0)

    context = GLib.MainContext.default()
    while context.pending():
        context.iteration(False)

    assert calls == []
