"""Synthetic behavioral regression cases for explicit advisory comparisons."""

import copy
import math

import pytest
from mp_models.comparison import ComparisonRequest
from mp_verify.comparison import compare_descriptions


def record(id, distance=100, bearing=90, **fields):
    return {
        "id": id,
        "quote": f"  original {id}  ",
        "occurrence_id": "occ-" + id,
        "source_reference": "synthetic deed " + id,
        "call": {
            "course": 1,
            "direction_text": "verbatim direction",
            "distance_ft": distance,
            "bearing_azimuth_deg_from_north": bearing,
            **fields,
        },
    }


def request(left=None, right=None, basis="grid"):
    left = left or [record("a")]
    right = right or [record("b")]
    return {
        "left": {
            "id": "old",
            "plot": {
                "title": "old",
                "calculation_id": "old",
                "foot_definition": "international_ft",
                "calls": left,
            },
            "bearing_basis": {
                "label": "same label",
                "identity": basis,
                "source_references": ["survey"],
            },
        },
        "right": {
            "id": "new",
            "plot": {
                "title": "new",
                "calculation_id": "new",
                "foot_definition": "international_ft",
                "calls": right,
            },
            "bearing_basis": {
                "label": "same label",
                "identity": basis,
                "source_references": ["survey"],
            },
        },
        "pairs": [
            {
                "id": "pair",
                "left": {"call_ids": [x["id"] for x in left], "direction": "forward"},
                "right": {"call_ids": [x["id"] for x in right], "direction": "forward"},
            }
        ],
        "tolerances": {
            "length": 0.1,
            "displacement": 0.1,
            "position": 0.1,
            "linear_unit": "international_ft",
            "bearing_deg": 0.01,
            "source_references": ["review criteria"],
        },
    }


def run(data):
    return compare_descriptions(ComparisonRequest.model_validate(data))


def test_identical_length_and_vector_without_position_and_no_mutation():
    data = request()
    before = copy.deepcopy(data)
    result = run(data)
    pair = result.pairs[0]
    assert pair.length.outcome == pair.bearing.outcome == pair.displacement.outcome == "agree"
    assert pair.position.outcome == "unavailable"
    assert pair.position.reason
    assert data == before
    assert not result.boundary_established and not result.verified_export_eligible
    assert pair.left_sources[0].quote == "  original a  "


def test_explicit_reversal_and_wrap():
    data = request(right=[record("b", bearing=270)])
    data["pairs"][0]["right"]["direction"] = "reverse"
    assert run(data).pairs[0].displacement.outcome == "agree"
    data = request([record("a", bearing=359.999)], [record("b", bearing=0.001)])
    assert run(data).pairs[0].bearing.difference == pytest.approx(0.002)


def test_discrepancy_and_inclusive_tolerance():
    data = request(right=[record("b", distance=100.45)])
    assert run(data).pairs[0].length.difference == pytest.approx(0.45)
    assert run(data).pairs[0].length.outcome == "differ"
    data["tolerances"]["length"] = 0.45
    assert run(data).pairs[0].length.outcome == "agree"


def test_unknown_basis_preserves_changed_monument_and_unavailable_position():
    data = request(
        [record("a", to="original iron pipe")], [record("b", to="replacement iron pin")], basis=None
    )
    result = run(data)
    assert result.pairs[0].displacement.outcome == "not_comparable"
    assert result.pairs[0].position.outcome == "unavailable"
    changed = [d for d in result.structural if d.kind == "changed"]
    assert changed[0].left_sources[0].call.to == "original iron pipe"
    assert changed[0].right_sources[0].call.to == "replacement iron pin"
    assert "to" in changed[0].changed_fields


def test_foot_definitions_explicit_conversion_and_unknown_failure():
    data = request()
    data["right"]["plot"]["foot_definition"] = "us_survey_ft"
    pair = run(data).pairs[0]
    assert pair.length.difference == pytest.approx(100 * (1200 / 3937 / 0.3048 - 1))
    data["right"]["plot"]["foot_definition"] = "unknown_ft"
    assert run(data).pairs[0].length.outcome == "not_comparable"
    assert run(data).pairs[0].displacement.outcome == "not_comparable"


def test_explicit_sourced_rotation_no_autoalignment():
    data = request(right=[record("b", bearing=0)])
    assert run(data).pairs[0].bearing.outcome == "differ"
    data["right"]["bearing_basis"]["identity"] = "other grid"
    assert run(data).pairs[0].bearing.outcome == "not_comparable"
    data["right_to_left_transform"] = {
        "rotation_deg": 90,
        "source_references": ["recorded rotation"],
    }
    assert run(data).pairs[0].displacement.outcome == "agree"


def test_split_and_reversed_split_and_aggregate_length():
    data = request(right=[record("b", 40), record("c", 60)])
    assert run(data).pairs[0].displacement.outcome == "agree"
    assert any(d.kind == "split_candidate" for d in run(data).structural)
    data = request(right=[record("b", 60, 270), record("c", 40, 270)])
    data["pairs"][0]["right"].update(call_ids=["c", "b"], direction="reverse")
    assert run(data).pairs[0].displacement.outcome == "agree"
    data["right"]["plot"]["calls"][0]["call"]["distance_ft"] = 61
    assert run(data).pairs[0].length.outcome == "differ"


@pytest.mark.parametrize("reverse", [False, True])
def test_many_to_one_merge_preserves_explicit_direction_and_every_source(reverse):
    left = (
        [record("a", 60, 270), record("b", 40, 270)]
        if reverse
        else [record("a", 40), record("b", 60)]
    )
    data = request(left=left, right=[record("c", 100)])
    if reverse:
        data["pairs"][0]["left"].update(call_ids=["b", "a"], direction="reverse")
    before = copy.deepcopy(data)
    result = run(data)
    pair = result.pairs[0]
    assert pair.length.outcome == pair.bearing.outcome == pair.displacement.outcome == "agree"
    assert pair.left_displacement == pytest.approx((100, 0), abs=1e-12)
    expected_ids = ("b", "a") if reverse else ("a", "b")
    assert pair.left_call_ids == expected_ids
    assert tuple(source.id for source in pair.left_sources) == expected_ids
    assert tuple(source.quote for source in pair.left_sources) == tuple(
        f"  original {id}  " for id in expected_ids
    )
    assert pair.right_call_ids == ("c",)
    assert pair.right_sources[0].quote == "  original c  "
    assert pair.position.outcome == "unavailable"
    if not reverse:
        merge = next(item for item in result.structural if item.kind == "merge_candidate")
        assert merge.left_call_ids == ("a", "b") and merge.right_call_ids == ("c",)
        assert merge.tentative is True
    assert result.boundary_established is False and result.verified_export_eligible is False
    assert data == before


@pytest.mark.parametrize("kind", ["noncollinear", "cancellation", "noncontiguous", "wrong_order"])
def test_invalid_groups_rejected_as_not_comparable(kind):
    data = request(right=[record("b", 40), record("c", 60)])
    if kind == "noncollinear":
        data["right"]["plot"]["calls"][1]["call"]["bearing_azimuth_deg_from_north"] = 91
    elif kind == "cancellation":
        data["right"]["plot"]["calls"][1]["call"].update(
            distance_ft=60, bearing_azimuth_deg_from_north=270
        )
    elif kind == "noncontiguous":
        data["right"]["plot"]["calls"].insert(1, record("gap", 5))
    else:
        data["pairs"][0]["right"]["call_ids"].reverse()
    pair = run(data).pairs[0]
    assert pair.displacement.outcome == "not_comparable"
    assert pair.displacement.reason


def test_comparison_tolerance_does_not_relax_group_collinearity():
    data = request([record("a", 200, 45)], [record("b", 100, 0), record("c", 100, 90)])
    data["tolerances"].update(bearing_deg=100, displacement=100)
    pair = run(data).pairs[0]
    assert pair.displacement.outcome == "not_comparable"
    assert "collinear" in pair.displacement.reason


@pytest.mark.parametrize("flag", ["is_tie_in", "is_exception", "is_meander", "is_indefinite"])
def test_structural_split_does_not_treat_nonboundary_single_as_boundary(flag):
    data = request([record("a", 100, **{flag: True})], [record("b", 40), record("c", 60)])
    result = run(data)
    assert not any(d.kind in {"split_candidate", "merge_candidate"} for d in result.structural)


@pytest.mark.parametrize("change", ["curve", "missing", "relative"])
def test_unsupported_visible(change):
    data = request()
    if change == "curve":
        data["left"]["plot"]["calls"][0]["call"].update(
            curve_dir="right", radius_ft=50, delta_deg=90
        )
    elif change == "missing":
        data["left"]["plot"]["calls"][0]["call"]["bearing_azimuth_deg_from_north"] = None
    else:
        data["left"]["plot"]["calls"][0]["call"]["is_meander"] = True
    assert run(data).pairs[0].displacement.outcome == "not_comparable"


def test_duplicate_dangling_pairs_and_nonfinite_rejected():
    for mutate in [
        lambda d: d["pairs"].append(copy.deepcopy(d["pairs"][0])),
        lambda d: d["pairs"][0]["left"]["call_ids"].append("missing"),
        lambda d: d["tolerances"].update(length=math.inf),
    ]:
        data = request()
        mutate(data)
        with pytest.raises(ValueError):
            run(data)


def test_structural_insert_delete_reorder_and_ambiguous_repeats():
    data = request(
        [record("a", 10), record("b", 20), record("c", 30)],
        [record("d", 20), record("e", 10), record("f", 40)],
    )
    kinds = {d.kind for d in run(data).structural}
    assert {"reordered", "unmatched_left", "unmatched_right"} <= kinds
    data = request([record("a", 10), record("b", 10)], [record("c", 10), record("d", 10)])
    differences = run(data).structural
    assert len([d for d in differences if d.kind == "ambiguous"]) == 4
    assert all(d.tentative for d in differences)


def test_derived_overflow_fails_closed():
    data = request(right=[record("b", 1e308), record("c", 1e308)])
    result = run(data)
    assert result.pairs[0].displacement.outcome == "not_comparable"


def placed_request():
    from mp_verify.plot import prepare_plot

    data = request()
    data["scene"] = {
        "id": "shared",
        "name": "recorded survey grid",
        "kind": "projected",
        "crs": "EPSG:2234",
        "units": "international_ft",
        "basis": "grid",
    }
    for side in ("left", "right"):
        description = (
            ComparisonRequest.model_validate(data).left
            if side == "left"
            else ComparisonRequest.model_validate(data).right
        )
        geometry = prepare_plot(description.plot).geometry
        data[side]["placement"] = {
            "id": side + "-place",
            "calculation_id": geometry.calculation_id,
            "geometry_hash": geometry.geometry_hash,
            "scene_id": "shared",
            "status": "referenced",
            "rationale": "recorded control",
            "position_evidence": ["recorded origin"],
            "orientation_evidence": ["recorded grid"],
        }
    return data


def test_placement_identity_and_fresh_geometry_required_for_position():
    data = placed_request()
    assert run(data).pairs[0].position.outcome == "agree"
    data["right"]["placement"]["translation"] = [0, 0.45]
    assert run(data).pairs[0].position.difference == pytest.approx(0.45)
    assert run(data).pairs[0].position.outcome == "differ"
    data["right"]["plot"]["calls"][0]["call"]["distance_ft"] = 101
    assert run(data).pairs[0].position.outcome == "unavailable"
    assert "stale" in run(data).pairs[0].position.reason


def test_partial_curve_before_selection_cannot_establish_position():
    from mp_verify.plot import prepare_plot

    data = placed_request()
    for side in ("left", "right"):
        data[side]["plot"]["calls"].insert(0, record(side + "-prior", 20, radial_bearing="N 0 E"))
        description = getattr(ComparisonRequest.model_validate(data), side)
        data[side]["placement"]["geometry_hash"] = prepare_plot(
            description.plot
        ).geometry.geometry_hash
    pair = run(data).pairs[0]
    assert pair.displacement.outcome == "agree"
    assert pair.position.outcome == "unavailable"


def test_unknown_scene_units_cannot_become_positional_compatibility():
    data = placed_request()
    data["scene"].update(kind="local", crs=None, units="unknown_ft")
    assert run(data).pairs[0].position.outcome == "unavailable"
    assert "unknown" in run(data).pairs[0].position.reason


def test_source_mutation_changes_input_hash_and_keeps_original_immutable():
    data = request()
    original = ComparisonRequest.model_validate(data)
    old = compare_descriptions(original)
    data["left"]["plot"]["calls"][0]["quote"] = "different source excerpt"
    fresh = run(data)
    assert fresh.input_hash != old.input_hash
    assert compare_descriptions(original) == old
    assert fresh.pairs[0].left_sources[0].quote == "different source excerpt"


def test_independent_vector_and_distance_finite_difference():
    data = request([record("a", 10, 30)], [record("b", 10, 30)])
    pair = run(data).pairs[0]
    assert pair.left_displacement == pytest.approx((5, 5 * math.sqrt(3)))
    epsilon = 1e-5
    data["right"]["plot"]["calls"][0]["call"]["distance_ft"] = 10 + epsilon
    changed = run(data).pairs[0]
    derivative = tuple(
        (b - a) / epsilon
        for a, b in zip(pair.right_displacement, changed.right_displacement, strict=True)
    )
    assert derivative == pytest.approx((0.5, math.sqrt(3) / 2), rel=1e-8)
    assert changed.displacement.difference == pytest.approx(epsilon, rel=1e-8)


def test_relative_description_explicitly_unsupported():
    records = [record("a", 10, 90), record("b", 10, 180), record("c", 10, 270)]
    data = request(left=records)
    data["left"]["plot"]["relative"] = {
        "frame": {
            "name": "arbitrary",
            "first_azimuth_deg": 90.0,
            "origin": [0.0, 0.0],
            "orientation": "cw",
        },
        "courses": [
            {
                "course_id": r["id"],
                "distance_ft": 10.0,
                "recorded_bearing_azimuth_deg_from_north": float(
                    r["call"]["bearing_azimuth_deg_from_north"]
                ),
                "source": {"reference": "synthetic", "quote": r["quote"]},
            }
            for r in records
        ],
        "constraints": [],
    }
    pair = run(data).pairs[0]
    assert pair.displacement.outcome == "not_comparable"
    assert "relative" in pair.displacement.reason


@pytest.mark.parametrize(
    "curve_field",
    [
        "arc_length_ft",
        "delta_deg",
        "chord_length_ft",
        "chord_bearing",
        "curve_type",
        "radial_bearing",
        "non_tangent",
    ],
)
def test_partial_curve_evidence_is_never_silently_straightened(curve_field):
    data = request()
    value = {
        "arc_length_ft": 100,
        "delta_deg": 45,
        "chord_length_ft": 100,
        "chord_bearing": "N 90 E",
        "curve_type": "simple",
        "radial_bearing": "N 0 E",
        "non_tangent": True,
    }[curve_field]
    data["left"]["plot"]["calls"][0]["call"][curve_field] = value
    if curve_field in {"arc_length_ft", "delta_deg", "chord_length_ft"}:
        with pytest.raises(ValueError, match="curve_dir"):
            run(data)
        return
    result = run(data)
    assert result.pairs[0].displacement.outcome == "not_comparable"
    assert "curv" in result.pairs[0].displacement.reason
