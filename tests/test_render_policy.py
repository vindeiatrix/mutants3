from mutants.app import context
from mutants.app.render_policy import RenderPolicy
from mutants.repl.dispatch import Dispatch
from mutants.commands.register_all import register_all


def make_dispatch_ctx():
    ctx = context.build_context()
    dispatch = Dispatch()
    dispatch.set_feedback_bus(ctx["feedback_bus"])
    register_all(dispatch, ctx)
    return dispatch, ctx


def test_render_policy_for_commands():
    dispatch, ctx = make_dispatch_ctx()

    assert dispatch.call("north", "") is RenderPolicy.ROOM
    assert dispatch.call("look", "") is RenderPolicy.ROOM
    assert dispatch.call("look", "east") is RenderPolicy.ROOM
    # Non movement/look commands should not trigger a repaint
    assert dispatch.call("help", "") is RenderPolicy.NEVER
