"""Screen primitives for class selection and in-game mode."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from mutants.state.manager import StateManager


@dataclass
class ScreenResponse:
    action: str
    payload: Optional[Any] = None


def _pos_tuple(pos: Iterable[int]) -> tuple[int, int, int]:
    data = list(pos) if not isinstance(pos, list) else pos
    if len(data) < 3:
        data = list(data) + [0] * (3 - len(data))
    try:
        year = int(data[0])
    except (TypeError, ValueError):
        year = 0
    try:
        x = int(data[1])
    except (TypeError, ValueError):
        x = 0
    try:
        y = int(data[2])
    except (TypeError, ValueError):
        y = 0
    return year, x, y


class ClassSelectionScreen:
    """Render and parse the class selection menu."""

    def __init__(self, manager: StateManager) -> None:
        self.manager = manager

    def render(self) -> List[str]:
        lines: List[str] = []
        for idx, class_id in enumerate(self.manager.template_order, start=1):
            player = self.manager.save_data.players[class_id].to_dict()
            class_name = player.get("class") or player.get("class_name") or player.get("name") or class_id
            display_name = f"Mutant {class_name}".strip()
            display = f"{idx}. {display_name:<17}"
            level = player.get("level") or player.get("level_start") or 1
            try:
                level_val = int(level)
            except (TypeError, ValueError):
                level_val = 1
            year, x, y = _pos_tuple(player.get("pos", [2000, 0, 0]))
            suffix = f"Level: {level_val:<2}   Year: {year:<4}   ({x:>2}  {y:>2})"
            lines.append(f"{display}{suffix}")
        lines.append("Type BURY [class number] to reset a player.")
        lines.append("***")
        lines.append("Select (Bury, 1–5, ?)")
        return lines

    def handle(self, input_str: str) -> ScreenResponse:
        raw = (input_str or "").strip()
        if not raw:
            return ScreenResponse("noop")

        lowered = raw.lower()
        if lowered in ("q",) or (len(lowered) >= 3 and lowered.startswith("qui")):
            return ScreenResponse("quit")

        token = raw.upper()
        if token == "?":
            return ScreenResponse("message", "Enter 1–5 to choose a class; 'Bury' resets later.")

        if token.startswith("BURY"):
            parts = raw.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return ScreenResponse("message", "Bury not implemented yet.")
            return ScreenResponse("message", "Usage: BURY <class number> (not implemented yet).")

        if raw.isdigit():
            choice = int(raw)
            if 1 <= choice <= len(self.manager.template_order):
                class_id = self.manager.template_order[choice - 1]
                return ScreenResponse("enter_game", class_id)
        return ScreenResponse("message", "Unknown selection. Enter 1–5, ?, or BURY <n>.")


class InGameScreen:
    """Thin wrapper around the legacy room renderer."""

    def __init__(self, render_room_callable) -> None:
        self._render_room = render_room_callable

    def render(self, ctx: Dict[str, Any]) -> List[str]:
        return self._render_room(ctx)


class ScreenManager:
    def __init__(self, manager: StateManager, render_room_callable) -> None:
        self.manager = manager
        self.selection = ClassSelectionScreen(manager)
        self.ingame = InGameScreen(render_room_callable)
        self.mode = "selection"

    def in_selection(self) -> bool:
        return self.mode == "selection"

    def render(self, ctx: Dict[str, Any]) -> List[str]:
        if self.in_selection():
            return self.selection.render()
        return self.ingame.render(ctx)

    def handle_selection(self, raw: str, ctx: Dict[str, Any]) -> ScreenResponse:
        response = self.selection.handle(raw)
        if response.action == "enter_game" and isinstance(response.payload, str):
            try:
                self.manager.switch_active(response.payload)
            except KeyError:
                return ScreenResponse("message", "Unknown class.")
            self.mode = "game"
            ctx["render_next"] = True
        elif response.action == "quit":
            ctx["render_next"] = False
            bus = ctx.get("feedback_bus")
            if bus is not None:
                bus.push("SYSTEM/OK", "Goodbye!")
        elif response.action == "message" and response.payload:
            print(response.payload)
            ctx["render_next"] = True
        elif response.action == "noop":
            ctx["render_next"] = True
        return response

    def enter_selection(self, ctx: Dict[str, Any]) -> None:
        self.mode = "selection"
        ctx["render_next"] = True

    def enter_game(self, ctx: Dict[str, Any]) -> None:
        self.mode = "game"
        ctx["render_next"] = True

