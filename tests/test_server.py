import asyncio
import json
import os
import sys
import types
from unittest.mock import patch


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))

if "websockets" not in sys.modules:
    websockets = types.ModuleType("websockets")
    websockets.exceptions = types.SimpleNamespace(ConnectionClosed=Exception)
    sys.modules["websockets"] = websockets

from minios_store.server import StoreServer


class FakeInstaller:
    def __init__(self, result=None):
        self.call = None
        self.cancelled = False
        self._result = result or ([], [])

    async def install_batch(self, recipes, callback, mode, packaging, module_name):
        self.call = (recipes, mode, packaging, module_name)
        return self._result

    def cancel(self):
        self.cancelled = True


class FakeWS:
    """Minimal websocket double capturing JSON messages sent to the client."""

    def __init__(self):
        self.sent = []
        self.remote_address = ("127.0.0.1", 54321)

    async def send(self, data):
        self.sent.append(json.loads(data))


_SYSTEM_INFO = {
    "codename": "trixie",
    "id": "minios",
    "name": "MiniOS",
    "version_id": "5",
    "arch": "amd64",
    "is_native": False,
}


def make_server(system_info=None, modules_dir="/modules", is_fallback=False):
    info = system_info or dict(_SYSTEM_INFO)
    with patch(
        "minios_store.server.config.get_writable_modules_dir",
        return_value=(modules_dir, is_fallback),
    ), patch(
        "minios_store.server.config.get_system_info", return_value=info
    ):
        return StoreServer()


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_native_server_forces_system_installation():
    system_info = dict(_SYSTEM_INFO)
    system_info["is_native"] = True
    server = make_server(system_info)

    installer = FakeInstaller()
    server.installer = installer

    async def ignore_message(_message):
        return None

    server._broadcast = ignore_message
    message = {
        "type": "install",
        "mode": "module",
        "packaging": "separate",
        "moduleName": "requested-module",
        "recipes": [{"id": "test", "name": "Test", "method": "apt"}],
    }
    run(server._handle_install(object(), message))

    assert installer.call[1:] == ("system", "single", "")


# ---------------------------------------------------------------------------
# handle_message dispatch
# ---------------------------------------------------------------------------

def test_handle_message_invalid_json():
    server = make_server()
    ws = FakeWS()
    run(server.handle_message(ws, "not json{"))
    assert ws.sent[-1]["type"] == "install_error"
    assert "Invalid JSON" in ws.sent[-1]["error"]


def test_handle_message_ping_pong():
    server = make_server()
    ws = FakeWS()
    run(server.handle_message(ws, json.dumps({"type": "ping"})))
    assert ws.sent[-1] == {"type": "pong"}


def test_handle_message_unknown_type():
    server = make_server()
    ws = FakeWS()
    run(server.handle_message(ws, json.dumps({"type": "frobnicate"})))
    assert ws.sent[-1]["type"] == "install_error"
    assert "Unknown message type" in ws.sent[-1]["error"]


def test_handle_message_get_status_idle():
    server = make_server()
    ws = FakeWS()
    run(server.handle_message(ws, json.dumps({"type": "get_status"})))
    assert ws.sent[-1]["type"] == "install_status"
    assert ws.sent[-1]["installing"] is False


# ---------------------------------------------------------------------------
# _handle_install validation
# ---------------------------------------------------------------------------

def test_handle_install_no_recipes():
    server = make_server()
    ws = FakeWS()
    run(server._handle_install(ws, {"type": "install", "recipes": []}))
    assert ws.sent[-1]["type"] == "install_error"
    assert "No recipes" in ws.sent[-1]["error"]


def test_handle_install_invalid_mode():
    server = make_server()
    ws = FakeWS()
    run(server._handle_install(ws, {
        "recipes": [{"id": "x", "method": "apt"}],
        "mode": "bogus",
    }))
    assert ws.sent[-1]["type"] == "install_error"
    assert "Invalid mode" in ws.sent[-1]["error"]


def test_handle_install_invalid_packaging():
    server = make_server()
    ws = FakeWS()
    run(server._handle_install(ws, {
        "recipes": [{"id": "x", "method": "apt"}],
        "mode": "module",
        "packaging": "bogus",
    }))
    assert ws.sent[-1]["type"] == "install_error"
    assert "Invalid packaging" in ws.sent[-1]["error"]


def test_handle_install_recipe_missing_id():
    server = make_server()
    ws = FakeWS()
    run(server._handle_install(ws, {
        "recipes": [{"method": "apt"}],
        "mode": "module",
        "packaging": "single",
    }))
    assert ws.sent[-1]["type"] == "install_error"
    assert "missing 'id'" in ws.sent[-1]["error"]


def test_handle_install_recipe_invalid_method():
    server = make_server()
    ws = FakeWS()
    run(server._handle_install(ws, {
        "recipes": [{"id": "x", "method": "bogus"}],
        "mode": "module",
        "packaging": "single",
    }))
    assert ws.sent[-1]["type"] == "install_error"
    assert "Invalid method" in ws.sent[-1]["error"]


def test_handle_install_already_installing():
    server = make_server()
    server._installing = True
    ws = FakeWS()
    run(server._handle_install(ws, {
        "recipes": [{"id": "x", "method": "apt"}],
    }))
    assert ws.sent[-1]["type"] == "install_error"
    assert "already in progress" in ws.sent[-1]["error"]


def test_handle_install_success_broadcasts_and_resets_flag():
    server = make_server()
    server.installer = FakeInstaller(result=(["vlc"], []))
    ws = FakeWS()
    server._clients.add(ws)
    run(server._handle_install(ws, {
        "recipes": [{"id": "vlc", "name": "VLC", "method": "apt"}],
        "mode": "module",
        "packaging": "single",
    }))
    assert server._installing is False
    assert server.installer.call[1:] == ("module", "single", "")


# ---------------------------------------------------------------------------
# _handle_cancel
# ---------------------------------------------------------------------------

def test_handle_cancel_when_idle():
    server = make_server()
    ws = FakeWS()
    run(server._handle_cancel(ws))
    assert ws.sent[-1]["type"] == "log"
    assert "No installation in progress" in ws.sent[-1]["message"]


def test_handle_cancel_when_installing():
    server = make_server()
    server._installing = True
    installer = FakeInstaller()
    server.installer = installer
    ws = FakeWS()
    run(server._handle_cancel(ws))
    assert installer.cancelled is True
    assert ws.sent[-1]["level"] == "warn"


# ---------------------------------------------------------------------------
# _handle_get_status with active install
# ---------------------------------------------------------------------------

def test_handle_get_status_active_includes_details():
    server = make_server()
    server._installing = True
    server._install_state = {
        "active": True,
        "current": 2,
        "total": 5,
        "recipe_name": "VLC",
        "step": "install",
        "successful": ["a"],
        "failed": [],
        "output_lines": ["line1", "line2"],
    }
    ws = FakeWS()
    run(server._handle_get_status(ws))
    msg = ws.sent[-1]
    assert msg["installing"] is True
    assert msg["current"] == 2
    assert msg["total"] == 5
    assert msg["recipeName"] == "VLC"
    assert msg["outputLines"] == ["line1", "line2"]


# ---------------------------------------------------------------------------
# _handle_open_folder
# ---------------------------------------------------------------------------

def test_handle_open_folder_missing_path_is_ignored():
    server = make_server()
    ws = FakeWS()
    run(server._handle_open_folder(ws, {"type": "open_folder"}))
    assert ws.sent == []


def test_handle_open_folder_nonexistent_path_reports_error():
    server = make_server()
    ws = FakeWS()
    run(server._handle_open_folder(ws, {"path": "/no/such/folder/xyz"}))
    assert ws.sent[-1]["type"] == "log"
    assert ws.sent[-1]["level"] == "error"
    assert "does not exist" in ws.sent[-1]["message"]


def test_handle_open_folder_launches_file_manager(monkeypatch, tmp_path):
    import shutil
    import subprocess as sp

    server = make_server()
    monkeypatch.setattr(
        sp, "run", lambda *a, **k: sp.CompletedProcess(a, 0, "", "")
    )
    monkeypatch.setattr(
        shutil, "which",
        lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None,
    )
    popen_calls = []
    monkeypatch.setattr(sp, "Popen", lambda *a, **k: popen_calls.append(a))

    ws = FakeWS()
    run(server._handle_open_folder(ws, {"path": str(tmp_path)}))
    assert popen_calls  # a file manager subprocess was spawned


def test_handle_open_folder_no_file_manager(monkeypatch, tmp_path):
    import shutil
    import subprocess as sp

    server = make_server()
    monkeypatch.setattr(
        sp, "run", lambda *a, **k: sp.CompletedProcess(a, 0, "", "")
    )
    monkeypatch.setattr(shutil, "which", lambda name: None)

    ws = FakeWS()
    run(server._handle_open_folder(ws, {"path": str(tmp_path)}))
    assert ws.sent[-1]["level"] == "error"
    assert "no working file manager" in ws.sent[-1]["message"]


# ---------------------------------------------------------------------------
# init / _send / _broadcast
# ---------------------------------------------------------------------------

def test_server_init_with_fallback_dir():
    server = make_server(
        modules_dir="/var/lib/minios-store/modules", is_fallback=True
    )
    assert server.installer.is_fallback_dir is True
    assert server.installer.modules_dir == "/var/lib/minios-store/modules"


def test_send_swallows_connection_closed():
    import websockets

    server = make_server()

    class DeadWS:
        async def send(self, _data):
            raise websockets.exceptions.ConnectionClosed(1006, "gone")

    run(server._send(DeadWS(), {"type": "x"}))  # must not raise


def test_broadcast_drops_dead_clients():
    import websockets

    server = make_server()
    good = FakeWS()

    class DeadWS:
        remote_address = ("1", "2")

        async def send(self, _data):
            raise websockets.exceptions.ConnectionClosed(1006, "gone")

    dead = DeadWS()
    server._clients = {good, dead}
    run(server._broadcast({"type": "log"}))
    assert good.sent[-1] == {"type": "log"}
    assert dead not in server._clients


# ---------------------------------------------------------------------------
# handle_message dispatch (cancel / open_folder)
# ---------------------------------------------------------------------------

def test_handle_message_dispatches_cancel():
    server = make_server()
    server._installing = True
    server.installer = FakeInstaller()
    ws = FakeWS()
    run(server.handle_message(ws, json.dumps({"type": "cancel"})))
    assert server.installer.cancelled is True


def test_handle_message_dispatches_open_folder():
    server = make_server()
    ws = FakeWS()
    run(server.handle_message(ws, json.dumps({"type": "open_folder"})))
    assert ws.sent == []  # missing path -> silently ignored


# ---------------------------------------------------------------------------
# _handle_install state tracking + error handling
# ---------------------------------------------------------------------------

class CallbackInstaller:
    """Installer double that drives the send_message callback."""

    def __init__(self):
        self.call = None

    async def install_batch(self, recipes, callback, mode, packaging, module_name):
        self.call = (recipes, mode, packaging, module_name)
        await callback({"type": "install_start", "total": 2})
        await callback({
            "type": "install_progress",
            "current": 1, "recipeName": "VLC", "step": "install",
        })
        await callback({"type": "output", "text": "building"})
        await callback({
            "type": "install_complete", "successful": ["vlc"], "failed": [],
        })
        return ["vlc"], []


def test_handle_install_tracks_state_and_broadcasts():
    server = make_server()
    server.installer = CallbackInstaller()
    ws = FakeWS()
    server._clients.add(ws)
    run(server._handle_install(ws, {
        "recipes": [{"id": "vlc", "name": "VLC", "method": "apt"}],
        "mode": "module",
        "packaging": "single",
    }))
    types = [m["type"] for m in ws.sent]
    assert "install_start" in types
    assert "install_progress" in types
    assert "install_complete" in types
    assert server._install_state["successful"] == ["vlc"]
    assert server._install_state["active"] is False


class BoomInstaller:
    async def install_batch(self, *_a, **_k):
        raise RuntimeError("kaboom")


def test_handle_install_unexpected_error_is_reported():
    server = make_server()
    server.installer = BoomInstaller()
    ws = FakeWS()
    run(server._handle_install(ws, {
        "recipes": [{"id": "vlc", "method": "apt"}],
        "mode": "module",
        "packaging": "single",
    }))
    assert any(m["type"] == "install_error" for m in ws.sent)
    assert server._installing is False


# ---------------------------------------------------------------------------
# handler() connection lifecycle
# ---------------------------------------------------------------------------

def test_handler_sends_system_info_and_processes_messages():
    import websockets

    server = make_server()
    ws = FakeWS()
    seq = iter([json.dumps({"type": "ping"})])

    async def recv():
        try:
            return next(seq)
        except StopIteration:
            raise websockets.exceptions.ConnectionClosed(1000, "bye")

    ws.recv = recv
    run(server.handler(ws))

    assert ws.sent[0]["type"] == "system_info"
    assert {"type": "pong"} in ws.sent
    assert ws not in server._clients
