from __future__ import annotations

import pytest

from bench.subset import EndpointRef
from bench.verbs.base import OvsCommand, VerbError, resolve

EP = {
    "a": EndpointRef(host="h1", mac="00:00:00:00:00:01"),
    "b": EndpointRef(host="h3", mac="00:00:00:00:00:03"),
}


def test_resolve_returns_the_endpoint():
    assert resolve(EP, "a").host == "h1"


def test_resolve_rejects_an_unknown_endpoint():
    with pytest.raises(VerbError):
        resolve(EP, "ghost")


def test_ovs_command_is_immutable():
    cmd = OvsCommand(target="s1", command="ovs-ofctl show s1")
    with pytest.raises(Exception):
        cmd.target = "s2"


def test_ovs_command_keeps_markers_verbatim():
    cmd = OvsCommand(target="all", command="set interface {swport:h1} up")
    assert "{swport:h1}" in cmd.command
