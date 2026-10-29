"""Independent miter fixtures bound error beyond chord sampling alone."""

import math

import pytest
from mp_models.corridor import CorridorRequest
from mp_verify.corridor import analyze_corridor


def request(turn=1e-6, taper=False, error=1e-10):
    return CorridorRequest.model_validate(
        {
            "id": "precision-ribbon",
            "centerline": {
                "title": "Analytic near-tangent lines",
                "calculation_id": "centerline",
                "foot_definition": "international_ft",
                "calls": [
                    {
                        "id": identifier,
                        "source_reference": "Supplied analytical fixture",
                        "call": {
                            "course": i,
                            "direction_text": "Analytic line",
                            "distance_ft": 100.0,
                            "bearing_azimuth_deg_from_north": bearing,
                        },
                    }
                    for i, (identifier, bearing) in enumerate(
                        (("first", 90.0), ("second", 90.0 - turn)), 1
                    )
                ],
            },
            "widths": [
                {
                    "id": "widths",
                    "start": {"call_id": "first", "fraction": 0},
                    "end": {"call_id": "second", "fraction": 1},
                    "left_start": 10.0,
                    "left_end": 12.0 if taper else 10.0,
                    "right_start": 10.0,
                    "right_end": 12.0 if taper else 10.0,
                    "rule": "linear_taper" if taper else "step",
                    "source_refs": [
                        {"source_id": "fixture", "quote": "Explicit analytical widths"}
                    ],
                }
            ],
            "width_unit": "international_ft",
            "join": "miter",
            "cap": "butt",
            "construction_source_refs": [{"source_id": "fixture", "quote": "Explicit miter join"}],
            "error_budget": {"max_error": error, "unit": "international_ft", "max_segments": 2048},
        }
    )


@pytest.mark.parametrize("turn", [1e-5, 1e-6, 1e-7])
def test_near_parallel_constant_width_miter_respects_certified_error(turn):
    result = analyze_corridor(request(turn))
    assert result.availability == "supported", result.limitations
    displacement = 10 * math.tan(math.radians(turn) / 2)
    expected = ((100 - displacement, 10.0), (100 + displacement, -10.0))
    for point in expected:
        actual_error = min(math.dist(vertex, point) for vertex in result.polygon)
        assert actual_error <= result.error.total_bound
        assert actual_error <= result.request.error_budget.max_error


def test_ill_conditioned_taper_join_cannot_claim_an_uncertified_tight_budget():
    result = analyze_corridor(request(taper=True))
    assert result.availability == "unsupported"
    assert "conditioning" in result.limitations[-1]
    assert result.polygon is None and result.error is None
