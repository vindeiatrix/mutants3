from mutants.commands.argcmd import ArgSpec, run_argcmd


class FakeBus:
    def __init__(self):
        self.events = []
    def push(self, kind, text, **_):
        self.events.append((kind, text))


def _ctx():
    return {"feedback_bus": FakeBus()}


def test_get_empty_arg_shows_usage():
    ctx = _ctx()
    spec = ArgSpec(
        verb="GET",
        arg_policy="required",
        messages={"usage": "Type GET [item name] to pick up an item."},
        success_kind="LOOT/PICKUP",
    )
    run_argcmd(ctx, spec, "", lambda s: {"ok": False})
    assert ctx["feedback_bus"].events == [
        ("SYSTEM/WARN", "Type GET [item name] to pick up an item.")
    ]


def test_get_invalid_subject_maps_reason():
    ctx = _ctx()
    spec = ArgSpec(
        verb="GET",
        arg_policy="required",
        messages={"invalid": "There isn't a {subject} here."},
        reason_messages={"not_found": "There isn't a {subject} here."},
        success_kind="LOOT/PICKUP",
    )
    run_argcmd(ctx, spec, "baditem", lambda s: {"ok": False, "reason": "not_found"})
    assert ctx["feedback_bus"].events == [
        ("SYSTEM/WARN", "There isn't a baditem here.")
    ]


def test_drop_inventory_empty_is_preserved():
    ctx = _ctx()
    spec = ArgSpec(
        verb="DROP",
        arg_policy="required",
        messages={"invalid": "You're not carrying a {subject}."},
        reason_messages={"inventory_empty": "You have nothing to drop."},
        success_kind="LOOT/DROP",
    )
    run_argcmd(ctx, spec, "skull", lambda s: {"ok": False, "reason": "inventory_empty"})
    assert ctx["feedback_bus"].events == [
        ("SYSTEM/WARN", "You have nothing to drop.")
    ]


def test_drop_success_includes_name():
    ctx = _ctx()
    spec = ArgSpec(
        verb="DROP",
        arg_policy="required",
        messages={"success": "You drop the {name}."},
        success_kind="LOOT/DROP",
    )
    run_argcmd(ctx, spec, "sk", lambda s: {"ok": True, "display_name": "Skull"})
    assert ctx["feedback_bus"].events == [
        ("LOOT/DROP", "You drop the Skull.")
    ]

