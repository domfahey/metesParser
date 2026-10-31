"""Closure verification, traverse calculations, and quality scoring.

Compatibility facade over ``mp_verify``: every guardrail, the traverse, area,
perimeter, confidence scoring and the closure summary are computed once by the
package. This module only converts the monolith's models to package models and
back, preserving the legacy ``ClosureChecker`` API and its audit behaviour.

Guardrails: A) traverse closure, B) interior angles, C) parallelism,
D) curve consistency, E) area reasonableness, F) double-entry validation,
G) bearing reversals, H) distance reasonableness.
"""

from collections.abc import Mapping
from typing import overload

import mp_models
import mp_verify.checks as package_checks
import mp_verify.closure as package_closure
import mp_verify.confidence as package_confidence
import mp_verify.tangents as package_tangents
import mp_verify.traverse as package_traverse

from . import package_bridge
from .models import (
    AuditContext,
    ClosureResult,
    DeedCall,
    Point,
    SkippedCourse,
    Tract,
    VerificationAudit,
)

_package_calls = package_bridge.package_calls
_package_skips = package_bridge.package_skips


def _package_points(points: list[Point]) -> list[mp_models.Point]:
    return [mp_models.Point(x=point.x, y=point.y) for point in points]


def _monolith_points(points: list[mp_models.Point]) -> list[Point]:
    return [Point(x=point.x, y=point.y) for point in points]


def _package_result(result: ClosureResult) -> mp_models.ClosureResult:
    return mp_models.ClosureResult.model_validate(result.model_dump())


def _monolith_result(result: mp_models.ClosureResult) -> ClosureResult:
    return ClosureResult.model_validate(result.model_dump())


def _monolith_audit(audit: mp_models.VerificationAudit) -> VerificationAudit:
    return VerificationAudit.model_validate(audit.model_dump())


class ClosureChecker:
    """Verify traverse closure and perform validation checks (package facade)."""

    CLOSURE_TOLERANCE_FT = package_closure.CLOSURE_TOLERANCE_FT

    @classmethod
    def verify_tract(
        cls,
        calls: list[DeedCall],
        *,
        stated_area_sq_ft: float = 0.0,
        closure_tolerance_ft: float | None = None,
        audit_context: AuditContext | None = None,
        skipped_courses: list[SkippedCourse] | None = None,
    ) -> ClosureResult:
        """Check one independent tract using every standard verification guardrail."""
        boundary = [call.model_copy(update={"is_exception": False}) for call in calls]
        return cls.verify_closure(
            boundary,
            stated_area_sq_ft=stated_area_sq_ft,
            closure_tolerance_ft=closure_tolerance_ft,
            audit_context=audit_context,
            skipped_courses=skipped_courses,
        )

    @overload
    @classmethod
    def verify_closure(
        cls,
        calls: list[DeedCall],
        stated_area_sq_ft: float = ...,
        closure_tolerance_ft: float | None = ...,
        double_entry_calls: list[DeedCall] | None = ...,
        audit_context: AuditContext | None = ...,
        *,
        tracts: None = None,
        skipped_courses: list[SkippedCourse] | None = ...,
    ) -> ClosureResult: ...

    @overload
    @classmethod
    def verify_closure(
        cls,
        calls: list[DeedCall],
        stated_area_sq_ft: float = ...,
        closure_tolerance_ft: float | None = ...,
        double_entry_calls: list[DeedCall] | None = ...,
        audit_context: AuditContext | None = ...,
        *,
        tracts: list[Tract],
        skipped_courses: list[SkippedCourse] | None = ...,
    ) -> list[ClosureResult]: ...

    @classmethod
    def verify_closure(
        cls,
        calls: list[DeedCall],
        stated_area_sq_ft: float = 0.0,
        closure_tolerance_ft: float | None = None,
        double_entry_calls: list[DeedCall] | None = None,
        audit_context: AuditContext | None = None,
        *,
        tracts: list[Tract] | None = None,
        skipped_courses: list[SkippedCourse] | None = None,
    ) -> ClosureResult | list[ClosureResult]:
        """Verify traverse closure and perform all validation checks.

        Delegates to ``mp_verify.closure.verify_closure``; results and audits are
        converted back to monolith models.

        Args:
            calls: List of DeedCall objects
            stated_area_sq_ft: Stated area from deed (optional, for comparison)
            closure_tolerance_ft: Custom closure tolerance (default: 0.01 ft)
            double_entry_calls: Optional independently-entered call set for guardrail F
            audit_context: Optional audit context for recording check results; its
                skipped courses block closure like ``skipped_courses``
            skipped_courses: Courses extraction could not parse; any skip blocks
                traverse closure (see ``mp_verify.closure.verify_closure``)

        Returns:
            ClosureResult with all checks, computed values, and confidence_score.
            If tracts provided, returns list[ClosureResult] with one per tract.
            Easement and exception tracts keep their computed geometry but are
            blocked (``non_boundary_tract``) from geometry eligibility.
        """
        # The package records audits on a scratch context holding only those fields;
        # they are copied back so the caller's context reflects the latest run alone.
        scratch = (
            mp_models.AuditContext.model_construct(
                verification_audit=None, tract_verification_audits=[]
            )
            if audit_context is not None
            else None
        )
        package_double_entry = (
            _package_calls(double_entry_calls) if double_entry_calls is not None else None
        )
        package_skips = _package_skips(
            [*(skipped_courses or []), *(audit_context.skipped_courses if audit_context else [])]
        )
        results: list[ClosureResult]
        if tracts is not None:
            package_tracts = [
                mp_models.Tract.model_construct(
                    label=tract.label,
                    tract_type=tract.tract_type,
                    calls=_package_calls(tract.calls),
                    skipped_courses=_package_skips(tract.skipped_courses),
                    stated_area_sq_ft=tract.stated_area_sq_ft,
                )
                for tract in tracts
            ]
            results = [
                _monolith_result(result)
                for result in package_closure.verify_closure(
                    _package_calls(calls),
                    tracts=package_tracts,
                    stated_area_sq_ft=stated_area_sq_ft,
                    closure_tolerance_ft=closure_tolerance_ft,
                    double_entry_calls=package_double_entry,
                    audit_context=scratch,
                    skipped_courses=package_skips,
                )
            ]
        else:
            results = [
                _monolith_result(
                    package_closure.verify_closure(
                        _package_calls(calls),
                        stated_area_sq_ft=stated_area_sq_ft,
                        closure_tolerance_ft=closure_tolerance_ft,
                        double_entry_calls=package_double_entry,
                        audit_context=scratch,
                        skipped_courses=package_skips,
                    )
                )
            ]
        if audit_context is not None and scratch is not None:
            audit_context.verification_audit = (
                _monolith_audit(scratch.verification_audit)
                if scratch.verification_audit is not None
                else None
            )
            audit_context.tract_verification_audits = [
                _monolith_audit(audit) for audit in scratch.tract_verification_audits
            ]
        return results if tracts is not None else results[0]

    @staticmethod
    def _package_call(call: DeedCall) -> mp_models.DeedCall:
        """Mirror a monolith call as a package call without revalidating it."""
        return package_bridge.package_call(call)

    @staticmethod
    def _chord_positioned_delta(call: DeedCall) -> float | None:
        """Return the sweep (deg) when a tangent-less curve is positioned by its chord."""
        return package_tangents.chord_positioned_delta(ClosureChecker._package_call(call))

    @staticmethod
    def _has_determined_direction(call: DeedCall) -> bool:
        """Stated bearing, or tangents fixed by chord bearing and sweep (shared helper)."""
        return package_tangents.has_determined_direction(ClosureChecker._package_call(call))

    @classmethod
    def traverse_positions(
        cls, calls: list[DeedCall], start_point: Point | None = None
    ) -> tuple[list[Point], list[bool]]:
        """Compute the traverse path and which calls it actually advanced through.

        Returns:
            (vertices, positioned) where positioned[i] is True only when calls[i]
            produced a vertex. Callers derive unpositioned courses from this outcome.
        """
        start = mp_models.Point(x=start_point.x, y=start_point.y) if start_point else None
        points, positioned = package_traverse.traverse_positions(_package_calls(calls), start)
        return _monolith_points(points), positioned

    @classmethod
    def compute_traverse(
        cls, calls: list[DeedCall], start_point: Point | None = None
    ) -> list[Point]:
        """Compute the traverse path from calls (vertices only)."""
        return cls.traverse_positions(calls, start_point)[0]

    @classmethod
    def calculate_area(cls, points: list[Point], *, calls: list[DeedCall] | None = None) -> float:
        """Calculate polygon area, including circular segments when calls are supplied.

        Raises:
            ValueError: If fewer than 3 points provided without a curved boundary
        """
        return package_closure.calculate_area(
            _package_points(points), calls=_package_calls(calls) if calls is not None else None
        )

    @classmethod
    def calculate_perimeter(cls, calls: list[DeedCall]) -> float:
        """Calculate total perimeter from calls (feet)."""
        return package_closure.calculate_perimeter(_package_calls(calls))

    @classmethod
    def check_interior_angles(cls, calls: list[DeedCall]) -> bool:
        """Check that a straight polygon's signed exterior angles sum to +/-360 degrees."""
        return package_checks.check_interior_angles(_package_calls(calls), [])

    @classmethod
    def check_boundary_intersections(
        cls, calls: list[DeedCall], coordinates: list[Point]
    ) -> list[str]:
        """Use the shared straight/circular checker for the legacy model API."""
        return package_checks.check_boundary_intersections(
            _package_calls(calls), _package_points(coordinates)
        )

    @classmethod
    def check_straight_boundary_intersections(
        cls, calls: list[DeedCall], coordinates: list[Point]
    ) -> list[str]:
        """Detect crossings, overlaps, and nonadjacent touches between straight edges."""
        return package_checks.check_straight_boundary_intersections(
            _package_calls(calls), _package_points(coordinates)
        )

    @classmethod
    def check_parallelism(cls, calls: list[DeedCall]) -> list[str]:
        """Check for 'continuing' lines whose bearings differ from the previous course."""
        return package_checks.check_parallelism(_package_calls(calls))

    @staticmethod
    def _tangent_chord_issue(call: DeedCall) -> str | None:
        """Canonical stated-tangent vs chord/radius issue for one call (package check)."""
        return package_checks.tangent_chord_issue(ClosureChecker._package_call(call))

    @classmethod
    def curve_consistency_issues(
        cls,
        calls: list[DeedCall],
        tangent_issues: Mapping[int, str | None] | None = None,
    ) -> list[str]:
        """Return the curve-math inconsistencies found by the canonical package check."""
        passed, warnings = package_checks.check_curve_consistency(
            _package_calls(calls), tangent_issues=tangent_issues
        )
        return [] if passed else warnings or ["Curve math inconsistency detected"]

    @classmethod
    def check_curve_consistency(cls, calls: list[DeedCall]) -> bool:
        """Check curve math consistency: L ~ R*delta, chord ~ 2R*sin(delta/2), tangent vs chord."""
        return not cls.curve_consistency_issues(calls)

    @classmethod
    def check_bearing_reversals(cls, calls: list[DeedCall]) -> list[str]:
        """Flag adjacent straight courses with bearings ~180 degrees apart."""
        return package_checks.check_bearing_reversals(_package_calls(calls))

    @classmethod
    def check_distance_reasonableness(cls, calls: list[DeedCall]) -> list[str]:
        """Flag suspiciously short, long (>10x median) or dominant (>90%) distances."""
        return package_checks.check_distance_reasonableness(_package_calls(calls))

    @classmethod
    def score_call_quality(cls, call: DeedCall) -> str:
        """Rate individual call quality as high/medium/low."""
        return package_confidence.score_call_quality(cls._package_call(call))

    @classmethod
    def calculate_confidence_score(cls, result: ClosureResult, calls: list[DeedCall]) -> float:
        """Calculate overall confidence score (0.0-1.0) for a closure result."""
        return package_confidence.calculate_confidence_score(
            _package_result(result), _package_calls(calls)
        )

    @classmethod
    def compare_double_entry(cls, calls1: list[DeedCall], calls2: list[DeedCall]) -> list[str]:
        """Compare two entry sets for discrepancies (double-entry validation)."""
        return package_checks.compare_double_entry(_package_calls(calls1), _package_calls(calls2))

    @classmethod
    def get_closure_summary(
        cls,
        result: ClosureResult,
        calls: list[DeedCall] | None = None,
    ) -> str:
        """Generate a human-readable closure summary."""
        return package_closure.get_closure_summary(
            _package_result(result), _package_calls(calls) if calls is not None else None
        )
