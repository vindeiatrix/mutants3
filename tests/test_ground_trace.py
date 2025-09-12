from mutants.app import context, trace
from mutants.ui import renderer


def test_ground_tracing_emits_events():
    ctx = context.build_context()
    trace.set_flag("ui", True)
    bus = ctx["feedback_bus"]
    bus.drain()
    vm = {
        "header": "",
        "coords": {"x": 0, "y": 0},
        "dirs": {},
        "monsters_here": [],
        "ground_item_ids": ["nuclear_decay", "bottle_cap"],
        "events": [],
        "shadows": [],
        "flags": {"dark": False},
    }
    renderer.render_token_lines(vm, width=80)
    events = bus.drain()
    texts = [e["text"] for e in events]
    assert any(t.startswith("UI/GROUND raw=") for t in texts)
    assert any(t.startswith("UI/GROUND wrap") for t in texts)
    trace.set_flag("ui", False)
