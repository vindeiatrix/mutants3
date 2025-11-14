from __future__ import annotations

from mutants.app import trace as traceflags
from mutants.engine import edge_resolver as ER
from mutants.registries import dynamics as dyn
from mutants.ui import renderer as uirender
from mutants.ui import item_display as idisp
from mutants.services import item_transfer as itx
from mutants.services import player_state as pstate
from mutants.ui.wrap import wrap_segments, WRAP_DEBUG_OPTS
import random
import logging
import json


def _probe_wrap(count: int = 12, width: int = 80, ctx=None) -> None:
    """Generate a hyphenated list and log wrapping diagnostics."""

    logger = logging.getLogger(__name__)
    hy = "\u2011"  # non-breaking hyphen
    samples = [
        f"A Nuclear{hy}Decay",
        f"A Bottle{hy}Cap",
        f"A Cigarette{hy}Butt",
        f"A Light{hy}Spear",
    ]
    items = [samples[i % len(samples)] for i in range(count)]
    raw = "On the ground lies: " + ", ".join(items) + "."
    lines = wrap_segments([raw], width=width)
    fb = ctx.get("feedback_bus") if ctx else None
    if fb:
        fb.push("SYSTEM/INFO", f'UI/PROBE raw={json.dumps(raw, ensure_ascii=False)}')
        fb.push(
            "SYSTEM/INFO",
            (
                f'UI/PROBE wrap width={width} '
                f'opts={json.dumps(WRAP_DEBUG_OPTS, sort_keys=True)} '
                f'lines={json.dumps(lines, ensure_ascii=False)}'
            ),
        )
    logger.info("UI/PROBE raw=%s", json.dumps(raw, ensure_ascii=False))
    logger.info(
        "UI/PROBE wrap width=%d opts=%s lines=%s",
        width,
        json.dumps(WRAP_DEBUG_OPTS, sort_keys=True),
        json.dumps(lines, ensure_ascii=False),
    )
    bad = False
    for a, b in zip(lines, lines[1:]):
        if a.endswith("-") and b[:1].isalpha():
            bad = True
            if fb:
                fb.push(
                    "SYSTEM/WARN",
                    f'UI/WRAP/BAD_SPLIT at line="{a}" next="{b}"',
                )
            logger.warning("UI/WRAP/BAD_SPLIT at line='%s' next='%s'", a, b)
    if not bad:
        if fb:
            fb.push("SYSTEM/OK", "UI/WRAP/OK")
        logger.info("UI/WRAP/OK")


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
    if len(parts) >= 2 and parts[0] == "verify" and parts[1] == "separators":
        ok, failures = uirender.verify_separators_scenarios()
        if failures:
            for f in failures:
                logging.getLogger(__name__).warning("VERIFY/SEPARATORS - %s", f)
            ctx["feedback_bus"].push(
                "SYSTEM/WARN",
                f"Separator verify found {len(failures)} issue(s). See game.log.",
            )
        else:
            ctx["feedback_bus"].push(
                "SYSTEM/OK", f"Separator verify OK: {ok} scenarios passed."
            )
        return
    if len(parts) >= 2 and parts[0] == "verify" and parts[1] == "items":
        cases = [
            (["ion_decay", "skull", "skull", "opal_knife"],
             "An Ion-Decay, A Skull, A Skull (1), An Opal-Knife."),
            (["gold_chunk"], "A Gold-Chunk."),
            (["battery", "battery", "battery"],
             "A Battery, A Battery (1), A Battery (2)."),
        ]
        fails = 0
        for ids, expect in cases:
            got = idisp.render_ground_list(ids)
            if got != expect:
                fails += 1
                logging.getLogger(__name__).warning(
                    'VERIFY/ITEMS - expected "%s" got "%s" for %r', expect, got, ids
                )
        if fails:
            ctx["feedback_bus"].push(
                "SYSTEM/WARN", f"Item verify found {fails} failure(s). See game.log."
            )
        else:
            ctx["feedback_bus"].push(
                "SYSTEM/OK", f"Item verify OK: {len(cases)} cases passed."
            )
        return
    if len(parts) >= 2 and parts[0] == "verify" and parts[1] == "getdrop":
        seed = 12345
        itx._rng(seed)  # touch RNG for deterministic path
        ctx["feedback_bus"].push("SYSTEM/OK", "Get/Drop verify executed.")
        logging.getLogger(__name__).info("VERIFY/GETDROP - seed=%s", seed)
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
    if len(parts) >= 2 and parts[0] == "probe" and parts[1] == "wrap":
        count = 12
        width = 80
        it = iter(parts[2:])
        for tok in it:
            if tok == "--count":
                try:
                    count = int(next(it))
                except StopIteration:
                    pass
            elif tok == "--width":
                try:
                    width = int(next(it))
                except StopIteration:
                    pass
        _probe_wrap(count=count, width=width, ctx=ctx)
        ctx["feedback_bus"].push(
            "SYSTEM/OK", f"Wrap probe logged (count={count}, width={width})."
        )
        return
    if not parts or parts[0] == "tail":
        n = int(parts[1]) if len(parts) > 1 else 100
        for line in sink.tail(n):
            print(line)
        return
    if parts[0] == "clear":
        sink.clear()
        ctx["feedback_bus"].push("SYSTEM/OK", "Logs cleared.")
        return
    # unknown subcommand -> show tail
    for line in sink.tail(100):
        print(line)


def _verify_edges(sample_count: int, ctx) -> None:
    """Sample random tiles and verify resolver symmetry."""
    logger = logging.getLogger(__name__)
    world_loader = ctx["world_loader"]
    year, px, py = pstate.canonical_player_pos(ctx.get("player_state"))
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
