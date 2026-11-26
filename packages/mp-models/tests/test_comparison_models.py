"""Validation invariants for advisory description-comparison models."""

from __future__ import annotations

import pytest
from mp_models import DeedCall, PlotCall, PlotRequest
from mp_models.comparison import (
    BearingBasis,
    ComparisonDescription,
    ComparisonPair,
    ComparisonRequest,
    ComparisonSelection,
    ComparisonTolerance,
    ComparisonTransform,
)
from pydantic import ValidationError


def _plot(cid: str) -> PlotRequest:
    return PlotRequest(
        title="P",
        calculation_id=cid,
        foot_definition="international_ft",
        calls=(
            PlotCall(
                id="c1",
                call=DeedCall(
                    course=1,
                    direction_text="N",
                    bearing_azimuth_deg_from_north=0.0,
                    distance_ft=10.0,
                ),
            ),
        ),
    )


def test_comparison_model_validation_guards():
    # BearingBasis: identity requires source_references; blank reference rejected.
    with pytest.raises(ValidationError, match="identity and source references"):
        BearingBasis(label="Grid", identity="NAD83")
    with pytest.raises(ValidationError, match="references must not be blank"):
        BearingBasis(label="Grid", identity="NAD83", source_references=("   ",))

    # ComparisonTolerance: unknown_ft or blank reference rejected.
    with pytest.raises(ValidationError, match="known units and provenance"):
        ComparisonTolerance(
            length=0.5,
            displacement=0.5,
            position=0.5,
            linear_unit="unknown_ft",
            bearing_deg=0.5,
            source_references=("review",),
        )
    with pytest.raises(ValidationError, match="known units and provenance"):
        ComparisonTolerance(
            length=0.5,
            displacement=0.5,
            position=0.5,
            linear_unit="international_ft",
            bearing_deg=0.5,
            source_references=("  ",),
        )

    # ComparisonSelection: duplicate call_ids rejected.
    with pytest.raises(ValidationError, match="call IDs must be unique"):
        ComparisonSelection(call_ids=("c1", "c1"), direction="forward")

    # ComparisonTransform: blank source reference rejected.
    with pytest.raises(ValidationError, match="source evidence"):
        ComparisonTransform(rotation_deg=1.0, source_references=("   ",))

    # ComparisonRequest: identical left/right IDs, duplicate pair IDs, dangling call IDs.
    basis = BearingBasis(label="Grid", identity="NAD83", source_references=("p1",))
    tol = ComparisonTolerance(
        length=0.5,
        displacement=0.5,
        position=0.5,
        linear_unit="international_ft",
        bearing_deg=0.5,
        source_references=("review",),
    )
    left = ComparisonDescription(id="same", plot=_plot("l"), bearing_basis=basis)
    right_same = ComparisonDescription(id="same", plot=_plot("r"), bearing_basis=basis)
    with pytest.raises(ValidationError, match="distinguish versions/occurrences"):
        ComparisonRequest(left=left, right=right_same, tolerances=tol)

    right = ComparisonDescription(id="other", plot=_plot("r"), bearing_basis=basis)
    pair = ComparisonPair(
        id="p1",
        left=ComparisonSelection(call_ids=("c1",), direction="forward"),
        right=ComparisonSelection(call_ids=("c1",), direction="forward"),
    )
    with pytest.raises(ValidationError, match="pair IDs must be unique"):
        ComparisonRequest(left=left, right=right, pairs=(pair, pair), tolerances=tol)

    bad_pair = ComparisonPair(
        id="p1",
        left=ComparisonSelection(call_ids=("missing",), direction="forward"),
        right=ComparisonSelection(call_ids=("c1",), direction="forward"),
    )
    with pytest.raises(ValidationError, match="dangling call IDs"):
        ComparisonRequest(left=left, right=right, pairs=(bad_pair,), tolerances=tol)
