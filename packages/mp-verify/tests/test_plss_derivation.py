"""Independent rectangular reference fixtures; no nominal section dimensions."""

import copy
import math

import pytest
from mp_models.plss import PLSSDerivationRequest
from mp_verify.plss import derive_plss


def request_data():
    return {
        "schema_version": "1.0",
        "dataset": {
            "id": "survey-data",
            "version": "2026-01",
            "authority_citation": "Synthetic supplied corner survey, sheet 1",
            "scene": {
                "id": "grid",
                "name": "Supplied grid",
                "kind": "projected",
                "crs": "EPSG:3857",
                "units": "m",
                "basis": "grid",
            },
            "source": {
                "id": "survey-sheet",
                "label": "Synthetic survey",
                "sha256": "a" * 64,
                "source_date": "2026-01-02",
                "native_crs": "EPSG:3857",
                "native_units": "m",
                "feature_ids": ["section-one"],
            },
            "references": [
                {
                    "id": "section-one",
                    "section": {
                        "principal_meridian": "Synthetic Meridian",
                        "township": 2,
                        "township_direction": "N",
                        "range": 3,
                        "range_direction": "W",
                        "section": 1,
                    },
                    "subdivision_class": "rectangular",
                    "corners": [
                        {"name": name, "xy": xy, "source_id": "survey-sheet"}
                        for name, xy in [
                            ("SW", [10, 20]),
                            ("SE", [210, 20]),
                            ("NE", [210, 120]),
                            ("NW", [10, 120]),
                        ]
                    ],
                }
            ],
        },
        "selected_dataset_id": "survey-data",
        "selected_reference_id": "section-one",
        "section": {
            "principal_meridian": "Synthetic Meridian",
            "township": 2,
            "township_direction": "N",
            "range": 3,
            "range_direction": "W",
            "section": 1,
        },
        "rule": "rectangular_aliquot_v1",
        "aliquot_steps": ["SE4", "NW4"],
        "purpose": "computed_reference_geometry",
    }


def test_outer_then_inner_fraction_and_area():
    result = derive_plss(PLSSDerivationRequest.model_validate(request_data()))
    # SE quarter is x=110..210,y=20..70; its NW quarter is x=110..160,y=45..70.
    assert result.ring == ((110, 45), (160, 45), (160, 70), (110, 70), (110, 45))
    assert result.area_scene_units_squared == pytest.approx(1250)
    assert result.status == "needs_review"
    assert result.verified_export_eligible is False
    assert result.boundary_established is False
    assert result.vector_layers[0].coordinates == (result.ring,)


def test_rotated_rectangle_uses_supplied_axes_and_changes_hash():
    data = request_data()
    original = derive_plss(PLSSDerivationRequest.model_validate(data))
    theta = math.radians(30)
    for corner in data["dataset"]["references"][0]["corners"]:
        x, y = corner["xy"]
        corner["xy"] = [
            1000 + x * math.cos(theta) - y * math.sin(theta),
            2000 + x * math.sin(theta) + y * math.cos(theta),
        ]
    rotated = derive_plss(PLSSDerivationRequest.model_validate(data))
    assert rotated.area_scene_units_squared == pytest.approx(1250)
    x, y = original.ring[0]
    assert rotated.ring[0] == pytest.approx(
        (
            1000 + x * math.cos(theta) - y * math.sin(theta),
            2000 + x * math.sin(theta) + y * math.cos(theta),
        )
    )
    assert rotated.input_hash != original.input_hash


def test_repeat_labels_different_meridians_require_exact_reference():
    data = request_data()
    other = copy.deepcopy(data["dataset"]["references"][0])
    other["id"] = "section-other"
    other["section"]["principal_meridian"] = "Other Meridian"
    data["dataset"]["references"].append(other)
    derive_plss(PLSSDerivationRequest.model_validate(data))
    data["section"]["principal_meridian"] = "Other Meridian"
    result = derive_plss(PLSSDerivationRequest.model_validate(data))
    assert result.availability == "unsupported"
    assert "section identity" in result.reason


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "source",
        "irregular",
        "excess",
        "lot",
        "skew",
        "order",
        "crs",
        "units",
        "rule",
        "selection",
    ],
)
def test_refuses_unsupported_or_conflicting_reference(change):
    data = request_data()
    ref = data["dataset"]["references"][0]
    if change == "missing":
        ref["corners"].pop()
    elif change == "duplicate":
        data["dataset"]["references"].append(copy.deepcopy(ref))
    elif change == "source":
        ref["corners"][0]["source_id"] = "other-source"
    elif change in ("irregular", "excess", "lot"):
        ref["subdivision_class"] = {
            "irregular": "irregular",
            "excess": "excess_deficiency",
            "lot": "government_lot",
        }[change]
    elif change == "skew":
        ref["corners"][2]["xy"][0] += 10
    elif change == "order":
        ref["corners"][1]["xy"], ref["corners"][3]["xy"] = (
            ref["corners"][3]["xy"],
            ref["corners"][1]["xy"],
        )
    elif change == "crs":
        data["dataset"]["scene"]["crs"] = "EPSG:4326"
    elif change == "units":
        data["dataset"]["scene"]["units"] = "unknown_ft"
    elif change == "rule":
        data["rule"] = "legal-midpoint-survey"
    elif change == "selection":
        data["selected_dataset_id"] = "another-dataset"
    if change in ("duplicate", "units", "rule"):
        with pytest.raises(ValueError):
            PLSSDerivationRequest.model_validate(data)
    else:
        result = derive_plss(PLSSDerivationRequest.model_validate(data))
        assert result.availability == "unsupported"
        assert result.ring is None
        assert not result.vector_layers
        assert result.reason


def test_changed_provenance_changes_identity_even_with_same_coordinates():
    data = request_data()
    original = derive_plss(PLSSDerivationRequest.model_validate(data))
    data["dataset"]["version"] = "new-reading"
    changed = derive_plss(PLSSDerivationRequest.model_validate(data))
    assert original.ring == changed.ring
    assert original.input_hash != changed.input_hash
    assert original.dataset_hash != changed.dataset_hash
    assert original.vector_layers[0].id != changed.vector_layers[0].id


def test_conflicting_provenance_and_insufficient_precision_are_unsupported():
    data = request_data()
    data["dataset"]["source"]["native_units"] = "international_ft"
    assert derive_plss(PLSSDerivationRequest.model_validate(data)).availability == "unsupported"
    data = request_data()
    for corner in data["dataset"]["references"][0]["corners"]:
        corner["xy"] = [x + 1e15 for x in corner["xy"]]
    assert derive_plss(PLSSDerivationRequest.model_validate(data)).availability == "unsupported"
