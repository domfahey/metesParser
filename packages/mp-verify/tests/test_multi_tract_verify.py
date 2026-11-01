"""Tests for multi-tract verification."""

from mp_models import ClosureResult, DeedCall, Tract, TractType
from mp_verify import verify_closure
from mp_verify.closure import verify_tract


def _square_calls(size: float = 100.0, course_start: int = 1) -> list[DeedCall]:
    """Generate a perfect square of calls."""
    return [
        DeedCall(
            course=course_start,
            direction_text="N 45\u00b000' E",
            bearing_quadrant="N 45\u00b000' E",
            bearing_azimuth_deg_from_north=45.0,
            distance_ft=size,
        ),
        DeedCall(
            course=course_start + 1,
            direction_text="S 45\u00b000' E",
            bearing_quadrant="S 45\u00b000' E",
            bearing_azimuth_deg_from_north=135.0,
            distance_ft=size,
        ),
        DeedCall(
            course=course_start + 2,
            direction_text="S 45\u00b000' W",
            bearing_quadrant="S 45\u00b000' W",
            bearing_azimuth_deg_from_north=225.0,
            distance_ft=size,
        ),
        DeedCall(
            course=course_start + 3,
            direction_text="N 45\u00b000' W",
            bearing_quadrant="N 45\u00b000' W",
            bearing_azimuth_deg_from_north=315.0,
            distance_ft=size,
        ),
    ]


class TestVerifyTract:
    def test_single_tract_closes(self):
        calls = _square_calls()
        result = verify_tract(calls)
        assert isinstance(result, ClosureResult)
        assert result.closure_passed
        assert result.area_sq_ft > 0

    def test_verify_tract_includes_all_calls(self):
        """verify_tract treats all calls as one traverse - no exception filtering."""
        calls = _square_calls()
        # Mark some as exception - verify_tract should still include them
        calls_with_exc = [c.model_copy(update={"is_exception": True}) for c in calls]
        result = verify_tract(calls_with_exc)
        assert isinstance(result, ClosureResult)
        # Should close because all 4 sides are included
        assert result.closure_passed

    def test_verify_tract_has_confidence(self):
        calls = _square_calls()
        result = verify_tract(calls)
        assert result.confidence_score is not None
        assert result.confidence_score > 0.0

    def test_verify_tract_zero_calls_fails(self):
        result = verify_tract([])
        assert not result.closure_passed
        assert result.area_sq_ft == 0.0
        assert result.warnings

    def test_verify_tract_two_calls_fails(self):
        calls = _square_calls()[:2]
        result = verify_tract(calls)
        assert not result.closure_passed
        assert result.misclosure_ft > 100
        assert not result.is_fully_verified()


class TestVerifyClosureMultiTract:
    def test_multi_tract_returns_list(self):
        t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=_square_calls(100.0))
        t2 = Tract(label="Exception 1", tract_type=TractType.EXCEPTION, calls=_square_calls(50.0))
        result = verify_closure(_square_calls(100.0), tracts=[t1, t2])
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(r, ClosureResult) for r in result)

    def test_no_tracts_returns_single_result(self):
        """Backward compat: no tracts param = single ClosureResult."""
        result = verify_closure(_square_calls())
        assert isinstance(result, ClosureResult)

    def test_per_tract_closure_independent(self):
        t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=_square_calls(100.0))
        t2 = Tract(label="Tract 2", tract_type=TractType.MAIN, calls=_square_calls(50.0))
        results = verify_closure(_square_calls(100.0), tracts=[t1, t2])
        assert isinstance(results, list)
        assert results[0].closure_passed
        assert results[1].closure_passed
        # Areas should differ (100^2 vs 50^2 = 10000 vs 2500)
        assert results[0].area_sq_ft > results[1].area_sq_ft

    def test_empty_tracts_list_returns_empty_list(self):
        """tracts=[] should return an empty list, not fall through to single-tract."""
        result = verify_closure(_square_calls(), tracts=[])
        assert isinstance(result, list)
        assert result == []

    def test_backward_compat_kwargs(self):
        """Existing keyword args still work when tracts not provided."""
        result = verify_closure(
            _square_calls(), stated_area_sq_ft=10000.0, closure_tolerance_ft=0.1
        )
        assert isinstance(result, ClosureResult)


class TestVerifyTractRoleBinding:
    def test_role_check_argument_is_rejected(self):
        import pytest
        from mp_verify.checks import evaluate_tract_role

        with pytest.raises(TypeError):
            verify_tract(  # type: ignore[call-arg]
                _square_calls(),
                role_check=evaluate_tract_role("Tract 1", TractType.EASEMENT),
            )

    def test_easement_tract_is_blocked(self):
        tract = Tract(label="Tract 1", tract_type=TractType.EASEMENT, calls=_square_calls())
        result = verify_tract(tract.calls, tract=tract)
        assert not result.is_fully_verified()

    def test_main_tract_verifies(self):
        tract = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=_square_calls())
        assert verify_tract(tract.calls, tract=tract).is_fully_verified()
