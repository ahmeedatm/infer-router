"""Loader for the intent set (``data/intents_spike.yaml``).

Reads a YAML file rooted on an ``intents:`` key, validates every entry
against the frozen :class:`~app.llm.schema.Intent` model, and returns an
immutable tuple. Any failure (missing file, invalid YAML, malformed
intent) is surfaced through :class:`IntentLoadError` — never a silent
fallback, per project coding-style rules.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import ValidationError

from app import config
from app.llm.schema import Intent


class IntentLoadError(RuntimeError):
    """Raised when intents cannot be loaded or validated."""


def _read_yaml(path: Path) -> Any:
    """Read and parse a YAML file, mapping low-level failures to IntentLoadError."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise IntentLoadError(f"Intent file not found: {path}") from exc
    except OSError as exc:
        raise IntentLoadError(f"Cannot read intent file {path}: {exc}") from exc

    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise IntentLoadError(f"Invalid YAML in {path}: {exc}") from exc


def _extract_entries(document: Any, path: Path) -> list:
    """Pull the ``intents`` list out of the parsed document, validating shape."""
    if not isinstance(document, dict) or "intents" not in document:
        raise IntentLoadError(
            f"Missing root 'intents' key in {path}."
        )
    entries = document["intents"]
    if not isinstance(entries, list):
        raise IntentLoadError(
            f"Root 'intents' in {path} must be a list, got {type(entries).__name__}."
        )
    return entries


def _build_intent(entry: Any, index: int) -> Intent:
    """Validate one raw entry into an Intent, with a precise error message."""
    if not isinstance(entry, dict):
        raise IntentLoadError(
            f"Intent at position {index} is not a mapping: {entry!r}."
        )
    try:
        return Intent(**entry)
    except ValidationError as exc:
        label = entry.get("id", f"position {index}")
        raise IntentLoadError(f"Invalid intent '{label}': {exc}") from exc


def load_intents(path: Optional[str] = None) -> tuple[Intent, ...]:
    """Load and validate the intents from a YAML file.

    Args:
        path: Path to the YAML file. Defaults to ``config.INTENTS_SPIKE_PATH``.

    Returns:
        An immutable tuple of validated :class:`Intent` objects.

    Raises:
        IntentLoadError: file missing, YAML invalid, or any intent malformed.
    """
    resolved = Path(path if path is not None else config.INTENTS_SPIKE_PATH)
    document = _read_yaml(resolved)
    entries = _extract_entries(document, resolved)
    return tuple(_build_intent(entry, i) for i, entry in enumerate(entries))
