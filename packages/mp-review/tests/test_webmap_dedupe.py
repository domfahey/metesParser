"""One shared projection factory and one closure-gap rule across build, replay and renderer."""

import importlib.util
from pathlib import Path

import pytest
from mp_models.plot import PlotScene
from mp_review.delivery import load_delivery, publish_delivery

pytest.importorskip("pyproj")

_TESTS = Path(__file__).parent


def _placed_case(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "_dedupe_store", _TESTS / "test_delivery_store.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._placed_case(tmp_path)


def test_build_and_recorded_replay_share_projection_factory(tmp_path, monkeypatch):
    import mp_review.webmap_projection as module

    assert hasattr(module, "projection_from_pipeline")
    real = module.projection_from_pipeline
    calls = []

    def spy(*args, **kwargs):
        calls.append(kwargs.get("pipeline"))
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "projection_from_pipeline", spy)
    module.build_web_map_projection(
        PlotScene(id="g", name="G", kind="projected", crs="EPSG:3857", units="m", basis="grid")
    )
    assert len(calls) == 1
    bundle, revision, request = _placed_case(tmp_path)
    publish_delivery(bundle, revision, request, tmp_path / "out")
    calls.clear()
    load_delivery(bundle, revision, tmp_path / "out" / request.id)
    assert calls and all(isinstance(c, str) and c for c in calls)


def test_closure_gap_rule_is_shared():
    import mp_review.webmap as renderer
    import mp_verify.webmap as verifier

    assert renderer.CLOSURE_GAP_THRESHOLD is verifier.CLOSURE_GAP_THRESHOLD
    assert verifier.CLOSURE_GAP_THRESHOLD == 1e-8
    assert renderer.has_closure_gap((0.0, 0.0), (1e-7, 0.0))
    assert not renderer.has_closure_gap((0.0, 0.0), (1e-9, 0.0))
