"""Did the switch accept the command the bench just issued?

Mininet's ``Node.cmd`` returns stdout and stderr combined and no exit status,
so a rejected ``ovs-ofctl`` / ``ovs-vsctl`` invocation looks exactly like a
successful one unless the output is read. Both tools are silent on success and
print a recognisable line on failure, which is what this module keys on.

Why it matters for the results: a rejected command means the rule was never
installed, so the check that would have observed it fails and the model is
charged for a bench problem. A model failure must be measured; a bench
malfunction must propagate.

Deliberately free of any Mininet import, so the detection rule is testable
outside the Lima VM. ``bench.topology`` is its only consumer.
"""
from __future__ import annotations

from typing import Optional

#: Substrings that only ever appear in a rejection. ``ovs-ofctl`` and
#: ``ovs-vsctl`` prefix their diagnostics with the program name; the rest cover
#: the argument- and prerequisite-level messages they emit without it.
ERROR_MARKERS: tuple[str, ...] = (
    "ovs-ofctl: ",
    "ovs-vsctl: ",
    "Error",
    "error:",
    "usage:",
    "unknown",
    "Invalid",
    "missing prerequisites",
)


class ApplyError(RuntimeError):
    """Raised when a switch rejected a command the bench issued.

    Attributes:
        switch: Name of the switch the command ran on.
        command: The command as expanded and executed, markers substituted.
        output: Everything the switch printed, kept verbatim for diagnosis.
    """

    def __init__(self, switch: str, command: str, output: str) -> None:
        self.switch = switch
        self.command = command
        self.output = output
        super().__init__(
            f"{switch} rejected the command: {command}\n{output.strip()}"
        )


def failure_marker(output: str) -> Optional[str]:
    """Return the first rejection marker found in ``output``, else ``None``."""
    for marker in ERROR_MARKERS:
        if marker in output:
            return marker
    return None


def raise_if_failed(switch: str, command: str, output: str) -> None:
    """Raise :class:`ApplyError` if ``output`` reports a rejection."""
    if failure_marker(output) is not None:
        raise ApplyError(switch, command, output)
