from __future__ import annotations

import pytest

from app.llm.intent_plan import BlockOp
from bench.subset import EndpointRef
from bench.verbs import REGISTRY, commands_for
from bench.verbs.base import OvsCommand, VerbError

EP = {
    "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
    "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
}


def test_registered_modules_expose_the_interface():
    for verb, module in REGISTRY.items():
        assert hasattr(module, "OP_MODEL"), verb
        assert callable(module.to_commands), verb


def test_commands_for_dispatches_on_the_verb():
    cmds = commands_for(BlockOp(verb="block", src="a", dst="b"), EP)
    assert cmds and all(isinstance(c, OvsCommand) for c in cmds)


def test_commands_for_rejects_an_unregistered_verb():
    class _Fake:
        verb = "teleport"

    with pytest.raises(VerbError):
        commands_for(_Fake(), EP)
