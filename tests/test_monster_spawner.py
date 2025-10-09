import random

import pytest

from mutants.registries import monsters_instances, sqlite_store
from mutants.services import monster_spawner


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, delta: float) -> None:
        self.value += float(delta)

    def jump_to(self, target: float) -> None:
        if target < self.value:
            raise AssertionError("clock cannot move backwards")
        self.value = float(target)


class WorldStub:
    def __init__(self, year: int, coords: list[tuple[int, int]]) -> None:
        self._tiles = [[year, x, y] for x, y in coords]

    def iter_tiles(self):
        for year, x, y in self._tiles:
            yield {"pos": [year, x, y]}


def _world_loader_factory(layout: dict[int, list[tuple[int, int]]]):
    def _loader(year: int) -> WorldStub:
        coords = layout.get(year, [])
        if not coords:
            raise FileNotFoundError(f"Missing world for {year}")
        return WorldStub(year, coords)

    return _loader


def _template(monster_id: str, *, years: list[int]) -> dict:
    return {
        "id": monster_id,
        "name": monster_id.title(),
        "level": 2,
        "hp": {"current": 6, "max": 6},
        "derived": {"armour_class": 3},
        "bag": [
            {"item_id": "club", "iid": f"{monster_id}#club"},
            {"item_id": "potion", "iid": f"{monster_id}#potion", "qty": 2},
        ],
        "armour_slot": {"item_id": "leather", "iid": f"{monster_id}#leather"},
        "innate_attack": {
            "name": "Slash",
            "power_base": 2,
            "power_per_level": 1,
            "message": "{monster} slashes {target}!",
        },
        "spells": ["blink"],
        "taunt": "The bandit eyes you warily.",
        "ions": 5,
        "riblets": 3,
        "pinned_years": list(years),
    }


@pytest.fixture
def instances(tmp_path):
    db_path = tmp_path / "monsters.db"
    stores = sqlite_store.get_stores(db_path)
    path = tmp_path / "instances.json"
    return monsters_instances.MonstersInstances(str(path), [], store=stores.monsters)


def test_spawner_respects_rate_limit_and_floor(instances):
    world_loader = _world_loader_factory({2000: [(0, 0), (1, 1)]})
    template = _template("bandit#template", years=[2000])
    clock = FakeClock()
    controller = monster_spawner.MonsterSpawnerController(
        templates=[template],
        instances=instances,
        world_loader=world_loader,
        rng=random.Random(1),
        time_func=clock,
        floor_per_year=3,
    )

    controller.tick()
    monsters = list(instances.list_all())
    assert len(monsters) == 1
    spawn = monsters[0]
    assert spawn["hp"] == {"current": 6, "max": 6}
    assert spawn["armour_class"] == 3
    assert spawn["level"] == 2
    assert spawn["ions"] == 5 and spawn["riblets"] == 3
    assert spawn["innate_attack"]["name"] == "Slash"
    assert spawn["armour_wearing"] in {entry.get("instance_id") for entry in spawn["inventory"]}
    assert all(entry.get("origin") == "native" for entry in spawn["inventory"] if isinstance(entry, dict))

    scheduled = controller._years[2000].next_spawn_at
    assert 45 <= scheduled <= 75

    clock.jump_to(scheduled - 0.5)
    controller.tick()
    assert len(list(instances.list_all())) == 1

    clock.jump_to(scheduled + 0.5)
    controller.tick()
    assert len(list(instances.list_all())) == 2

    next_time = controller._years[2000].next_spawn_at
    clock.jump_to(next_time + 1)
    controller.tick()
    assert len(list(instances.list_all())) == 3

    ids = {inst["instance_id"] for inst in instances.list_all()}
    assert len(ids) == 3


def test_spawner_refills_after_deaths(instances):
    world_loader = _world_loader_factory({2000: [(0, 0)]})
    template = _template("ghoul#template", years=[2000])
    clock = FakeClock()
    controller = monster_spawner.MonsterSpawnerController(
        templates=[template],
        instances=instances,
        world_loader=world_loader,
        rng=random.Random(2),
        time_func=clock,
        floor_per_year=2,
    )

    controller.tick()
    first_time = controller._years[2000].next_spawn_at
    clock.jump_to(first_time + 1)
    controller.tick()
    assert len(list(instances.list_all())) == 2

    # Simulate two deaths by clearing instances but keep one survivor
    survivors = instances.list_all()
    assert survivors, "expected at least one monster"
    for inst in survivors[1:]:
        instances.delete(inst["instance_id"])

    refill_time = controller._years[2000].next_spawn_at
    clock.jump_to(refill_time + 1)
    controller.tick()
    assert len(list(instances.list_all())) == 2

    refill_time = controller._years[2000].next_spawn_at
    clock.jump_to(refill_time + 1)
    controller.tick()
    assert len(list(instances.list_all())) == 2
