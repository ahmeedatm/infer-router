"""The rule that decides whether a switch rejected a bench command.

Lives in its own module precisely so it can be tested on the Mac: the runner
that uses it (``bench.topology``) imports Mininet and can only run in the VM.
"""
from __future__ import annotations

import pytest

from bench.apply_result import ApplyError, failure_marker, raise_if_failed

# Real rejection texts from ovs-ofctl / ovs-vsctl, shortened.
_OFCTL_PREREQ = (
    "ovs-ofctl: tp_dst: prerequisites not met for setting tp_dst\n"
)
_OFCTL_USAGE = "ovs-ofctl: 'add-flow' command requires at least 2 arguments\n"
_VSCTL_NO_PORT = 'ovs-vsctl: no port named "s1-eth9"\n'
_VSCTL_SYNTAX = "ovs-vsctl: Invalid syntax in argument\n"
_UNKNOWN_FIELD = "unknown field nw_prot\n"
_MISSING_PREREQ = "missing prerequisites for tp_dst\n"


@pytest.mark.parametrize(
    "output",
    [_OFCTL_PREREQ, _OFCTL_USAGE, _VSCTL_NO_PORT, _VSCTL_SYNTAX,
     _UNKNOWN_FIELD, _MISSING_PREREQ, "Error: bridge does not exist\n",
     "error: something went wrong\n"],
)
def test_rejection_texts_are_detected(output):
    assert failure_marker(output) is not None


@pytest.mark.parametrize(
    "output",
    ["", "\n", "8f2b4a1c-0d3e-4c9a-9f21-1a2b3c4d5e6f\n"],
)
def test_successful_output_carries_no_marker(output):
    """ovs-ofctl is silent on success; ovs-vsctl create prints a UUID."""
    assert failure_marker(output) is None


def test_raise_if_failed_is_quiet_on_success():
    raise_if_failed("s1", "ovs-ofctl add-flow s1 'actions=drop'", "")


def test_raise_if_failed_raises_apply_error_on_rejection():
    with pytest.raises(ApplyError):
        raise_if_failed("s2", "ovs-ofctl add-flow s2 'bad'", _OFCTL_PREREQ)


def test_apply_error_names_switch_command_and_output():
    """A failed case must be diagnosable from the exception alone: without
    the offending command, a rejection is indistinguishable from the model
    simply not having asked for that behaviour."""
    command = "ovs-ofctl add-flow s2 'priority=300,tp_dst=22,actions=drop'"
    with pytest.raises(ApplyError) as excinfo:
        raise_if_failed("s2", command, _OFCTL_PREREQ)
    error = excinfo.value
    assert error.switch == "s2"
    assert error.command == command
    assert error.output == _OFCTL_PREREQ
    message = str(error)
    assert "s2" in message
    assert command in message
    assert "prerequisites" in message
