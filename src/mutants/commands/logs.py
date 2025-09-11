from __future__ import annotations

from typing import List

from mutants.app import trace as traceflags
from mutants.engine import edge_resolver as ER
from mutants.registries import dynamics as dyn
import random
import logging


def _active(state):
    aid = state.get("active_id")
    for p in state.get("players", []):
        if p.get("id") == aid:
            return p
    return state["players"][0]


def log_cmd(arg: str, ctx) -> None:
    parts = arg.split()
    sink = ctx["logsink"]
    if len(parts) >= 3 and parts[0] == "trace":
        if parts[1] not in ("move", "ui") or parts[2] not in ("on", "off"):
            ctx["feedback_bus"].push("SYSTEM/OK", "Usage: logs trace <move|ui> <on|off>")
            return
        name = parts[1]
        on = parts[2] == "on"
        traceflags.set_flag(name, on)
        state = "enabled" if on else "disabled"
        ctx["feedback_bus"].push("SYSTEM/OK", f"Trace {name} {state}.")
        return
    if len(parts) >= 2 and parts[0] == "verify" and parts[1] == "edges":
        count = 64
        if len(parts) >= 3:
            try:
                count = max(1, int(parts[2]))
            except Exception:
                pass
        _verify_edges(count, ctx)
        return
    if not parts or parts[0] == "tail":
        n = int(parts[1]) if len(parts) > 1 else 50
        for line in sink.tail(n):
            print(line)
        return
    if parts[0] == "clear":
        sink.clear()
        ctx["feedback_bus"].push("SYSTEM/OK", "Logs cleared.")
        return
    # unknown subcommand -> show tail
    for line in sink.tail(50):
        print(line)


def _verify_edges(sample_count: int, ctx) -> None:
    """Sample random tiles and verify resolver symmetry."""
    logger = logging.getLogger(__name__)
    world_loader = ctx["world_loader"]
    p = _active(ctx["player_state"])
    year, px, py = p.get("pos", [0, 0, 0])
    world = world_loader(year)

    tiles = []
    try:
        if hasattr(world, "iter_open_tiles"):
            tiles = list(world.iter_open_tiles())
        elif hasattr(world, "open_coords"):
            tiles = list(world.open_coords())
        elif hasattr(world, "iter_tiles"):
            for t in world.iter_tiles():
                if not isinstance(t, dict):
                    continue
                pos = t.get("pos")
                edges = t.get("edges") or {}
                if isinstance(pos, list) and len(pos) >= 3:
                    if any(int(e.get("base", 0)) == 0 for e in edges.values()):
                        tiles.append((int(pos[1]), int(pos[2])))
    except Exception:
        tiles = []
    if not tiles:
        tiles = [(int(px), int(py))]

    random.shuffle(tiles)
    tiles = tiles[:sample_count]

    dirs = ["n", "s", "e", "w"]
    opp = {"n": "s", "s": "n", "e": "w", "w": "e"}
    delta = {"n": (0, 1), "s": (0, -1), "e": (1, 0), "w": (-1, 0)}
    bad = 0
    total = 0
    for (x, y) in tiles:
        for d in dirs:
            total += 1
            d1 = ER.resolve(world, dyn, year, x, y, d, actor={})
            dx, dy = delta[d]
            d2 = ER.resolve(world, dyn, year, x + dx, y + dy, opp[d], actor={})
            if d1.passable != d2.passable:
                bad += 1
                logger.warning(
                    "VERIFY/EDGE mismatch year=%s at (%s,%s) dir=%s | cur.pass=%s desc=%s | nbr.pass=%s desc=%s | cur=%r nbr=%r",
                    year,
                    x,
                    y,
                    d.upper(),
                    d1.passable,
                    d1.descriptor,
                    d2.passable,
                    d2.descriptor,
                    d1.cur_raw,
                    d1.nbr_raw,
                )
    if bad == 0:
        ctx["feedback_bus"].push(
            "SYSTEM/OK", f"Edge verify OK: {total} checks, 0 mismatches."
        )
    else:
        ctx["feedback_bus"].push(
            "SYSTEM/WARN",
            f"Edge verify found {bad}/{total} mismatches. See game.log for details.",
        )


def register(dispatch, ctx) -> None:
    dispatch.register("logs", lambda arg: log_cmd(arg, ctx))
    dispatch.alias("log", "logs")
