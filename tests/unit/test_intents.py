"""Unit tests for app.llm.intents — the spike intent loader."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.llm.intents import IntentLoadError, load_intents
from app.llm.schema import Intent


def _write(tmp_path: Path, content: str) -> str:
    path = tmp_path / "intents.yaml"
    path.write_text(content, encoding="utf-8")
    return str(path)


class TestLoadRealFile:
    def test_loads_twenty_valid_intents(self):
        intents = load_intents()  # uses config.INTENTS_SPIKE_PATH

        assert isinstance(intents, tuple)
        assert len(intents) == 20
        assert all(isinstance(i, Intent) for i in intents)

    def test_returns_immutable_tuple(self):
        intents = load_intents()
        with pytest.raises(TypeError):
            intents[0] = None  # type: ignore[index]

    def test_covers_varied_domains(self):
        intents = load_intents()
        domains = {i.domain for i in intents}
        assert domains == {"ran", "core", "security", "slice"}

    def test_covers_all_three_complexity_levels(self):
        intents = load_intents()
        levels = {i.expected_complexity for i in intents}
        assert levels == {"simple", "medium", "complex"}


class TestLoadErrors:
    def test_missing_file_raises(self, tmp_path: Path):
        absent = str(tmp_path / "does-not-exist.yaml")
        with pytest.raises(IntentLoadError) as exc:
            load_intents(absent)
        assert "does-not-exist.yaml" in str(exc.value)

    def test_malformed_yaml_raises(self, tmp_path: Path):
        path = _write(tmp_path, "intents: [this is : : broken yaml\n")
        with pytest.raises(IntentLoadError):
            load_intents(path)

    def test_missing_root_key_raises(self, tmp_path: Path):
        path = _write(tmp_path, "not_intents:\n  - id: x\n")
        with pytest.raises(IntentLoadError) as exc:
            load_intents(path)
        assert "intents" in str(exc.value).lower()

    def test_unknown_domain_raises(self, tmp_path: Path):
        path = _write(
            tmp_path,
            "intents:\n"
            "  - id: bad-domain\n"
            '    text: "Some intent"\n'
            "    domain: teleport\n"
            "    expected_complexity: simple\n"
            "    criticality: low\n"
            "    slice_type: null\n",
        )
        with pytest.raises(IntentLoadError) as exc:
            load_intents(path)
        assert "bad-domain" in str(exc.value)

    def test_intents_not_a_list_raises(self, tmp_path: Path):
        path = _write(tmp_path, "intents:\n  id: scalar\n")
        with pytest.raises(IntentLoadError):
            load_intents(path)
