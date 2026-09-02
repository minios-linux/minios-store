import os
import sys
from unittest.mock import Mock, patch


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


def test_launcher_uses_minios_action_palette():
    css = launcher.LAUNCHER_CSS.decode("ascii")

    assert "linear-gradient(to bottom, #6bb5ff, #4a90d9)" in css
    assert "linear-gradient(to bottom, #7fc3ff, #5ba0e9)" in css
    assert "#10b5ce" not in css
    assert "#29c9df" not in css


def test_launcher_card_and_progress_use_theme_surfaces():
    css = launcher.LAUNCHER_CSS.decode("ascii")
    card_rule = css.split(".launcher-card {", 1)[1].split("}", 1)[0]
    progress_rule = css.split(".launcher-progress progress {", 1)[1].split("}", 1)[0]

    assert "border:" not in card_rule
    assert "background" not in card_rule
    assert "background" not in progress_rule
