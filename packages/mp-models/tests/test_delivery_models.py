"""Export selections freeze membership, transforms and appearance explicitly."""

import pytest
from mp_models.delivery import DeliveryRequest


def test_delivery_requires_explicit_complete_snapshot_selection():
    request = {
        "id": "x",
        "baseline": {"id": "b", "bundle_sha256": "0" * 64},
        "revision_id": "r",
        "revision_generation": 0,
        "geometry": "scenario",
        "coordinate_mode": "local",
        "units": "unknown_ft",
        "formats": ["svg"],
        "layers": [
            {"id": "c", "kind": "calculation", "visible": False, "opacity": 0, "required": True}
        ],
    }
    parsed = DeliveryRequest.model_validate(request)
    assert parsed.layers[0].visible is False and parsed.layers[0].opacity == 0
    for update in (
        {"coordinate_mode": "placed"},
        {"formats": ["svg", "svg"]},
        {"layers": request["layers"] * 2},
        {"revision_generation": True},
    ):
        with pytest.raises(ValueError):
            DeliveryRequest.model_validate(request | update)
