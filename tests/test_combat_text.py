from mutants.combat.text import render_innate_attack_line
from mutants.services.monster_entities import DEFAULT_INNATE_ATTACK_LINE


def test_render_innate_attack_line_substitutes_tokens():
    result = render_innate_attack_line(
        "Junkyard Scrapper",
        {"name": "Rusty Shiv", "line": "The {monster} slashes with {attack}!"},
    )
    assert result == "The Junkyard Scrapper slashes with Rusty Shiv!"


def test_render_innate_attack_line_uses_target():
    result = render_innate_attack_line(
        "Rad Swarm Matron",
        {"name": "Toxic Bite", "line": "{monster} poisons {target} with {attack}!"},
        target_name="the hero",
    )
    assert result == "Rad Swarm Matron poisons the hero with Toxic Bite!"


def test_render_innate_attack_line_fallback():
    result = render_innate_attack_line("Titan", {"name": "Slam"})
    assert result == DEFAULT_INNATE_ATTACK_LINE.replace("{monster}", "Titan").replace(
        "{attack}", "Slam"
    ).replace("{target}", "you")
