"""Tests for tools/repo_parser.py.

Covers category/icon mapping, recipe-id generation, AppStream component
detection and extraction, recipe construction and YAML serialisation
(round-tripped through PyYAML), the DEP-11 multi-document parser, network
fetching (mocked), and the existing-recipe update / distribution parsing
orchestration.
"""

import gzip
import urllib.error

import pytest
import yaml

import repo_parser


# ---------------------------------------------------------------------------
# map_category
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("categories,expected", [
    (["WebBrowser"], "internet"),
    (["AudioVideo"], "multimedia"),
    (["Graphics"], "graphics"),
    (["Office"], "office"),
    (["Development"], "development"),
    (["Game"], "games"),
    (["Security"], "security"),
    (["System"], "system"),
    ([], "system"),
    (["TotallyUnknown"], "system"),
])
def test_map_category(categories, expected):
    assert repo_parser.map_category(categories) == expected


def test_map_category_respects_priority():
    # internet outranks development
    assert repo_parser.map_category(["Development", "WebBrowser"]) == "internet"
    # games outranks system
    assert repo_parser.map_category(["Utility", "Game"]) == "games"


# ---------------------------------------------------------------------------
# map_icon
# ---------------------------------------------------------------------------

def test_map_icon_exact_package_match():
    info = {"package": "vlc", "icon_name": "", "appstream_id": ""}
    assert repo_parser.map_icon(info, "multimedia") == "Video"


def test_map_icon_from_icon_name():
    info = {"package": "unknownpkg", "icon_name": "firefox.png", "appstream_id": ""}
    assert repo_parser.map_icon(info, "internet") == "Globe"


def test_map_icon_from_appstream_id():
    info = {"package": "unknownpkg", "icon_name": "", "appstream_id": "org.videolan.vlc"}
    assert repo_parser.map_icon(info, "multimedia") == "Video"


def test_map_icon_category_fallback():
    info = {"package": "zzz", "icon_name": "", "appstream_id": ""}
    assert repo_parser.map_icon(info, "games") == "Gamepad2"


def test_map_icon_default_package_when_no_hint():
    info = {"package": "zzz", "icon_name": "", "appstream_id": ""}
    assert repo_parser.map_icon(info, "no-such-category") == "Package"


# ---------------------------------------------------------------------------
# generate_recipe_id
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("package,expected", [
    ("vlc", "vlc"),
    ("VLC", "vlc"),
    ("foo+bar", "fooplusbar"),
    ("foo.bar", "foo-bar"),
    ("g++", "gplusplus"),
])
def test_generate_recipe_id(package, expected):
    assert repo_parser.generate_recipe_id({"package": package}) == expected


# ---------------------------------------------------------------------------
# is_desktop_application
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("comp_type,expected", [
    ("desktop-application", True),
    ("web-application", True),
    ("console-application", True),
    ("addon", False),
    ("font", False),
    (None, False),
])
def test_is_desktop_application(comp_type, expected):
    assert repo_parser.is_desktop_application({"Type": comp_type}) is expected


# ---------------------------------------------------------------------------
# extract_app_info
# ---------------------------------------------------------------------------

def _vlc_doc():
    return {
        "Type": "desktop-application",
        "ID": "org.videolan.VLC",
        "Name": {"C": "VLC"},
        "Summary": {"C": "Media player"},
        "Description": {"C": "Plays everything"},
        "Package": "vlc",
        "Categories": ["AudioVideo", "Player"],
        "Icon": {"cached": [{"name": "vlc.png", "width": 64, "height": 64}]},
        "Keywords": {"C": ["media", "video"]},
        "ProjectLicense": "GPL-2.0",
        "DeveloperName": {"C": "VideoLAN"},
        "Url": {"homepage": "https://videolan.org"},
        "Screenshots": [
            {
                "source-image": {"url": "ss/1.png", "width": 1920, "height": 1080},
                "thumbnails": [{"url": "ss/1_624.png", "width": 624}],
            }
        ],
    }


def test_extract_app_info_full():
    info = repo_parser.extract_app_info(_vlc_doc())
    assert info["package"] == "vlc"
    assert info["name"] == "VLC"
    assert info["summary"] == "Media player"
    assert info["description"] == "Plays everything"
    assert info["categories"] == ["AudioVideo", "Player"]
    assert info["keywords"] == ["media", "video"]
    assert info["license"] == "GPL-2.0"
    assert info["developer"] == "VideoLAN"
    assert info["homepage"] == "https://videolan.org"
    assert info["screenshots"][0]["url"] == "ss/1.png"
    assert info["screenshots"][0]["thumbnailUrl"] == "ss/1_624.png"
    assert info["icon_sources"][0]["cached"] == "vlc.png"


def test_extract_app_info_remote_icon():
    doc = _vlc_doc()
    doc["Icon"] = {"remote": [{"url": "icons/vlc.png", "width": 128, "height": 128}]}
    info = repo_parser.extract_app_info(doc)
    assert info["icon_sources"][0]["url"] == "icons/vlc.png"
    assert info["icon_sources"][0]["width"] == 128


def test_extract_app_info_name_as_string():
    doc = {"ID": "x", "Name": "Plain", "Package": "plain"}
    info = repo_parser.extract_app_info(doc)
    assert info["name"] == "Plain"


def test_extract_app_info_requires_id():
    assert repo_parser.extract_app_info({"Name": {"C": "X"}, "Package": "x"}) is None


def test_extract_app_info_requires_name():
    assert repo_parser.extract_app_info({"ID": "x", "Package": "x"}) is None


def test_extract_app_info_requires_package():
    assert repo_parser.extract_app_info({"ID": "x", "Name": {"C": "X"}}) is None


def test_extract_app_info_package_from_pkgname_list():
    doc = {"ID": "x", "Name": {"C": "X"}, "Pkgname": ["mypkg"]}
    info = repo_parser.extract_app_info(doc)
    assert info["package"] == "mypkg"


# ---------------------------------------------------------------------------
# app_to_recipe
# ---------------------------------------------------------------------------

def test_app_to_recipe():
    info = repo_parser.extract_app_info(_vlc_doc())
    recipe = repo_parser.app_to_recipe(info, "trixie", "amd64")
    assert recipe["id"] == "vlc"
    assert recipe["name"] == "VLC"
    assert recipe["method"] == "apt"
    assert recipe["categoryId"] == "multimedia"
    assert recipe["packages"] == ["vlc"]
    assert recipe["distributions"]["include"][0]["name"] == "trixie"
    assert recipe["distributions"]["include"][0]["architectures"] == ["amd64"]
    assert recipe["tags"] == ["media", "video"]
    assert recipe["longDescription"] == "Plays everything"
    assert recipe["developer"] == "VideoLAN"
    assert recipe["homepage"] == "https://videolan.org"
    assert recipe["screenshotSources"][0]["url"] == "ss/1.png"


# ---------------------------------------------------------------------------
# recipe_to_yaml (round-trip through PyYAML)
# ---------------------------------------------------------------------------

def test_recipe_to_yaml_roundtrip():
    info = repo_parser.extract_app_info(_vlc_doc())
    recipe = repo_parser.app_to_recipe(info, "trixie", "amd64")
    text = repo_parser.recipe_to_yaml(recipe)
    parsed = yaml.safe_load(text)

    assert parsed["id"] == "vlc"
    assert parsed["name"] == "VLC"
    assert parsed["categoryId"] == "multimedia"
    assert parsed["method"] == "apt"
    assert parsed["packages"] == ["vlc"]
    assert parsed["distributions"]["include"][0]["name"] == "trixie"
    assert parsed["distributions"]["include"][0]["architectures"] == ["amd64"]
    assert parsed["tags"] == ["media", "video"]
    assert "Plays everything" in parsed["longDescription"]
    assert parsed["enabled"] is True


def test_recipe_to_yaml_quotes_values_with_colons():
    recipe = {
        "id": "x",
        "name": "Name: with colon",
        "description": "Desc",
        "categoryId": "system",
        "icon": "Wrench",
        "method": "apt",
        "level": "auto",
        "compression": "zstd",
    }
    text = repo_parser.recipe_to_yaml(recipe)
    parsed = yaml.safe_load(text)
    assert parsed["name"] == "Name: with colon"


# ---------------------------------------------------------------------------
# parse_dep11_documents
# ---------------------------------------------------------------------------

def test_parse_dep11_documents_yields_all():
    text = "---\nID: a\n---\nID: b\n---\n"
    docs = list(repo_parser.parse_dep11_documents(text))
    ids = [d.get("ID") for d in docs]
    assert ids == ["a", "b"]


# ---------------------------------------------------------------------------
# fetch_dep11 (mocked network)
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


def test_fetch_dep11_success(monkeypatch):
    raw = gzip.compress(b"ID: x\n")
    monkeypatch.setattr(
        repo_parser.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResp(raw),
    )
    text = repo_parser.fetch_dep11("http://mirror", "trixie", "main", "amd64")
    assert "ID: x" in text


def test_fetch_dep11_404_returns_none(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.HTTPError("u", 404, "nf", None, None)

    monkeypatch.setattr(repo_parser.urllib.request, "urlopen", boom)
    assert repo_parser.fetch_dep11("http://mirror", "trixie", "main", "amd64") is None


def test_fetch_dep11_network_error_returns_none(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(repo_parser.urllib.request, "urlopen", boom)
    assert repo_parser.fetch_dep11("http://mirror", "trixie", "main", "amd64") is None


# ---------------------------------------------------------------------------
# load_existing_recipes
# ---------------------------------------------------------------------------

def test_load_existing_recipes(tmp_path):
    d = tmp_path / "internet"
    d.mkdir()
    (d / "firefox.yaml").write_text("id: firefox\nname: Firefox\n")
    existing = repo_parser.load_existing_recipes(str(tmp_path))
    assert "firefox" in existing
    filepath, data = existing["firefox"]
    assert data["name"] == "Firefox"


def test_load_existing_recipes_missing_dir():
    assert repo_parser.load_existing_recipes("/no/such/dir") == {}


# ---------------------------------------------------------------------------
# update_existing_recipe_distributions
# ---------------------------------------------------------------------------

def test_update_existing_recipe_adds_distribution(tmp_path):
    p = tmp_path / "firefox.yaml"
    recipe = {
        "id": "firefox", "name": "Firefox", "description": "Web",
        "categoryId": "internet", "icon": "Globe", "method": "apt",
        "level": "auto", "compression": "zstd", "packages": ["firefox"],
    }
    p.write_text(repo_parser.recipe_to_yaml(recipe))

    modified = repo_parser.update_existing_recipe_distributions(
        str(p), dict(recipe), "trixie", "amd64",
    )
    assert modified is True
    reloaded = yaml.safe_load(p.read_text())
    include = reloaded["distributions"]["include"]
    assert include[0]["name"] == "trixie"
    assert "amd64" in include[0]["architectures"]


def test_update_existing_recipe_noop_when_present(tmp_path):
    p = tmp_path / "firefox.yaml"
    recipe = {
        "id": "firefox", "name": "Firefox", "description": "Web",
        "categoryId": "internet", "icon": "Globe", "method": "apt",
        "level": "auto", "compression": "zstd", "packages": ["firefox"],
        "distributions": {"include": [{"name": "trixie", "architectures": ["amd64"]}]},
    }
    p.write_text(repo_parser.recipe_to_yaml(recipe))

    modified = repo_parser.update_existing_recipe_distributions(
        str(p), dict(recipe), "trixie", "amd64",
    )
    assert modified is False


def test_update_existing_recipe_adds_arch_to_existing_entry(tmp_path):
    p = tmp_path / "firefox.yaml"
    recipe = {
        "id": "firefox", "name": "Firefox", "description": "Web",
        "categoryId": "internet", "icon": "Globe", "method": "apt",
        "level": "auto", "compression": "zstd", "packages": ["firefox"],
        "distributions": {"include": [{"name": "trixie", "architectures": ["amd64"]}]},
    }
    p.write_text(repo_parser.recipe_to_yaml(recipe))

    modified = repo_parser.update_existing_recipe_distributions(
        str(p), dict(recipe), "trixie", "i386",
    )
    assert modified is True
    reloaded = yaml.safe_load(p.read_text())
    archs = reloaded["distributions"]["include"][0]["architectures"]
    assert archs == ["amd64", "i386"]


# ---------------------------------------------------------------------------
# parse_distribution (mocked fetch_dep11)
# ---------------------------------------------------------------------------

def test_parse_distribution_unknown_returns_zeros(tmp_path):
    assert repo_parser.parse_distribution(
        "nosuchdist", "amd64", recipes_dir=str(tmp_path)
    ) == (0, 0, 0)


def test_parse_distribution_creates_new_recipe(tmp_path, monkeypatch):
    dep11 = (
        "---\n"
        "Type: desktop-application\n"
        "ID: org.x.Foo\n"
        "Name:\n"
        "  C: Foo\n"
        "Summary:\n"
        "  C: A foo app\n"
        "Package: foo\n"
        "Categories:\n"
        "  - Utility\n"
    )

    def fake_fetch(mirror, codename, component, arch):
        return dep11 if component == "main" else None

    monkeypatch.setattr(repo_parser, "fetch_dep11", fake_fetch)
    new, updated, skipped = repo_parser.parse_distribution(
        "trixie", "amd64", recipes_dir=str(tmp_path),
    )
    assert new >= 1
    # "Utility" maps to the system category
    assert (tmp_path / "system" / "foo.yaml").exists()


def test_parse_distribution_dry_run_writes_nothing(tmp_path, monkeypatch):
    dep11 = (
        "---\n"
        "Type: desktop-application\n"
        "ID: org.x.Foo\n"
        "Name:\n"
        "  C: Foo\n"
        "Summary:\n"
        "  C: A foo app\n"
        "Package: foo\n"
        "Categories:\n"
        "  - Utility\n"
    )
    monkeypatch.setattr(
        repo_parser, "fetch_dep11",
        lambda m, c, comp, a: dep11 if comp == "main" else None,
    )
    new, _updated, _skipped = repo_parser.parse_distribution(
        "trixie", "amd64", recipes_dir=str(tmp_path), dry_run=True,
    )
    assert new >= 1
    assert not (tmp_path / "system" / "foo.yaml").exists()


_FOO_DEP11 = (
    "---\n"
    "Type: desktop-application\n"
    "ID: org.x.Foo\n"
    "Name:\n"
    "  C: Foo\n"
    "Summary:\n"
    "  C: A foo app\n"
    "Package: foo\n"
    "Categories:\n"
    "  - Utility\n"
)


def test_parse_distribution_skips_existing_without_update(tmp_path, monkeypatch):
    d = tmp_path / "system"
    d.mkdir()
    (d / "foo.yaml").write_text("id: foo\nname: Foo\n")
    monkeypatch.setattr(
        repo_parser, "fetch_dep11",
        lambda m, c, comp, a: _FOO_DEP11 if comp == "main" else None,
    )
    new, updated, skipped = repo_parser.parse_distribution(
        "trixie", "amd64", recipes_dir=str(tmp_path), update_existing=False,
    )
    assert new == 0
    assert skipped >= 1


def test_parse_distribution_updates_existing(tmp_path, monkeypatch):
    d = tmp_path / "system"
    d.mkdir()
    recipe = {
        "id": "foo", "name": "Foo", "description": "A foo app",
        "categoryId": "system", "icon": "Wrench", "method": "apt",
        "level": "auto", "compression": "zstd", "packages": ["foo"],
        "distributions": {"include": [{"name": "trixie", "architectures": ["amd64"]}]},
    }
    (d / "foo.yaml").write_text(repo_parser.recipe_to_yaml(recipe))
    monkeypatch.setattr(
        repo_parser, "fetch_dep11",
        lambda m, c, comp, a: _FOO_DEP11 if comp == "main" else None,
    )
    new, updated, skipped = repo_parser.parse_distribution(
        "trixie", "i386", recipes_dir=str(tmp_path), update_existing=True,
    )
    assert updated >= 1
    reloaded = yaml.safe_load((d / "foo.yaml").read_text())
    archs = reloaded["distributions"]["include"][0]["architectures"]
    assert "i386" in archs


# ---------------------------------------------------------------------------
# main() -- CLI entry point
# ---------------------------------------------------------------------------

def test_main_prints_summary(monkeypatch, capsys):
    monkeypatch.setattr(repo_parser, "parse_distribution", lambda **kw: (2, 1, 3))
    monkeypatch.setattr(
        repo_parser.sys, "argv",
        ["repo_parser.py", "--dist", "trixie", "--arch", "amd64"],
    )
    repo_parser.main()
    out = capsys.readouterr().out
    assert "Summary" in out
    assert "New recipes:     2" in out
    assert "Updated recipes: 1" in out


def test_main_dry_run_notice(monkeypatch, capsys):
    monkeypatch.setattr(repo_parser, "parse_distribution", lambda **kw: (1, 0, 0))
    monkeypatch.setattr(
        repo_parser.sys, "argv",
        ["repo_parser.py", "--dist", "trixie", "--dry-run"],
    )
    repo_parser.main()
    assert "dry-run mode" in capsys.readouterr().out
