"""The tract-role check blocks tracts that are not the conveyed parcel's boundary."""

from __future__ import annotations

from mp_models import TractType
from mp_verify.checks import evaluate_tract_role


def test_boundary_tracts_have_no_role_check() -> None:
    assert evaluate_tract_role("Tract 1", TractType.MAIN) is None
    assert evaluate_tract_role("Addition 1", TractType.ADDITION) is None


def test_non_boundary_tracts_are_blocked() -> None:
    check = evaluate_tract_role("Easement 1", TractType.EASEMENT)
    assert check is not None
    assert (check.name, check.status, check.reason) == ("non_boundary_tract", "blocked", "easement")
    assert "Easement 1" in check.detail
    assert "not a parcel boundary" in check.detail
    assert check.inputs == {"tract_type": "easement"}


def test_plain_string_tract_types_are_accepted() -> None:
    assert evaluate_tract_role("Exception 1", "exception") is not None
    assert evaluate_tract_role("Tract 1", "main") is None
