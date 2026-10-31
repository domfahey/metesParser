"""PR #60 round 54: the tract-role check is internal, not a public verify_closure input."""

from __future__ import annotations

import pytest
from mp_models import CheckResult, DeedCall, Tract, TractType, non_boundary_detail
from mp_verify import verify_closure, verify_tract
from mp_verify.closure import _verify_single


def _square() -> list[DeedCall]:
    return [
        DeedCall(
            course=i + 1, direction_text=d, bearing_azimuth_deg_from_north=a, distance_ft=100.0
        )
        for i, (d, a) in enumerate((("N", 0.0), ("E", 90.0), ("S", 180.0), ("W", 270.0)))
    ]


def test_verify_closure_rejects_role_check() -> None:
    fake = CheckResult(name="non_boundary_tract", status="passed", detail="ok")
    with pytest.raises(TypeError):
        verify_closure(_square(), role_check=fake)  # type: ignore[call-overload]
    with pytest.raises(TypeError):
        verify_closure(
            [],
            tracts=[Tract(label="T", tract_type=TractType.MAIN, calls=_square())],
            role_check=fake,
        )  # type: ignore[call-overload]


def test_internal_helper_only_accepts_blocked_role_check() -> None:
    fake = CheckResult(name="non_boundary_tract", status="passed", detail="ok")
    with pytest.raises(ValueError):
        _verify_single(_square(), role_checks=[fake])


def test_article_grammar() -> None:
    assert "is an easement tract" in non_boundary_detail("E", TractType.EASEMENT)
    assert "is an exception tract" in non_boundary_detail("E", TractType.EXCEPTION)


def test_verify_tract_unaffected_for_main() -> None:
    assert verify_tract(_square()).is_fully_verified()
