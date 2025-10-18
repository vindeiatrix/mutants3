from __future__ import annotations

import json
from pathlib import Path

import logging

from mutants.services import combat_config


def test_defaults_without_override(tmp_path):
    cfg = combat_config.load_combat_config(state_dir=str(tmp_path))

    assert cfg.override_path == Path(tmp_path) / "config" / "combat.json"
    assert cfg.wake_on_look == 15
    assert cfg.wake_on_entry == 10
    assert cfg.attack_pct == 35
    assert cfg.rng_seeds == combat_config.CombatRNGSeeds()
    assert cfg.heal_cost_multiplier["wizard"] == 1_000
    assert cfg.heal_cost_multiplier["default"] == 200


def test_override_applied_and_logged(tmp_path, caplog):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    cfg_path = cfg_dir / "combat.json"
    cfg_path.write_text(
        json.dumps(
            {
                "wake_on_look": 42,
                "attack_pct": 55,
                "rng_seeds": {"wake": 1001},
            }
        ),
        encoding="utf-8",
    )

    caplog.set_level(logging.INFO, logger=combat_config.LOG.name)
    cfg = combat_config.load_combat_config(state_dir=str(tmp_path))

    assert cfg.wake_on_look == 42
    assert cfg.attack_pct == 55
    assert cfg.rng_seeds == combat_config.CombatRNGSeeds(wake=1001)

    assert any(
        "combat config overrides applied" in record.message and str(cfg_path) in record.message
        for record in caplog.records
    )


def test_override_heal_cost_multiplier(tmp_path) -> None:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    cfg_path = cfg_dir / "combat.json"
    cfg_path.write_text(
        json.dumps(
            {
                "heal_cost_multiplier.wizard": 777,
                "heal_cost_multiplier": {"priest": 444},
            }
        ),
        encoding="utf-8",
    )

    cfg = combat_config.load_combat_config(state_dir=str(tmp_path))

    assert cfg.heal_cost_multiplier["wizard"] == 777
    assert cfg.heal_cost_multiplier["priest"] == 444
    assert cfg.heal_cost_multiplier["default"] == 200
