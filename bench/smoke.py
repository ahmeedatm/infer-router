# bench/smoke.py
"""Pre-run sanity check (inside the VM): does the base network actually work?

Secure mode means the bench installs forwarding itself, so a mistake there
breaks every case silently. Run this before any full bench run.
"""
from __future__ import annotations

from bench.topology import MininetRunner, build_topology
from bench.verifier import parse_ping_loss

_PAIRS = (("h1", "h3"), ("h2", "h4"), ("h1", "h2"), ("h3", "h4"))


def main() -> int:
    net = build_topology("diamond4")
    runner = MininetRunner(net)
    failures = []
    try:
        for src, dst in _PAIRS:
            loss = parse_ping_loss(runner.ping(src, dst))
            print(f"{src} -> {dst}: {loss:.0f} % loss")
            if loss >= 100.0:
                failures.append(f"{src}->{dst}")
    finally:
        runner.stop()
    if failures:
        print(f"SMOKE FAILED: no connectivity for {', '.join(failures)}")
        return 1
    print("SMOKE OK: base forwarding works on diamond4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
