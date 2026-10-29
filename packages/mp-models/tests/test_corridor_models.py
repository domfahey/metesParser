"""Explicit corridor construction and provenance/schema guardrails."""

import copy

import pytest
from mp_models.corridor import CorridorErrorReport, CorridorRequest


def payload():
    return {
        "id": "strip",
        "centerline": {
            "title": "recorded centerline",
            "foot_definition": "international_ft",
            "calls": [
                {
                    "id": "road",
                    "source_reference": "deed page 3",
                    "call": {
                        "course": 1,
                        "direction_text": "East",
                        "distance_ft": 100,
                        "bearing_azimuth_deg_from_north": 90,
                    },
                }
            ],
        },
        "widths": [
            {
                "id": "width",
                "start": {"call_id": "road", "fraction": 0},
                "end": {"call_id": "road", "fraction": 1},
                "left_start": 20,
                "left_end": 20,
                "right_start": 10,
                "right_end": 10,
                "rule": "step",
                "source_refs": [{"source_id": "deed", "quote": "  original width clause  "}],
            }
        ],
        "width_unit": "international_ft",
        "join": "bevel",
        "cap": "butt",
        "construction_source_refs": [
            {"source_id": "review", "quote": "explicit construction instructions"}
        ],
        "error_budget": {"max_error": 0.01, "unit": "international_ft"},
    }


def test_full_width_endpoint_definition_and_provenance_are_lossless():
    original = CorridorRequest.model_validate(payload())
    restored = CorridorRequest.model_validate_json(original.model_dump_json())
    assert restored == original
    assert restored.widths[0].source_refs[0].quote == "  original width clause  "
    assert restored.side_reference == "forward_centerline"


@pytest.mark.parametrize(
    "field", ["join", "cap", "construction_source_refs", "error_budget", "width_unit"]
)
def test_construction_choices_and_unit_evidence_are_explicit(field):
    data = payload()
    del data[field]
    with pytest.raises(ValueError):
        CorridorRequest.model_validate(data)


@pytest.mark.parametrize(
    "change",
    [
        {"left_start": -1},
        {"left_end": 21},
        {"source_refs": []},
        {"start": {"call_id": "unknown", "fraction": 0}},
        {"end": {"call_id": "road", "fraction": 2}},
        {"rule": "preferred_overlap"},
        {"left_start": 0, "right_start": 0},
    ],
)
def test_width_schema_rejects_implicit_or_invalid_geometry(change):
    data = payload()
    data["widths"][0].update(change)
    with pytest.raises(ValueError):
        CorridorRequest.model_validate(data)


def test_interval_identity_is_unique_but_order_and_coverage_are_engine_evidence():
    data = payload()
    data["widths"].append(copy.deepcopy(data["widths"][0]))
    with pytest.raises(ValueError, match="unique"):
        CorridorRequest.model_validate(data)
    data["widths"][1]["id"] = "another-width"
    assert len(CorridorRequest.model_validate(data).widths) == 2


@pytest.mark.parametrize(
    "change",
    [{"max_error": 0}, {"max_error": float("inf")}, {"unit": "unknown_ft"}, {"max_segments": True}],
)
def test_error_budget_requires_finite_known_linear_precision_and_bounded_work(change):
    data = payload()
    data["error_budget"].update(change)
    with pytest.raises(ValueError):
        CorridorRequest.model_validate(data)


def test_computed_error_report_cannot_exceed_or_omit_error_allocations():
    report = {
        "unit": "international_ft",
        "linearization_bound": 0.005,
        "floating_point_bound": 0.001,
        "total_bound": 0.006,
        "requested_max_error": 0.01,
        "boundary_segments": 12,
    }
    assert CorridorErrorReport.model_validate(report).total_bound == 0.006
    for update in ({"total_bound": 0.004}, {"requested_max_error": 0.005}):
        with pytest.raises(ValueError):
            CorridorErrorReport.model_validate(report | update)
