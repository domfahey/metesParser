"""Copied Python models must satisfy the same PLSS evidence schema as JSON inputs."""

import pytest
from mp_models.plss import PLSSDerivationRequest
from mp_verify.plss import derive_plss


def request():
    key = {
        "principal_meridian": "Supplied test meridian",
        "township": 1,
        "township_direction": "N",
        "range": 1,
        "range_direction": "E",
        "section": 1,
    }
    return PLSSDerivationRequest.model_validate(
        {
            "dataset": {
                "id": "data",
                "version": "v1",
                "authority_citation": "Supplied synthetic corner coordinates",
                "scene": {
                    "id": "grid",
                    "name": "Explicit grid",
                    "kind": "projected",
                    "crs": "EPSG:3857",
                    "units": "m",
                    "basis": "grid",
                },
                "source": {
                    "id": "survey",
                    "label": "Supplied survey",
                    "sha256": "a" * 64,
                    "native_crs": "EPSG:3857",
                    "native_units": "m",
                },
                "references": [
                    {
                        "id": "section",
                        "section": key,
                        "subdivision_class": "rectangular",
                        "corners": [
                            {"name": name, "xy": point, "source_id": "survey"}
                            for name, point in (
                                ("SW", (0.0, 0.0)),
                                ("SE", (80.0, 0.0)),
                                ("NE", (80.0, 40.0)),
                                ("NW", (0.0, 40.0)),
                            )
                        ],
                    }
                ],
            },
            "selected_dataset_id": "data",
            "selected_reference_id": "section",
            "section": key,
            "rule": "rectangular_aliquot_v1",
            "aliquot_steps": ["N2"],
        }
    )


def test_copied_duplicate_section_model_cannot_bypass_reference_identity_gate():
    original = request()
    selected = original.dataset.references[0]
    duplicate = selected.model_copy(update={"id": "same-section-different-reference"})
    changed = original.model_copy(
        update={
            "dataset": original.dataset.model_copy(update={"references": (selected, duplicate)})
        }
    )
    with pytest.raises(ValueError, match="duplicate or ambiguous section"):
        derive_plss(changed)


def test_copied_invalid_derivation_rule_is_a_schema_error():
    changed = request().model_copy(update={"rule": "unpublished-legal-survey-rule"})
    with pytest.raises(ValueError):
        derive_plss(changed)


def test_valid_copied_metadata_still_recomputes_and_changes_identity():
    original = request()
    changed = original.model_copy(
        update={"dataset": original.dataset.model_copy(update={"version": "v2"})}
    )
    first, second = derive_plss(original), derive_plss(changed)
    assert first.availability == second.availability == "computed"
    assert first.ring == second.ring
    assert first.input_hash != second.input_hash
