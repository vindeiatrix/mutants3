from __future__ import annotations


def test_import_and_statistics_command_runs():
    # Import app modules; this catches import errors / bad runtime typing usage.
    import mutants
    from mutants.services import player_state as pstate
    from mutants.commands.statistics import statistics_cmd

    # Build a minimal ctx with a bus that collects pushes so we don't crash on prints.
    class Bus:
        def __init__(self):
            self.msgs = []

        def push(self, kind, msg):
            self.msgs.append((kind, msg))

    bus = Bus()
    ctx = {"bus": bus, "feedback_bus": bus}

    # Ensure state can load; no assertions on game data—just smoke.
    st = pstate.load_state()
    assert isinstance(st, dict)

    # Call statistics through its public entry; should not raise.
    statistics_cmd("", ctx)

    # Basic sanity: something got pushed to the bus.
    assert any(k.startswith("SYSTEM/") for k, _ in bus.msgs)
