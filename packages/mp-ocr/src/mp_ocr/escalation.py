"""Deterministic closure-triggered escalation policy and disagreement reporting.

Decides when an independent blind high-DPI image re-read should run, compares
course-level outputs between primary and escalated passes, and applies
fail-closed selection rules without ever fabricating or blending measurements.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from mp_models import ClosureResult, DeedCall

EscalationPolicy = Literal["never", "closure_failed", "unverified"]


@dataclass(frozen=True)
class CourseDisagreement:
    """Course-level discrepancy between primary and escalated OCR readings."""

    course: int | None
    kind: Literal["call_count", "value_mismatch"]
    details: tuple[str, ...]
    primary_direction: str | None = None
    escalated_direction: str | None = None
    primary_distance_ft: float | None = None
    escalated_distance_ft: float | None = None

    def format_warning(self) -> str:
        """Render a human-readable review warning for this discrepancy."""
        joined = "; ".join(self.details)
        if self.kind == "call_count" or self.course is None:
            return (
                f"OCR escalation disagreement (call count: {joined}) — "
                "manual source verification required"
            )
        return (
            f"OCR escalation disagreement on course {self.course} ({joined}) — "
            "manual source verification required"
        )


@dataclass(frozen=True)
class EscalationReport:
    """Auditable summary of a blind OCR escalation check."""

    triggered: bool
    policy: EscalationPolicy
    trigger_reasons: tuple[str, ...] = field(default_factory=tuple)
    legal_pages: tuple[int, ...] = field(default_factory=tuple)
    primary_model: str | None = None
    escalation_model: str | None = None
    agrees: bool = True
    disagreements: tuple[CourseDisagreement, ...] = field(default_factory=tuple)
    selected: Literal["primary", "escalated"] = "primary"
    selection_reason: str = "not_triggered"

    @property
    def review_warnings(self) -> list[str]:
        """Return explicit warnings for every disagreement requiring human review."""
        return [item.format_warning() for item in self.disagreements]


def _normalize_results(
    results: ClosureResult | Sequence[ClosureResult],
) -> list[ClosureResult]:
    if isinstance(results, ClosureResult):
        return [results]
    return list(results)


def _angle_diff_deg(a: float, b: float) -> float:
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


def should_escalate_closure(
    results: ClosureResult | Sequence[ClosureResult],
    *,
    policy: EscalationPolicy = "closure_failed",
) -> tuple[bool, list[str]]:
    """Return ``(should_escalate, reasons)`` for verification *results* under *policy*.

    Policies:
    - ``"never"``: never escalate.
    - ``"closure_failed"``: escalate when any tract's ``traverse_closure`` check
      explicitly failed (e.g., misclosure exceeds tolerance).
    - ``"unverified"``: escalate when any tract did not pass closure (covers
      both failed traverse closure and blocked checks such as incomplete
      bearings or skipped courses).
    """
    if policy == "never":
        return False, []

    result_list = _normalize_results(results)
    if not result_list:
        return False, []

    reasons: list[str] = []
    for idx, res in enumerate(result_list, start=1):
        prefix = f"tract_{idx}" if len(result_list) > 1 else "parcel"
        tc_check = next((c for c in res.checks if c.name == "traverse_closure"), None)

        if tc_check is not None:
            if tc_check.status == "failed":
                reasons.append(
                    f"{prefix}: traverse_closure failed "
                    f"(misclosure={res.misclosure_ft:.4f} ft, reason={tc_check.reason})"
                )
            elif policy == "unverified" and tc_check.status != "passed":
                reasons.append(
                    f"{prefix}: traverse_closure {tc_check.status} (reason={tc_check.reason})"
                )
        elif not res.closure_passed:
            if policy == "unverified" or (res.misclosure_available and res.misclosure_ft > 0.0):
                reasons.append(
                    f"{prefix}: closure_passed=False (misclosure={res.misclosure_ft:.4f} ft)"
                )

    return bool(reasons), reasons


def compare_call_readings(
    primary_calls: Sequence[DeedCall],
    escalated_calls: Sequence[DeedCall],
    *,
    distance_tol_ft: float = 0.05,
    azimuth_tol_deg: float = 0.05,
) -> list[CourseDisagreement]:
    """Return every course-level discrepancy between primary and escalated calls."""
    disagreements: list[CourseDisagreement] = []
    n_pri = len(primary_calls)
    n_esc = len(escalated_calls)

    if n_pri != n_esc:
        disagreements.append(
            CourseDisagreement(
                course=None,
                kind="call_count",
                details=(f"primary={n_pri}, escalated={n_esc}",),
            )
        )

    for idx in range(min(n_pri, n_esc)):
        pri = primary_calls[idx]
        esc = escalated_calls[idx]
        issues: list[str] = []

        if pri.distance_ft is not None and esc.distance_ft is not None:
            if abs(pri.distance_ft - esc.distance_ft) > distance_tol_ft:
                issues.append(
                    f"distance_ft: primary={pri.distance_ft}, escalated={esc.distance_ft}"
                )
        elif pri.distance_ft != esc.distance_ft:
            issues.append(f"distance_ft: primary={pri.distance_ft}, escalated={esc.distance_ft}")

        pri_az = pri.bearing_azimuth_deg_from_north
        esc_az = esc.bearing_azimuth_deg_from_north
        if pri_az is not None and esc_az is not None:
            if _angle_diff_deg(pri_az, esc_az) > azimuth_tol_deg:
                issues.append(
                    f"bearing: primary={pri.direction_text!r} ({pri_az:.4f}°), "
                    f"escalated={esc.direction_text!r} ({esc_az:.4f}°)"
                )
        elif pri_az != esc_az:
            issues.append(
                f"bearing: primary={pri.direction_text!r} ({pri_az}), "
                f"escalated={esc.direction_text!r} ({esc_az})"
            )

        pri_curve = getattr(pri.curve_dir, "value", pri.curve_dir)
        esc_curve = getattr(esc.curve_dir, "value", esc.curve_dir)
        if pri_curve != esc_curve:
            issues.append(f"curve_dir: primary={pri_curve}, escalated={esc_curve}")

        if pri.radius_ft is not None and esc.radius_ft is not None:
            if abs(pri.radius_ft - esc.radius_ft) > distance_tol_ft:
                issues.append(f"radius_ft: primary={pri.radius_ft}, escalated={esc.radius_ft}")
        elif pri.radius_ft != esc.radius_ft:
            issues.append(f"radius_ft: primary={pri.radius_ft}, escalated={esc.radius_ft}")

        if pri.arc_length_ft is not None and esc.arc_length_ft is not None:
            if abs(pri.arc_length_ft - esc.arc_length_ft) > distance_tol_ft:
                issues.append(
                    f"arc_length_ft: primary={pri.arc_length_ft}, escalated={esc.arc_length_ft}"
                )
        elif pri.arc_length_ft != esc.arc_length_ft:
            issues.append(
                f"arc_length_ft: primary={pri.arc_length_ft}, escalated={esc.arc_length_ft}"
            )

        if issues:
            disagreements.append(
                CourseDisagreement(
                    course=pri.course,
                    kind="value_mismatch",
                    details=tuple(issues),
                    primary_direction=pri.direction_text,
                    escalated_direction=esc.direction_text,
                    primary_distance_ft=pri.distance_ft,
                    escalated_distance_ft=esc.distance_ft,
                )
            )

    return disagreements


def select_escalation_outcome(
    *,
    primary_calls: Sequence[DeedCall],
    escalated_calls: Sequence[DeedCall],
    primary_results: ClosureResult | Sequence[ClosureResult],
    escalated_results: ClosureResult | Sequence[ClosureResult],
    disagreements: Sequence[CourseDisagreement],
) -> tuple[Literal["primary", "escalated"], str]:
    """Deterministically choose between primary and escalated readings.

    Never fabricates or merges individual courses from separate passes.
    """
    if primary_calls and not escalated_calls:
        return "primary", "escalated_empty_fallback_to_primary"

    if not disagreements:
        return "primary", "readings_agree_confirmed_by_escalation"

    pri_list = _normalize_results(primary_results)
    esc_list = _normalize_results(escalated_results)
    pri_all_closed = bool(pri_list) and all(r.closure_passed for r in pri_list)
    esc_all_closed = bool(esc_list) and all(r.closure_passed for r in esc_list)

    if esc_all_closed and not pri_all_closed:
        return "escalated", "escalated_passed_closure_where_primary_failed"

    if pri_all_closed and not esc_all_closed:
        return "primary", "primary_passed_closure_where_escalated_failed"

    return "escalated", "escalated_high_dpi_selected_with_disagreement_warning"
