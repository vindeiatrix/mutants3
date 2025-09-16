from mutants.commands import inv


class FakeBus:
    def __init__(self):
        self.events = []

    def push(self, key, message):
        self.events.append((key, message))


class FakeCatalog:
    def __init__(self, items):
        self._items = items

    def get(self, item_id):
        return self._items.get(item_id)


def test_inventory_empty_shows_header_and_nothing(monkeypatch):
    bus = FakeBus()
    ctx = {"feedback_bus": bus}

    monkeypatch.setattr(inv, "get_player_inventory_instances", lambda _ctx: [])
    monkeypatch.setattr(inv.items_catalog, "load_catalog", lambda: FakeCatalog({}))

    inv.inv_cmd("", ctx)

    assert bus.events == [
        ("SYSTEM/OK", "You are carrying the following items: (Total Weight: 0 LB's)"),
        ("SYSTEM/OK", "Nothing."),
    ]


def test_inventory_header_includes_single_item_weight(monkeypatch):
    bus = FakeBus()
    ctx = {"feedback_bus": bus}

    monkeypatch.setattr(inv, "get_player_inventory_instances", lambda _ctx: ["iid-1"])

    catalog_items = {
        "test_sword": {"item_id": "test_sword", "weight": 2.6, "name": "Sword"}
    }
    monkeypatch.setattr(
        inv.items_catalog, "load_catalog", lambda: FakeCatalog(catalog_items)
    )
    monkeypatch.setattr(
        inv.itemsreg, "get_instance", lambda iid: {"item_id": "test_sword"}
    )

    inv.inv_cmd("", ctx)

    assert bus.events[0] == (
        "SYSTEM/OK",
        "You are carrying the following items: (Total Weight: 3 LB's)",
    )
    assert all(event[1] != "Nothing." for event in bus.events[1:])


def test_inventory_header_sums_multiple_items_with_quantities(monkeypatch):
    bus = FakeBus()
    ctx = {"feedback_bus": bus}

    monkeypatch.setattr(
        inv,
        "get_player_inventory_instances",
        lambda _ctx: ["iid-1", "iid-2"],
    )

    catalog_items = {
        "item_a": {"item_id": "item_a", "weight": 1.6},
        "item_b": {"item_id": "item_b", "weight": 0.5},
    }
    monkeypatch.setattr(
        inv.items_catalog, "load_catalog", lambda: FakeCatalog(catalog_items)
    )

    instances = {
        "iid-1": {"item_id": "item_a", "quantity": 2},
        "iid-2": {"item_id": "item_b", "quantity": 3},
    }

    monkeypatch.setattr(inv.itemsreg, "get_instance", lambda iid: instances[iid])

    inv.inv_cmd("", ctx)

    assert bus.events[0] == (
        "SYSTEM/OK",
        "You are carrying the following items: (Total Weight: 5 LB's)",
    )
    assert len(bus.events) > 1
