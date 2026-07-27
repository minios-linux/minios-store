"""Tests for minios_store.installer -- the core installation logic.

Covers filename construction, cancellation, command execution, per-method
module/system installers, combined script generation, the thread-safe line
callback, and the async batch orchestrator (system / single / separate).
"""

import asyncio
import os
import subprocess
import threading

import pytest

from minios_store import config
from minios_store.installer import (
    Installer,
    InstallationError,
    InstallCancelled,
)


def run(coro):
    """Run a coroutine on a fresh event loop and return its result."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class Collector:
    """Async callable that records every message it receives."""

    def __init__(self):
        self.messages = []

    async def __call__(self, msg):
        self.messages.append(msg)

    def types(self):
        return [m.get("type") for m in self.messages]

    def of_type(self, msg_type):
        return [m for m in self.messages if m.get("type") == msg_type]


def _fake_run_creating_module(cmd, cwd=None, env=None, line_callback=None):
    """Stand-in for _run_cmd that creates the -n <name> output file."""
    name = cmd[cmd.index("-n") + 1]
    open(os.path.join(cwd, name), "w").close()
    return subprocess.CompletedProcess(cmd, 0, "", "")


# ---------------------------------------------------------------------------
# __init__ (regression for the AttributeError fallback bug)
# ---------------------------------------------------------------------------

def test_default_modules_dir_falls_back_to_config():
    inst = Installer()
    assert inst.modules_dir == config.MODULES_DIR


def test_custom_modules_dir_is_used():
    inst = Installer("/x/y", is_fallback_dir=True)
    assert inst.modules_dir == "/x/y"
    assert inst.is_fallback_dir is True


# ---------------------------------------------------------------------------
# _build_module_filename
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rid,level,custom,expected", [
    ("firefox", "auto", "", "firefox.sb"),
    ("firefox", "", "", "firefox.sb"),
    ("firefox", "05", "", "05-firefox.sb"),
    ("firefox", "05", "myname", "05-myname.sb"),
    ("firefox", "auto", "myname", "myname.sb"),
])
def test_build_module_filename(rid, level, custom, expected):
    inst = Installer("/tmp")
    assert inst._build_module_filename(rid, level, custom) == expected


# ---------------------------------------------------------------------------
# cancel / reset / _check_cancelled
# ---------------------------------------------------------------------------

def test_reset_clears_state():
    inst = Installer("/tmp")
    inst._cancelled = True
    inst._current_process = object()
    inst.last_module_filename = "x.sb"
    inst.reset()
    assert inst._cancelled is False
    assert inst._current_process is None
    assert inst.last_module_filename is None


def test_check_cancelled_raises():
    inst = Installer("/tmp")
    inst._cancelled = True
    with pytest.raises(InstallCancelled):
        inst._check_cancelled()


def test_cancel_sets_flag_and_terminates_process():
    inst = Installer("/tmp")

    class FakeProc:
        def __init__(self):
            self.terminated = False

        def terminate(self):
            self.terminated = True

    proc = FakeProc()
    inst._current_process = proc
    inst.cancel()
    assert inst._cancelled is True
    assert proc.terminated is True


def test_cancel_tolerates_process_lookup_error():
    inst = Installer("/tmp")

    class FakeProc:
        def terminate(self):
            raise ProcessLookupError()

    inst._current_process = FakeProc()
    inst.cancel()  # must not raise
    assert inst._cancelled is True


# ---------------------------------------------------------------------------
# _run_cmd
# ---------------------------------------------------------------------------

def test_run_cmd_success_collects_output():
    inst = Installer("/tmp")
    lines = []
    result = inst._run_cmd(
        ["sh", "-c", "echo hello; echo world"], line_callback=lines.append
    )
    assert result.returncode == 0
    assert "hello" in lines and "world" in lines
    assert "hello" in result.stdout


def test_run_cmd_failure_raises_installation_error():
    inst = Installer("/tmp")
    with pytest.raises(InstallationError):
        inst._run_cmd(["sh", "-c", "exit 3"])


def test_run_cmd_precancelled_raises_before_exec():
    inst = Installer("/tmp")
    inst._cancelled = True
    with pytest.raises(InstallCancelled):
        inst._run_cmd(["true"])


def test_run_cmd_cancel_during_stream_raises():
    inst = Installer("/tmp")

    def cb(_line):
        inst._cancelled = True

    with pytest.raises(InstallCancelled):
        inst._run_cmd(["sh", "-c", "echo one"], line_callback=cb)


def test_run_cmd_line_callback_exception_is_swallowed():
    inst = Installer("/tmp")

    def cb(_line):
        raise RuntimeError("boom")

    result = inst._run_cmd(["sh", "-c", "echo hi"], line_callback=cb)
    assert result.returncode == 0


def test_run_cmd_missing_binary_raises_installation_error():
    inst = Installer("/tmp")
    with pytest.raises(InstallationError):
        inst._run_cmd(["minios-store-nonexistent-binary-xyz"])


def test_run_cmd_passes_extra_env(tmp_path):
    inst = Installer("/tmp")
    lines = []
    inst._run_cmd(
        ["sh", "-c", "echo $MYVAR"],
        env={"MYVAR": "value123"},
        line_callback=lines.append,
    )
    assert "value123" in lines


# ---------------------------------------------------------------------------
# module installers -- validation errors
# ---------------------------------------------------------------------------

def test_install_module_apt_requires_packages():
    inst = Installer("/tmp")
    with pytest.raises(InstallationError):
        inst._install_module_apt({"id": "x", "packages": []})


def test_install_module_script_requires_script():
    inst = Installer("/tmp")
    with pytest.raises(InstallationError):
        inst._install_module_script({"id": "x", "script": ""})


def test_install_module_deb_requires_url():
    inst = Installer("/tmp")
    with pytest.raises(InstallationError):
        inst._install_module_deb({"id": "x", "debUrl": ""})


# ---------------------------------------------------------------------------
# module installers -- success paths (mocked _run_cmd)
# ---------------------------------------------------------------------------

def test_install_module_apt_success(tmp_path, monkeypatch):
    inst = Installer(str(tmp_path))
    monkeypatch.setattr(inst, "_run_cmd", _fake_run_creating_module)
    recipe = {
        "id": "vlc", "method": "apt", "level": "05",
        "packages": ["vlc"], "compression": "zstd",
    }
    path = inst._install_module_apt(recipe)
    assert path.endswith("05-vlc.sb")
    assert os.path.exists(path)


def test_install_module_apt_missing_output_raises(tmp_path, monkeypatch):
    inst = Installer(str(tmp_path))
    monkeypatch.setattr(
        inst, "_run_cmd",
        lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""),
    )
    with pytest.raises(InstallationError):
        inst._install_module_apt({"id": "vlc", "method": "apt", "packages": ["vlc"]})


def test_install_module_script_success(tmp_path, monkeypatch):
    inst = Installer(str(tmp_path))
    monkeypatch.setattr(inst, "_run_cmd", _fake_run_creating_module)
    recipe = {"id": "foo", "method": "script", "script": "echo hi", "level": "auto"}
    path = inst._install_module_script(recipe)
    assert path.endswith("foo.sb")
    assert os.path.exists(path)


def test_install_module_deb_success(tmp_path, monkeypatch):
    inst = Installer(str(tmp_path))

    def fake_retrieve(url, path):
        with open(path, "wb") as f:
            f.write(b"deb-bytes")

    monkeypatch.setattr(
        "minios_store.installer.urllib.request.urlretrieve", fake_retrieve
    )
    monkeypatch.setattr(inst, "_run_cmd", _fake_run_creating_module)
    recipe = {"id": "bar", "method": "deb", "debUrl": "http://x/p.deb", "level": "auto"}
    path = inst._install_module_deb(recipe)
    assert path.endswith("bar.sb")
    assert os.path.exists(path)


def test_install_module_deb_download_failure_raises(tmp_path, monkeypatch):
    inst = Installer(str(tmp_path))

    def boom(url, path):
        raise OSError("network down")

    monkeypatch.setattr(
        "minios_store.installer.urllib.request.urlretrieve", boom
    )
    with pytest.raises(InstallationError):
        inst._install_module_deb(
            {"id": "bar", "method": "deb", "debUrl": "http://x/p.deb"}
        )


# ---------------------------------------------------------------------------
# system installers -- validation errors
# ---------------------------------------------------------------------------

def test_install_system_apt_requires_packages():
    inst = Installer("/tmp")
    with pytest.raises(InstallationError):
        inst._install_system_apt({"id": "x", "packages": []})


def test_install_system_script_requires_script():
    inst = Installer("/tmp")
    with pytest.raises(InstallationError):
        inst._install_system_script({"id": "x"})


def test_install_system_deb_requires_url():
    inst = Installer("/tmp")
    with pytest.raises(InstallationError):
        inst._install_system_deb({"id": "x"})


def test_install_system_apt_runs_expected_commands(monkeypatch):
    inst = Installer("/tmp")
    calls = []

    def fake_run(cmd, cwd=None, env=None, line_callback=None):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(inst, "_run_cmd", fake_run)
    inst._install_system_apt({"id": "vlc", "name": "VLC", "packages": ["vlc"]})
    # update, install, clean
    assert calls[0][:2] == ["apt-get", "update"]
    assert "install" in calls[1]
    assert calls[-1] == ["apt-get", "clean"]


def test_install_system_script_runs_bash(monkeypatch):
    inst = Installer("/tmp")
    calls = []

    def fake_run(cmd, cwd=None, env=None, line_callback=None):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(inst, "_run_cmd", fake_run)
    inst._install_system_script(
        {"id": "foo", "name": "Foo", "script": "echo hi"}
    )
    assert calls[0][0] == "bash"
    # the temp script path must have been cleaned up
    assert not os.path.exists(calls[0][1])


def test_install_system_deb_success(monkeypatch):
    inst = Installer("/tmp")

    def fake_retrieve(url, path):
        with open(path, "wb") as f:
            f.write(b"deb")

    monkeypatch.setattr(
        "minios_store.installer.urllib.request.urlretrieve", fake_retrieve
    )
    calls = []

    def fake_run(cmd, cwd=None, env=None, line_callback=None):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(inst, "_run_cmd", fake_run)
    inst._install_system_deb(
        {"id": "bar", "name": "Bar", "debUrl": "http://host/pkg.deb"}
    )
    assert calls[0][:3] == ["apt", "install", "-y"]


def test_install_system_deb_download_failure_raises(monkeypatch):
    inst = Installer("/tmp")

    def boom(url, path):
        raise OSError("no network")

    monkeypatch.setattr(
        "minios_store.installer.urllib.request.urlretrieve", boom
    )
    with pytest.raises(InstallationError):
        inst._install_system_deb(
            {"id": "bar", "name": "Bar", "debUrl": "http://host/pkg.deb"}
        )


# ---------------------------------------------------------------------------
# dispatch helpers -- unknown method
# ---------------------------------------------------------------------------

def test_install_module_unknown_method_raises():
    inst = Installer("/tmp")
    with pytest.raises(InstallationError):
        inst._install_module({"id": "x", "method": "bogus"})


def test_install_system_unknown_method_raises():
    inst = Installer("/tmp")
    with pytest.raises(InstallationError):
        inst._install_system({"id": "x", "method": "bogus"})


# ---------------------------------------------------------------------------
# _build_combined_script
# ---------------------------------------------------------------------------

def test_build_combined_script_apt():
    inst = Installer("/tmp")
    script = inst._build_combined_script(
        [{"id": "vlc", "method": "apt", "packages": ["vlc", "x264"]}]
    )
    assert script.startswith("#!/bin/bash")
    assert "apt-get update -qq" in script
    assert "apt-get install -y --no-install-recommends vlc x264" in script
    assert "apt-get clean" in script


def test_build_combined_script_inlines_script_method():
    inst = Installer("/tmp")
    script = inst._build_combined_script(
        [{"id": "foo", "method": "script", "script": "echo custom-step"}]
    )
    assert "echo custom-step" in script


def test_build_combined_script_deb_downloads_and_installs():
    inst = Installer("/tmp")
    script = inst._build_combined_script(
        [{"id": "bar", "method": "deb", "debUrl": "http://host/pkg.deb"}]
    )
    assert "wget -O" in script
    assert "pkg.deb" in script
    assert "apt install -y" in script
    assert "rm -f" in script


# ---------------------------------------------------------------------------
# _make_line_callback
# ---------------------------------------------------------------------------

def test_make_line_callback_returns_none_without_callback():
    assert Installer._make_line_callback(None, None) is None


def test_make_line_callback_delivers_output_message():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    got = []
    done = threading.Event()

    async def cb(msg):
        got.append(msg)
        done.set()

    line_cb = Installer._make_line_callback(loop, cb)
    assert callable(line_cb)
    line_cb("a line")

    assert done.wait(2)
    assert got == [{"type": "output", "text": "a line"}]

    loop.call_soon_threadsafe(loop.stop)
    thread.join(2)
    loop.close()


# ---------------------------------------------------------------------------
# install_recipe / install_recipe_system (progress callbacks)
# ---------------------------------------------------------------------------

def test_install_recipe_reports_progress_and_returns_path(monkeypatch):
    inst = Installer("/tmp")
    monkeypatch.setattr(
        inst, "_install_module",
        lambda recipe, line_cb, custom_name: "/tmp/out.sb",
    )
    steps = []

    async def progress(step, detail):
        steps.append(step)

    path = run(inst.install_recipe({"id": "x", "name": "X"}, progress_callback=progress))
    assert path == "/tmp/out.sb"
    assert steps[0] == "install"
    assert steps[-1] == "done"


def test_install_recipe_system_reports_progress(monkeypatch):
    inst = Installer("/tmp")
    captured = {}

    def fake_system(recipe, line_cb):
        captured["recipe"] = recipe

    monkeypatch.setattr(inst, "_install_system", fake_system)
    steps = []

    async def progress(step, detail):
        steps.append(step)

    run(inst.install_recipe_system({"id": "x", "name": "X"}, progress_callback=progress))
    assert captured["recipe"]["id"] == "x"
    assert "install" in steps and "done" in steps


# ---------------------------------------------------------------------------
# install_batch -- system mode
# ---------------------------------------------------------------------------

def test_install_batch_system_success(monkeypatch):
    inst = Installer("/tmp")

    def fake_run(cmd, cwd=None, env=None, line_callback=None):
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(inst, "_run_cmd", fake_run)
    col = Collector()
    recipes = [{"id": "vlc", "name": "VLC", "method": "apt", "packages": ["vlc"]}]

    successful, failed = run(inst.install_batch(recipes, col, mode="system"))
    assert successful == ["vlc"]
    assert failed == []
    assert "install_start" in col.types()
    assert "install_complete" in col.types()


def test_install_batch_system_reports_failure(monkeypatch):
    inst = Installer("/tmp")

    def fake_run(cmd, cwd=None, env=None, line_callback=None):
        raise InstallationError("apt failed")

    monkeypatch.setattr(inst, "_run_cmd", fake_run)
    col = Collector()
    recipes = [{"id": "vlc", "name": "VLC", "method": "apt", "packages": ["vlc"]}]

    successful, failed = run(inst.install_batch(recipes, col, mode="system"))
    assert successful == []
    assert failed == ["vlc"]
    assert col.of_type("install_error")


def test_install_batch_system_cancellation_marks_remaining_failed(monkeypatch):
    inst = Installer("/tmp")

    def fake_run(cmd, cwd=None, env=None, line_callback=None):
        inst._cancelled = True
        raise InstallCancelled("cancelled")

    monkeypatch.setattr(inst, "_run_cmd", fake_run)
    col = Collector()
    recipes = [
        {"id": "a", "name": "A", "method": "apt", "packages": ["a"]},
        {"id": "b", "name": "B", "method": "apt", "packages": ["b"]},
    ]

    successful, failed = run(inst.install_batch(recipes, col, mode="system"))
    assert successful == []
    assert set(failed) == {"a", "b"}


# ---------------------------------------------------------------------------
# install_batch -- module / single packaging
# ---------------------------------------------------------------------------

def test_install_batch_single_apt_combines_into_one_module(tmp_path, monkeypatch):
    inst = Installer(str(tmp_path))
    monkeypatch.setattr(inst, "_run_cmd", _fake_run_creating_module)
    col = Collector()
    recipes = [
        {"id": "vlc", "name": "VLC", "method": "apt", "packages": ["vlc"]},
        {"id": "gimp", "name": "GIMP", "method": "apt", "packages": ["gimp"]},
    ]

    successful, failed = run(
        inst.install_batch(recipes, col, mode="module", packaging="single")
    )
    assert set(successful) == {"vlc", "gimp"}
    assert failed == []
    assert inst.last_module_filename == "vlc+gimp.sb"
    loc = col.of_type("module_location")
    assert loc and loc[0]["moduleName"] == "vlc+gimp.sb"
    assert os.path.exists(tmp_path / "vlc+gimp.sb")


def test_install_batch_single_uses_custom_module_name(tmp_path, monkeypatch):
    inst = Installer(str(tmp_path))
    monkeypatch.setattr(inst, "_run_cmd", _fake_run_creating_module)
    col = Collector()
    recipes = [{"id": "vlc", "name": "VLC", "method": "apt", "packages": ["vlc"]}]

    successful, _failed = run(
        inst.install_batch(
            recipes, col, mode="module", packaging="single", module_name="bundle"
        )
    )
    assert successful == ["vlc"]
    assert inst.last_module_filename == "bundle.sb"


def test_install_batch_single_no_packages_fails(monkeypatch):
    inst = Installer("/tmp")
    col = Collector()
    recipes = [{"id": "vlc", "name": "VLC", "method": "apt", "packages": []}]

    successful, failed = run(
        inst.install_batch(recipes, col, mode="module", packaging="single")
    )
    assert successful == []
    assert failed == ["vlc"]
    assert col.of_type("install_error")


def test_install_batch_single_mixed_methods_uses_script(tmp_path, monkeypatch):
    inst = Installer(str(tmp_path))
    monkeypatch.setattr(inst, "_run_cmd", _fake_run_creating_module)
    col = Collector()
    recipes = [
        {"id": "vlc", "name": "VLC", "method": "apt", "packages": ["vlc"]},
        {"id": "foo", "name": "Foo", "method": "script", "script": "echo hi"},
    ]

    successful, failed = run(
        inst.install_batch(
            recipes, col, mode="module", packaging="single", module_name="mybundle"
        )
    )
    assert set(successful) == {"vlc", "foo"}
    assert failed == []
    assert inst.last_module_filename == "mybundle.sb"
    assert os.path.exists(tmp_path / "mybundle.sb")


def test_install_batch_single_failure_reports_error(tmp_path, monkeypatch):
    inst = Installer(str(tmp_path))

    def fake_run(cmd, cwd=None, env=None, line_callback=None):
        raise InstallationError("apt2sb failed")

    monkeypatch.setattr(inst, "_run_cmd", fake_run)
    col = Collector()
    recipes = [{"id": "vlc", "name": "VLC", "method": "apt", "packages": ["vlc"]}]

    successful, failed = run(
        inst.install_batch(recipes, col, mode="module", packaging="single")
    )
    assert successful == []
    assert failed == ["vlc"]
    assert col.of_type("install_error")


# ---------------------------------------------------------------------------
# install_batch -- module / separate packaging
# ---------------------------------------------------------------------------

def test_install_batch_separate_creates_one_module_each(tmp_path, monkeypatch):
    inst = Installer(str(tmp_path))
    monkeypatch.setattr(inst, "_run_cmd", _fake_run_creating_module)
    col = Collector()
    recipes = [
        {"id": "vlc", "name": "VLC", "method": "apt", "packages": ["vlc"], "level": "05"},
        {"id": "gimp", "name": "GIMP", "method": "apt", "packages": ["gimp"], "level": "auto"},
    ]

    successful, failed = run(
        inst.install_batch(recipes, col, mode="module", packaging="separate")
    )
    assert set(successful) == {"vlc", "gimp"}
    assert failed == []
    assert os.path.exists(tmp_path / "05-vlc.sb")
    assert os.path.exists(tmp_path / "gimp.sb")


def test_install_batch_separate_prefixes_custom_name(tmp_path, monkeypatch):
    inst = Installer(str(tmp_path))
    monkeypatch.setattr(inst, "_run_cmd", _fake_run_creating_module)
    col = Collector()
    recipes = [
        {"id": "vlc", "name": "VLC", "method": "apt", "packages": ["vlc"], "level": "auto"},
    ]

    run(inst.install_batch(
        recipes, col, mode="module", packaging="separate", module_name="pre",
    ))
    assert os.path.exists(tmp_path / "pre-vlc.sb")


def test_install_batch_separate_partial_failure(tmp_path, monkeypatch):
    inst = Installer(str(tmp_path))

    def fake_run(cmd, cwd=None, env=None, line_callback=None):
        name = cmd[cmd.index("-n") + 1]
        if "gimp" in name:
            raise InstallationError("boom")
        open(os.path.join(cwd, name), "w").close()
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(inst, "_run_cmd", fake_run)
    col = Collector()
    recipes = [
        {"id": "vlc", "name": "VLC", "method": "apt", "packages": ["vlc"]},
        {"id": "gimp", "name": "GIMP", "method": "apt", "packages": ["gimp"]},
    ]

    successful, failed = run(
        inst.install_batch(recipes, col, mode="module", packaging="separate")
    )
    assert "vlc" in successful
    assert "gimp" in failed
    assert col.of_type("install_error")


def test_install_batch_separate_cancellation(tmp_path, monkeypatch):
    inst = Installer(str(tmp_path))

    def fake_run(cmd, cwd=None, env=None, line_callback=None):
        inst._cancelled = True
        raise InstallCancelled("cancelled")

    monkeypatch.setattr(inst, "_run_cmd", fake_run)
    col = Collector()
    recipes = [
        {"id": "a", "name": "A", "method": "apt", "packages": ["a"]},
        {"id": "b", "name": "B", "method": "apt", "packages": ["b"]},
    ]

    successful, failed = run(
        inst.install_batch(recipes, col, mode="module", packaging="separate")
    )
    assert successful == []
    assert set(failed) == {"a", "b"}


def test_install_batch_single_apt_cancellation(tmp_path, monkeypatch):
    inst = Installer(str(tmp_path))

    def fake_run(cmd, cwd=None, env=None, line_callback=None):
        inst._cancelled = True
        raise InstallCancelled("cancelled")

    monkeypatch.setattr(inst, "_run_cmd", fake_run)
    col = Collector()
    recipes = [{"id": "vlc", "name": "VLC", "method": "apt", "packages": ["vlc"]}]

    successful, failed = run(
        inst.install_batch(recipes, col, mode="module", packaging="single")
    )
    assert successful == []
    assert failed == ["vlc"]


def test_install_batch_single_mixed_cancellation(tmp_path, monkeypatch):
    inst = Installer(str(tmp_path))

    def fake_run(cmd, cwd=None, env=None, line_callback=None):
        inst._cancelled = True
        raise InstallCancelled("cancelled")

    monkeypatch.setattr(inst, "_run_cmd", fake_run)
    col = Collector()
    recipes = [
        {"id": "vlc", "name": "VLC", "method": "apt", "packages": ["vlc"]},
        {"id": "foo", "name": "Foo", "method": "script", "script": "echo hi"},
    ]

    successful, failed = run(
        inst.install_batch(recipes, col, mode="module", packaging="single")
    )
    assert successful == []
    assert set(failed) == {"vlc", "foo"}


def test_install_batch_single_mixed_failure(tmp_path, monkeypatch):
    inst = Installer(str(tmp_path))

    def fake_run(cmd, cwd=None, env=None, line_callback=None):
        raise InstallationError("script2sb failed")

    monkeypatch.setattr(inst, "_run_cmd", fake_run)
    col = Collector()
    recipes = [
        {"id": "vlc", "name": "VLC", "method": "apt", "packages": ["vlc"]},
        {"id": "foo", "name": "Foo", "method": "script", "script": "echo hi"},
    ]

    successful, failed = run(
        inst.install_batch(recipes, col, mode="module", packaging="single")
    )
    assert successful == []
    assert set(failed) == {"vlc", "foo"}
    assert col.of_type("install_error")
