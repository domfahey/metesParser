"""Backfill must not invent distances for ground-truth calls missing distance_ft."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backfill_run_registry.py"

CALL_WITHOUT_DISTANCE = {
    "course": 1,
    "direction_text": "N 10° E",
    "bearing_azimuth_deg_from_north": 10.0,
}
CALL_WITH_DISTANCE = {
    "course": 1,
    "direction_text": "N 10° E",
    "bearing_azimuth_deg_from_north": 10.0,
    "distance_ft": 100.0,
}


@pytest.fixture
def backfill_mod() -> ModuleType:
    spec = importlib.util.spec_from_file_location("backfill_run_registry", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_calls_does_not_fabricate_zero_distance(backfill_mod: ModuleType) -> None:
    with pytest.raises(ValueError):
        backfill_mod._build_calls([CALL_WITHOUT_DISTANCE])


def test_build_calls_keeps_stated_distance(backfill_mod: ModuleType) -> None:
    (call,) = backfill_mod._build_calls([CALL_WITH_DISTANCE])
    assert call.distance_ft == 100.0


def test_backfill_skips_deed_missing_distance(
    backfill_mod: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    deeds = tmp_path / "sample_deeds"
    deeds.mkdir()
    (deeds / "bad.ground_truth.json").write_text(
        json.dumps({"expected_calls": [CALL_WITHOUT_DISTANCE]})
    )
    (deeds / "good.ground_truth.json").write_text(
        json.dumps({"expected_calls": [CALL_WITH_DISTANCE]})
    )
    monkeypatch.setattr(backfill_mod, "SAMPLE_DEEDS_DIR", deeds)
    runs = tmp_path / "runs"

    written = backfill_mod.backfill(runs)

    out = capsys.readouterr().out
    assert written == 1
    assert "NOT BACKFILLABLE: bad.pdf" in out
    assert "WROTE:" in out
    manifests = sorted(p.name for p in runs.glob("*.json"))
    assert len(manifests) == 1
    assert "bad" not in manifests[0]
