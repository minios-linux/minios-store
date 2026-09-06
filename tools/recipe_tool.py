#!/usr/bin/env python3
"""Create, update, or delete a recipe and refresh its generated artifacts."""

import json
import os
import re
import shutil
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parent
RECIPES_DIR = PROJECT_ROOT / "recipes"
OUTPUT_PATH = PROJECT_ROOT / "web/public/data/recipes.json"
SCREENSHOTS_DIR = PROJECT_ROOT / "web/public/screenshots"
ICONS_DIR = PROJECT_ROOT / "web/public/icons"
TRANSLATIONS_DIR = PROJECT_ROOT / "web/public/data/recipe-translations"

sys.path.insert(0, str(TOOLS_DIR))
import build_recipes  # noqa: E402

try:
    import yaml
except ImportError:
    yaml = None

SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
EDITABLE_FIELDS = (
    "id", "name", "description", "longDescription", "categoryId", "icon",
    "method", "level", "compression", "packages", "script", "debUrl",
    "distributions", "developer", "homepage", "tags", "screenshots",
    "license", "enabled", "order",
)
MEDIA_SOURCE_FIELDS = ("screenshotSources", "iconSources")


class RecipeToolError(Exception):
    pass


def _require_yaml():
    if yaml is None:
        raise RecipeToolError(
            "PyYAML is required to edit recipe sources (install python3-yaml)"
        )


def _load_json_stdin():
    try:
        return json.load(sys.stdin)
    except (ValueError, TypeError) as exc:
        raise RecipeToolError("Invalid JSON request: {}".format(exc))


def _find_source(recipe_id):
    matches = list(RECIPES_DIR.rglob(recipe_id + ".yaml"))
    matches.extend(RECIPES_DIR.rglob(recipe_id + ".yml"))
    if len(matches) > 1:
        raise RecipeToolError(
            "Duplicate recipe sources for '{}': {}".format(
                recipe_id, ", ".join(str(p) for p in matches)
            )
        )
    return matches[0] if matches else None


def _merge_recipe(existing, incoming):
    merged = dict(existing or {})
    for field in EDITABLE_FIELDS:
        if field in incoming and incoming[field] is not None:
            merged[field] = incoming[field]
        else:
            merged.pop(field, None)

    # Media source metadata is not exposed by every admin form. Preserve it
    # when omitted, replace it when provided, and remove it only via null.
    for field in MEDIA_SOURCE_FIELDS:
        if field not in incoming:
            continue
        if incoming[field] is None:
            merged.pop(field, None)
        else:
            merged[field] = incoming[field]

    method = merged.get("method")
    if method != "apt":
        merged.pop("packages", None)
    if method != "script":
        merged.pop("script", None)
    if method != "deb":
        merged.pop("debUrl", None)
    # Cached screenshots are generated artifacts, not source data. Keep an
    # explicit source-level screenshots list only when the old YAML owned one.
    if merged.get("screenshotSources") and "screenshots" not in existing:
        merged.pop("screenshots", None)
    merged.pop("appIcon", None)
    return merged
def _dump_yaml(data):
    _require_yaml()

    class Dumper(yaml.SafeDumper):
        pass

    def represent_string(dumper, value):
        style = "|" if "\n" in value else None
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)

    Dumper.add_representer(str, represent_string)
    kwargs = {
        "Dumper": Dumper,
        "allow_unicode": True,
        "default_flow_style": False,
        "width": 4096,
    }
    try:
        return yaml.dump(data, sort_keys=False, **kwargs)
    except TypeError:
        return yaml.dump(data, **kwargs)


def _load_generated_recipes():
    if OUTPUT_PATH.is_file():
        try:
            with OUTPUT_PATH.open(encoding="utf-8") as stream:
                recipes = json.load(stream)
            if isinstance(recipes, list):
                return recipes
        except (OSError, ValueError):
            pass

    recipes, errors = build_recipes.build_recipes(str(RECIPES_DIR))
    if errors:
        raise RecipeToolError("; ".join(errors))
    return [
        build_recipes.prepare_recipe_for_output(
            recipe, str(SCREENSHOTS_DIR), str(ICONS_DIR)
        )
        for recipe in recipes
    ]


def _write_artifacts(recipes, changed_ids):
    return build_recipes.write_recipe_artifacts(
        recipes, str(OUTPUT_PATH), pretty=True, changed_ids=changed_ids
    )


def get_recipe(recipe_id):
    if not SAFE_NAME.match(recipe_id):
        raise RecipeToolError("Invalid recipe ID")
    source = _find_source(recipe_id)
    if source is None:
        raise RecipeToolError("Recipe source not found: {}".format(recipe_id))
    return build_recipes.load_recipe(str(source))


def _clear_media_cache(recipe, screenshots=False, icon=False):
    if not recipe or not recipe.get("id"):
        return
    media_name = build_recipes.recipe_media_name(recipe)
    if screenshots:
        shutil.rmtree(SCREENSHOTS_DIR / media_name, ignore_errors=True)
    if icon:
        icon_path = ICONS_DIR / (media_name + ".png")
        marker = ICONS_DIR / (".no_icon_" + media_name)
        for path in (icon_path, marker):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def save_recipe(incoming):
    recipe_id = str(incoming.get("id", "")).strip()
    category_id = str(incoming.get("categoryId", "")).strip()
    if not SAFE_NAME.match(recipe_id):
        raise RecipeToolError("Invalid recipe ID")
    if not SAFE_NAME.match(category_id):
        raise RecipeToolError("Invalid category ID")

    source = _find_source(recipe_id)
    existing = build_recipes.load_recipe(str(source)) if source else {}
    merged = _merge_recipe(existing, incoming)
    errors = build_recipes.validate_recipe(merged, recipe_id)
    if errors:
        raise RecipeToolError("; ".join(errors))

    target_dir = RECIPES_DIR / category_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / (recipe_id + ".yaml")
    if target.exists() and target != source:
        raise RecipeToolError("Target recipe source already exists: {}".format(target))

    old_recipes = _load_generated_recipes()
    old_source_bytes = source.read_bytes() if source else None
    old_target_bytes = target.read_bytes() if target.exists() else None
    target.write_text(_dump_yaml(merged), encoding="utf-8")
    if source and source != target:
        source.unlink()

    old_media_name = (
        build_recipes.recipe_media_name(existing) if existing.get("id") else None
    )
    new_media_name = build_recipes.recipe_media_name(merged)
    screenshots_changed = (
        existing.get("screenshotSources") != merged.get("screenshotSources")
        or (old_media_name is not None and old_media_name != new_media_name)
    )
    icon_changed = (
        existing.get("iconSources") != merged.get("iconSources")
        or (old_media_name is not None and old_media_name != new_media_name)
    )
    if screenshots_changed:
        _clear_media_cache(existing, screenshots=True)
        _clear_media_cache(merged, screenshots=True)
    if icon_changed:
        _clear_media_cache(existing, icon=True)
        _clear_media_cache(merged, icon=True)

    # Download/copy media immediately so the generated recipe always points to
    # the same local cache used by a full build_recipes.py run.
    build_recipes.fetch_recipe_media(
        merged, str(SCREENSHOTS_DIR), str(ICONS_DIR),
        media_root=str(RECIPES_DIR),
    )
    generated = build_recipes.prepare_recipe_for_output(
        merged, str(SCREENSHOTS_DIR), str(ICONS_DIR)
    )
    new_recipes = [r for r in old_recipes if r.get("id") != recipe_id]
    new_recipes.append(generated)

    try:
        _write_artifacts(new_recipes, {recipe_id})
    except Exception:
        if target.exists():
            if old_target_bytes is None:
                target.unlink()
            else:
                target.write_bytes(old_target_bytes)
        if source and source != target and old_source_bytes is not None:
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(old_source_bytes)
        try:
            _write_artifacts(old_recipes, {recipe_id})
        except Exception:
            pass
        raise

    return target


def delete_recipe(recipe_id):
    if not SAFE_NAME.match(recipe_id):
        raise RecipeToolError("Invalid recipe ID")

    source = _find_source(recipe_id)
    if source is None:
        raise RecipeToolError("Recipe source not found: {}".format(recipe_id))

    existing = build_recipes.load_recipe(str(source))
    old_recipes = _load_generated_recipes()
    new_recipes = [r for r in old_recipes if r.get("id") != recipe_id]
    backup = source.with_suffix(source.suffix + ".deleted")
    if backup.exists():
        backup.unlink()
    source.rename(backup)
    try:
        _write_artifacts(new_recipes, {recipe_id})
    except Exception:
        backup.rename(source)
        try:
            _write_artifacts(old_recipes, {recipe_id})
        except Exception:
            pass
        raise
    backup.unlink()
    _clear_media_cache(existing, screenshots=True, icon=True)
    shutil.rmtree(RECIPES_DIR / "media" / recipe_id, ignore_errors=True)

    if TRANSLATIONS_DIR.is_dir():
        for lang_dir in TRANSLATIONS_DIR.iterdir():
            if not lang_dir.is_dir():
                continue
            translation = lang_dir / (recipe_id + ".json")
            if translation.exists():
                translation.unlink()


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("upsert", "delete", "get"):
        print("Usage: recipe_tool.py {upsert|delete|get}", file=sys.stderr)
        return 2

    try:
        payload = _load_json_stdin()
        if sys.argv[1] == "upsert":
            source = save_recipe(payload)
            result = {
                "success": True,
                "source": os.path.relpath(str(source), str(PROJECT_ROOT)),
            }
        elif sys.argv[1] == "get":
            recipe_id = str(payload.get("id", "")).strip()
            result = {"success": True, "recipe": get_recipe(recipe_id)}
        else:
            recipe_id = str(payload.get("id", "")).strip()
            delete_recipe(recipe_id)
            result = {"success": True}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except RecipeToolError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
