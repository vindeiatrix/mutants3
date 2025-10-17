import random

from mutants.services.monster_ai import emote


def test_emote_lines_count():
    assert len(emote.EMOTE_LINES) == 20


def test_cascade_emote_action_seeded_rng_covers_all_lines():
    rng = random.Random(0)
    monster = {"name": "Gloop"}
    ctx: dict[str, object] = {}

    expected_messages = {
        idx: template.format(monster=monster["name"])
        for idx, template in enumerate(emote.EMOTE_LINES)
    }

    seen: set[int] = set()

    for _ in range(200):
        payload = emote.cascade_emote_action(monster, ctx, rng)
        assert payload["ok"] is True
        index = payload["index"]
        assert payload["message"] == expected_messages[index]
        seen.add(index)

    assert seen == set(range(len(emote.EMOTE_LINES)))
