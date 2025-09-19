import json


def test_per_class_bags_isolated(tmp_path, monkeypatch):
    """
    Regression: picking up with Class A must not appear in Class B's inventory.
    We simulate by writing/reading the playerlivestate via a tmp file and using
    the normalization/binding helpers.
    """
    state_file = tmp_path / "playerlivestate.json"

    from mutants.services import player_state as ps

    monkeypatch.setattr(ps, "_player_path", lambda: state_file)

    # Seed a canonical empty state (bags + active profile)
    ps.save_state({"active": {"class": "Thief"}, "inventory": [], "bags": {}})

    # --- Simulate Class A (Thief) pickup
    state = ps.load_state()
    state["active"]["class"] = "Thief"
    ps.bind_inventory_to_active_class(state)
    state["inventory"].append("IID1")
    ps.save_state(state)

    # --- Switch to Class B (Priest) and confirm isolation
    state = ps.load_state()
    state["active"]["class"] = "Priest"
    ps.save_state(state)  # persist the class swap and normalize bags
    state = ps.load_state()
    ps.bind_inventory_to_active_class(state)
    priest_inventory_before = list(state["inventory"])
    assert "IID1" not in priest_inventory_before, "Thief item leaked into Priest bag"
    state["inventory"].append("IID2")
    ps.save_state(state)

    # --- Switch back to Thief; ensure Priest's item didn't leak
    state = ps.load_state()
    state["active"]["class"] = "Thief"
    ps.save_state(state)
    state = ps.load_state()
    ps.bind_inventory_to_active_class(state)
    assert "IID1" in state["inventory"]
    assert "IID2" not in state["inventory"]

    bags = state["bags"]
    assert "IID1" in bags["Thief"]
    assert "IID2" in bags["Priest"]
    assert "IID1" not in bags["Priest"]


def test_first_run_migrates_legacy_inventory_once(tmp_path, monkeypatch):
    state_file = tmp_path / "playerlivestate.json"
    legacy = {"inventory": ["OLD_IID"], "year": 2000}
    state_file.write_text(json.dumps(legacy), encoding="utf-8")

    from mutants.services import player_state as ps

    monkeypatch.setattr(ps, "_player_path", lambda: state_file)

    state = ps.load_state()
    assert state["bags"][state["active"]["class"]] == ["OLD_IID"]
    assert state["inventory"] == ["OLD_IID"]

    state["active"]["class"] = "Priest"
    ps.save_state(state)
    state = ps.load_state()
    ps.bind_inventory_to_active_class(state)
    assert state["inventory"] == [], "Legacy items should not re-migrate to new bag"
