from __future__ import annotations
import importlib, pkgutil
from typing import Any

def register_all(dispatch: Any, ctx: dict) -> None:
    """
    Auto-discover and register all command modules under mutants.commands.
    A module is considered a command module if it exposes register(dispatch, ctx).
    """
    pkg_name = "mutants.commands"
    pkg = importlib.import_module(pkg_name)

    modules = []
    for m in pkgutil.iter_modules(pkg.__path__):  # type: ignore[attr-defined]
        name = m.name
        # Retire the 'switch' command; menu replaces it.
        if name in {"__init__", "register_all", "switch"} or name.startswith("_"):
            continue
        modules.append(name)

    for name in sorted(modules):
        mod = importlib.import_module(f"{pkg_name}.{name}")
        reg = getattr(mod, "register", None)
        if callable(reg):
            reg(dispatch, ctx)
