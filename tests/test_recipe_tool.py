"""Tests for the single-recipe source/artifact tool."""

import pytest

import recipe_tool


def _recipe(**updates):
    data = {
        "id": "demo",
        "name": "Demo",
        "description": "Demo application",
        "categoryId": "system",
        "icon": "Package",
        "method": "apt",
        "level": "auto",
        "compression": "zstd",
        "packages": ["demo"],
        "enabled": True,
        "order": 1,
    }
    data.update(updates)
    return data


def test_merge_preserves_source_only_fields_and_drops_generated_media():
    existing = _recipe(
        screenshotSources=[{"url": "shot.png"}],
        iconSources=[{"url": "icon.png"}],
    )
    incoming = _recipe(
        method="script",
        script="#!/bin/sh\necho ok\n",
        screenshots=["/screenshots/demo/1.png"],
    )
    incoming["appIcon"] = "/icons/demo.png"

    merged = recipe_tool._merge_recipe(existing, incoming)

    assert merged["screenshotSources"] == [{"url": "shot.png"}]
    assert merged["iconSources"] == [{"url": "icon.png"}]
    assert "screenshots" not in merged
    assert "packages" not in merged
    assert merged["script"].startswith("#!/bin/sh")
    assert "appIcon" not in merged


def test_save_recipe_moves_source_and_updates_artifacts(tmp_path, monkeypatch):
    if recipe_tool.yaml is None:
        pytest.skip("PyYAML not installed")

    recipes_dir = tmp_path / "recipes"
    source = recipes_dir / "system" / "demo.yaml"
    source.parent.mkdir(parents=True)
    source.write_text(
        "id: demo\nname: Demo\ndescription: Demo application\n"
        "categoryId: system\nicon: Package\nmethod: apt\nlevel: auto\n"
        "compression: zstd\npackages: [demo]\n"
        "iconSources:\n  - url: icon.png\nenabled: true\norder: 1\n"
    )
    monkeypatch.setattr(recipe_tool, "RECIPES_DIR", recipes_dir)
    monkeypatch.setattr(recipe_tool, "SCREENSHOTS_DIR", tmp_path / "screenshots")
    monkeypatch.setattr(recipe_tool, "ICONS_DIR", tmp_path / "icons")
    monkeypatch.setattr(recipe_tool, "_load_generated_recipes", lambda: [_recipe()])
    monkeypatch.setattr(
        recipe_tool.build_recipes, "fetch_recipe_media", lambda *args, **kwargs: {}
    )
    calls = []
    monkeypatch.setattr(
        recipe_tool, "_write_artifacts",
        lambda recipes, changed: calls.append((recipes, changed)),
    )

    target = recipe_tool.save_recipe(_recipe(categoryId="games"))

    assert target == recipes_dir / "games" / "demo.yaml"
    assert not source.exists()
    saved = recipe_tool.build_recipes.load_recipe(str(target))
    assert saved["categoryId"] == "games"
    assert saved["iconSources"] == [{"url": "icon.png"}]
    assert calls[0][1] == {"demo"}
    assert calls[0][0][0]["categoryId"] == "games"


def test_save_recipe_rolls_back_source_on_artifact_failure(tmp_path, monkeypatch):
    if recipe_tool.yaml is None:
        pytest.skip("PyYAML not installed")

    recipes_dir = tmp_path / "recipes"
    source = recipes_dir / "system" / "demo.yaml"
    source.parent.mkdir(parents=True)
    original = (
        "id: demo\nname: Demo\ndescription: Demo application\n"
        "categoryId: system\nicon: Package\nmethod: apt\nlevel: auto\n"
        "compression: zstd\npackages: [demo]\nenabled: true\norder: 1\n"
    )
    source.write_text(original)
    monkeypatch.setattr(recipe_tool, "RECIPES_DIR", recipes_dir)
    monkeypatch.setattr(recipe_tool, "SCREENSHOTS_DIR", tmp_path / "screenshots")
    monkeypatch.setattr(recipe_tool, "ICONS_DIR", tmp_path / "icons")
    monkeypatch.setattr(recipe_tool, "_load_generated_recipes", lambda: [_recipe()])
    monkeypatch.setattr(
        recipe_tool.build_recipes, "fetch_recipe_media", lambda *args, **kwargs: {}
    )

    def fail_write(_recipes, _changed):
        raise recipe_tool.RecipeToolError("boom")

    monkeypatch.setattr(recipe_tool, "_write_artifacts", fail_write)
    with pytest.raises(recipe_tool.RecipeToolError, match="boom"):
        recipe_tool.save_recipe(_recipe(name="Changed"))

    assert source.read_text() == original


def test_delete_recipe_removes_source_and_generated_entry(tmp_path, monkeypatch):
    recipes_dir = tmp_path / "recipes"
    source = recipes_dir / "system" / "demo.yaml"
    source.parent.mkdir(parents=True)
    source.write_text("id: demo\n")
    translations = tmp_path / "translations"
    lang_dir = translations / "ru"
    lang_dir.mkdir(parents=True)
    translation = lang_dir / "demo.json"
    translation.write_text("{}")

    monkeypatch.setattr(recipe_tool, "RECIPES_DIR", recipes_dir)
    monkeypatch.setattr(recipe_tool, "TRANSLATIONS_DIR", translations)
    monkeypatch.setattr(recipe_tool, "SCREENSHOTS_DIR", tmp_path / "screenshots")
    monkeypatch.setattr(recipe_tool, "ICONS_DIR", tmp_path / "icons")
    monkeypatch.setattr(
        recipe_tool,
        "_load_generated_recipes",
        lambda: [_recipe(), _recipe(id="other", name="Other")],
    )
    calls = []
    monkeypatch.setattr(
        recipe_tool, "_write_artifacts",
        lambda recipes, changed: calls.append((recipes, changed)),
    )

    recipe_tool.delete_recipe("demo")

    assert not source.exists()
    assert not translation.exists()
    assert calls[0][1] == {"demo"}
    assert [recipe["id"] for recipe in calls[0][0]] == ["other"]


def test_merge_accepts_media_sources_from_new_recipe():
    incoming = _recipe(
        screenshotSources=[{"url": "https://example.org/shot.png"}],
        iconSources=[{"url": "https://example.org/icon.png"}],
    )

    merged = recipe_tool._merge_recipe({}, incoming)

    assert merged["screenshotSources"] == [
        {"url": "https://example.org/shot.png"}
    ]
    assert merged["iconSources"] == [
        {"url": "https://example.org/icon.png"}
    ]


def test_get_recipe_returns_canonical_source(tmp_path, monkeypatch):
    recipes_dir = tmp_path / "recipes"
    source = recipes_dir / "system" / "demo.yaml"
    source.parent.mkdir(parents=True)
    source.write_text(
        "id: demo\nname: Demo\ndescription: Demo application\n"
        "categoryId: system\nicon: Package\nmethod: apt\npackages: [demo]\n"
        "screenshotSources:\n  - file: media/demo/shot.png\n"
    )
    monkeypatch.setattr(recipe_tool, "RECIPES_DIR", recipes_dir)

    recipe = recipe_tool.get_recipe("demo")
    assert recipe["id"] == "demo"
    assert recipe["screenshotSources"] == [{"file": "media/demo/shot.png"}]


def test_delete_recipe_removes_local_media_and_cache(tmp_path, monkeypatch):
    recipes_dir = tmp_path / "recipes"
    source = recipes_dir / "system" / "demo.yaml"
    media_dir = recipes_dir / "media" / "demo"
    source.parent.mkdir(parents=True)
    media_dir.mkdir(parents=True)
    source.write_text("id: demo\npackages: [demo]\n")
    (media_dir / "icon.png").write_bytes(b"icon")

    screenshots_dir = tmp_path / "screenshots"
    icons_dir = tmp_path / "icons"
    (screenshots_dir / "demo").mkdir(parents=True)
    icons_dir.mkdir(parents=True)
    (screenshots_dir / "demo" / "1.png").write_bytes(b"shot")
    (icons_dir / "demo.png").write_bytes(b"icon-cache")

    monkeypatch.setattr(recipe_tool, "RECIPES_DIR", recipes_dir)
    monkeypatch.setattr(recipe_tool, "SCREENSHOTS_DIR", screenshots_dir)
    monkeypatch.setattr(recipe_tool, "ICONS_DIR", icons_dir)
    monkeypatch.setattr(recipe_tool, "TRANSLATIONS_DIR", tmp_path / "translations")
    monkeypatch.setattr(recipe_tool, "_load_generated_recipes", lambda: [_recipe()])
    monkeypatch.setattr(recipe_tool, "_write_artifacts", lambda recipes, changed: None)

    recipe_tool.delete_recipe("demo")

    assert not source.exists()
    assert not media_dir.exists()
    assert not (screenshots_dir / "demo").exists()
    assert not (icons_dir / "demo.png").exists()
