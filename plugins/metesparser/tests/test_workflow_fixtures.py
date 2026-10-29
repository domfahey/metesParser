"""Check numerical evidence in the guided workflow fixture, not skill wording."""

import json
from pathlib import Path

import pytest
from mp_models.plot import PlotScene
from mp_models.raster import RasterControl
from mp_review.raster_registration import fit_affine

FIXTURES = Path(__file__).parents[1] / "evals" / "fixtures"


def test_guided_controls_keep_checkpoint_independent():
    data = json.loads((FIXTURES / "guided-controls.json").read_text())
    scene = PlotScene.model_validate(data["scene"])
    registration = fit_affine(tuple(RasterControl.model_validate(c) for c in data["controls"]))

    assert scene.units == "m"
    assert registration.matrix == pytest.approx((2, 0, 100, 0, -2, 200))
    assert registration.fit_rms == pytest.approx(0, abs=1e-12)
    assert registration.checkpoint_rms == pytest.approx(5)
    assert registration.status == "approximate"
    assert len([r for r in registration.residuals if r.role == "checkpoint"]) == 1
