#!/usr/bin/env python3
"""Auto-populate MiniOS Store recipes from Debian/Ubuntu AppStream metadata.

Downloads DEP-11 AppStream YAML from repository mirrors, parses desktop
application components, maps them to store categories, and generates
YAML recipe files.

Usage:
    # Parse Debian Trixie, generate recipes
    python3 tools/repo_parser.py --dist trixie

    # Parse Ubuntu Noble, custom mirror
    python3 tools/repo_parser.py --dist noble --mirror http://archive.ubuntu.com/ubuntu

    # Update distribution tags on existing recipes
    python3 tools/repo_parser.py --dist bookworm --update-existing

    # Dry run: show what would be generated
    python3 tools/repo_parser.py --dist trixie --dry-run

    # Parse multiple distributions at once
    python3 tools/repo_parser.py --dist bookworm trixie sid

    # Custom architecture
    python3 tools/repo_parser.py --dist trixie --arch arm64
"""

import argparse
import gzip
import logging
import os
import sys
import textwrap
import urllib.error
import urllib.request

# PyYAML is optional but strongly recommended for AppStream parsing
try:
    import yaml
except ImportError:
    yaml = None

logger = logging.getLogger("repo_parser")

# ============================================
# Distribution Configuration
# ============================================

DEBIAN_MIRROR = "https://deb.debian.org/debian"
DEBIAN_ARCHIVE = "https://archive.debian.org/debian"
UBUNTU_MIRROR = "http://archive.ubuntu.com/ubuntu"

# Debian components by era:
# - buster/bullseye: main, contrib, non-free (no non-free-firmware split yet)
# - bookworm+: main, contrib, non-free, non-free-firmware (split in bookworm)
_DEBIAN_OLD = ["main", "contrib", "non-free"]
_DEBIAN_NEW = ["main", "contrib", "non-free", "non-free-firmware"]

# Map codename -> (family, mirror, components)
DISTRIBUTIONS = {
    # Debian (archived — no longer on deb.debian.org)
    "buster": ("debian", DEBIAN_ARCHIVE, _DEBIAN_OLD),
    # Debian (release suites)
    "bullseye": ("debian", DEBIAN_MIRROR, _DEBIAN_OLD),
    "bookworm": ("debian", DEBIAN_MIRROR, _DEBIAN_NEW),
    "trixie": ("debian", DEBIAN_MIRROR, _DEBIAN_NEW),
    "sid": ("debian", DEBIAN_MIRROR, _DEBIAN_NEW),
    # Debian (backports)
    "bullseye-backports": ("debian", DEBIAN_MIRROR, _DEBIAN_OLD),
    "bookworm-backports": ("debian", DEBIAN_MIRROR, _DEBIAN_NEW),
    "trixie-backports": ("debian", DEBIAN_MIRROR, _DEBIAN_NEW),
    # Ubuntu
    "bionic": ("ubuntu", UBUNTU_MIRROR, ["main", "universe"]),
    "focal": ("ubuntu", UBUNTU_MIRROR, ["main", "universe"]),
    "jammy": ("ubuntu", UBUNTU_MIRROR, ["main", "universe"]),
    "noble": ("ubuntu", UBUNTU_MIRROR, ["main", "universe"]),
}

# ============================================
# FreeDesktop Category -> Store Category Mapping
# ============================================

# Maps FreeDesktop .desktop categories to store category IDs
CATEGORY_MAP = {
    # Internet
    "Network": "internet",
    "WebBrowser": "internet",
    "Email": "internet",
    "Chat": "internet",
    "InstantMessaging": "internet",
    "IRCClient": "internet",
    "FileTransfer": "internet",
    "P2P": "internet",
    "RemoteAccess": "internet",
    "Telephony": "internet",
    "VideoConference": "internet",
    # Multimedia
    "AudioVideo": "multimedia",
    "Audio": "multimedia",
    "Video": "multimedia",
    "Midi": "multimedia",
    "Mixer": "multimedia",
    "Sequencer": "multimedia",
    "Tuner": "multimedia",
    "Player": "multimedia",
    "Recorder": "multimedia",
    "Music": "multimedia",
    # Graphics
    "Graphics": "graphics",
    "2DGraphics": "graphics",
    "3DGraphics": "graphics",
    "VectorGraphics": "graphics",
    "RasterGraphics": "graphics",
    "Photography": "graphics",
    "Scanning": "graphics",
    "ImageViewer": "graphics",
    # Office
    "Office": "office",
    "WordProcessor": "office",
    "Spreadsheet": "office",
    "Presentation": "office",
    "Publishing": "office",
    "Calendar": "office",
    "ContactManagement": "office",
    "ProjectManagement": "office",
    "Finance": "office",
    # Development
    "Development": "development",
    "IDE": "development",
    "TextEditor": "development",
    "Debugger": "development",
    "RevisionControl": "development",
    "WebDevelopment": "development",
    "GUIDesigner": "development",
    "Profiling": "development",
    "Translation": "development",
    "Building": "development",
    # Games
    "Game": "games",
    "ActionGame": "games",
    "AdventureGame": "games",
    "ArcadeGame": "games",
    "BoardGame": "games",
    "BlocksGame": "games",
    "CardGame": "games",
    "KidsGame": "games",
    "LogicGame": "games",
    "RolePlaying": "games",
    "Shooter": "games",
    "Simulation": "games",
    "SportsGame": "games",
    "StrategyGame": "games",
    # System
    "System": "system",
    "Settings": "system",
    "PackageManager": "system",
    "Monitor": "system",
    "TerminalEmulator": "system",
    "FileManager": "system",
    "FileTools": "system",
    "Filesystem": "system",
    "Security": "security",
    # Science & Education
    "Science": "development",
    "Education": "office",
    "Math": "office",
    "Astronomy": "development",
    "Biology": "development",
    "Chemistry": "development",
    "Physics": "development",
    # Accessibility / Utility
    "Utility": "system",
    "Accessibility": "system",
    "Core": "system",
}

# Priority order: if a package has multiple categories, prefer this order
CATEGORY_PRIORITY = [
    "internet", "multimedia", "graphics", "office",
    "development", "games", "security", "system",
]

# ============================================
# Icon Mapping (FreeDesktop icon names -> lucide-react)
# ============================================

# Best-effort mapping from common icon names to lucide-react icons
ICON_MAP = {
    # Browsers
    "firefox": "Globe",
    "firefox-esr": "Globe",
    "chromium": "Globe",
    "chromium-browser": "Globe",
    "google-chrome": "Globe",
    "epiphany": "Globe",
    "midori": "Globe",
    "falkon": "Globe",
    "web-browser": "Globe",
    # Email / Chat
    "thunderbird": "Mail",
    "evolution": "Mail",
    "geary": "Mail",
    "telegram": "MessageCircle",
    "signal": "MessageCircle",
    "pidgin": "MessageCircle",
    "hexchat": "MessageCircle",
    "element": "MessageCircle",
    "discord": "MessageCircle",
    # File transfer / Remote
    "filezilla": "Download",
    "transmission": "Download",
    "deluge": "Download",
    "qbittorrent": "Download",
    "remmina": "Monitor",
    "vinagre": "Monitor",
    "x11vnc": "Monitor",
    # Multimedia
    "vlc": "Video",
    "mpv": "Video",
    "totem": "Video",
    "celluloid": "Video",
    "kodi": "Video",
    "audacity": "Music",
    "rhythmbox": "Music",
    "clementine": "Music",
    "lmms": "Music",
    "obs-studio": "Video",
    "kdenlive": "Video",
    "shotcut": "Video",
    "pitivi": "Video",
    "openshot": "Video",
    "handbrake": "Video",
    "sound-juicer": "Music",
    # Graphics
    "gimp": "Palette",
    "inkscape": "Palette",
    "blender": "Palette",
    "krita": "Palette",
    "darktable": "Camera",
    "rawtherapee": "Camera",
    "shotwell": "Camera",
    "digikam": "Camera",
    "eog": "Image",
    "ristretto": "Image",
    "feh": "Image",
    "gthumb": "Image",
    "gwenview": "Image",
    "drawing": "Palette",
    "pinta": "Palette",
    "scribus": "FileText",
    # Office
    "libreoffice": "FileText",
    "libreoffice-writer": "FileText",
    "libreoffice-calc": "FileText",
    "libreoffice-impress": "FileText",
    "libreoffice-draw": "FileText",
    "libreoffice-base": "Database",
    "abiword": "FileText",
    "gnumeric": "FileText",
    "evince": "BookOpen",
    "okular": "BookOpen",
    "zathura": "BookOpen",
    "calibre": "BookOpen",
    "pdfarranger": "FileText",
    # Development
    "code": "Code",
    "codium": "Code",
    "vscodium": "Code",
    "gedit": "Code",
    "kate": "Code",
    "mousepad": "Code",
    "pluma": "Code",
    "geany": "Code",
    "gnome-builder": "Code",
    "meld": "Code",
    "gitg": "Code",
    "ghex": "Code",
    # Games
    "supertuxkart": "Gamepad2",
    "minetest": "Gamepad2",
    "0ad": "Gamepad2",
    "openttd": "Gamepad2",
    "wesnoth": "Gamepad2",
    "xonotic": "Gamepad2",
    "frozen-bubble": "Gamepad2",
    "gnome-chess": "Gamepad2",
    "gnome-mines": "Gamepad2",
    "gnome-sudoku": "Gamepad2",
    "aisleriot": "Gamepad2",
    # System
    "gparted": "HardDrive",
    "gnome-disks": "HardDrive",
    "grsync": "FolderOpen",
    "doublecmd": "FolderOpen",
    "thunar": "FolderOpen",
    "nautilus": "FolderOpen",
    "nemo": "FolderOpen",
    "pcmanfm": "FolderOpen",
    "dolphin": "FolderOpen",
    "synaptic": "Package",
    "software-center": "Package",
    "gnome-terminal": "Terminal",
    "xfce4-terminal": "Terminal",
    "konsole": "Terminal",
    "tilix": "Terminal",
    "alacritty": "Terminal",
    "htop": "Gauge",
    "gnome-system-monitor": "Gauge",
    "ksysguard": "Gauge",
    "task-manager": "Gauge",
    "hardinfo": "Cpu",
    "bleachbit": "Wrench",
    "galculator": "Wrench",
    "timeshift": "Wrench",
    "virt-manager": "Monitor",
    "virtualbox": "Monitor",
    # Security
    "keepassxc": "Lock",
    "veracrypt": "Shield",
    "wireshark": "Shield",
    "guymager": "Shield",
    "clamtk": "Shield",
    "seahorse": "Lock",
    "gnome-keyring": "Lock",
}

# Fallback icon based on category
CATEGORY_ICON_FALLBACK = {
    "internet": "Globe",
    "multimedia": "Video",
    "graphics": "Palette",
    "office": "FileText",
    "development": "Code",
    "games": "Gamepad2",
    "system": "Wrench",
    "security": "Shield",
}


# ============================================
# AppStream DEP-11 Parser
# ============================================

def fetch_dep11(mirror, codename, component, arch):
    """Download and decompress DEP-11 AppStream metadata.

    Args:
        mirror: Repository mirror URL.
        codename: Distribution codename (e.g. 'trixie').
        component: Repository component (e.g. 'main').
        arch: Architecture (e.g. 'amd64').

    Returns:
        Raw YAML text or None if not found.
    """
    url = "{mirror}/dists/{codename}/{component}/dep11/Components-{arch}.yml.gz".format(
        mirror=mirror.rstrip("/"),
        codename=codename,
        component=component,
        arch=arch,
    )

    logger.info("Fetching %s", url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MiniOS-Store-RepoParser/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            compressed = resp.read()
        return gzip.decompress(compressed).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            logger.warning("DEP-11 not found at %s (404)", url)
            return None
        raise
    except Exception as e:
        logger.error("Failed to fetch %s: %s", url, e)
        return None


def parse_dep11_documents(text):
    """Parse multi-document YAML from DEP-11 AppStream data.

    Args:
        text: Raw YAML text containing multiple documents separated by '---'.

    Yields:
        Parsed YAML documents (dicts).
    """
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required for DEP-11 parsing. Install it: pip install pyyaml"
        )

    for doc in yaml.safe_load_all(text):
        if doc is not None:
            yield doc


def is_desktop_application(doc):
    """Check if an AppStream component is a user-installable application.

    Follows KDE Discover behavior: shows desktop, web, and console applications.

    Args:
        doc: Parsed AppStream component dict.

    Returns:
        True if this is an installable application.
    """
    comp_type = doc.get("Type")
    return comp_type in ("desktop-application", "web-application", "console-application")


def extract_app_info(doc):
    """Extract relevant info from an AppStream component.

    Args:
        doc: Parsed AppStream component dict.

    Returns:
        Dict with extracted fields, or None if insufficient data.
    """
    comp_id = doc.get("ID", "")
    if not comp_id:
        return None

    # Name: can be a dict (localized) or string
    name_raw = doc.get("Name", {})
    if isinstance(name_raw, dict):
        name = name_raw.get("C") or name_raw.get("en") or ""
        if not name:
            # Try first available
            for v in name_raw.values():
                if v:
                    name = v
                    break
    else:
        name = str(name_raw)

    if not name:
        return None

    # Summary (short description)
    summary_raw = doc.get("Summary", {})
    if isinstance(summary_raw, dict):
        summary = summary_raw.get("C") or summary_raw.get("en") or ""
        if not summary:
            for v in summary_raw.values():
                if v:
                    summary = v
                    break
    else:
        summary = str(summary_raw)

    # Description (long, may be HTML-ish)
    desc_raw = doc.get("Description", {})
    if isinstance(desc_raw, dict):
        description = desc_raw.get("C") or desc_raw.get("en") or ""
        if not description:
            for v in desc_raw.values():
                if v:
                    description = v
                    break
    else:
        description = str(desc_raw) if desc_raw else ""

    # Package name
    package = doc.get("Package", "")
    if not package:
        pkgs = doc.get("Pkgname", [])
        if isinstance(pkgs, list) and pkgs:
            package = pkgs[0]

    if not package:
        return None

    # Categories
    categories = doc.get("Categories", [])
    if not isinstance(categories, list):
        categories = []

    # Icon
    icon_data = doc.get("Icon", {})
    icon_name = ""
    if isinstance(icon_data, dict):
        # Try stock icons first
        stock = icon_data.get("stock", "")
        if stock:
            icon_name = stock
        else:
            # cached icons
            cached = icon_data.get("cached", [])
            if isinstance(cached, list) and cached:
                if isinstance(cached[0], dict):
                    icon_name = cached[0].get("name", "")
                else:
                    icon_name = str(cached[0])

    # Keywords
    keywords_raw = doc.get("Keywords", {})
    keywords = []
    if isinstance(keywords_raw, dict):
        kw = keywords_raw.get("C") or keywords_raw.get("en") or []
        if isinstance(kw, list):
            keywords = kw
    elif isinstance(keywords_raw, list):
        keywords = keywords_raw

    # Project license
    project_license = doc.get("ProjectLicense", "")

    # Icon sources (relative URLs from AppStream media for real app icons)
    icon_sources = []
    if isinstance(icon_data, dict):
        remote = icon_data.get("remote", [])
        if isinstance(remote, list):
            for ri in remote:
                if isinstance(ri, dict) and ri.get("url"):
                    icon_sources.append({
                        "url": ri["url"],
                        "width": int(ri.get("width", 0)),
                        "height": int(ri.get("height", 0)),
                    })
        # If no remote icons, try cached (from dep11 icons tarball)
        if not icon_sources:
            cached = icon_data.get("cached", [])
            if isinstance(cached, list):
                # Pick the largest cached icon
                best = None
                best_w = 0
                for ci in cached:
                    if isinstance(ci, dict) and ci.get("name"):
                        w = int(ci.get("width", 0))
                        if w > best_w:
                            best = ci
                            best_w = w
                if best:
                    icon_sources.append({
                        "cached": best["name"],
                        "width": int(best.get("width", 0)),
                        "height": int(best.get("height", 0)),
                    })

    # Developer name
    dev_raw = doc.get("DeveloperName", {})
    if isinstance(dev_raw, dict):
        developer = dev_raw.get("C") or dev_raw.get("en") or ""
        if not developer:
            for v in dev_raw.values():
                if v:
                    developer = v
                    break
    else:
        developer = str(dev_raw) if dev_raw else ""

    # Homepage URL
    urls = doc.get("Url", {})
    homepage = ""
    if isinstance(urls, dict):
        homepage = urls.get("homepage", "")

    # Version from Releases (latest release) — no longer extracted
    # (version is not stored in recipes)

    # Screenshots (relative URLs from AppStream media)
    screenshots_raw = doc.get("Screenshots", [])
    screenshots = []
    if isinstance(screenshots_raw, list):
        for shot in screenshots_raw:
            if not isinstance(shot, dict):
                continue
            source = shot.get("source-image", {})
            if not isinstance(source, dict):
                continue
            source_url = source.get("url", "")
            if not source_url:
                continue

            entry = {"url": source_url}

            # Include source image dimensions if available
            if source.get("width"):
                entry["width"] = int(source["width"])
            if source.get("height"):
                entry["height"] = int(source["height"])

            # Pick the best thumbnail (prefer ~624px width, fallback to largest)
            thumbnails = shot.get("thumbnails", [])
            if isinstance(thumbnails, list) and thumbnails:
                best_thumb = None
                best_width = 0
                for thumb in thumbnails:
                    if not isinstance(thumb, dict):
                        continue
                    tw = int(thumb.get("width", 0))
                    thumb_url = thumb.get("url", "")
                    if not thumb_url:
                        continue
                    # Prefer ~624px, otherwise take the largest
                    if best_thumb is None or abs(tw - 624) < abs(best_width - 624):
                        best_thumb = thumb_url
                        best_width = tw
                if best_thumb:
                    entry["thumbnailUrl"] = best_thumb

            screenshots.append(entry)

    return {
        "appstream_id": comp_id,
        "name": name.strip(),
        "summary": summary.strip(),
        "description": description.strip() if description else "",
        "package": package.strip(),
        "categories": categories,
        "icon_name": icon_name,
        "icon_sources": icon_sources,
        "keywords": [str(k).lower() for k in keywords if k],
        "license": project_license,
        "screenshots": screenshots,
        "developer": developer.strip() if developer else "",
        "homepage": homepage.strip() if homepage else "",
    }


# ============================================
# Recipe Generation
# ============================================

def map_category(categories):
    """Map FreeDesktop categories to a store category ID.

    Args:
        categories: List of FreeDesktop category strings.

    Returns:
        Store category ID string.
    """
    found = set()
    for cat in categories:
        store_cat = CATEGORY_MAP.get(cat)
        if store_cat:
            found.add(store_cat)

    if not found:
        return "system"  # fallback

    # Use priority order
    for cat_id in CATEGORY_PRIORITY:
        if cat_id in found:
            return cat_id

    return found.pop()


def map_icon(app_info, category_id):
    """Map an application's icon to a lucide-react icon name.

    Args:
        app_info: Application info dict.
        category_id: Resolved store category ID.

    Returns:
        lucide-react icon name string.
    """
    package = app_info["package"]

    # Try exact package name match first
    if package in ICON_MAP:
        return ICON_MAP[package]

    # Try icon name
    icon_name = app_info.get("icon_name", "")
    if icon_name:
        # Strip extension and path
        base = os.path.splitext(os.path.basename(icon_name))[0]
        if base in ICON_MAP:
            return ICON_MAP[base]

        # Try lowercase
        base_lower = base.lower()
        for key, val in ICON_MAP.items():
            if key in base_lower or base_lower in key:
                return val

    # Try appstream ID
    app_id = app_info.get("appstream_id", "")
    if app_id:
        # e.g. "org.gnome.Calculator" -> "calculator"
        parts = app_id.lower().split(".")
        for part in reversed(parts):
            if part in ICON_MAP:
                return ICON_MAP[part]

    # Fallback to category icon
    return CATEGORY_ICON_FALLBACK.get(category_id, "Package")


def generate_recipe_id(app_info):
    """Generate a unique recipe ID from package/app info.

    Args:
        app_info: Application info dict.

    Returns:
        Recipe ID string.
    """
    # Use package name as ID (it's unique per repository)
    return app_info["package"].lower().replace("+", "plus").replace(".", "-")


def app_to_recipe(app_info, codename, arch):
    """Convert parsed app info to a recipe dict.

    Args:
        app_info: Application info dict from extract_app_info().
        codename: Distribution codename.
        arch: Architecture string (e.g. 'amd64', 'i386').

    Returns:
        Recipe dict matching the YAML recipe format.
    """
    category_id = map_category(app_info["categories"])
    icon = map_icon(app_info, category_id)
    recipe_id = generate_recipe_id(app_info)

    recipe = {
        "id": recipe_id,
        "name": app_info["name"],
        "description": app_info["summary"] or "Desktop application",
        "categoryId": category_id,
        "icon": icon,
        "method": "apt",
        "level": "auto",
        "compression": "zstd",
        "packages": [app_info["package"]],
        "distributions": {
            "include": [
                {"name": codename, "architectures": [arch]},
            ],
        },
        "enabled": True,
        "order": 99,
    }

    # Add long description if available
    if app_info["description"] and app_info["description"] != app_info["summary"]:
        recipe["longDescription"] = app_info["description"]

    # Add tags from keywords
    if app_info["keywords"]:
        recipe["tags"] = app_info["keywords"][:10]  # limit to 10 tags

    # Add screenshot sources from AppStream metadata (relative URLs)
    if app_info.get("screenshots"):
        recipe["screenshotSources"] = app_info["screenshots"]

    # Add icon sources from AppStream metadata (relative URLs)
    if app_info.get("icon_sources"):
        recipe["iconSources"] = app_info["icon_sources"]

    # Add developer name
    if app_info.get("developer"):
        recipe["developer"] = app_info["developer"]

    # Add homepage URL
    if app_info.get("homepage"):
        recipe["homepage"] = app_info["homepage"]

    return recipe


# ============================================
# YAML Output
# ============================================

def recipe_to_yaml(recipe):
    """Serialize a recipe dict to YAML string.

    Uses manual formatting for clean, consistent output matching
    the existing recipe file style.

    Args:
        recipe: Recipe dict.

    Returns:
        YAML string.
    """
    lines = []

    def add(key, value, quote=False):
        if value is None:
            return
        if isinstance(value, bool):
            lines.append("{}: {}".format(key, "true" if value else "false"))
        elif isinstance(value, (int, float)):
            lines.append("{}: {}".format(key, value))
        elif quote or not value:
            lines.append('{}: "{}"'.format(key, str(value).replace('"', '\\"')))
        else:
            # Check if value needs quoting
            val = str(value)
            # If value contains double quotes, use single quotes
            if '"' in val:
                lines.append("{}: '{}'".format(key, val.replace("'", "''")))
            elif any(c in val for c in (":", "#", "{", "}", "[", "]", ",")):
                lines.append('{}: "{}"'.format(key, val.replace('"', '\\"')))
            else:
                lines.append("{}: {}".format(key, val))

    add("id", recipe["id"], quote=True)
    add("name", recipe["name"])
    add("description", recipe["description"])

    # Long description as block scalar
    long_desc = recipe.get("longDescription", "")
    if long_desc:
        lines.append("longDescription: |")
        for ld_line in long_desc.split("\n"):
            lines.append("  " + ld_line)

    add("categoryId", recipe["categoryId"])
    add("icon", recipe["icon"])
    add("method", recipe["method"])
    add("level", recipe["level"], quote=True)
    add("compression", recipe["compression"])

    # Packages
    packages = recipe.get("packages", [])
    if packages:
        lines.append("packages:")
        for pkg in packages:
            lines.append("  - {}".format(pkg))

    # Distributions (new per-distribution architecture format)
    distributions = recipe.get("distributions", {})
    if distributions:
        include = distributions.get("include", [])
        exclude = distributions.get("exclude", [])
        if include or exclude:
            lines.append("distributions:")
            if include:
                lines.append("  include:")
                for entry in include:
                    if isinstance(entry, dict):
                        lines.append("    - name: {}".format(entry["name"]))
                        archs = entry.get("architectures", [])
                        if archs:
                            lines.append("      architectures: [{}]".format(", ".join(archs)))
                    else:
                        # Legacy string format fallback
                        lines.append("    - name: {}".format(entry))
            if exclude:
                lines.append("  exclude:")
                for entry in exclude:
                    if isinstance(entry, dict):
                        lines.append("    - name: {}".format(entry["name"]))
                        archs = entry.get("architectures", [])
                        if archs:
                            lines.append("      architectures: [{}]".format(", ".join(archs)))
                    else:
                        lines.append("    - name: {}".format(entry))

    # Tags
    tags = recipe.get("tags", [])
    if tags:
        lines.append("tags:")
        for tag in tags:
            lines.append("  - {}".format(tag))

    # Screenshot sources (AppStream relative URLs)
    screenshot_sources = recipe.get("screenshotSources", [])
    if screenshot_sources:
        lines.append("screenshotSources:")
        for src in screenshot_sources:
            lines.append("  - url: {}".format(src["url"]))
            if src.get("thumbnailUrl"):
                lines.append("    thumbnailUrl: {}".format(src["thumbnailUrl"]))
            if src.get("width"):
                lines.append("    width: {}".format(src["width"]))
            if src.get("height"):
                lines.append("    height: {}".format(src["height"]))

    # Icon sources (AppStream relative URLs or cached names)
    icon_sources = recipe.get("iconSources", [])
    if icon_sources:
        lines.append("iconSources:")
        for src in icon_sources:
            if src.get("url"):
                lines.append("  - url: {}".format(src["url"]))
            elif src.get("cached"):
                lines.append("  - cached: {}".format(src["cached"]))
            if src.get("width"):
                lines.append("    width: {}".format(src["width"]))
            if src.get("height"):
                lines.append("    height: {}".format(src["height"]))

    # Developer name
    if recipe.get("developer"):
        add("developer", recipe["developer"])

    # Homepage URL
    if recipe.get("homepage"):
        add("homepage", recipe["homepage"])

    add("enabled", recipe.get("enabled", True))
    add("order", recipe.get("order", 99))

    return "\n".join(lines) + "\n"


# ============================================
# Main Logic
# ============================================

def load_existing_recipes(recipes_dir):
    """Load existing recipe IDs and their data.

    Args:
        recipes_dir: Path to the recipes/ directory.

    Returns:
        Dict mapping recipe_id -> (filepath, recipe_dict).
    """
    existing = {}
    if not os.path.isdir(recipes_dir):
        return existing

    for root, _dirs, files in os.walk(recipes_dir):
        for filename in files:
            if not filename.endswith((".yaml", ".yml")):
                continue
            filepath = os.path.join(root, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                if yaml is not None:
                    data = yaml.safe_load(content)
                else:
                    # Minimal parsing to get ID
                    data = {}
                    for line in content.split("\n"):
                        if line.startswith("id:"):
                            data["id"] = line.split(":", 1)[1].strip()
                            break
                if data and data.get("id"):
                    existing[str(data["id"])] = (filepath, data)
            except Exception as e:
                logger.warning("Failed to load %s: %s", filepath, e)

    return existing


def update_existing_recipe_distributions(filepath, recipe_data, codename, arch,
                                         screenshot_sources=None,
                                         icon_sources=None,
                                         developer=None,
                                         homepage=None):
    """Update an existing recipe's distributions with codename+arch.

    Finds or creates a distribution entry matching codename, then ensures
    the architecture is present in that entry's architectures list.
    Also populates screenshotSources, iconSources, developer, and homepage
    from DEP-11. screenshotSources and iconSources are always overwritten
    (hashes change when Debian updates metadata). developer and homepage
    use fill-if-empty strategy (stable values).

    Args:
        filepath: Path to the recipe YAML file.
        recipe_data: Parsed recipe dict.
        codename: Distribution codename to add.
        arch: Architecture string to add (e.g. 'amd64', 'i386').
        screenshot_sources: Optional list of screenshot source dicts from DEP-11.
        icon_sources: Optional list of icon source dicts from DEP-11.
        developer: Optional developer name string.
        homepage: Optional homepage URL string.

    Returns:
        True if the file was modified.
    """
    if yaml is None:
        logger.warning("PyYAML required for --update-existing; skipping %s", filepath)
        return False

    distributions = recipe_data.get("distributions", {})
    if not isinstance(distributions, dict):
        distributions = {}

    include = distributions.get("include", [])
    if not isinstance(include, list):
        include = []

    # Find existing entry for this codename
    entry = None
    for item in include:
        if isinstance(item, dict) and item.get("name") == codename:
            entry = item
            break
        elif isinstance(item, str) and item == codename:
            # Legacy string format — upgrade to dict
            idx = include.index(item)
            entry = {"name": codename, "architectures": []}
            include[idx] = entry
            break

    modified = False

    if entry is None:
        # Add new entry
        entry = {"name": codename, "architectures": [arch]}
        include.append(entry)
        # Sort entries by name
        include.sort(key=lambda e: e["name"] if isinstance(e, dict) else e)
        modified = True
    else:
        # Ensure arch is in the architectures list
        archs = entry.get("architectures", [])
        if not isinstance(archs, list):
            archs = []
        if arch not in archs:
            archs.append(arch)
            archs.sort()
            entry["architectures"] = archs
            modified = True

    # Always overwrite screenshotSources and iconSources from DEP-11.
    # These contain hashes that change when Debian updates metadata,
    # so stale values would cause download failures in build_recipes.py.
    if screenshot_sources and recipe_data.get("screenshotSources") != screenshot_sources:
        recipe_data["screenshotSources"] = screenshot_sources
        modified = True

    if icon_sources and recipe_data.get("iconSources") != icon_sources:
        recipe_data["iconSources"] = icon_sources
        modified = True

    # Populate developer if not already present
    if developer and not recipe_data.get("developer"):
        recipe_data["developer"] = developer
        modified = True

    # Populate homepage if not already present
    if homepage and not recipe_data.get("homepage"):
        recipe_data["homepage"] = homepage
        modified = True

    if not modified:
        return False

    # Update recipe_data in memory
    recipe_data.setdefault("distributions", {})["include"] = include

    # Remove legacy top-level architectures if present
    recipe_data.pop("architectures", None)

    # Rewrite the file using recipe_to_yaml for consistent formatting
    yaml_content = recipe_to_yaml(recipe_data)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(yaml_content)
    return True


def parse_distribution(codename, arch, mirror_override=None, recipes_dir="recipes",
                       update_existing=False, dry_run=False):
    """Parse a single distribution and generate recipes.

    Extracts application metadata from DEP-11 AppStream components.
    Follows KDE Discover behavior: includes desktop, web, and console applications.

    Args:
        codename: Distribution codename.
        arch: Architecture string.
        mirror_override: Custom mirror URL (overrides default).
        recipes_dir: Path to recipes directory.
        update_existing: If True, update distribution tags on existing recipes.
        dry_run: If True, don't write files.

    Returns:
        Tuple of (new_count, updated_count, skipped_count).
    """
    if codename not in DISTRIBUTIONS:
        logger.error("Unknown distribution: %s", codename)
        logger.error("Supported: %s", ", ".join(sorted(DISTRIBUTIONS.keys())))
        return 0, 0, 0

    family, default_mirror, components = DISTRIBUTIONS[codename]
    mirror = mirror_override or default_mirror

    logger.info("Parsing %s (%s) arch=%s from %s",
                codename, family, arch, mirror)

    # Load existing recipes
    existing = load_existing_recipes(recipes_dir)
    logger.info("Found %d existing recipes", len(existing))

    # Collect DEP-11 metadata from all components
    all_apps = {}  # package -> app_info

    for component in components:
        text = fetch_dep11(mirror, codename, component, arch)
        if text is None:
            logger.warning("No DEP-11 data for %s/%s/%s", codename, component, arch)
            continue

        count = 0
        for doc in parse_dep11_documents(text):
            if not is_desktop_application(doc):
                continue

            app_info = extract_app_info(doc)
            if app_info is None:
                continue

            pkg = app_info["package"]
            # Prefer first occurrence (main over contrib/universe)
            if pkg not in all_apps:
                all_apps[pkg] = app_info
                count += 1

        logger.info("DEP-11: %d apps in %s/%s", count, codename, component)

    logger.info("Total: %d unique applications from DEP-11", len(all_apps))

    return _process_apps(all_apps, existing, codename, arch,
                         recipes_dir, update_existing, dry_run)


def _process_apps(all_apps, existing, codename, arch,
                  recipes_dir, update_existing, dry_run):
    """Process discovered apps: create new recipes or update existing ones.

    Args:
        all_apps: Dict mapping package_name -> app_info.
        existing: Dict mapping recipe_id -> (filepath, recipe_data).
        codename: Distribution codename.
        arch: Architecture string.
        recipes_dir: Path to recipes directory.
        update_existing: If True, update distribution tags on existing recipes.
        dry_run: If True, don't write files.

    Returns:
        Tuple of (new_count, updated_count, skipped_count).
    """
    new_count = 0
    updated_count = 0
    skipped_count = 0

    for pkg, app_info in sorted(all_apps.items()):
        recipe = app_to_recipe(app_info, codename, arch)
        recipe_id = recipe["id"]

        if recipe_id in existing:
            if update_existing:
                filepath, recipe_data = existing[recipe_id]
                if not dry_run:
                    modified = update_existing_recipe_distributions(
                        filepath, recipe_data, codename, arch,
                        screenshot_sources=app_info.get("screenshots"),
                        icon_sources=app_info.get("icon_sources"),
                        developer=app_info.get("developer"),
                        homepage=app_info.get("homepage"),
                    )
                    if modified:
                        logger.info("Updated %s: distributions (+%s/%s)", recipe_id, codename, arch)
                        updated_count += 1
                    else:
                        skipped_count += 1
                else:
                    logger.info("[DRY-RUN] Would update: %s", recipe_id)
                    updated_count += 1
            else:
                skipped_count += 1
            continue

        # New recipe
        source = app_info.get("_source", "dep11")
        category_dir = os.path.join(recipes_dir, recipe["categoryId"])
        filepath = os.path.join(category_dir, "{}.yaml".format(recipe_id))

        if dry_run:
            logger.info("[DRY-RUN] Would create: %s (%s) [%s]",
                        recipe_id, recipe["name"], source)
            new_count += 1
            continue

        os.makedirs(category_dir, exist_ok=True)
        yaml_content = recipe_to_yaml(recipe)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(yaml_content)

        logger.info("Created: %s -> %s [%s]", recipe_id, filepath, source)
        new_count += 1

        # Add to existing so subsequent distributions don't re-create
        existing[recipe_id] = (filepath, recipe)

    return new_count, updated_count, skipped_count


def main():
    parser = argparse.ArgumentParser(
        description="Auto-populate MiniOS Store recipes from repository AppStream metadata",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Supported distributions:
              Debian:    buster*, bullseye, bookworm, trixie, sid
              Backports: bullseye-backports, bookworm-backports, trixie-backports
              Ubuntu:    bionic, focal, jammy, noble
              (* = archived, fetched from archive.debian.org)

            Components parsed:
              Debian buster/bullseye: main, contrib, non-free
              Debian bookworm+:      main, contrib, non-free, non-free-firmware
              Ubuntu:                main, universe

            Examples:
              %(prog)s --dist trixie
              %(prog)s --dist bookworm trixie
              %(prog)s --dist bookworm-backports trixie-backports
              %(prog)s --dist noble --mirror http://archive.ubuntu.com/ubuntu
              %(prog)s --dist trixie --arch amd64 i386
              %(prog)s --dist trixie --dry-run
        """),
    )
    parser.add_argument(
        "--dist", "-d",
        nargs="+",
        required=True,
        help="Distribution codename(s) to parse",
    )
    parser.add_argument(
        "--arch", "-a",
        nargs="+",
        default=["amd64"],
        help="Architecture(s) to parse (default: amd64)",
    )
    parser.add_argument(
        "--mirror", "-m",
        default=None,
        help="Custom mirror URL (overrides default per-family mirror)",
    )
    parser.add_argument(
        "--recipes-dir", "-r",
        default="recipes",
        help="Path to recipes directory (default: recipes)",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be done without writing files",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(levelname)s: %(message)s",
    )

    if yaml is None:
        logger.error("PyYAML is required. Install it: pip install pyyaml")
        sys.exit(1)

    total_new = 0
    total_updated = 0
    total_skipped = 0

    for codename in args.dist:
        codename = codename.lower().strip()
        for arch in args.arch:
            arch = arch.lower().strip()
            new, updated, skipped = parse_distribution(
                codename=codename,
                arch=arch,
                mirror_override=args.mirror,
                recipes_dir=args.recipes_dir,
                update_existing=True,
                dry_run=args.dry_run,
            )
            total_new += new
            total_updated += updated
            total_skipped += skipped
            print("")

    print("=" * 50)
    print("Summary:")
    print("  New recipes:     {}".format(total_new))
    print("  Updated recipes: {}".format(total_updated))
    print("  Skipped:         {}".format(total_skipped))
    if args.dry_run:
        print("  (dry-run mode - no files were written)")
    print("=" * 50)


if __name__ == "__main__":
    main()
