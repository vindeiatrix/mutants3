from __future__ import annotations
import json, os
from ..ui import item_display as idisp
from ..ui import wrap as uwrap


def _player_file() -> str:
    return os.path.join(os.getcwd(), "state", "playerlivestate.json")


def _load_player():
    try:
        return json.load(open(_player_file(), "r", encoding="utf-8"))
    except FileNotFoundError:
        return {}


def inv_cmd(arg: str, ctx):
    p = _load_player()
    inv = list(p.get("inventory") or [])
    names = [idisp.canonical_name_from_iid(i) for i in inv]
    numbered = idisp.number_duplicates(names)
    with_articles = [idisp.with_article(n) for n in numbered]
    bus = ctx["feedback_bus"]
    if not with_articles:
        bus.push("SYSTEM/OK", "You are carrying nothing.")
        return
    bus.push("SYSTEM/OK", "You are carrying:")
    line = ", ".join(with_articles) + "."
    try:
        for ln in uwrap.wrap(line):
            bus.push("SYSTEM/OK", ln)
    except Exception:
        bus.push("SYSTEM/OK", line)


def register(dispatch, ctx) -> None:
    dispatch.register("inv", lambda arg: inv_cmd(arg, ctx))
    dispatch.alias("inventory", "inv")
