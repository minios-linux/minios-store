#!/usr/bin/env python3
"""Build recipes.json from YAML recipe files.

Scans the recipes/ directory for .yaml files, validates them,
fetches screenshots from screenshots.debian.net (cached locally),
and outputs combined JSON files suitable for the web UI.

Usage:
    python3 tools/build_recipes.py
    python3 tools/build_recipes.py --output web/public/data/recipes.json
    python3 tools/build_recipes.py --validate  # validate only, no output
    python3 tools/build_recipes.py --no-screenshots  # skip screenshot fetching
"""

import argparse
import gzip
import io
import json
import logging
import os
import sys
import tarfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

# PyYAML is optional — use a simple YAML subset parser if not available
try:
    import yaml
except ImportError:
    yaml = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ============================================
# Screenshot fetching from AppStream media
# ============================================

# AppStream media base URLs (suite is inserted at runtime)
APPSTREAM_DEBIAN_MEDIA = "https://appstream.debian.org/media/{suite}/"
APPSTREAM_UBUNTU_MEDIA = "https://appstream.ubuntu.com/media/{suite}/"

# Fallback: legacy screenshots.debian.net API
SCREENSHOTS_API = "https://screenshots.debian.net/json/package/{}"

USER_AGENT = "MiniOS-Store/1.0 (screenshot fetcher)"
REQUEST_TIMEOUT = 30
DEFAULT_CONCURRENCY = 10
MAX_SCREENSHOTS = 3

# Known Debian/Ubuntu suites for AppStream media fallback
DEBIAN_SUITES = ["trixie", "bookworm", "bullseye", "sid"]
UBUNTU_SUITES = ["noble", "jammy", "focal"]


def fetch_json(url):
    """Fetch and parse JSON from a URL.

    Args:
        url: URL to fetch.

    Returns:
        Parsed JSON data, or None on failure.
        Raises urllib.error.HTTPError for 404 specifically so caller can
        distinguish "not found" from transient network errors.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise  # Let caller handle 404 specifically
        logger.debug("Failed to fetch %s: %s", url, e)
        return None
    except (urllib.error.URLError, OSError, ValueError) as e:
        logger.debug("Failed to fetch %s: %s", url, e)
        return None


def download_file(url, dest_path):
    """Download a binary file from URL to dest_path.

    Args:
        url: URL to download.
        dest_path: Local file path to write to.

    Returns:
        Number of bytes written on success, 0 on failure.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = resp.read()
            if not data:
                return 0
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, "wb") as f:
                f.write(data)
            return len(data)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        logger.debug("Failed to download %s: %s", url, e)
        return 0


def get_file_extension(url):
    """Detect file extension from URL path.

    Args:
        url: URL string.

    Returns:
        Extension string (e.g. ".png"), defaults to ".png" if unknown.
    """
    path = url.split("?")[0].split("#")[0]
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        if path.lower().endswith(ext):
            return ext
    return ".png"


def fetch_package_screenshots(package_name, output_dir,
                              screenshot_sources=None, suites=None):
    """Fetch screenshots for a single package from AppStream media or screenshots.debian.net.

    Prefers AppStream media URLs from screenshotSources (populated by repo_parser).
    Falls back to screenshots.debian.net JSON API for packages without screenshotSources.
    Downloads both full-size and thumbnail versions.
    Skips files that already exist and are non-empty (caching).

    Negative-cache markers (.no_screenshots) store a fingerprint of the source
    URLs used when the marker was created. If the URLs change (e.g. Debian
    updates metadata hashes), the marker is automatically invalidated.

    Args:
        package_name: Debian package name.
        output_dir: Base output directory (e.g. web/public/screenshots).
        screenshot_sources: List of screenshot source dicts from recipe YAML
                            (each has 'url', optional 'thumbnailUrl').
        suites: Dict with 'debian' and 'ubuntu' keys listing suite names
                from the recipe's distributions.include.

    Returns:
        Tuple of (screenshot_count, bytes_downloaded, was_cached).
        was_cached is True if all screenshots were already on disk.
    """
    pkg_dir = os.path.join(output_dir, package_name)
    no_screenshots_marker = os.path.join(pkg_dir, ".no_screenshots")

    # Build a fingerprint from current source URLs for cache invalidation
    current_fingerprint = ""
    if screenshot_sources:
        current_fingerprint = "|".join(
            src.get("url", "") for src in screenshot_sources
        )

    # Check if we already have cached screenshots
    if os.path.isdir(pkg_dir):
        if os.path.isfile(no_screenshots_marker):
            # Check if the marker is still valid (same URLs)
            try:
                with open(no_screenshots_marker, "r") as f:
                    stored_fingerprint = f.read().strip()
            except OSError:
                stored_fingerprint = ""

            if stored_fingerprint == current_fingerprint and current_fingerprint:
                # Same URLs, still no screenshots — skip
                return (0, 0, True)
            elif not current_fingerprint and not stored_fingerprint:
                # Both empty (legacy marker, no sources) — still valid
                return (0, 0, True)
            else:
                # URLs changed — remove stale marker and retry
                logger.info("URLs changed for %s, retrying screenshot download", package_name)
                os.remove(no_screenshots_marker)

        existing = [f for f in os.listdir(pkg_dir) if not f.startswith(".") and "_small" not in f and os.path.getsize(os.path.join(pkg_dir, f)) > 0]
        if existing:
            # Check if any thumbnails are missing — if so, proceed to
            # _fetch_from_appstream which handles "full exists, thumb missing"
            small_files = [f for f in os.listdir(pkg_dir) if "_small" in f and os.path.getsize(os.path.join(pkg_dir, f)) > 0]
            if len(small_files) >= len(existing) or not screenshot_sources:
                return (len(existing), 0, True)
            # Fall through to _fetch_from_appstream to download missing thumbnails

    if suites is None:
        suites = {"debian": [], "ubuntu": []}

    # ---- Strategy 1: AppStream media (from screenshotSources in recipe YAML) ----
    if screenshot_sources:
        return _fetch_from_appstream(
            package_name, pkg_dir, no_screenshots_marker,
            screenshot_sources, suites, current_fingerprint,
        )

    # ---- Strategy 2: Legacy screenshots.debian.net API ----
    return _fetch_from_debian_screenshots(
        package_name, pkg_dir, no_screenshots_marker,
    )


def _thumb_url_at1(url):
    """Insert @1 retina suffix before the file extension.

    DEP-11 metadata stores thumbnail filenames like image-1_624x351.png,
    but the CDN actually serves them as image-1_624x351@1.png.

    Args:
        url: Original thumbnail URL.

    Returns:
        URL with @1 inserted before the extension, or original if no
        recognized extension found.
    """
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        if url.lower().endswith(ext):
            return url[:-len(ext)] + "@1" + url[-len(ext):]
    return url


def _download_thumbnail(base_url, rel_thumb, small_path):
    """Download a thumbnail, trying @1 retina suffix as fallback.

    Args:
        base_url: AppStream media base URL.
        rel_thumb: Relative thumbnail path from DEP-11.
        small_path: Local destination path.

    Returns:
        Number of bytes downloaded (0 if both attempts failed).
    """
    nbytes = download_file(base_url + rel_thumb, small_path)
    if nbytes > 0:
        return nbytes
    # Fallback: try with @1 retina suffix
    alt_thumb = _thumb_url_at1(rel_thumb)
    if alt_thumb != rel_thumb:
        nbytes = download_file(base_url + alt_thumb, small_path)
    return nbytes


def _fetch_from_appstream(package_name, pkg_dir, no_screenshots_marker,
                          screenshot_sources, suites, fingerprint=""):
    """Download screenshots using AppStream media URLs.

    Tries Debian suites first, then Ubuntu suites, for each screenshot source.

    Args:
        package_name: Package name (for logging).
        pkg_dir: Target directory for this package's screenshots.
        no_screenshots_marker: Path to .no_screenshots marker file.
        screenshot_sources: List of screenshot source dicts.
        suites: Dict with 'debian' and 'ubuntu' suite lists.
        fingerprint: URL fingerprint string to write into negative-cache marker.

    Returns:
        Tuple of (screenshot_count, bytes_downloaded, was_cached).
    """
    # Build ordered list of (base_url_template, suite) to try
    media_urls = []
    for suite in suites.get("debian", []):
        media_urls.append(APPSTREAM_DEBIAN_MEDIA.format(suite=suite))
    for suite in suites.get("ubuntu", []):
        media_urls.append(APPSTREAM_UBUNTU_MEDIA.format(suite=suite))

    # If no suites from recipe, try common defaults
    if not media_urls:
        media_urls = [
            APPSTREAM_DEBIAN_MEDIA.format(suite="trixie"),
            APPSTREAM_DEBIAN_MEDIA.format(suite="bookworm"),
            APPSTREAM_UBUNTU_MEDIA.format(suite="noble"),
        ]

    count = 0
    total_bytes = 0

    for idx, src in enumerate(screenshot_sources[:MAX_SCREENSHOTS], 1):
        rel_url = src.get("url", "")
        rel_thumb = src.get("thumbnailUrl", "")
        if not rel_url:
            continue

        ext = get_file_extension(rel_url)
        full_path = os.path.join(pkg_dir, "{}{}".format(idx, ext))
        small_path = os.path.join(pkg_dir, "{}_small{}".format(idx, ext))

        # Skip if already cached
        full_exists = os.path.isfile(full_path) and os.path.getsize(full_path) > 0
        small_exists = os.path.isfile(small_path) and os.path.getsize(small_path) > 0

        if full_exists:
            count += 1
            # Still try to fetch thumbnail if missing
            if rel_thumb and not small_exists:
                for base_url in media_urls:
                    nbytes = _download_thumbnail(base_url, rel_thumb, small_path)
                    if nbytes > 0:
                        total_bytes += nbytes
                        break
            continue

        # Try each media base URL until one works
        downloaded = False
        for base_url in media_urls:
            full_url = base_url + rel_url
            nbytes = download_file(full_url, full_path)
            if nbytes > 0:
                count += 1
                total_bytes += nbytes
                downloaded = True

                # Also fetch thumbnail from the same source
                if rel_thumb and not small_exists:
                    tnbytes = _download_thumbnail(base_url, rel_thumb, small_path)
                    total_bytes += tnbytes
                break

        if not downloaded:
            logger.debug("No AppStream media found for %s screenshot %d", package_name, idx)

    if count == 0:
        # Cache negative result with URL fingerprint for invalidation
        os.makedirs(pkg_dir, exist_ok=True)
        with open(no_screenshots_marker, "w") as f:
            f.write(fingerprint)

    return (count, total_bytes, False)


def _fetch_from_debian_screenshots(package_name, pkg_dir, no_screenshots_marker):
    """Fallback: fetch screenshots from screenshots.debian.net JSON API.

    Args:
        package_name: Debian package name.
        pkg_dir: Target directory.
        no_screenshots_marker: Path to .no_screenshots marker file.

    Returns:
        Tuple of (screenshot_count, bytes_downloaded, was_cached).
    """
    try:
        data = fetch_json(SCREENSHOTS_API.format(package_name))
    except urllib.error.HTTPError:
        # 404: package doesn't exist on screenshots.debian.net
        os.makedirs(pkg_dir, exist_ok=True)
        with open(no_screenshots_marker, "w") as f:
            f.write("")
        return (0, 0, False)

    if not data:
        return (0, 0, False)

    screenshots = data.get("screenshots", [])
    if not screenshots:
        os.makedirs(pkg_dir, exist_ok=True)
        with open(no_screenshots_marker, "w") as f:
            f.write("")
        return (0, 0, False)

    # Sort by version (newest first)
    screenshots.sort(key=lambda s: s.get("version", ""), reverse=True)

    count = 0
    total_bytes = 0
    for idx, shot in enumerate(screenshots[:MAX_SCREENSHOTS], 1):
        full_url = shot.get("screenshot_image_url")
        small_url = shot.get("small_image_url")

        if not full_url:
            continue

        ext = get_file_extension(full_url)
        full_path = os.path.join(pkg_dir, "{}{}".format(idx, ext))
        small_path = os.path.join(pkg_dir, "{}_small{}".format(idx, ext))

        full_exists = os.path.isfile(full_path) and os.path.getsize(full_path) > 0
        small_exists = os.path.isfile(small_path) and os.path.getsize(small_path) > 0

        if not full_exists:
            nbytes = download_file(full_url, full_path)
            if nbytes > 0:
                count += 1
                total_bytes += nbytes
            else:
                continue
        else:
            count += 1

        if small_url and not small_exists:
            nbytes = download_file(small_url, small_path)
            total_bytes += nbytes

    return (count, total_bytes, False)


def _format_size(nbytes):
    """Format byte count as human-readable string."""
    if nbytes < 1024:
        return "{} B".format(nbytes)
    elif nbytes < 1024 * 1024:
        return "{:.1f} KB".format(nbytes / 1024)
    elif nbytes < 1024 * 1024 * 1024:
        return "{:.1f} MB".format(nbytes / (1024 * 1024))
    else:
        return "{:.2f} GB".format(nbytes / (1024 * 1024 * 1024))


def _format_speed(bytes_per_sec):
    """Format download speed as human-readable string."""
    if bytes_per_sec < 1024:
        return "{:.0f} B/s".format(bytes_per_sec)
    elif bytes_per_sec < 1024 * 1024:
        return "{:.1f} KB/s".format(bytes_per_sec / 1024)
    else:
        return "{:.1f} MB/s".format(bytes_per_sec / (1024 * 1024))


def _extract_suites(recipe):
    """Extract Debian and Ubuntu suite names from recipe distributions.

    Args:
        recipe: Recipe dict with optional 'distributions' field.

    Returns:
        Dict with 'debian' and 'ubuntu' keys, each a list of suite names.
    """
    suites = {"debian": [], "ubuntu": []}
    distributions = recipe.get("distributions", {})
    if not isinstance(distributions, dict):
        return suites

    include = distributions.get("include", [])
    if not isinstance(include, list):
        return suites

    for entry in include:
        if isinstance(entry, dict):
            name = entry.get("name", "")
        elif isinstance(entry, str):
            name = entry
        else:
            continue

        # Classify suite by family
        base_name = name.split("-")[0]  # e.g. "bookworm-backports" -> "bookworm"
        if base_name in ("buster", "bullseye", "bookworm", "trixie", "sid"):
            if name not in suites["debian"]:
                suites["debian"].append(name)
        elif base_name in ("bionic", "focal", "jammy", "noble"):
            if name not in suites["ubuntu"]:
                suites["ubuntu"].append(name)

    return suites


def fetch_all_screenshots(recipes, output_dir, concurrency=DEFAULT_CONCURRENCY):
    """Fetch screenshots for all recipes using a thread pool.

    Uses AppStream media URLs from screenshotSources when available,
    falling back to screenshots.debian.net for packages without them.

    Displays a live progress line with counts, download speed, and ETA.

    Args:
        recipes: List of recipe dicts.
        output_dir: Base screenshots directory.
        concurrency: Number of parallel download threads.

    Returns:
        Dict mapping package_name -> number of screenshots.
    """
    import threading

    # Build a map of package_name -> (screenshot_sources, suites)
    # from recipe data, and collect unique package names
    package_info = {}  # pkg_name -> (screenshot_sources, suites)
    for recipe in recipes:
        pkgs = recipe.get("packages")
        if pkgs and isinstance(pkgs, list) and len(pkgs) > 0:
            pkg_name = str(pkgs[0])
        elif recipe.get("id"):
            pkg_name = str(recipe["id"])
        else:
            continue

        if pkg_name in package_info:
            continue  # First recipe wins

        screenshot_sources = recipe.get("screenshotSources")
        suites = _extract_suites(recipe)
        package_info[pkg_name] = (screenshot_sources, suites)

    total_packages = len(package_info)
    logger.info(
        "Fetching screenshots for %d packages (concurrency=%d)...",
        total_packages, concurrency,
    )

    # Count how many have AppStream sources vs fallback
    with_sources = sum(1 for ss, _ in package_info.values() if ss)
    logger.info(
        "  %d with AppStream screenshotSources, %d will use screenshots.debian.net fallback",
        with_sources, total_packages - with_sources,
    )

    results = {}
    # Thread-safe counters
    lock = threading.Lock()
    counters = {
        "done": 0,
        "cached": 0,
        "downloaded": 0,
        "no_screenshots": 0,
        "failed": 0,
        "bytes": 0,
    }
    start = time.time()
    is_tty = sys.stderr.isatty()

    def _print_progress():
        """Print a single-line progress update to stderr."""
        elapsed = time.time() - start
        speed = counters["bytes"] / elapsed if elapsed > 0 else 0
        pct = 100.0 * counters["done"] / total_packages if total_packages else 100

        # ETA based on packages processed
        remaining = total_packages - counters["done"]
        rate = counters["done"] / elapsed if elapsed > 0 else 0
        eta = remaining / rate if rate > 0 else 0

        line = (
            "\r  [{done}/{total}] {pct:.0f}%  "
            "cached: {cached}  downloaded: {downloaded} ({size})  "
            "no screenshots: {noss}  failed: {failed}  "
            "speed: {speed}  ETA: {eta}"
        ).format(
            done=counters["done"],
            total=total_packages,
            pct=pct,
            cached=counters["cached"],
            downloaded=counters["downloaded"],
            size=_format_size(counters["bytes"]),
            noss=counters["no_screenshots"],
            failed=counters["failed"],
            speed=_format_speed(speed),
            eta="{:.0f}s".format(eta) if eta < 3600 else "{:.0f}m".format(eta / 60),
        )

        if is_tty:
            # Overwrite current line
            sys.stderr.write(line + "   ")
            sys.stderr.flush()
        elif counters["done"] % 100 == 0 or counters["done"] == total_packages:
            # Log periodic summary for non-TTY environments
            logger.info(line.strip())

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {}
        for pkg_name, (screenshot_sources, suites) in package_info.items():
            future = pool.submit(
                fetch_package_screenshots, pkg_name, output_dir,
                screenshot_sources=screenshot_sources,
                suites=suites,
            )
            futures[future] = pkg_name

        for future in as_completed(futures):
            pkg = futures[future]
            try:
                screenshot_count, bytes_downloaded, was_cached = future.result()
                with lock:
                    counters["done"] += 1
                    if was_cached:
                        counters["cached"] += 1
                    elif screenshot_count > 0:
                        counters["downloaded"] += 1
                        counters["bytes"] += bytes_downloaded
                    else:
                        counters["no_screenshots"] += 1
                    if screenshot_count > 0:
                        results[pkg] = screenshot_count
            except Exception as e:
                with lock:
                    counters["done"] += 1
                    counters["failed"] += 1
                logger.warning("Screenshot fetch failed for %s: %s", pkg, e)

            _print_progress()

    # Final newline after progress
    if is_tty:
        sys.stderr.write("\n")
        sys.stderr.flush()

    elapsed = time.time() - start
    have = len(results)
    speed = counters["bytes"] / elapsed if elapsed > 0 else 0
    logger.info(
        "Screenshots done: %d/%d have screenshots "
        "(cached: %d, downloaded: %d [%s], no screenshots: %d, failed: %d) "
        "in %.1fs (avg %s)",
        have, total_packages,
        counters["cached"], counters["downloaded"],
        _format_size(counters["bytes"]),
        counters["no_screenshots"], counters["failed"],
        elapsed, _format_speed(speed),
    )

    return results


def scan_screenshots(screenshots_dir, package_name):
    """Scan the screenshots directory for a package and return relative paths.

    Returns paths relative to the screenshots_dir parent (for use as web URLs).
    Only returns full-size images (not _small thumbnails).
    Removes excess screenshots beyond MAX_SCREENSHOTS from disk.

    Args:
        screenshots_dir: Base screenshots directory (e.g. web/public/screenshots).
        package_name: Package name to look up.

    Returns:
        List of relative screenshot paths (e.g. ["/screenshots/firefox/1.png"]),
        or empty list if no screenshots exist.
    """
    pkg_dir = os.path.join(screenshots_dir, package_name)
    if not os.path.isdir(pkg_dir):
        return []

    # Collect all full-size screenshot filenames (sorted)
    all_full = []
    for fname in sorted(os.listdir(pkg_dir)):
        fpath = os.path.join(pkg_dir, fname)
        if "_small" in fname or fname.startswith("."):
            continue
        if not os.path.isfile(fpath) or os.path.getsize(fpath) == 0:
            continue
        all_full.append(fname)

    # Keep first MAX_SCREENSHOTS, delete the rest (+ their thumbnails)
    shots = []
    for i, fname in enumerate(all_full):
        if i < MAX_SCREENSHOTS:
            shots.append("/screenshots/{}/{}".format(package_name, fname))
        else:
            # Remove excess full-size image
            fpath = os.path.join(pkg_dir, fname)
            os.remove(fpath)
            # Remove corresponding thumbnail
            base, ext = os.path.splitext(fname)
            thumb = os.path.join(pkg_dir, "{}_small{}".format(base, ext))
            if os.path.isfile(thumb):
                os.remove(thumb)
            logger.debug("Removed excess screenshot %s/%s", package_name, fname)

    return shots


# ============================================
# Icon fetching from AppStream media / tarballs
# ============================================

# DEP-11 icons tarball URL template
# Icons are distributed as icons-{size}.tar.gz inside the dep11 directory
ICONS_TARBALL_DEBIAN = "https://deb.debian.org/debian/dists/{suite}/{component}/dep11/icons-{size}.tar.gz"
ICONS_TARBALL_UBUNTU = "https://archive.ubuntu.com/ubuntu/dists/{suite}/{component}/dep11/icons-{size}.tar.gz"

# Preferred icon size for cached icons
PREFERRED_ICON_SIZE = "128x128"
# Fallback sizes if preferred is not available
FALLBACK_ICON_SIZES = ["64x64", "48x48"]


def fetch_package_icon(package_name, output_dir, icon_sources=None, suites=None,
                       icon_tarballs=None):
    """Fetch an app icon for a single package.

    Handles two icon source types:
    - remote: direct download from AppStream media CDN (like screenshots)
    - cached: extracted from pre-downloaded icons tarball

    Negative-cache markers (.no_icon_*) store a fingerprint of the source
    URL used when the marker was created. If the URL changes (e.g. Debian
    updates metadata hashes), the marker is automatically invalidated.

    Args:
        package_name: Package name.
        output_dir: Base icons directory (e.g. web/public/icons).
        icon_sources: List of icon source dicts from recipe YAML.
        suites: Dict with 'debian' and 'ubuntu' suite lists.
        icon_tarballs: Dict of pre-loaded icon tarballs, keyed by
                       (suite, component, size) -> {name: bytes}.

    Returns:
        Tuple of (found, bytes_downloaded, was_cached).
        found: 1 if icon was obtained, 0 otherwise.
    """
    if not icon_sources:
        return (0, 0, False)

    icon_path = os.path.join(output_dir, "{}.png".format(package_name))
    no_icon_marker = os.path.join(output_dir, ".no_icon_{}".format(package_name))

    # Build fingerprint from current icon source for cache invalidation
    src = icon_sources[0]  # Use first (best) icon source
    current_fingerprint = src.get("url", "") or src.get("cached", "")

    # Check negative cache
    if os.path.isfile(no_icon_marker):
        try:
            with open(no_icon_marker, "r") as f:
                stored_fingerprint = f.read().strip()
        except OSError:
            stored_fingerprint = ""

        if stored_fingerprint == current_fingerprint and current_fingerprint:
            # Same URL, still no icon — skip
            return (0, 0, True)
        else:
            # URL changed — remove stale marker and retry
            logger.info("Icon URL changed for %s, retrying download", package_name)
            os.remove(no_icon_marker)

    # Check if already cached
    if os.path.isfile(icon_path) and os.path.getsize(icon_path) > 0:
        return (1, 0, True)

    if suites is None:
        suites = {"debian": [], "ubuntu": []}

    # ---- Remote icon (direct URL from AppStream media CDN) ----
    if src.get("url"):
        rel_url = src["url"]

        # Build ordered list of base URLs to try
        media_urls = []
        for suite in suites.get("debian", []):
            media_urls.append(APPSTREAM_DEBIAN_MEDIA.format(suite=suite))
        for suite in suites.get("ubuntu", []):
            media_urls.append(APPSTREAM_UBUNTU_MEDIA.format(suite=suite))
        if not media_urls:
            media_urls = [
                APPSTREAM_DEBIAN_MEDIA.format(suite="trixie"),
                APPSTREAM_DEBIAN_MEDIA.format(suite="bookworm"),
                APPSTREAM_UBUNTU_MEDIA.format(suite="noble"),
            ]

        for base_url in media_urls:
            full_url = base_url + rel_url
            nbytes = download_file(full_url, icon_path)
            if nbytes > 0:
                return (1, nbytes, False)

        # All URLs failed — write negative cache with fingerprint
        with open(no_icon_marker, "w") as f:
            f.write(current_fingerprint)
        return (0, 0, False)

    # ---- Cached icon (from dep11 icons tarball) ----
    if src.get("cached") and icon_tarballs:
        cached_name = src["cached"]
        # Try to find in pre-loaded tarballs
        for key, members in icon_tarballs.items():
            if cached_name in members:
                os.makedirs(output_dir, exist_ok=True)
                with open(icon_path, "wb") as f:
                    f.write(members[cached_name])
                return (1, len(members[cached_name]), False)

        # Not found in any tarball
        with open(no_icon_marker, "w") as f:
            f.write(current_fingerprint)
        return (0, 0, False)

    return (0, 0, False)


def _load_icon_tarballs(recipes):
    """Download and extract icon tarballs for all needed suites/components.

    Args:
        recipes: List of recipe dicts (to determine which suites are needed).

    Returns:
        Dict keyed by (suite, component, size) -> {icon_name: icon_bytes}.
    """
    # Determine which suites we need
    needed_suites = {"debian": set(), "ubuntu": set()}
    has_cached_icons = False

    for recipe in recipes:
        icon_sources = recipe.get("iconSources", [])
        if not icon_sources:
            continue
        src = icon_sources[0]
        if src.get("cached"):
            has_cached_icons = True
            suites = _extract_suites(recipe)
            for s in suites.get("debian", []):
                needed_suites["debian"].add(s)
            for s in suites.get("ubuntu", []):
                needed_suites["ubuntu"].add(s)

    if not has_cached_icons:
        return {}

    # If no suites found, use defaults
    if not needed_suites["debian"] and not needed_suites["ubuntu"]:
        needed_suites["debian"] = {"bookworm", "trixie"}

    tarballs = {}

    # Components to try per family
    debian_components = ["main", "contrib", "non-free"]
    ubuntu_components = ["main", "universe"]

    for suite in sorted(needed_suites["debian"]):
        for component in debian_components:
            _try_load_tarball(
                ICONS_TARBALL_DEBIAN, suite, component,
                PREFERRED_ICON_SIZE, FALLBACK_ICON_SIZES, tarballs,
            )

    for suite in sorted(needed_suites["ubuntu"]):
        for component in ubuntu_components:
            _try_load_tarball(
                ICONS_TARBALL_UBUNTU, suite, component,
                PREFERRED_ICON_SIZE, FALLBACK_ICON_SIZES, tarballs,
            )

    total_icons = sum(len(v) for v in tarballs.values())
    logger.info("Loaded %d icons from %d tarballs", total_icons, len(tarballs))

    return tarballs


def _try_load_tarball(url_template, suite, component, preferred_size,
                      fallback_sizes, tarballs):
    """Try to download and extract an icons tarball.

    Args:
        url_template: URL template with {suite}, {component}, {size} placeholders.
        suite: Distribution suite name.
        component: Repository component.
        preferred_size: Preferred icon size (e.g. "128x128").
        fallback_sizes: List of fallback sizes to try.
        tarballs: Dict to populate with extracted icons.
    """
    sizes_to_try = [preferred_size] + list(fallback_sizes)

    for size in sizes_to_try:
        url = url_template.format(suite=suite, component=component, size=size)
        key = (suite, component, size)

        if key in tarballs:
            continue

        logger.debug("Trying icons tarball: %s", url)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()

            # Extract all PNG files from tarball
            members = {}
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
                for member in tar.getmembers():
                    if member.isfile() and member.name.endswith(".png"):
                        f = tar.extractfile(member)
                        if f:
                            # Use just the filename, not the path
                            name = os.path.basename(member.name)
                            members[name] = f.read()

            tarballs[key] = members
            logger.info("Icons tarball %s/%s/%s: %d icons",
                        suite, component, size, len(members))
            return  # Success, no need to try smaller sizes

        except urllib.error.HTTPError as e:
            if e.code == 404:
                logger.debug("Icons tarball not found: %s (404)", url)
            else:
                logger.warning("Failed to fetch icons tarball %s: %s", url, e)
        except Exception as e:
            logger.warning("Failed to process icons tarball %s: %s", url, e)


def fetch_all_icons(recipes, output_dir, concurrency=DEFAULT_CONCURRENCY):
    """Fetch icons for all recipes using a thread pool.

    Downloads remote icons directly from AppStream media CDN.
    For cached icons, downloads tarballs first, then extracts needed icons.

    Args:
        recipes: List of recipe dicts.
        output_dir: Base icons directory.
        concurrency: Number of parallel download threads.

    Returns:
        Dict mapping package_name -> 1 (if icon exists).
    """
    import threading

    # Load tarballs for cached icons
    icon_tarballs = _load_icon_tarballs(recipes)

    # Build a map of package_name -> (icon_sources, suites)
    package_info = {}
    for recipe in recipes:
        icon_sources = recipe.get("iconSources")
        if not icon_sources:
            continue

        pkgs = recipe.get("packages")
        if pkgs and isinstance(pkgs, list) and len(pkgs) > 0:
            pkg_name = str(pkgs[0])
        elif recipe.get("id"):
            pkg_name = str(recipe["id"])
        else:
            continue

        if pkg_name in package_info:
            continue

        suites = _extract_suites(recipe)
        package_info[pkg_name] = (icon_sources, suites)

    total_packages = len(package_info)
    if total_packages == 0:
        logger.info("No icon sources found in recipes")
        return {}

    logger.info("Fetching icons for %d packages (concurrency=%d)...",
                total_packages, concurrency)

    # Count types
    remote_count = sum(1 for src, _ in package_info.values()
                       if src and src[0].get("url"))
    cached_count = total_packages - remote_count
    logger.info("  %d remote icons, %d cached icons", remote_count, cached_count)

    os.makedirs(output_dir, exist_ok=True)

    results = {}
    lock = threading.Lock()
    counters = {
        "done": 0, "cached": 0, "downloaded": 0,
        "no_icon": 0, "failed": 0, "bytes": 0,
    }
    start = time.time()
    is_tty = sys.stderr.isatty()

    def _print_progress():
        elapsed = time.time() - start
        speed = counters["bytes"] / elapsed if elapsed > 0 else 0
        pct = 100.0 * counters["done"] / total_packages if total_packages else 100
        remaining = total_packages - counters["done"]
        rate = counters["done"] / elapsed if elapsed > 0 else 0
        eta = remaining / rate if rate > 0 else 0

        line = (
            "\r  [{done}/{total}] {pct:.0f}%  "
            "cached: {cached}  downloaded: {downloaded} ({size})  "
            "no icon: {noic}  failed: {failed}  "
            "speed: {speed}  ETA: {eta}"
        ).format(
            done=counters["done"], total=total_packages, pct=pct,
            cached=counters["cached"], downloaded=counters["downloaded"],
            size=_format_size(counters["bytes"]),
            noic=counters["no_icon"], failed=counters["failed"],
            speed=_format_speed(speed),
            eta="{:.0f}s".format(eta) if eta < 3600 else "{:.0f}m".format(eta / 60),
        )

        if is_tty:
            sys.stderr.write(line + "   ")
            sys.stderr.flush()
        elif counters["done"] % 100 == 0 or counters["done"] == total_packages:
            logger.info(line.strip())

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {}
        for pkg_name, (icon_sources, suites) in package_info.items():
            future = pool.submit(
                fetch_package_icon, pkg_name, output_dir,
                icon_sources=icon_sources,
                suites=suites,
                icon_tarballs=icon_tarballs,
            )
            futures[future] = pkg_name

        for future in as_completed(futures):
            pkg = futures[future]
            try:
                found, bytes_downloaded, was_cached = future.result()
                with lock:
                    counters["done"] += 1
                    if was_cached:
                        counters["cached"] += 1
                    elif found > 0:
                        counters["downloaded"] += 1
                        counters["bytes"] += bytes_downloaded
                    else:
                        counters["no_icon"] += 1
                    if found > 0:
                        results[pkg] = 1
            except Exception as e:
                with lock:
                    counters["done"] += 1
                    counters["failed"] += 1
                logger.warning("Icon fetch failed for %s: %s", pkg, e)

            _print_progress()

    if is_tty:
        sys.stderr.write("\n")
        sys.stderr.flush()

    elapsed = time.time() - start
    have = len(results)
    speed = counters["bytes"] / elapsed if elapsed > 0 else 0
    logger.info(
        "Icons done: %d/%d have icons "
        "(cached: %d, downloaded: %d [%s], no icon: %d, failed: %d) "
        "in %.1fs (avg %s)",
        have, total_packages,
        counters["cached"], counters["downloaded"],
        _format_size(counters["bytes"]),
        counters["no_icon"], counters["failed"],
        elapsed, _format_speed(speed),
    )

    return results


def scan_icon(icons_dir, package_name):
    """Check if an icon exists on disk for a package.

    Args:
        icons_dir: Base icons directory (e.g. web/public/icons).
        package_name: Package name.

    Returns:
        Icon web path (e.g. "/icons/firefox.png") or None.
    """
    icon_path = os.path.join(icons_dir, "{}.png".format(package_name))
    if os.path.isfile(icon_path) and os.path.getsize(icon_path) > 0:
        return "/icons/{}.png".format(package_name)
    return None


# Minimal YAML parser for simple recipe files (no anchors, no complex types)
# Supports: scalars, lists, dicts (2-level nesting), multiline strings (|),
# and lists of dicts (for distributions.include/exclude entries).
def _parse_simple_yaml(text):
    """Parse a simple YAML document without PyYAML dependency.

    Supports basic key-value pairs, lists (including inline [a, b] syntax),
    nested dicts (2 levels), lists of dicts, and multiline block scalars (|).
    This is sufficient for recipe YAML files.
    """
    result = {}
    lines = text.split("\n")
    i = 0

    def _parse_inline_list(value):
        """Parse inline list like [amd64, i386]."""
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item.strip()) for item in inner.split(",") if item.strip()]

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # Detect indentation level
        indent = len(line) - len(line.lstrip())

        # Top-level key-value
        if indent == 0 and ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()

            if value == "|":
                # Multiline block scalar
                block_lines = []
                i += 1
                while i < len(lines):
                    bline = lines[i]
                    bstripped = bline.strip()
                    bindent = len(bline) - len(bline.lstrip())
                    if bstripped == "" or bindent > 0:
                        block_lines.append(bline)
                        i += 1
                    else:
                        break
                # Find the minimum indentation of non-empty lines
                non_empty = [l for l in block_lines if l.strip()]
                if non_empty:
                    min_indent = min(
                        len(l) - len(l.lstrip()) for l in non_empty
                    )
                    block_lines = [
                        l[min_indent:] if len(l) > min_indent else ""
                        for l in block_lines
                    ]
                result[key] = "\n".join(block_lines).rstrip("\n") + "\n"
                continue

            elif value.startswith("[") and value.endswith("]"):
                # Inline list
                result[key] = _parse_inline_list(value)
                i += 1
                continue

            elif value == "":
                # Could be a list, nested dict, or list of dicts — check next lines
                i += 1
                first_child = None
                # Peek at the first non-empty child to determine structure
                peek = i
                while peek < len(lines):
                    pline = lines[peek].strip()
                    if pline == "" or pline.startswith("#"):
                        peek += 1
                        continue
                    pindent = len(lines[peek]) - len(lines[peek].lstrip())
                    if pindent <= 0:
                        break
                    first_child = pline
                    break

                if first_child is not None and first_child.startswith("- "):
                    # List (possibly of dicts) or simple list
                    items = []
                    while i < len(lines):
                        nline = lines[i]
                        nstripped = nline.strip()
                        nindent = len(nline) - len(nline.lstrip())
                        if nstripped == "" or nstripped.startswith("#"):
                            i += 1
                            continue
                        if nindent <= 0:
                            break
                        if nstripped.startswith("- "):
                            item_value = nstripped[2:].strip()
                            # Check if this list item is a dict (has "key: value")
                            if ":" in item_value:
                                # List item is a dict — parse key-value pairs
                                item_key, _, item_val = item_value.partition(":")
                                item_dict = {item_key.strip(): _parse_scalar(item_val.strip()) if item_val.strip() else None}
                                # Check for continuation lines (further indented)
                                base_indent = nindent
                                i += 1
                                while i < len(lines):
                                    cline = lines[i]
                                    cstripped = cline.strip()
                                    cindent = len(cline) - len(cline.lstrip())
                                    if cstripped == "" or cstripped.startswith("#"):
                                        i += 1
                                        continue
                                    if cindent <= base_indent:
                                        break
                                    if ":" in cstripped:
                                        ck, _, cv = cstripped.partition(":")
                                        cv = cv.strip()
                                        if cv.startswith("[") and cv.endswith("]"):
                                            item_dict[ck.strip()] = _parse_inline_list(cv)
                                        elif cv:
                                            item_dict[ck.strip()] = _parse_scalar(cv)
                                        else:
                                            # Sub-list
                                            sub_items = []
                                            i += 1
                                            while i < len(lines):
                                                sline = lines[i]
                                                sstripped = sline.strip()
                                                sindent = len(sline) - len(sline.lstrip())
                                                if sstripped == "" or sstripped.startswith("#"):
                                                    i += 1
                                                    continue
                                                if sindent <= cindent:
                                                    break
                                                if sstripped.startswith("- "):
                                                    sub_items.append(_parse_scalar(sstripped[2:].strip()))
                                                i += 1
                                            item_dict[ck.strip()] = sub_items
                                            continue
                                    i += 1
                                items.append(item_dict)
                                continue
                            else:
                                items.append(_parse_scalar(item_value))
                            i += 1
                        else:
                            i += 1
                    result[key] = items
                    continue

                elif first_child is not None and ":" in first_child and not first_child.startswith("- "):
                    # Nested dict (e.g. distributions: { include: [...], exclude: [...] })
                    nested = {}
                    while i < len(lines):
                        nline = lines[i]
                        nstripped = nline.strip()
                        nindent = len(nline) - len(nline.lstrip())
                        if nstripped == "" or nstripped.startswith("#"):
                            i += 1
                            continue
                        if nindent <= 0:
                            break
                        if ":" in nstripped:
                            nkey, _, nvalue = nstripped.partition(":")
                            nkey = nkey.strip()
                            nvalue = nvalue.strip()
                            if nvalue.startswith("[") and nvalue.endswith("]"):
                                nested[nkey] = _parse_inline_list(nvalue)
                                i += 1
                            elif nvalue:
                                nested[nkey] = _parse_scalar(nvalue)
                                i += 1
                            else:
                                # Sub-list or sub-dict
                                sub_items = []
                                sub_indent = nindent
                                i += 1
                                while i < len(lines):
                                    sline = lines[i]
                                    sstripped = sline.strip()
                                    sindent = len(sline) - len(sline.lstrip())
                                    if sstripped == "" or sstripped.startswith("#"):
                                        i += 1
                                        continue
                                    if sindent <= sub_indent:
                                        break
                                    if sstripped.startswith("- "):
                                        sub_val = sstripped[2:].strip()
                                        if ":" in sub_val:
                                            # List of dicts
                                            sk, _, sv = sub_val.partition(":")
                                            sub_dict = {sk.strip(): _parse_scalar(sv.strip()) if sv.strip() else None}
                                            item_base = sindent
                                            i += 1
                                            while i < len(lines):
                                                dline = lines[i]
                                                dstripped = dline.strip()
                                                dindent = len(dline) - len(dline.lstrip())
                                                if dstripped == "" or dstripped.startswith("#"):
                                                    i += 1
                                                    continue
                                                if dindent <= item_base:
                                                    break
                                                if ":" in dstripped:
                                                    dk, _, dv = dstripped.partition(":")
                                                    dv = dv.strip()
                                                    if dv.startswith("[") and dv.endswith("]"):
                                                        sub_dict[dk.strip()] = _parse_inline_list(dv)
                                                    elif dv:
                                                        sub_dict[dk.strip()] = _parse_scalar(dv)
                                                    else:
                                                        # Nested sub-list
                                                        nested_list = []
                                                        i += 1
                                                        while i < len(lines):
                                                            eline = lines[i]
                                                            estripped = eline.strip()
                                                            eindent = len(eline) - len(eline.lstrip())
                                                            if estripped == "" or estripped.startswith("#"):
                                                                i += 1
                                                                continue
                                                            if eindent <= dindent:
                                                                break
                                                            if estripped.startswith("- "):
                                                                nested_list.append(_parse_scalar(estripped[2:].strip()))
                                                            i += 1
                                                        sub_dict[dk.strip()] = nested_list
                                                        continue
                                                i += 1
                                            sub_items.append(sub_dict)
                                            continue
                                        else:
                                            sub_items.append(_parse_scalar(sub_val))
                                    i += 1
                                nested[nkey] = sub_items
                        else:
                            i += 1
                    result[key] = nested
                    continue
                else:
                    # Empty value, no children
                    result[key] = None

            else:
                result[key] = _parse_scalar(value)
        i += 1

    return result


def _parse_scalar(value):
    """Parse a YAML scalar value."""
    # Remove quotes
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]

    # Booleans
    if value.lower() in ("true", "yes"):
        return True
    if value.lower() in ("false", "no"):
        return False

    # Null
    if value.lower() in ("null", "~"):
        return None

    # Numbers
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass

    return value


# Required fields in a recipe
REQUIRED_FIELDS = ["id", "name", "description", "categoryId", "icon", "method"]

# Valid values
VALID_METHODS = {"apt", "script", "deb"}
VALID_LEVELS = {"auto"} | {"{:02d}".format(i) for i in range(0, 10)}
VALID_COMPRESSIONS = {"zstd", "xz", "gzip", "lzo", "lz4"}


def load_recipe(filepath):
    """Load and parse a single YAML recipe file.

    Args:
        filepath: Path to the YAML file.

    Returns:
        Parsed recipe dict.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if yaml is not None:
        recipe = yaml.safe_load(content)
    else:
        recipe = _parse_simple_yaml(content)

    if recipe is None:
        recipe = {}

    return recipe


def validate_recipe(recipe, filepath):
    """Validate a recipe dict.

    Args:
        recipe: Recipe dict to validate.
        filepath: Source file path (for error messages).

    Returns:
        List of error strings (empty if valid).
    """
    errors = []

    for field in REQUIRED_FIELDS:
        if field not in recipe or not recipe[field]:
            errors.append("{}: missing required field '{}'".format(filepath, field))

    method = recipe.get("method", "")
    if method and method not in VALID_METHODS:
        errors.append(
            "{}: invalid method '{}' (must be one of: {})".format(
                filepath, method, ", ".join(sorted(VALID_METHODS))
            )
        )

    level = recipe.get("level", "05")
    if str(level) not in VALID_LEVELS:
        errors.append(
            "{}: invalid level '{}' (must be 00-09)".format(filepath, level)
        )

    compression = recipe.get("compression", "zstd")
    if compression not in VALID_COMPRESSIONS:
        errors.append(
            "{}: invalid compression '{}'".format(filepath, compression)
        )

    # Method-specific validation
    if method == "apt" and not recipe.get("packages"):
        errors.append("{}: apt method requires 'packages' list".format(filepath))
    if method == "script" and not recipe.get("script"):
        errors.append("{}: script method requires 'script' field".format(filepath))
    if method == "deb" and not recipe.get("debUrl"):
        errors.append("{}: deb method requires 'debUrl' field".format(filepath))

    # Distributions structure validation (new per-distribution architecture format)
    distributions = recipe.get("distributions")
    if distributions is not None:
        if not isinstance(distributions, dict):
            errors.append(
                "{}: 'distributions' must be an object".format(filepath)
            )
        else:
            for list_key in ("include", "exclude"):
                entries = distributions.get(list_key)
                if entries is None:
                    continue
                if not isinstance(entries, list):
                    errors.append(
                        "{}: distributions.{} must be a list".format(
                            filepath, list_key
                        )
                    )
                    continue
                for idx, entry in enumerate(entries):
                    if isinstance(entry, str):
                        # Legacy format (plain codename string) — warn
                        errors.append(
                            "{}: distributions.{}[{}] is a plain string '{}'; "
                            "expected object with 'name' field".format(
                                filepath, list_key, idx, entry
                            )
                        )
                    elif isinstance(entry, dict):
                        if "name" not in entry:
                            errors.append(
                                "{}: distributions.{}[{}] missing required 'name' field".format(
                                    filepath, list_key, idx
                                )
                            )
                        archs = entry.get("architectures")
                        if archs is not None and not isinstance(archs, list):
                            errors.append(
                                "{}: distributions.{}[{}].architectures must be a list".format(
                                    filepath, list_key, idx
                                )
                            )
                    else:
                        errors.append(
                            "{}: distributions.{}[{}] must be an object with 'name' field".format(
                                filepath, list_key, idx
                            )
                        )

    # Top-level 'architectures' is deprecated (merged into distributions)
    if "architectures" in recipe:
        errors.append(
            "{}: top-level 'architectures' field is deprecated; "
            "use per-distribution architectures inside 'distributions' instead".format(
                filepath
            )
        )

    return errors


def build_recipes(recipes_dir, validate_only=False):
    """Scan recipes directory and build combined JSON.

    Args:
        recipes_dir: Path to the recipes/ directory.
        validate_only: If True, only validate without producing output.

    Returns:
        Tuple of (recipes_list, errors_list).
    """
    recipes = []
    all_errors = []
    seen_ids = set()

    if not os.path.isdir(recipes_dir):
        all_errors.append("Recipes directory not found: {}".format(recipes_dir))
        return recipes, all_errors

    # Walk through subdirectories
    for root, _dirs, files in sorted(os.walk(recipes_dir)):
        for filename in sorted(files):
            if not filename.endswith((".yaml", ".yml")):
                continue

            filepath = os.path.join(root, filename)
            try:
                recipe = load_recipe(filepath)
            except Exception as e:
                all_errors.append(
                    "{}: failed to parse YAML: {}".format(filepath, str(e))
                )
                continue

            errors = validate_recipe(recipe, filepath)
            all_errors.extend(errors)

            if errors:
                continue

            # Check for duplicate IDs
            recipe_id = str(recipe["id"])
            if recipe_id in seen_ids:
                all_errors.append(
                    "{}: duplicate recipe ID '{}'".format(filepath, recipe_id)
                )
                continue
            seen_ids.add(recipe_id)

            # Ensure correct types (YAML may parse e.g. "2048" as int)
            recipe["level"] = str(recipe.get("level", "05"))
            for str_field in ("id", "name", "description", "categoryId"):
                if str_field in recipe:
                    recipe[str_field] = str(recipe[str_field])

            # Set defaults
            recipe.setdefault("compression", "zstd")
            recipe.setdefault("enabled", True)
            recipe.setdefault("order", 99)

            # Ensure order is int for consistent sorting
            try:
                recipe["order"] = int(recipe["order"])
            except (ValueError, TypeError):
                recipe["order"] = 99

            recipes.append(recipe)

    # Sort by categoryId, then order, then name
    recipes.sort(key=lambda r: (r["categoryId"], r.get("order", 99), r["name"]))

    return recipes, all_errors


def main():
    parser = argparse.ArgumentParser(
        description="Build recipes.json from YAML recipe files"
    )
    parser.add_argument(
        "--recipes-dir",
        default="recipes",
        help="Path to recipes directory (default: recipes)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="web/public/data/recipes.json",
        help="Output JSON file path (default: web/public/data/recipes.json)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate recipes only, don't write output",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        default=True,
        help="Pretty-print JSON output (default: true)",
    )
    parser.add_argument(
        "--no-screenshots",
        action="store_true",
        help="Skip screenshot fetching (use existing cached screenshots only)",
    )
    parser.add_argument(
        "--screenshots-dir",
        default="web/public/screenshots",
        help="Directory for screenshot images (default: web/public/screenshots)",
    )
    parser.add_argument(
        "--screenshot-concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help="Concurrent screenshot download threads (default: {})".format(DEFAULT_CONCURRENCY),
    )
    parser.add_argument(
        "--no-icons",
        action="store_true",
        help="Skip icon fetching (use existing cached icons only)",
    )
    parser.add_argument(
        "--icons-dir",
        default="web/public/icons",
        help="Directory for icon images (default: web/public/icons)",
    )
    parser.add_argument(
        "--icon-concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help="Concurrent icon download threads (default: {})".format(DEFAULT_CONCURRENCY),
    )

    args = parser.parse_args()

    recipes, errors = build_recipes(args.recipes_dir, args.validate)

    if errors:
        print("Validation errors:", file=sys.stderr)
        for err in errors:
            print("  ERROR: {}".format(err), file=sys.stderr)
        sys.exit(1)

    print(
        "Found {} valid recipes across {} categories".format(
            len(recipes),
            len(set(r["categoryId"] for r in recipes)),
        )
    )

    if args.validate:
        print("Validation passed!")
        return

    # --- Screenshot fetching ---
    screenshots_dir = args.screenshots_dir
    if not args.no_screenshots:
        fetch_all_screenshots(
            recipes,
            screenshots_dir,
            concurrency=args.screenshot_concurrency,
        )

    # --- Icon fetching ---
    icons_dir = args.icons_dir
    if not args.no_icons:
        fetch_all_icons(
            recipes,
            icons_dir,
            concurrency=args.icon_concurrency,
        )

    # Populate screenshots field from on-disk files
    # Uses the first package name (or recipe ID) to find screenshot directory
    screenshots_populated = 0
    for recipe in recipes:
        pkg_name = None
        pkgs = recipe.get("packages")
        if pkgs and isinstance(pkgs, list) and len(pkgs) > 0:
            pkg_name = str(pkgs[0])
        else:
            pkg_name = str(recipe["id"])

        shots = scan_screenshots(screenshots_dir, pkg_name)
        if shots:
            recipe["screenshots"] = shots
            screenshots_populated += 1
        else:
            # Don't override if recipe YAML had manual screenshots
            recipe.setdefault("screenshots", None)

    if screenshots_populated > 0:
        logger.info("Populated screenshots for %d recipes", screenshots_populated)

    # Populate appIcon field from on-disk icon files
    icons_populated = 0
    for recipe in recipes:
        pkg_name = None
        pkgs = recipe.get("packages")
        if pkgs and isinstance(pkgs, list) and len(pkgs) > 0:
            pkg_name = str(pkgs[0])
        else:
            pkg_name = str(recipe["id"])

        icon = scan_icon(icons_dir, pkg_name)
        if icon:
            recipe["appIcon"] = icon
            icons_populated += 1

    if icons_populated > 0:
        logger.info("Populated appIcon for %d recipes", icons_populated)

    # Strip build-only fields before writing JSON (not needed by frontend)
    BUILD_ONLY_FIELDS = {"screenshotSources", "iconSources"}
    for recipe in recipes:
        for field in BUILD_ONLY_FIELDS:
            recipe.pop(field, None)

    # Ensure output directory exists
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    indent = 2 if args.pretty else None

    # Write full recipes.json (backward compatibility + admin panel)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(recipes, f, indent=indent, ensure_ascii=False)
        f.write("\n")

    print("Written to: {}".format(args.output))

    # Build lightweight index (without heavy fields: longDescription, script, screenshots)
    # This is loaded by the store UI for browsing and search.
    HEAVY_FIELDS = {"longDescription", "script", "screenshots", "screenshotSources"}
    index = []
    for recipe in recipes:
        light = {k: v for k, v in recipe.items() if k not in HEAVY_FIELDS}
        index.append(light)

    index_path = os.path.join(output_dir, "recipes-index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
        f.write("\n")

    # Write individual recipe detail files (for lazy-loading)
    details_dir = os.path.join(output_dir, "recipes")
    os.makedirs(details_dir, exist_ok=True)
    for recipe in recipes:
        detail = {
            "longDescription": recipe.get("longDescription"),
            "script": recipe.get("script"),
            "screenshots": recipe.get("screenshots"),
        }
        # Only write if there's something worth loading
        if any(v for v in detail.values()):
            detail_path = os.path.join(details_dir, "{}.json".format(recipe["id"]))
            with open(detail_path, "w", encoding="utf-8") as f:
                json.dump(detail, f, ensure_ascii=False)
                f.write("\n")

    full_size = os.path.getsize(args.output)
    index_size = os.path.getsize(index_path)
    print(
        "Index written to: {} ({:,} bytes, {:.0f}% smaller than full)".format(
            index_path, index_size,
            100 * (1 - index_size / full_size) if full_size else 0,
        )
    )
    print("Detail files written to: {}/".format(details_dir))

    # Build per-language aggregated index files (recipes-index.{lang}.json)
    # These allow the frontend to load a single pre-translated index per
    # language, eliminating the flash of English content.
    translations_dir = os.path.join(output_dir, "recipe-translations")
    if os.path.isdir(translations_dir):
        lang_count = 0
        for lang in sorted(os.listdir(translations_dir)):
            lang_dir = os.path.join(translations_dir, lang)
            if not os.path.isdir(lang_dir):
                continue

            # Read all per-recipe translation files for this language
            tr_map = {}
            for fname in os.listdir(lang_dir):
                if not fname.endswith(".json"):
                    continue
                recipe_id = fname[:-5]  # strip .json
                tr_path = os.path.join(lang_dir, fname)
                try:
                    with open(tr_path, "r", encoding="utf-8") as f:
                        tr = json.load(f)
                    tr_map[recipe_id] = tr
                except (json.JSONDecodeError, OSError):
                    continue

            if not tr_map:
                continue

            # Overlay translations onto the lightweight index
            translated_index = []
            for entry in index:
                recipe_id = entry.get("id", "")
                tr = tr_map.get(recipe_id)
                if tr:
                    merged = dict(entry)
                    if tr.get("name"):
                        merged["name"] = tr["name"]
                    if tr.get("description"):
                        merged["description"] = tr["description"]
                    translated_index.append(merged)
                else:
                    translated_index.append(entry)

            lang_index_path = os.path.join(
                output_dir, "recipes-index.{}.json".format(lang)
            )
            with open(lang_index_path, "w", encoding="utf-8") as f:
                json.dump(translated_index, f, ensure_ascii=False)
                f.write("\n")
            lang_count += 1

        if lang_count:
            print(
                "Translated index files written: {} language(s)".format(lang_count)
            )


if __name__ == "__main__":
    main()
