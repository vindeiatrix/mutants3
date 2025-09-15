from __future__ import annotations

from dataclasses import dataclass

from mutants.ui.screens import ScreenManager


@dataclass
class FakePlayer:
    data: dict

    def to_dict(self):
        return self.data


class FakeSaveData:
    def __init__(self, players):
        self.players = players
        self.active_id = "player_thief"


class FakeManager:
    def __init__(self):
        self.template_order = [
            "player_thief",
            "player_priest",
            "player_wizard",
            "player_warrior",
            "player_mage",
        ]
        base = {
            "pos": [2000, 0, 0],
            "hp": {"current": 10, "max": 10},
            "stats": {"str": 10, "int": 10, "wis": 10, "dex": 10, "con": 10, "cha": 10},
            "conditions": {"poisoned": False, "encumbered": False, "ion_starving": False},
            "level": 1,
            "class": "Thief",
            "name": "Thief",
        }
        players = {}
        for cid in self.template_order:
            entry = dict(base)
            entry = {**base, "class": cid.split("_")[-1].capitalize(), "name": cid.split("_")[-1].capitalize()}
            players[cid] = FakePlayer(entry)
        self.save_data = FakeSaveData(players)
        self.last_switch = None

    def switch_active(self, class_id: str) -> None:
        self.save_data.active_id = class_id
        self.last_switch = class_id


class FakeBus:
    def __init__(self):
        self.events = []

    def push(self, kind, text):
        self.events.append((kind, text))


def fake_render_room(ctx):
    return ["room"]


def test_selection_numeric_switch(capsys):
    mgr = FakeManager()
    screens = ScreenManager(mgr, fake_render_room)
    ctx = {"render_next": False, "feedback_bus": FakeBus()}
    screens.handle_selection("2", ctx)
    assert mgr.last_switch == "player_priest"
    assert screens.mode == "game"
    assert ctx["render_next"] is True


def test_selection_help_message(capsys):
    mgr = FakeManager()
    screens = ScreenManager(mgr, fake_render_room)
    ctx = {"render_next": False, "feedback_bus": FakeBus()}
    screens.handle_selection("?", ctx)
    out = capsys.readouterr().out
    assert "Enter 1–5" in out


def test_selection_bury_stub(capsys):
    mgr = FakeManager()
    screens = ScreenManager(mgr, fake_render_room)
    ctx = {"render_next": False, "feedback_bus": FakeBus()}
    screens.handle_selection("BURY 3", ctx)
    out = capsys.readouterr().out
    assert "Bury not implemented" in out


def test_selection_quit_returns_quit_action():
    mgr = FakeManager()
    screens = ScreenManager(mgr, fake_render_room)
    bus = FakeBus()
    ctx = {"render_next": False, "feedback_bus": bus}

    resp = screens.handle_selection("q", ctx)

    assert resp.action == "quit"
    assert ctx["render_next"] is False
    assert ("SYSTEM/OK", "Goodbye!") in bus.events
