from __future__ import annotations


def startup_banner(ctx) -> str:
    return (
        "Mutants — classic BBS vibes.  Type 'help' for commands; 'theme mono' for no color.\n"
    )


def render_help(dispatch) -> str:
    cmds = sorted(dispatch.list_commands().keys())
    # Grouping/formatting minimal for now
    return "Commands: " + ", ".join(cmds)
