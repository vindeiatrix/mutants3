from __future__ import annotations


def register(dispatch, ctx) -> None:
    bus = ctx["feedback_bus"]

    def _time(_: str = "") -> None:
        bus.push(
            "SYSTEM/WARN",
            "The 'time' command has been retired. Use 'travel <year>' (e.g., 'tra 2100').",
        )

    dispatch.register("time", _time)
