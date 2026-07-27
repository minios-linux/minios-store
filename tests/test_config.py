import os
import sys

import subprocess


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))

from minios_store import config
from minios_store.config import is_native_system


def test_boot_live_is_not_native(tmp_path):
    cmdline = tmp_path / "cmdline"
    cmdline.write_text("quiet boot=live")

    assert not is_native_system(str(cmdline), str(tmp_path / "missing"))


def test_regular_boot_is_native(tmp_path):
    cmdline = tmp_path / "cmdline"
    cmdline.write_text("quiet root=UUID=test")

    assert is_native_system(str(cmdline), str(tmp_path))


def test_missing_cmdline_uses_live_runtime_fallback(tmp_path):
    live_root = tmp_path / "memory"
    live_root.mkdir()

    assert not is_native_system(str(tmp_path / "missing"), str(live_root))
    assert is_native_system(str(tmp_path / "missing"), str(tmp_path / "absent"))


# ---------------------------------------------------------------------------
# get_system_info
# ---------------------------------------------------------------------------

def _patch_os_release(monkeypatch, path):
    import builtins
    real_open = builtins.open

    def fake_open(target, *args, **kwargs):
        if target in ("/etc/os-release", "/usr/lib/os-release"):
            return real_open(str(path), *args, **kwargs)
        return real_open(target, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)


def test_get_system_info_parses_os_release(monkeypatch, tmp_path):
    osr = tmp_path / "os-release"
    osr.write_text(
        'VERSION_CODENAME=trixie\n'
        'ID=minios\n'
        'NAME="MiniOS"\n'
        'VERSION_ID="5"\n'
    )
    _patch_os_release(monkeypatch, osr)
    monkeypatch.setattr(config, "is_native_system", lambda: False)
    monkeypatch.setattr(
        config.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "amd64\n", ""),
    )

    info = config.get_system_info()
    assert info["codename"] == "trixie"
    assert info["id"] == "minios"
    assert info["name"] == "MiniOS"
    assert info["version_id"] == "5"
    assert info["arch"] == "amd64"
    assert info["is_native"] is False


def test_get_system_info_arch_uname_fallback(monkeypatch, tmp_path):
    osr = tmp_path / "os-release"
    osr.write_text("ID=minios\n")
    _patch_os_release(monkeypatch, osr)
    monkeypatch.setattr(config, "is_native_system", lambda: True)

    def fake_run(cmd, **kw):
        if cmd[0] == "dpkg":
            raise OSError("no dpkg")
        return subprocess.CompletedProcess(cmd, 0, "x86_64\n", "")

    monkeypatch.setattr(config.subprocess, "run", fake_run)

    info = config.get_system_info()
    assert info["arch"] == "amd64"  # x86_64 mapped to amd64
    assert info["is_native"] is True


def test_get_system_info_missing_os_release(monkeypatch):
    import builtins
    real_open = builtins.open

    def fake_open(target, *args, **kwargs):
        if target in ("/etc/os-release", "/usr/lib/os-release"):
            raise OSError("missing")
        return real_open(target, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)
    monkeypatch.setattr(config, "is_native_system", lambda: False)
    monkeypatch.setattr(
        config.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "arm64\n", ""),
    )

    info = config.get_system_info()
    assert info["codename"] is None
    assert info["id"] is None
    assert info["arch"] == "arm64"


# ---------------------------------------------------------------------------
# get_writable_modules_dir
# ---------------------------------------------------------------------------

def test_get_writable_modules_dir_primary(tmp_path, monkeypatch):
    primary = tmp_path / "primary"
    monkeypatch.setattr(config, "MODULES_DIR_PRIMARY", str(primary))
    path, is_fallback = config.get_writable_modules_dir()
    assert path == str(primary)
    assert is_fallback is False
    assert primary.exists()


def test_get_writable_modules_dir_falls_back(tmp_path, monkeypatch):
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"
    monkeypatch.setattr(config, "MODULES_DIR_PRIMARY", str(primary))
    monkeypatch.setattr(config, "MODULES_DIR_FALLBACK", str(fallback))

    real_makedirs = os.makedirs

    def fake_makedirs(path, *args, **kwargs):
        if str(path).startswith(str(primary)):
            raise PermissionError("read-only")
        return real_makedirs(path, *args, **kwargs)

    monkeypatch.setattr(config.os, "makedirs", fake_makedirs)

    path, is_fallback = config.get_writable_modules_dir()
    assert path == str(fallback)
    assert is_fallback is True
    assert fallback.exists()


def test_get_writable_modules_dir_both_fail(monkeypatch):
    monkeypatch.setattr(
        config.os, "makedirs",
        lambda *a, **k: (_ for _ in ()).throw(OSError("nope")),
    )
    path, is_fallback = config.get_writable_modules_dir()
    assert path == config.MODULES_DIR_FALLBACK
    assert is_fallback is True
