from __future__ import annotations

import json
import shutil
from pathlib import Path

from mutants.commands.convert import convert_cmd
from mutants.registries import items_instances as itemsreg
from mutants.services import item_transfer as itx


class FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def push(self, kind: str, text: str, **_ignored) -> None:
        self.events.append((kind, text))


def _copy_state(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst)


def _setup_state(monkeypatch, tmp_path) -> tuple[dict, Path]:
    src_state = Path(__file__).resolve().parents[2] / "state"
    dst_state = tmp_path / "state"
    _copy_state(src_state, dst_state)
    monkeypatch.chdir(tmp_path)
    itemsreg.invalidate_cache()
    itx._STATE_CACHE = None
    return {"feedback_bus": FakeBus()}, dst_state / "playerlivestate.json"


def _prime_inventory(pfile: Path, iid: str, *, ions: int = 0) -> None:
    with pfile.open("r", encoding="utf-8") as f:
        pdata = json.load(f)
    pdata["players"][0]["inventory"] = [iid]
    pdata["players"][0]["ions"] = ions
    with pfile.open("w", encoding="utf-8") as f:
        json.dump(pdata, f, indent=2)


def test_convert_requires_argument() -> None:
    ctx = {"feedback_bus": FakeBus()}
    result = convert_cmd("", ctx)
    assert result == {"ok": False, "reason": "missing_argument"}
    assert ctx["feedback_bus"].events == [("SYSTEM/WARN", "You're not carrying a .")]


def test_convert_not_found(monkeypatch, tmp_path) -> None:
    ctx, pfile = _setup_state(monkeypatch, tmp_path)
    iid = itemsreg.create_and_save_instance("nuclear_decay", 2000, 0, 0)
    itemsreg.clear_position(iid)
    _prime_inventory(pfile, iid, ions=10)

    result = convert_cmd("zzz", ctx)

    assert result == {"ok": False, "reason": "not_found"}
    assert ctx["feedback_bus"].events == [("SYSTEM/WARN", "You're not carrying a zzz.")]
    with pfile.open("r", encoding="utf-8") as f:
        pdata = json.load(f)
    assert pdata["players"][0]["inventory"] == [iid]


def test_convert_success(monkeypatch, tmp_path) -> None:
    ctx, pfile = _setup_state(monkeypatch, tmp_path)
    iid = itemsreg.create_and_save_instance("nuclear_decay", 2000, 0, 0)
    itemsreg.clear_position(iid)
    _prime_inventory(pfile, iid, ions=5)

    result = convert_cmd("nuc", ctx)

    assert result == {"ok": True, "iid": iid, "item_id": "nuclear_decay", "ions": 85000}
    assert ctx["feedback_bus"].events == [
        ("SYSTEM/OK", "The Nuclear-Decay vanishes with a flash!"),
        ("SYSTEM/OK", "You convert the Nuclear-Decay into 85000 ions."),
    ]

    with pfile.open("r", encoding="utf-8") as f:
        pdata = json.load(f)
    assert pdata["players"][0]["inventory"] == []
    assert pdata["players"][0]["ions"] == 85005
    assert itemsreg.get_instance(iid) is None
