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
    for update, expected_match in (
        ({"coordinate_mode": "placed"}, "Placed delivery requires explicit scene identity"),
        ({"formats": ["svg", "svg"]}, "Duplicate delivery format"),
        ({"layers": request["layers"] * 2}, "Duplicate delivery layer identity"),
        ({"revision_generation": True}, "valid integer"),
    ):
        with pytest.raises(ValueError, match=expected_match):
            DeliveryRequest.model_validate(request | update)


def test_delivery_layer_source_binding_and_request_selection_invariants():
    from mp_models.delivery import DeliveryLayer, DeliverySourceBinding

    # DeliveryLayer requires placement_id and placement_sha256 together.
    with pytest.raises(ValueError, match="both identity and hash"):
        DeliveryLayer(
            id="l1", kind="calculation", visible=True, opacity=1.0, required=True, placement_id="p1"
        )

    # DeliverySourceBinding requires XOR of artifact_dir and revision_corridor_id; revision_corridor_id only for corridor.
    base_bind = {
        "id": "b1",
        "kind": "plss_reference",
        "layer_id": "l1",
        "manifest_sha256": "a" * 64,
        "input_sha256": "b" * 64,
        "geometry_sha256": "c" * 64,
    }
    with pytest.raises(ValueError, match="exactly one artifact or revision corridor"):
        DeliverySourceBinding(**base_bind)
    with pytest.raises(ValueError, match="Only corridor sources"):
        DeliverySourceBinding(**base_bind, revision_corridor_id="rc1")
    valid_bind = DeliverySourceBinding(**base_bind, artifact_dir="plss-out")
    assert valid_bind.artifact_dir == "plss-out"

    req = {
        "id": "x",
        "baseline": {"id": "b", "bundle_sha256": "0" * 64},
        "revision_id": "r",
        "revision_generation": 0,
        "geometry": "scenario",
        "coordinate_mode": "local",
        "units": "unknown_ft",
        "formats": ["svg"],
        "layers": [
            {"id": "c", "kind": "calculation", "visible": True, "opacity": 1.0, "required": True}
        ],
    }
    # Local delivery cannot apply placement transforms.
    with pytest.raises(ValueError, match="Local delivery cannot apply placement"):
        DeliveryRequest.model_validate(
            req
            | {
                "layers": [
                    {
                        "id": "c",
                        "kind": "calculation",
                        "visible": True,
                        "opacity": 1.0,
                        "required": True,
                        "placement_id": "p1",
                        "placement_sha256": "a" * 64,
                    }
                ]
            }
        )
    # Duplicate scenes and duplicate source bindings rejected.
    scene = {"id": "s1", "name": "S", "kind": "local", "units": "unknown_ft"}
    with pytest.raises(ValueError, match="Duplicate supplied scene"):
        DeliveryRequest.model_validate(req | {"scenes": [scene, scene]})
    cor_layer = {"id": "l1", "kind": "corridor", "visible": True, "opacity": 1.0, "required": True}
    cor_bind = base_bind | {"kind": "corridor", "artifact_dir": "cor-out"}
    with pytest.raises(ValueError, match="Duplicate derived source binding"):
        DeliveryRequest.model_validate(
            req | {"layers": [cor_layer], "source_bindings": [cor_bind, cor_bind]}
        )
    # Derived layer without matching binding, ordinary layer with binding, and dangling binding.
    with pytest.raises(ValueError, match="exactly one matching source binding"):
        DeliveryRequest.model_validate(req | {"layers": [cor_layer]})
    with pytest.raises(ValueError, match="Ordinary layer cannot substitute"):
        DeliveryRequest.model_validate(req | {"source_bindings": [cor_bind | {"layer_id": "c"}]})
    with pytest.raises(ValueError, match="unselected layer"):
        DeliveryRequest.model_validate(
            req | {"source_bindings": [cor_bind | {"layer_id": "unselected"}]}
        )
