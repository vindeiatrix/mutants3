from __future__ import annotations

import importlib
import json

import mutants.state as state_mod
import mutants.registries.items_catalog as items_catalog
import mutants.registries.items_instances as items_instances
import mutants.ui.item_display as item_display
import mutants.ui.styles as styles


def _reload_state_modules() -> None:
    importlib.reload(state_mod)
    importlib.reload(items_catalog)
    importlib.reload(items_instances)


def test_item_display_uses_state_root(tmp_path, monkeypatch):
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))

    items_dir = tmp_path / "items"
    items_dir.mkdir(parents=True)
    catalog = {"items": {"widget": {"display_name": "Widget"}}}
    overrides = {"widget": "Renamed Widget"}
    (items_dir / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    (items_dir / "naming_overrides.json").write_text(json.dumps(overrides), encoding="utf-8")

    try:
        _reload_state_modules()
        importlib.reload(item_display)
        assert item_display.canonical_name("widget") == "Renamed Widget"
    finally:
        monkeypatch.delenv("GAME_STATE_ROOT", raising=False)
        _reload_state_modules()
        importlib.reload(item_display)


def test_styles_colors_path_resolves_within_state_root(tmp_path, monkeypatch):
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))

    colors_dir = tmp_path / "ui"
    colors_dir.mkdir(parents=True)
    colors = {"defaults": "white", "map": {"compass.line": "magenta"}}
    (colors_dir / "colors.json").write_text(json.dumps(colors), encoding="utf-8")

    try:
        _reload_state_modules()
        monkeypatch.setenv("MUTANTS_UI_COLORS_PATH", "state/ui/colors.json")
        importlib.reload(styles)
        styles.reload_colors_map()
        assert styles.resolve_color_for_group("compass.line") == "magenta"
    finally:
        monkeypatch.delenv("MUTANTS_UI_COLORS_PATH", raising=False)
        monkeypatch.delenv("GAME_STATE_ROOT", raising=False)
        _reload_state_modules()
        importlib.reload(styles)
