"""Tests for the GTK installer's pure URI / CLI argument parsing helpers.

The GTK window itself needs a display and is not exercised here, but
parse_uri / resolve_params / build_cli_parser are plain logic and are
fully testable.
"""

import pytest

# gui.py imports GTK (gi) at module import time and calls sys.exit(1) when it
# is unavailable. Skip the whole module gracefully on headless machines.
try:
    from minios_store import gui
except (SystemExit, ImportError, ValueError):  # pragma: no cover
    pytest.skip("GTK (python3-gi / gir1.2-gtk-3.0) not available",
                allow_module_level=True)


# ---------------------------------------------------------------------------
# parse_uri
# ---------------------------------------------------------------------------

def test_parse_uri_single_recipe():
    result = gui.parse_uri(
        "minios-store://install?recipes=vlc:auto:zstd&mode=module&packaging=single"
    )
    assert result["mode"] == "module"
    assert result["packaging"] == "single"
    assert result["module_name"] == ""
    assert result["recipes"] == [{
        "id": "vlc",
        "name": "vlc",
        "method": "apt",
        "level": "auto",
        "compression": "zstd",
        "packages": ["vlc"],
    }]


def test_parse_uri_multiple_recipes_and_module_name():
    result = gui.parse_uri(
        "minios-store://install?recipes=vlc:05:zstd,gimp:auto:xz"
        "&packaging=separate&moduleName=bundle"
    )
    ids = [r["id"] for r in result["recipes"]]
    assert ids == ["vlc", "gimp"]
    assert result["recipes"][0]["level"] == "05"
    assert result["recipes"][1]["compression"] == "xz"
    assert result["packaging"] == "separate"
    assert result["module_name"] == "bundle"


def test_parse_uri_defaults_mode_and_packaging():
    result = gui.parse_uri("minios-store://install?recipes=vlc:auto:zstd")
    assert result["mode"] == "module"
    assert result["packaging"] == "single"


def test_parse_uri_invalid_scheme():
    with pytest.raises(ValueError):
        gui.parse_uri("https://install?recipes=vlc:auto:zstd")


def test_parse_uri_invalid_action():
    with pytest.raises(ValueError):
        gui.parse_uri("minios-store://remove?recipes=vlc:auto:zstd")


def test_parse_uri_missing_recipes():
    with pytest.raises(ValueError):
        gui.parse_uri("minios-store://install?mode=module")


def test_parse_uri_bad_recipe_format():
    with pytest.raises(ValueError):
        gui.parse_uri("minios-store://install?recipes=vlc:auto")


# ---------------------------------------------------------------------------
# build_cli_parser / resolve_params
# ---------------------------------------------------------------------------

def test_build_cli_parser_defaults():
    parser = gui.build_cli_parser()
    args = parser.parse_args(["--recipes", "vlc:auto:zstd"])
    assert args.mode == "module"
    assert args.packaging == "single"
    assert args.recipes == "vlc:auto:zstd"


def test_resolve_params_from_uri():
    parser = gui.build_cli_parser()
    args = parser.parse_args(["minios-store://install?recipes=vlc:auto:zstd"])
    recipes, mode, packaging, module_name = gui.resolve_params(args)
    assert recipes[0]["id"] == "vlc"
    assert mode == "module"
    assert packaging == "single"


def test_resolve_params_from_cli_flags():
    parser = gui.build_cli_parser()
    args = parser.parse_args([
        "--mode", "system",
        "--packaging", "separate",
        "--recipes", "vlc:auto:zstd,gimp:05:xz",
        "--module-name", "bundle",
    ])
    recipes, mode, packaging, module_name = gui.resolve_params(args)
    assert [r["id"] for r in recipes] == ["vlc", "gimp"]
    assert mode == "system"
    assert packaging == "separate"
    assert module_name == "bundle"


def test_resolve_params_none_when_no_input():
    parser = gui.build_cli_parser()
    args = parser.parse_args([])
    assert gui.resolve_params(args) == (None, None, None, None)


def test_resolve_params_bad_cli_recipe_raises():
    parser = gui.build_cli_parser()
    args = parser.parse_args(["--recipes", "vlc:auto"])
    with pytest.raises(ValueError):
        gui.resolve_params(args)
