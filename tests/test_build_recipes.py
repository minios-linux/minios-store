"""Tests for tools/build_recipes.py.

Covers the pure helpers (formatting, extension/thumbnail URL handling,
suite extraction, the fallback YAML parser and scalar coercion), recipe
validation, the on-disk scanners, the network helpers (mocked), and the
end-to-end build_recipes() scan.
"""

import urllib.error

import pytest

import build_recipes


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nbytes,expected", [
    (0, "0 B"),
    (512, "512 B"),
    (2048, "2.0 KB"),
    (5 * 1024 * 1024, "5.0 MB"),
    (3 * 1024 * 1024 * 1024, "3.00 GB"),
])
def test_format_size(nbytes, expected):
    assert build_recipes._format_size(nbytes) == expected


@pytest.mark.parametrize("bps,expected", [
    (500, "500 B/s"),
    (2048, "2.0 KB/s"),
    (5 * 1024 * 1024, "5.0 MB/s"),
])
def test_format_speed(bps, expected):
    assert build_recipes._format_speed(bps) == expected


# ---------------------------------------------------------------------------
# get_file_extension / _thumb_url_at1
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("http://x/a.png", ".png"),
    ("http://x/a.JPG", ".jpg"),
    ("http://x/a.jpeg", ".jpeg"),
    ("http://x/a.webp", ".webp"),
    ("http://x/a.gif?size=1", ".gif"),
    ("http://x/noext", ".png"),
])
def test_get_file_extension(url, expected):
    assert build_recipes.get_file_extension(url) == expected


def test_thumb_url_at1_inserts_suffix():
    assert (
        build_recipes._thumb_url_at1("http://x/img_624x351.png")
        == "http://x/img_624x351@1.png"
    )


def test_thumb_url_at1_unknown_extension_unchanged():
    assert build_recipes._thumb_url_at1("http://x/noext") == "http://x/noext"


# ---------------------------------------------------------------------------
# _extract_suites
# ---------------------------------------------------------------------------

def test_extract_suites_classifies_families():
    recipe = {
        "distributions": {
            "include": [
                {"name": "bookworm"},
                {"name": "trixie-backports"},
                {"name": "noble"},
                "jammy",  # plain string form
            ]
        }
    }
    suites = build_recipes._extract_suites(recipe)
    assert suites["debian"] == ["bookworm", "trixie-backports"]
    assert suites["ubuntu"] == ["noble", "jammy"]


def test_extract_suites_empty_when_no_distributions():
    assert build_recipes._extract_suites({}) == {"debian": [], "ubuntu": []}


def test_extract_suites_handles_non_dict_distributions():
    assert build_recipes._extract_suites(
        {"distributions": "bogus"}
    ) == {"debian": [], "ubuntu": []}


# ---------------------------------------------------------------------------
# _parse_scalar
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ('"quoted"', "quoted"),
    ("'single'", "single"),
    ("true", True),
    ("yes", True),
    ("false", False),
    ("no", False),
    ("null", None),
    ("~", None),
    ("42", 42),
    ("3.14", 3.14),
    ("plain", "plain"),
])
def test_parse_scalar(value, expected):
    assert build_recipes._parse_scalar(value) == expected


# ---------------------------------------------------------------------------
# _parse_simple_yaml (fallback parser used when PyYAML is unavailable)
# ---------------------------------------------------------------------------

def test_parse_simple_yaml_full_recipe():
    text = (
        "id: firefox\n"
        "name: Firefox\n"
        "enabled: true\n"
        "order: 5\n"
        "packages:\n"
        "  - firefox\n"
        "  - firefox-esr\n"
        "distributions:\n"
        "  include:\n"
        "    - name: bookworm\n"
        "      architectures: [amd64, i386]\n"
        "script: |\n"
        "  echo hello\n"
        "  echo world\n"
    )
    data = build_recipes._parse_simple_yaml(text)
    assert data["id"] == "firefox"
    assert data["enabled"] is True
    assert data["order"] == 5
    assert data["packages"] == ["firefox", "firefox-esr"]
    include = data["distributions"]["include"]
    assert include[0]["name"] == "bookworm"
    assert include[0]["architectures"] == ["amd64", "i386"]
    assert "echo hello" in data["script"]
    assert "echo world" in data["script"]


def test_parse_simple_yaml_inline_list():
    data = build_recipes._parse_simple_yaml("architectures: [amd64, arm64]\n")
    assert data["architectures"] == ["amd64", "arm64"]


# ---------------------------------------------------------------------------
# load_recipe (PyYAML path)
# ---------------------------------------------------------------------------

def test_load_recipe_reads_yaml(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("id: vlc\nname: VLC\n")
    data = build_recipes.load_recipe(str(p))
    assert data["id"] == "vlc"
    assert data["name"] == "VLC"


def test_load_recipe_empty_returns_dict(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("")
    assert build_recipes.load_recipe(str(p)) == {}


# ---------------------------------------------------------------------------
# validate_recipe
# ---------------------------------------------------------------------------

def _valid_recipe():
    return {
        "id": "firefox",
        "name": "Firefox",
        "description": "Web browser",
        "categoryId": "internet",
        "icon": "Globe",
        "method": "apt",
        "level": "05",
        "compression": "zstd",
        "packages": ["firefox"],
    }


def test_validate_recipe_accepts_valid():
    assert build_recipes.validate_recipe(_valid_recipe(), "f.yaml") == []


def test_validate_recipe_missing_required_fields():
    errors = build_recipes.validate_recipe({}, "f.yaml")
    assert any("missing required field" in e for e in errors)


def test_validate_recipe_invalid_method():
    r = _valid_recipe()
    r["method"] = "bogus"
    errors = build_recipes.validate_recipe(r, "f.yaml")
    assert any("invalid method" in e for e in errors)


def test_validate_recipe_invalid_level():
    r = _valid_recipe()
    r["level"] = "99"
    errors = build_recipes.validate_recipe(r, "f.yaml")
    assert any("invalid level" in e for e in errors)


def test_validate_recipe_invalid_compression():
    r = _valid_recipe()
    r["compression"] = "bzip2"
    errors = build_recipes.validate_recipe(r, "f.yaml")
    assert any("invalid compression" in e for e in errors)


def test_validate_recipe_apt_requires_packages():
    r = _valid_recipe()
    r["packages"] = []
    errors = build_recipes.validate_recipe(r, "f.yaml")
    assert any("apt method requires 'packages'" in e for e in errors)


def test_validate_recipe_script_requires_script():
    r = _valid_recipe()
    r["method"] = "script"
    r.pop("packages")
    errors = build_recipes.validate_recipe(r, "f.yaml")
    assert any("script method requires 'script'" in e for e in errors)


def test_validate_recipe_deb_requires_url():
    r = _valid_recipe()
    r["method"] = "deb"
    r.pop("packages")
    errors = build_recipes.validate_recipe(r, "f.yaml")
    assert any("deb method requires 'debUrl'" in e for e in errors)


def test_validate_recipe_distributions_must_be_object():
    r = _valid_recipe()
    r["distributions"] = ["bookworm"]
    errors = build_recipes.validate_recipe(r, "f.yaml")
    assert any("'distributions' must be an object" in e for e in errors)


def test_validate_recipe_distributions_include_must_be_list():
    r = _valid_recipe()
    r["distributions"] = {"include": "bookworm"}
    errors = build_recipes.validate_recipe(r, "f.yaml")
    assert any("must be a list" in e for e in errors)


def test_validate_recipe_distributions_plain_string_entry():
    r = _valid_recipe()
    r["distributions"] = {"include": ["bookworm"]}
    errors = build_recipes.validate_recipe(r, "f.yaml")
    assert any("plain string" in e for e in errors)


def test_validate_recipe_distributions_entry_missing_name():
    r = _valid_recipe()
    r["distributions"] = {"include": [{"architectures": ["amd64"]}]}
    errors = build_recipes.validate_recipe(r, "f.yaml")
    assert any("missing required 'name'" in e for e in errors)


def test_validate_recipe_distributions_architectures_must_be_list():
    r = _valid_recipe()
    r["distributions"] = {"include": [{"name": "bookworm", "architectures": "amd64"}]}
    errors = build_recipes.validate_recipe(r, "f.yaml")
    assert any("architectures must be a list" in e for e in errors)


def test_validate_recipe_deprecated_top_level_architectures():
    r = _valid_recipe()
    r["architectures"] = ["amd64"]
    errors = build_recipes.validate_recipe(r, "f.yaml")
    assert any("deprecated" in e for e in errors)


# ---------------------------------------------------------------------------
# build_recipes (end-to-end scan)
# ---------------------------------------------------------------------------

_VALID_YAML = (
    "id: {id}\n"
    "name: {name}\n"
    "description: Desc\n"
    "categoryId: internet\n"
    "icon: Globe\n"
    "method: apt\n"
    'level: "05"\n'
    "compression: zstd\n"
    "packages:\n"
    "  - {id}\n"
)


def test_build_recipes_collects_valid(tmp_path):
    d = tmp_path / "recipes" / "internet"
    d.mkdir(parents=True)
    (d / "firefox.yaml").write_text(_VALID_YAML.format(id="firefox", name="Firefox"))
    recipes, errors = build_recipes.build_recipes(str(tmp_path / "recipes"))
    assert errors == []
    assert len(recipes) == 1
    assert recipes[0]["id"] == "firefox"
    assert recipes[0]["order"] == 99  # default applied


def test_build_recipes_missing_dir_reports_error():
    recipes, errors = build_recipes.build_recipes("/no/such/dir/xyz")
    assert recipes == []
    assert any("not found" in e for e in errors)


def test_build_recipes_detects_duplicate_ids(tmp_path):
    d = tmp_path / "recipes" / "internet"
    d.mkdir(parents=True)
    (d / "a.yaml").write_text(_VALID_YAML.format(id="dup", name="A"))
    (d / "b.yaml").write_text(_VALID_YAML.format(id="dup", name="B"))
    _recipes, errors = build_recipes.build_recipes(str(tmp_path / "recipes"))
    assert any("duplicate recipe ID" in e for e in errors)


def test_build_recipes_reports_invalid(tmp_path):
    d = tmp_path / "recipes" / "internet"
    d.mkdir(parents=True)
    (d / "bad.yaml").write_text("id: bad\nmethod: apt\n")  # missing fields
    recipes, errors = build_recipes.build_recipes(str(tmp_path / "recipes"))
    assert recipes == []
    assert errors


# ---------------------------------------------------------------------------
# scan_screenshots / scan_icon
# ---------------------------------------------------------------------------

def test_scan_screenshots_returns_paths_and_trims_excess(tmp_path):
    pkg_dir = tmp_path / "vlc"
    pkg_dir.mkdir()
    for i in range(1, 6):
        (pkg_dir / "{}.png".format(i)).write_bytes(b"img")
        (pkg_dir / "{}_small.png".format(i)).write_bytes(b"thumb")

    shots = build_recipes.scan_screenshots(str(tmp_path), "vlc")
    assert len(shots) == build_recipes.MAX_SCREENSHOTS
    assert shots[0] == "/screenshots/vlc/1.png"
    # Excess full-size images and their thumbnails are deleted
    assert not (pkg_dir / "4.png").exists()
    assert not (pkg_dir / "4_small.png").exists()


def test_scan_screenshots_missing_dir(tmp_path):
    assert build_recipes.scan_screenshots(str(tmp_path), "nope") == []


def test_scan_icon_found(tmp_path):
    (tmp_path / "vlc.png").write_bytes(b"icon")
    assert build_recipes.scan_icon(str(tmp_path), "vlc") == "/icons/vlc.png"


def test_scan_icon_missing(tmp_path):
    assert build_recipes.scan_icon(str(tmp_path), "nope") is None


def test_scan_icon_empty_file_ignored(tmp_path):
    (tmp_path / "vlc.png").write_bytes(b"")
    assert build_recipes.scan_icon(str(tmp_path), "vlc") is None


# ---------------------------------------------------------------------------
# fetch_json / download_file (mocked urlopen)
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_fetch_json_success(monkeypatch):
    monkeypatch.setattr(
        build_recipes.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResp(b'{"a": 1}'),
    )
    assert build_recipes.fetch_json("http://x") == {"a": 1}


def test_fetch_json_404_reraises(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.HTTPError("http://x", 404, "nf", None, None)

    monkeypatch.setattr(build_recipes.urllib.request, "urlopen", boom)
    with pytest.raises(urllib.error.HTTPError):
        build_recipes.fetch_json("http://x")


def test_fetch_json_network_error_returns_none(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(build_recipes.urllib.request, "urlopen", boom)
    assert build_recipes.fetch_json("http://x") is None


def test_download_file_writes_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        build_recipes.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResp(b"data"),
    )
    dest = tmp_path / "sub" / "f.png"
    n = build_recipes.download_file("http://x", str(dest))
    assert n == 4
    assert dest.read_bytes() == b"data"


def test_download_file_empty_response_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(
        build_recipes.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResp(b""),
    )
    assert build_recipes.download_file("http://x", str(tmp_path / "f")) == 0


def test_download_file_error_returns_zero(tmp_path, monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(build_recipes.urllib.request, "urlopen", boom)
    assert build_recipes.download_file("http://x", str(tmp_path / "f")) == 0


# ---------------------------------------------------------------------------
# _fetch_from_appstream / _fetch_from_debian_screenshots
# ---------------------------------------------------------------------------

def test_fetch_from_appstream_downloads(tmp_path, monkeypatch):
    def fake_dl(url, dest):
        import os
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(b"img")
        return 3

    monkeypatch.setattr(build_recipes, "download_file", fake_dl)
    pkg_dir = tmp_path / "vlc"
    count, nbytes, cached = build_recipes._fetch_from_appstream(
        "vlc", str(pkg_dir), str(pkg_dir / ".no_screenshots"),
        [{"url": "a.png", "thumbnailUrl": "a-thumb.png"}],
        {"debian": ["bookworm"], "ubuntu": []}, "fp",
    )
    assert count == 1
    assert nbytes > 0
    assert cached is False


def test_fetch_from_appstream_no_media_writes_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(build_recipes, "download_file", lambda url, dest: 0)
    pkg_dir = tmp_path / "vlc"
    marker = pkg_dir / ".no_screenshots"
    count, _nbytes, _cached = build_recipes._fetch_from_appstream(
        "vlc", str(pkg_dir), str(marker),
        [{"url": "a.png"}], {"debian": [], "ubuntu": []}, "fp",
    )
    assert count == 0
    assert marker.exists()
    assert marker.read_text() == "fp"


def test_fetch_from_debian_screenshots_success(tmp_path, monkeypatch):
    data = {
        "screenshots": [
            {
                "screenshot_image_url": "http://x/1.png",
                "small_image_url": "http://x/1s.png",
                "version": "1",
            }
        ]
    }
    monkeypatch.setattr(build_recipes, "fetch_json", lambda url: data)

    def fake_dl(url, dest):
        import os
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(b"12345")
        return 5

    monkeypatch.setattr(build_recipes, "download_file", fake_dl)
    count, _nbytes, _cached = build_recipes._fetch_from_debian_screenshots(
        "vlc", str(tmp_path / "vlc"), str(tmp_path / "vlc" / ".no_screenshots")
    )
    assert count == 1


def test_fetch_from_debian_screenshots_404_writes_marker(tmp_path, monkeypatch):
    def boom(url):
        raise urllib.error.HTTPError(url, 404, "nf", None, None)

    monkeypatch.setattr(build_recipes, "fetch_json", boom)
    pkg_dir = tmp_path / "vlc"
    marker = pkg_dir / ".no_screenshots"
    count, _nbytes, _cached = build_recipes._fetch_from_debian_screenshots(
        "vlc", str(pkg_dir), str(marker)
    )
    assert count == 0
    assert marker.exists()


# ---------------------------------------------------------------------------
# fetch_package_screenshots / fetch_package_icon (caching)
# ---------------------------------------------------------------------------

def test_fetch_package_screenshots_uses_valid_negative_cache(tmp_path):
    pkg_dir = tmp_path / "vlc"
    pkg_dir.mkdir()
    (pkg_dir / ".no_screenshots").write_text("http://x/a.png")
    result = build_recipes.fetch_package_screenshots(
        "vlc", str(tmp_path),
        screenshot_sources=[{"url": "http://x/a.png"}],
    )
    assert result == (0, 0, True)


def test_fetch_package_icon_no_sources_returns_zero(tmp_path):
    assert build_recipes.fetch_package_icon("vlc", str(tmp_path)) == (0, 0, False)


def test_fetch_package_icon_cached_hit(tmp_path):
    (tmp_path / "vlc.png").write_bytes(b"icon")
    found, _nbytes, cached = build_recipes.fetch_package_icon(
        "vlc", str(tmp_path), icon_sources=[{"url": "x/icon.png"}]
    )
    assert found == 1
    assert cached is True


def test_fetch_package_icon_remote_download(tmp_path, monkeypatch):
    def fake_dl(url, dest):
        with open(dest, "wb") as f:
            f.write(b"icon")
        return 4

    monkeypatch.setattr(build_recipes, "download_file", fake_dl)
    found, nbytes, cached = build_recipes.fetch_package_icon(
        "vlc", str(tmp_path),
        icon_sources=[{"url": "icons/vlc.png"}],
        suites={"debian": ["bookworm"], "ubuntu": []},
    )
    assert found == 1
    assert nbytes == 4
    assert cached is False


# ---------------------------------------------------------------------------
# _parse_simple_yaml -- deeper nesting
# ---------------------------------------------------------------------------

def test_parse_simple_yaml_tags_list():
    data = build_recipes._parse_simple_yaml("tags:\n  - a\n  - b\n")
    assert data["tags"] == ["a", "b"]


def test_parse_simple_yaml_nested_sublist_architectures():
    text = (
        "distributions:\n"
        "  include:\n"
        "    - name: bookworm\n"
        "      architectures:\n"
        "        - amd64\n"
        "        - i386\n"
    )
    data = build_recipes._parse_simple_yaml(text)
    inc = data["distributions"]["include"][0]
    assert inc["name"] == "bookworm"
    assert inc["architectures"] == ["amd64", "i386"]


# ---------------------------------------------------------------------------
# _load_icon_tarballs / fetch_all_* orchestrators (mocked workers)
# ---------------------------------------------------------------------------

def test_load_icon_tarballs_no_cached_returns_empty():
    recipes = [{"id": "vlc", "iconSources": [{"url": "remote/icon.png"}]}]
    assert build_recipes._load_icon_tarballs(recipes) == {}


def test_fetch_all_screenshots_aggregates(tmp_path, monkeypatch):
    def fake(pkg, out, screenshot_sources=None, suites=None):
        return (2, 100, False)

    monkeypatch.setattr(build_recipes, "fetch_package_screenshots", fake)
    recipes = [
        {"id": "vlc", "packages": ["vlc"]},
        {"id": "gimp", "packages": ["gimp"]},
    ]
    results = build_recipes.fetch_all_screenshots(recipes, str(tmp_path), concurrency=2)
    assert results == {"vlc": 2, "gimp": 2}


def test_fetch_all_screenshots_handles_worker_error(tmp_path, monkeypatch):
    def boom(pkg, out, screenshot_sources=None, suites=None):
        raise RuntimeError("worker failed")

    monkeypatch.setattr(build_recipes, "fetch_package_screenshots", boom)
    results = build_recipes.fetch_all_screenshots(
        [{"id": "vlc", "packages": ["vlc"]}], str(tmp_path), concurrency=1
    )
    assert results == {}


def test_fetch_all_icons_aggregates(tmp_path, monkeypatch):
    monkeypatch.setattr(build_recipes, "_load_icon_tarballs", lambda recipes: {})

    def fake(pkg, out, icon_sources=None, suites=None, icon_tarballs=None):
        return (1, 50, False)

    monkeypatch.setattr(build_recipes, "fetch_package_icon", fake)
    recipes = [{"id": "vlc", "packages": ["vlc"], "iconSources": [{"url": "x"}]}]
    results = build_recipes.fetch_all_icons(recipes, str(tmp_path), concurrency=2)
    assert results == {"vlc": 1}


def test_fetch_all_icons_no_sources_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(build_recipes, "_load_icon_tarballs", lambda recipes: {})
    results = build_recipes.fetch_all_icons(
        [{"id": "vlc", "packages": ["vlc"]}], str(tmp_path)
    )
    assert results == {}


# ---------------------------------------------------------------------------
# main() -- CLI entry point / JSON build pipeline
# ---------------------------------------------------------------------------

def test_main_validate_only(tmp_path, monkeypatch, capsys):
    d = tmp_path / "recipes" / "internet"
    d.mkdir(parents=True)
    (d / "firefox.yaml").write_text(_VALID_YAML.format(id="firefox", name="Firefox"))
    monkeypatch.setattr(build_recipes.sys, "argv", [
        "build_recipes.py",
        "--recipes-dir", str(tmp_path / "recipes"),
        "--validate",
    ])
    build_recipes.main()
    assert "Validation passed" in capsys.readouterr().out


def test_main_builds_json(tmp_path, monkeypatch):
    import json
    d = tmp_path / "recipes" / "internet"
    d.mkdir(parents=True)
    (d / "firefox.yaml").write_text(_VALID_YAML.format(id="firefox", name="Firefox"))

    # Pre-seed on-disk media so the scan populates screenshots + appIcon and
    # writes a per-recipe detail file.
    shots = tmp_path / "shots" / "firefox"
    shots.mkdir(parents=True)
    (shots / "1.png").write_bytes(b"img")
    icons = tmp_path / "icons"
    icons.mkdir()
    (icons / "firefox.png").write_bytes(b"icon")

    output = tmp_path / "out" / "recipes.json"
    monkeypatch.setattr(build_recipes.sys, "argv", [
        "build_recipes.py",
        "--recipes-dir", str(tmp_path / "recipes"),
        "-o", str(output),
        "--no-screenshots", "--no-icons",
        "--screenshots-dir", str(tmp_path / "shots"),
        "--icons-dir", str(icons),
    ])
    build_recipes.main()

    assert output.exists()
    data = json.loads(output.read_text())
    assert data[0]["id"] == "firefox"
    assert data[0]["screenshots"] == ["/screenshots/firefox/1.png"]
    assert data[0]["appIcon"] == "/icons/firefox.png"
    assert (output.parent / "recipes-index.json").exists()
    # Detail file written because the recipe now has screenshots
    assert (output.parent / "recipes" / "firefox.json").exists()


def test_main_writes_translation_index(tmp_path, monkeypatch):
    import json
    d = tmp_path / "recipes" / "internet"
    d.mkdir(parents=True)
    (d / "firefox.yaml").write_text(_VALID_YAML.format(id="firefox", name="Firefox"))

    output = tmp_path / "out" / "recipes.json"
    # recipe-translations/<lang>/<id>.json lives next to the output
    tr_dir = output.parent / "recipe-translations" / "ru"
    tr_dir.mkdir(parents=True)
    (tr_dir / "firefox.json").write_text(
        json.dumps({"name": "Файрфокс", "description": "Браузер"})
    )

    monkeypatch.setattr(build_recipes.sys, "argv", [
        "build_recipes.py",
        "--recipes-dir", str(tmp_path / "recipes"),
        "-o", str(output),
        "--no-screenshots", "--no-icons",
        "--screenshots-dir", str(tmp_path / "shots"),
        "--icons-dir", str(tmp_path / "icons"),
    ])
    build_recipes.main()

    lang_index = output.parent / "recipes-index.ru.json"
    assert lang_index.exists()
    translated = json.loads(lang_index.read_text())
    assert translated[0]["name"] == "Файрфокс"


def test_main_invalid_recipe_exits(tmp_path, monkeypatch):
    d = tmp_path / "recipes" / "internet"
    d.mkdir(parents=True)
    (d / "bad.yaml").write_text("id: bad\nmethod: apt\n")
    monkeypatch.setattr(build_recipes.sys, "argv", [
        "build_recipes.py",
        "--recipes-dir", str(tmp_path / "recipes"),
        "--validate",
    ])
    with pytest.raises(SystemExit):
        build_recipes.main()
