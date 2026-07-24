"""Thin ONOS REST client for the bench (intents, ACL rules, flows)."""
from __future__ import annotations

import time
from typing import Callable, Optional

import httpx

from bench.translator import OnosCommand


class OnosError(RuntimeError):
    """Raised on a non-2xx ONOS REST response."""


class OnosClient:
    def __init__(
        self,
        base_url: str,
        user: str = "karaf",
        password: str = "karaf",
        client: Optional[httpx.Client] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(
            base_url=self._base_url, auth=(user, password), timeout=30.0
        )

    def execute(self, cmd: OnosCommand) -> str:
        resp = self._client.post(cmd.path, json=cmd.payload)
        if resp.status_code >= 400:
            raise OnosError(f"{cmd.path} -> {resp.status_code}: {resp.text[:200]}")
        return resp.headers.get("Location", "")

    def get_flows(self) -> list[dict]:
        resp = self._client.get("/onos/v1/flows")
        if resp.status_code >= 400:
            raise OnosError(f"get_flows -> {resp.status_code}: {resp.text[:200]}")
        return resp.json().get("flows", [])

    def wait_flows_installed(
        self,
        min_count: int,
        timeout_s: float = 10.0,
        poll_s: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> bool:
        deadline = timeout_s
        elapsed = 0.0
        while elapsed <= deadline:
            if len(self.get_flows()) >= min_count:
                return True
            sleep(poll_s)
            elapsed += poll_s if poll_s > 0 else deadline + 1
        return len(self.get_flows()) >= min_count
