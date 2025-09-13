from src.mutants.commands.argcmd import PosArg, PosArgSpec, run_argcmd_positional


class FakeBus:
    def __init__(self):
        self.events = []
    def push(self, kind, text, **_):
        self.events.append((kind, text))


def _ctx():
    return {"feedback_bus": FakeBus()}


def test_point_usage_when_missing_args():
    ctx = _ctx()
    spec = PosArgSpec(
        verb="POINT",
        args=[PosArg("dir","direction"), PosArg("item","item_in_inventory")],
        messages={"usage": "Type POINT [direction] [item]."},
        reason_messages={"invalid_direction": "That isn't a valid direction."},
        success_kind="SYSTEM/OK",
    )
    run_argcmd_positional(ctx, spec, "north", lambda **kw: {"ok": True})
    # Missing item → usage
    assert ctx["feedback_bus"].events == [("SYSTEM/WARN", "Type POINT [direction] [item].")]


def test_point_invalid_direction_reason_mapping():
    ctx = _ctx()
    spec = PosArgSpec(
        verb="POINT",
        args=[PosArg("dir","direction"), PosArg("item","item_in_inventory")],
        messages={"usage": "Type POINT [direction] [item]."},
        reason_messages={"invalid_direction": "That isn't a valid direction."},
    )
    run_argcmd_positional(ctx, spec, "up skull", lambda **kw: {"ok": True})
    assert ctx["feedback_bus"].events == [("SYSTEM/WARN", "That isn't a valid direction.")]


def test_throw_success_message_uses_values():
    ctx = _ctx()
    spec = PosArgSpec(
        verb="THROW",
        args=[PosArg("dir","direction"), PosArg("item","item_in_inventory")],
        messages={"usage": "Type THROW [direction] [item].",
                  "success": "You throw the {item} {dir}."},
        success_kind="COMBAT/THROW",
    )
    run_argcmd_positional(ctx, spec, "n skull", lambda **kw: {"ok": True})
    assert ctx["feedback_bus"].events == [("COMBAT/THROW", "You throw the skull north.")]


def test_success_message_can_use_display_name():
    ctx = _ctx()
    spec = PosArgSpec(
        verb="THROW",
        args=[PosArg("dir", "direction"), PosArg("item", "item_in_inventory")],
        messages={"success": "You throw the {name} {dir}."},
        success_kind="COMBAT/THROW",
    )
    run_argcmd_positional(
        ctx,
        spec,
        "n sk",
        lambda **kw: {"ok": True, "display_name": "Skull"},
    )
    assert ctx["feedback_bus"].events == [
        ("COMBAT/THROW", "You throw the Skull north."),
    ]


def test_buy_ions_amount_range_and_gate_messages():
    ctx = _ctx()
    spec = PosArgSpec(
        verb="BUY",
        args=[PosArg("what","literal:ions"), PosArg("amt","int_range:100000:999999")],
        messages={"usage": "Type BUY ions [amount]."},
        reason_messages={
            "wrong_item_literal": "You can only buy ions here.",
            "invalid_amount_range": "Amount must be between 100000 and 999999.",
            "not_at_maintenance_shop": "You're not at a maintenance shop!",
        },
        success_kind="SHOP/BUY",
    )
    # Wrong literal
    run_argcmd_positional(ctx, spec, "shields 250000", lambda **kw: {"ok": True})
    # Bad range
    run_argcmd_positional(ctx, spec, "ions 999", lambda **kw: {"ok": True})
    # Gate from action (pretend we're not at shop)
    run_argcmd_positional(ctx, spec, "ions 250000", lambda **kw: {"ok": False, "reason": "not_at_maintenance_shop"})
    assert ctx["feedback_bus"].events == [
        ("SYSTEM/WARN", "You can only buy ions here."),
        ("SYSTEM/WARN", "Amount must be between 100000 and 999999."),
        ("SYSTEM/WARN", "You're not at a maintenance shop!"),
    ]

