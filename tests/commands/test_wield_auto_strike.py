from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from mutants import state  # noqa: E402
from mutants.commands import strike, wield  # noqa: E402
from mutants.services import player_state  # noqa: E402


class FakeBus:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def push(self, kind: str, message: str) -> None:
        self.messages.append((kind, message))


class FakeMonsters:
    def __init__(self, target_id: str, *, hp: int) -> None:
        self._targets: dict[str, dict[str, object]] = {
            target_id: {
                "id": target_id,
                "name": "Goblin",
                "hp": {"current": hp, "max": hp},
            }
        }
        self.dirty_calls = 0

    def get(self, target_id: str) -> dict[str, object] | None:
        entry = self._targets.get(target_id)
        if entry is None:
            return None
        return entry

    def mark_dirty(self) -> None:
        self.dirty_calls += 1


@pytest.fixture()
def configure_state_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GAME_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(state, "STATE_ROOT", tmp_path)
    return tmp_path


def _write_ready_state(klass: str, weapon_iid: str, target_id: str) -> dict:
    player_id = f"player_{klass.lower()}"
    base_state = {
        "players": [
            {
                "id": player_id,
                "class": klass,
                "name": klass,
                "pos": [2000, 0, 0],
                "inventory": [weapon_iid],
                "bags": {klass: [weapon_iid]},
                "wielded_by_class": {klass: None},
                "ready_target_by_class": {klass: target_id},
                "target_monster_id_by_class": {klass: target_id},
                "stats": {"str": 30},
            }
        ],
        "active_id": player_id,
        "active": {
            "id": player_id,
            "class": klass,
            "pos": [2000, 0, 0],
            "inventory": [weapon_iid],
            "bags": {klass: [weapon_iid]},
            "wielded_by_class": {klass: None},
            "ready_target_by_class": {klass: target_id},
            "target_monster_id_by_class": {klass: target_id},
            "stats": {"str": 30},
        },
        "inventory": [weapon_iid],
        "bags": {klass: [weapon_iid]},
        "wielded_by_class": {klass: None},
        "ready_target_by_class": {klass: target_id},
        "target_monster_id_by_class": {klass: target_id},
        "stats_by_class": {klass: {"str": 30}},
    }
    player_state.save_state(base_state)
    return base_state


def test_wield_triggers_auto_strike(configure_state_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    weapon_iid = "weapon-123"
    target_id = "goblin-1"
    _write_ready_state("Warrior", weapon_iid, target_id)

    catalog_payload = {"sword": {"name": "Bronze Sword"}}

    def fake_get_instance(iid: str) -> dict[str, str] | None:
        if iid == weapon_iid:
            return {"iid": iid, "item_id": "sword"}
        return None

    class DummyAttack:
        def __init__(self, damage: int, source: str) -> None:
            self.damage = damage
            self.source = source

    def fake_resolve(item, attacker, defender):
        return DummyAttack(8, "melee")

    monkeypatch.setattr(wield.catreg, "load_catalog", lambda: dict(catalog_payload))
    monkeypatch.setattr(strike.items_catalog, "load_catalog", lambda: dict(catalog_payload))
    monkeypatch.setattr(wield.itemsreg, "get_instance", fake_get_instance)
    monkeypatch.setattr(strike.itemsreg, "get_instance", fake_get_instance)
    monkeypatch.setattr(wield, "get_effective_weight", lambda inst, tpl: 0)
    monkeypatch.setattr(strike.items_wear, "wear_from_event", lambda event: 0)
    monkeypatch.setattr(strike.items_wear, "apply_wear", lambda iid, wear: {"cracked": False})
    monkeypatch.setattr(strike.damage_engine, "resolve_attack", fake_resolve)
    monkeypatch.setattr(strike.turnlog, "emit", lambda *args, **kwargs: None)

    bus = FakeBus()
    monsters = FakeMonsters(target_id, hp=20)
    ctx = {"feedback_bus": bus, "monsters": monsters}

    result = wield.wield_cmd("sword", ctx)

    assert result["ok"] is True
    assert result["iid"] == weapon_iid
    assert "strike" in result
    assert result["strike"]["ok"] is True
    assert result["strike"]["target_id"] == target_id

    hit_messages = [message for message in bus.messages if message[0] == "COMBAT/HIT"]
    assert len(hit_messages) == 1
    assert "You strike" in hit_messages[0][1]
    assert "8" in hit_messages[0][1]
