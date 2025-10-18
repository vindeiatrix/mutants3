"""Utility for generating deterministic combat logs for regression tests."""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

# Ensure the project ``src`` directory is importable when running standalone or via tests.
repo_root = Path(__file__).resolve().parents[1]
src_path = repo_root / "src"
if str(src_path) not in sys.path:  # pragma: no cover - path setup
    sys.path.append(str(src_path))

from mutants.debug import turnlog
from mutants.combat.text import render_innate_attack_line
from mutants.services.monster_entities import DEFAULT_INNATE_ATTACK_LINE
from mutants.state import state_path
from mutants.ui import textutils

try:  # Optional integration with the runtime RNG pool
    from mutants.services import random_pool
except Exception:  # pragma: no cover - pool unavailable during some test runs
    random_pool = None  # type: ignore[assignment]


@dataclass
class GeneratedEntry:
    """Container describing an emitted combat log event."""

    kind: str
    meta: Dict[str, Any]
    text: str
    feedback: Optional[str]
    narrative: Optional[str]
    summary: List[str]


class MemorySink:
    """Minimal logsink implementation used to capture ``turnlog`` output."""

    def __init__(self) -> None:
        self.events: List[Dict[str, str]] = []

    def handle(self, event: Mapping[str, Any]) -> None:
        text = event.get("text")
        self.events.append(
            {
                "kind": str(event.get("kind", "")),
                "text": "" if text is None else str(text),
            }
        )


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_players(state_dir: Path) -> List[Dict[str, str]]:
    payload = json.loads((state_dir / "playerlivestate.json").read_text(encoding="utf-8"))
    players: List[Dict[str, str]] = []
    raw_players = payload.get("players") if isinstance(payload, Mapping) else None
    if isinstance(raw_players, Sequence):
        for entry in raw_players:
            if not isinstance(entry, Mapping):
                continue
            ident = str(entry.get("id") or entry.get("name") or "").strip()
            name = str(entry.get("name") or ident or "Player").strip()
            if not ident:
                ident = name or "player"
            if not name:
                name = ident
            players.append({"id": ident, "name": name})
    if not players and isinstance(payload, Mapping):
        name = str(payload.get("name") or payload.get("class") or "Player").strip()
        ident = str(payload.get("id") or name or "player").strip()
        players.append({"id": ident or "player", "name": name or ident or "Player"})
    return players


def _load_monsters(state_dir: Path) -> List[Dict[str, Any]]:
    catalog_path = state_dir / "monsters" / "catalog.json"
    raw_catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    monsters: List[Dict[str, Any]] = []
    if isinstance(raw_catalog, Sequence):
        for entry in raw_catalog:
            if not isinstance(entry, Mapping):
                continue
            monster_id = str(entry.get("monster_id") or entry.get("id") or "").strip()
            if not monster_id:
                continue
            name = str(entry.get("name") or monster_id).strip() or monster_id
            innate_payload = entry.get("innate_attack") if isinstance(entry.get("innate_attack"), Mapping) else {}
            innate_name = str(innate_payload.get("name") or "innate attack").strip() or "innate attack"
            innate_line = str(innate_payload.get("line") or DEFAULT_INNATE_ATTACK_LINE).strip() or DEFAULT_INNATE_ATTACK_LINE
            starter_items: List[str] = []
            raw_items = entry.get("starter_items")
            if isinstance(raw_items, Sequence):
                for item in raw_items:
                    token = str(item).strip()
                    if token:
                        starter_items.append(token)
            if not starter_items:
                starter_items = [innate_name]
            level = _coerce_int(entry.get("level"), default=1)
            hp_max = _coerce_int(entry.get("hp_max"), default=10)
            ions_min = _coerce_int(entry.get("ions_min"), default=0)
            ions_max = _coerce_int(entry.get("ions_max"), default=max(ions_min, 0))
            if ions_max < ions_min:
                ions_max = ions_min
            monsters.append(
                {
                    "id": monster_id,
                    "name": name,
                    "level": level,
                    "hp_max": hp_max if hp_max > 0 else 10,
                    "starter_items": starter_items,
                    "innate": {"name": innate_name, "line": innate_line},
                    "ions_range": (ions_min, ions_max),
                }
            )
    return monsters


def _resolve_rng(seed: Optional[int]) -> random.Random:
    if seed is not None:
        return random.Random(seed)
    if random_pool is not None:  # pragma: no cover - exercised via CLI integration
        try:
            return random_pool.get_rng("combat-log")
        except Exception:
            pass
    return random.Random(0)


def _emit_turnlog(kind: str, meta: Mapping[str, Any], sink: MemorySink) -> str:
    ctx: MutableMapping[str, Any] = {"logsink": sink}
    turnlog.emit(ctx, kind, **dict(meta))
    if not sink.events:
        return ""
    return sink.events[-1]["text"].strip()


EventBuilder = Callable[[random.Random, Mapping[str, Any], Mapping[str, str]], Tuple[str, Dict[str, Any], Optional[str], Optional[str]]]


def _event_monster_hit_melee(
    rng: random.Random, monster: Mapping[str, Any], player: Mapping[str, str]
) -> Tuple[str, Dict[str, Any], Optional[str], Optional[str]]:
    level = _coerce_int(monster.get("level"), 1)
    base = max(1, level)
    damage = base + rng.randrange(1, base + 5)
    weapon_name = str(monster.get("innate", {}).get("name") or "innate attack")
    meta = {
        "monster": monster.get("name"),
        "target": player.get("name"),
        "weapon": weapon_name,
        "damage": damage,
        "source": "melee",
    }
    narrative = render_innate_attack_line(
        str(monster.get("name")), monster.get("innate"), str(player.get("name"))
    )
    return "COMBAT/HIT", meta, textutils.TEMPLATE_MONSTER_MELEE_HIT, narrative


def _event_monster_hit_bolt(
    rng: random.Random, monster: Mapping[str, Any], player: Mapping[str, str]
) -> Tuple[str, Dict[str, Any], Optional[str], Optional[str]]:
    level = _coerce_int(monster.get("level"), 1)
    damage = rng.randrange(2, 2 + level * 2)
    weapon_name = rng.choice(monster.get("starter_items") or ["Bolt"])
    meta = {
        "monster": monster.get("name"),
        "target": player.get("name"),
        "weapon": weapon_name,
        "damage": damage,
        "source": "bolt",
    }
    narrative = render_innate_attack_line(
        str(monster.get("name")),
        {"name": weapon_name, "line": monster.get("innate", {}).get("line")},
        str(player.get("name")),
    )
    return "COMBAT/HIT", meta, textutils.TEMPLATE_MONSTER_RANGED_HIT, narrative


def _event_monster_convert(
    rng: random.Random, monster: Mapping[str, Any], player: Mapping[str, str]
) -> Tuple[str, Dict[str, Any], Optional[str], Optional[str]]:
    ions_min, ions_max = monster.get("ions_range", (0, 0))
    ions_value = rng.randint(int(ions_min), int(ions_max)) if ions_max >= ions_min else int(ions_min)
    item_name = rng.choice(monster.get("starter_items") or [monster.get("innate", {}).get("name", "relic")])
    meta = {
        "monster": monster.get("name"),
        "item_id": item_name,
        "ions": ions_value,
    }
    narrative = f"{monster.get('name')} channels scrap into raw ions."
    return "AI/ACT/CONVERT", meta, textutils.TEMPLATE_MONSTER_CONVERT, narrative


def _event_monster_heal(
    rng: random.Random, monster: Mapping[str, Any], player: Mapping[str, str]
) -> Tuple[str, Dict[str, Any], Optional[str], Optional[str]]:
    level = _coerce_int(monster.get("level"), 1)
    heal_amount = rng.randrange(3, 8 + level)
    ions_spent = max(1, heal_amount // 2)
    meta = {
        "actor": monster.get("name"),
        "hp_restored": heal_amount,
        "ions_spent": ions_spent,
    }
    visual = textutils.render_feedback_template(
        textutils.TEMPLATE_MONSTER_HEAL_VISUAL, monster=str(monster.get("name"))
    )
    return "COMBAT/HEAL", meta, textutils.TEMPLATE_MONSTER_HEAL, visual


def _event_monster_kill(
    rng: random.Random, monster: Mapping[str, Any], player: Mapping[str, str]
) -> Tuple[str, Dict[str, Any], Optional[str], Optional[str]]:
    drops = rng.randrange(0, 4)
    meta = {
        "victim": player.get("name"),
        "drops": drops,
        "source": "monster",
        "monster": monster.get("name"),
    }
    narrative = f"{player.get('name')} falls before {monster.get('name')}!"
    return "COMBAT/KILL", meta, None, narrative


def _event_player_strike(
    rng: random.Random, monster: Mapping[str, Any], player: Mapping[str, str]
) -> Tuple[str, Dict[str, Any], Optional[str], Optional[str]]:
    level = _coerce_int(monster.get("level"), 1)
    damage = rng.randrange(4, 10 + level)
    remaining = max(0, _coerce_int(monster.get("hp_max"), 10) - damage - rng.randrange(0, 4))
    killed = remaining == 0
    meta = {
        "actor": player.get("name"),
        "target_name": monster.get("name"),
        "damage": damage,
        "remaining_hp": remaining,
        "killed": killed,
    }
    narrative = f"{player.get('name')} strikes at {monster.get('name')}!"
    return "COMBAT/STRIKE", meta, None, narrative


def _event_item_crack(
    rng: random.Random, monster: Mapping[str, Any], player: Mapping[str, str]
) -> Tuple[str, Dict[str, Any], Optional[str], Optional[str]]:
    weapon = rng.choice(monster.get("starter_items") or [monster.get("innate", {}).get("name", "weapon")])
    meta = {
        "owner": monster.get("name"),
        "item_name": weapon,
    }
    narrative = f"{weapon} splinters in {monster.get('name')}'s grip."
    return "ITEM/CRACK", meta, None, narrative


def _event_item_convert(
    rng: random.Random, monster: Mapping[str, Any], player: Mapping[str, str]
) -> Tuple[str, Dict[str, Any], Optional[str], Optional[str]]:
    ions_min, ions_max = monster.get("ions_range", (0, 0))
    if ions_max < ions_min:
        ions_max = ions_min
    ions_value = rng.randint(int(ions_min), int(ions_max)) if ions_max >= ions_min else int(ions_min)
    item_name = rng.choice(monster.get("starter_items") or [monster.get("innate", {}).get("name", "relic")])
    meta = {
        "owner": monster.get("name"),
        "ions": ions_value,
        "item_name": item_name,
    }
    narrative = f"{monster.get('name')} sacrifices {item_name} for {ions_value} ions."
    return "ITEM/CONVERT", meta, None, narrative


_EVENT_BUILDERS: Dict[str, EventBuilder] = {
    "monster_hit_melee": _event_monster_hit_melee,
    "monster_hit_bolt": _event_monster_hit_bolt,
    "monster_convert": _event_monster_convert,
    "monster_heal": _event_monster_heal,
    "monster_kill": _event_monster_kill,
    "player_strike": _event_player_strike,
    "item_crack": _event_item_crack,
    "item_convert": _event_item_convert,
}

_EVENT_ORDER: Tuple[str, ...] = tuple(_EVENT_BUILDERS.keys())


def _generate_entry(
    rng: random.Random,
    sink: MemorySink,
    event_key: str,
    monster: Mapping[str, Any],
    player: Mapping[str, str],
) -> GeneratedEntry:
    builder = _EVENT_BUILDERS[event_key]
    kind, meta, template_key, narrative = builder(rng, monster, player)
    emitted_text = _emit_turnlog(kind, meta, sink)
    feedback: Optional[str] = None
    if template_key:
        payload = {"kind": kind, "template": template_key}
        payload.update(meta)
        payload.setdefault("monster", monster.get("name"))
        payload.setdefault("weapon", monster.get("innate", {}).get("name"))
        if template_key == textutils.TEMPLATE_MONSTER_HEAL:
            payload.setdefault("hp", meta.get("hp_restored"))
            payload.setdefault("ions", meta.get("ions_spent"))
        feedback = textutils.resolve_feedback_text(payload)
    summary = turnlog._summarize_events([(kind, meta)])
    return GeneratedEntry(kind=kind, meta=dict(meta), text=emitted_text, feedback=feedback, narrative=narrative, summary=summary)


def generate_combat_log(
    *, seed: Optional[int] = None, turns: int = 12, state_dir: Optional[str | Path] = None
) -> str:
    """Return the deterministic combat log text for ``turns`` simulated events."""

    if turns <= 0:
        raise ValueError("turns must be positive")

    state_root = Path(state_dir) if state_dir is not None else state_path()
    players = _load_players(state_root)
    monsters = _load_monsters(state_root)
    if not players:
        raise RuntimeError("no players available in state snapshot")
    if not monsters:
        raise RuntimeError("no monsters available in state snapshot")

    rng = _resolve_rng(seed)
    sink = MemorySink()

    lines: List[str] = []
    lines.append("=== Mutants Combat Log ===")
    lines.append(f"seed={seed if seed is not None else 'pool'}")
    lines.append(f"turns={turns}")
    lines.append("")

    entries: List[GeneratedEntry] = []
    event_keys = list(_EVENT_ORDER)

    for turn in range(1, turns + 1):
        monster = rng.choice(monsters)
        player = rng.choice(players)
        event_key = rng.choice(event_keys)
        entry = _generate_entry(rng, sink, event_key, monster, player)
        entries.append(entry)

        lines.append(f"Turn {turn}: {player['name']} vs {monster['name']} [{event_key}]")
        lines.append(f"  kind: {entry.kind}")
        lines.append(f"  meta: {json.dumps(entry.meta, sort_keys=True)}")
        if entry.text:
            lines.append(f"  turnlog: {entry.text}")
        else:
            lines.append("  turnlog: <empty>")
        if entry.feedback:
            lines.append(f"  feedback: {entry.feedback}")
        if entry.narrative:
            lines.append(f"  narrative: {entry.narrative}")
        if entry.summary:
            lines.append(f"  summary: {' | '.join(entry.summary)}")
        else:
            lines.append("  summary: (none)")
        lines.append("")

    aggregate = turnlog._summarize_events([(entry.kind, entry.meta) for entry in entries])
    lines.append("=== Aggregate Summary ===")
    if aggregate:
        for item in aggregate:
            lines.append(f"- {item}")
    else:
        lines.append("- (none)")
    lines.append("")

    return "\n".join(lines)


def _parse_seed(raw: Optional[str]) -> Optional[int]:
    if raw is None:
        return None
    try:
        return int(raw, 0)
    except ValueError as exc:  # pragma: no cover - argument parsing only
        raise argparse.ArgumentTypeError(f"invalid seed value: {raw}") from exc


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover - CLI wrapper
    parser = argparse.ArgumentParser(description="Generate deterministic combat logs.")
    parser.add_argument("--seed", type=_parse_seed, default=None, help="Seed for the RNG (int or 0x-prefixed hex).")
    parser.add_argument("--turns", type=int, default=12, help="Number of simulated turns to include.")
    parser.add_argument(
        "--state-dir",
        type=str,
        default=None,
        help="Override state directory (defaults to bundled state tree).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional path to write the generated log (prints to stdout otherwise).",
    )
    args = parser.parse_args(argv)

    try:
        log_text = generate_combat_log(seed=args.seed, turns=args.turns, state_dir=args.state_dir)
    except Exception as exc:
        parser.error(str(exc))
        return 2

    if args.output:
        Path(args.output).write_text(log_text, encoding="utf-8")
    else:
        sys.stdout.write(log_text)
    return 0


if __name__ == "__main__":  # pragma: no cover - script execution entry point
    raise SystemExit(main())
