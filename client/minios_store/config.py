"""Configuration constants for MiniOS Store daemon."""

import os
import subprocess
from typing import Dict, Optional, Tuple

# WebSocket server
WS_HOST = os.environ.get("MINIOS_STORE_HOST", "127.0.0.1")
WS_PORT = int(os.environ.get("MINIOS_STORE_PORT", "8765"))

# MiniOS paths
MINIOS_BASE = os.environ.get("MINIOS_BASE", "/run/initramfs/memory")
MODULES_DIR_PRIMARY = os.path.join(MINIOS_BASE, "data", "minios", "modules")
MODULES_DIR_FALLBACK = "/var/lib/minios-store/modules"

# Default modules directory (actual path determined at runtime by get_writable_modules_dir())
MODULES_DIR = MODULES_DIR_PRIMARY

# Default compression for apt2sb/script2sb (zstd, xz, gzip, lzo)
DEFAULT_COMPRESSION = "zstd"

# APT options to avoid interactive prompts
APT_ENV = {
    "DEBIAN_FRONTEND": "noninteractive",
    "DEBCONF_NONINTERACTIVE_SEEN": "true",
    "LC_ALL": "C",
}

# Ping/pong interval (seconds)
PING_INTERVAL = 30
PING_TIMEOUT = 10


def get_system_info() -> Dict[str, Optional[str]]:
    """Read distribution info from /etc/os-release.

    Returns:
        dict with keys: codename, id, name, version_id (any may be None)
    """
    info: Dict[str, Optional[str]] = {
        "codename": None,
        "id": None,
        "name": None,
        "version_id": None,
        "arch": None,
    }

    os_release_paths = ["/etc/os-release", "/usr/lib/os-release"]
    for path in os_release_paths:
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    # Strip quotes
                    value = value.strip('"').strip("'")
                    if key == "VERSION_CODENAME":
                        info["codename"] = value
                    elif key == "ID":
                        info["id"] = value
                    elif key == "NAME":
                        info["name"] = value
                    elif key == "VERSION_ID":
                        info["version_id"] = value
            break
        except OSError:
            continue

    # Get CPU architecture via dpkg (most reliable on Debian/Ubuntu)
    try:
        result = subprocess.run(
            ["dpkg", "--print-architecture"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            info["arch"] = result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        # dpkg not available, try uname -m as fallback
        try:
            result = subprocess.run(
                ["uname", "-m"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, timeout=5,
            )
            if result.returncode == 0:
                uname_arch = result.stdout.strip()
                # Map uname output to dpkg-style names
                arch_map = {
                    "x86_64": "amd64",
                    "i686": "i386",
                    "i386": "i386",
                    "aarch64": "arm64",
                    "armv7l": "armhf",
                }
                info["arch"] = arch_map.get(uname_arch, uname_arch)
        except (OSError, subprocess.TimeoutExpired):
            pass

    return info


def get_writable_modules_dir() -> Tuple[str, bool]:
    """Determine which modules directory to use.
    
    Returns:
        tuple of (directory_path, is_fallback)
        - directory_path: Path to use for storing modules
        - is_fallback: True if using fallback location
    """
    # Try primary location first
    try:
        os.makedirs(MODULES_DIR_PRIMARY, exist_ok=True)
        # Test write access by creating and removing a test file
        test_file = os.path.join(MODULES_DIR_PRIMARY, ".write_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.unlink(test_file)
        return MODULES_DIR_PRIMARY, False
    except (OSError, PermissionError):
        # Primary location not writable, try fallback
        pass
    
    # Fall back to /var/lib/minios-store/modules
    try:
        os.makedirs(MODULES_DIR_FALLBACK, mode=0o755, exist_ok=True)
        # Test write access to fallback as well
        test_file = os.path.join(MODULES_DIR_FALLBACK, ".write_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.unlink(test_file)
        return MODULES_DIR_FALLBACK, True
    except (OSError, PermissionError):
        # Even fallback failed, return it anyway and let installer fail with clear error
        return MODULES_DIR_FALLBACK, True
