"""Deterministic closure-triggered escalation policy and disagreement reporting.

Decides when an independent blind high-DPI image re-read should run, compares
course-level and tract-level outputs between primary and escalated passes, and
applies fail-closed selection rules without ever fabricating or blending
measurements.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from mp_models import ClosureResult, DeedCall, Tract

EscalationPolicy = Literal["never", "closure_failed", "unverified"]
VALID_ESCALATION_POLICIES: tuple[EscalationPolicy, ...] = (
    "never",
    "closure_failed",
    "unverified",
)

# Tight tolerances well below the 0.01 ft closure threshold (1e-4° ≈ 0.36 arc-sec)
# so a small OCR fix that closes a parcel is never discarded as "agrees=True".
DEFAULT_DISTANCE_TOL_FT: float = 1e-4
DEFAULT_AZIMUTH_TOL_DEG: float = 1e-4


def validate_escalation_policy(policy: object) -> EscalationPolicy:
    """Validate and return *policy*, raising ``ValueError`` for unknown strings."""
    if not isinstance(policy, str) or policy not in VALID_ESCALATION_POLICIES:
        allowed = ", ".join(VALID_ESCALATION_POLICIES)
        raise ValueError(f"Invalid escalation_policy {policy!r}; expected one of: {allowed}")
    return policy  # type: ignore[return-value]


@dataclass(frozen=True)
class CourseDisagreement:
    """Course- or tract-level discrepancy between primary and escalated OCR readings."""

    course: int | None
    kind: Literal["call_count", "tract_count", "tract_metadata", "value_mismatch"]
    details: tuple[str, ...]
    tract_label: str | None = None
    primary_direction: str | None = None
    escalated_direction: str | None = None
    primary_distance_ft: float | None = None
    escalated_distance_ft: float | None = None

    def format_warning(self) -> str:
        """Render a human-readable review warning for this discrepancy."""
        joined = "; ".join(self.details)
        scope = f" ({self.tract_label})" if self.tract_label else ""
        if self.kind == "tract_count":
            return (
                f"OCR escalation disagreement (tract count: {joined}) — "
                "manual source verification required"
            )
        if self.kind == "tract_metadata":
            return (
                f"OCR escalation disagreement{scope} (tract metadata: {joined}) — "
                "manual source verification required"
            )
        if self.kind == "call_count" or self.course is None:
            return (
                f"OCR escalation disagreement{scope} (call count: {joined}) — "
                "manual source verification required"
            )
        return (
            f"OCR escalation disagreement{scope} on course {self.course} ({joined}) — "
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


def _normalize_text_token(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().lower().split())
    return cleaned or None


def _compare_optional_float(
    field_name: str,
    pri_val: float | None,
    esc_val: float | None,
    tol: float,
    issues: list[str],
) -> None:
    if pri_val is not None and esc_val is not None:
        if abs(pri_val - esc_val) > tol:
            issues.append(f"{field_name}: primary={pri_val}, escalated={esc_val}")
    elif pri_val != esc_val:
        issues.append(f"{field_name}: primary={pri_val}, escalated={esc_val}")


def _result_is_clean(res: ClosureResult) -> bool:
    """Return True when closure passed and no verification check failed or was blocked."""
    if not res.closure_passed:
        return False
    return not any(check.status in ("failed", "blocked") for check in res.checks)


def should_escalate_closure(
    results: ClosureResult | Sequence[ClosureResult],
    *,
    policy: EscalationPolicy = "closure_failed",
    has_calls: bool = True,
) -> tuple[bool, list[str]]:
    """Return ``(should_escalate, reasons)`` for verification *results* under *policy*.

    Policies:
    - ``"never"``: never escalate.
    - ``"closure_failed"``: escalate when any tract's ``traverse_closure`` check
      explicitly failed (e.g., misclosure exceeds tolerance).
    - ``"unverified"``: escalate when any tract did not pass closure or has any
      failed/blocked verification check (e.g., incomplete bearings, skipped
      courses, curve consistency, or inferred description roles). Zero-call
      (lot/block) deeds with ``has_calls=False`` do not escalate.
    """
    validated_policy = validate_escalation_policy(policy)
    if validated_policy == "never" or not has_calls:
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
            elif validated_policy == "unverified" and tc_check.status != "passed":
                reasons.append(
                    f"{prefix}: traverse_closure {tc_check.status} (reason={tc_check.reason})"
                )
        elif not res.closure_passed:
            if validated_policy == "unverified" or (
                res.misclosure_available and res.misclosure_ft > 0.0
            ):
                reasons.append(
                    f"{prefix}: closure_passed=False (misclosure={res.misclosure_ft:.4f} ft)"
                )

        if validated_policy == "unverified":
            for check in res.checks:
                if check.name == "traverse_closure":
                    continue
                if check.status in ("failed", "blocked"):
                    reasons.append(f"{prefix}: {check.name} {check.status} (reason={check.reason})")

    return bool(reasons), reasons


def _compare_flat_calls(
    primary_calls: Sequence[DeedCall],
    escalated_calls: Sequence[DeedCall],
    *,
    distance_tol_ft: float,
    azimuth_tol_deg: float,
    tract_label: str | None = None,
) -> list[CourseDisagreement]:
    disagreements: list[CourseDisagreement] = []
    n_pri = len(primary_calls)
    n_esc = len(escalated_calls)

    if n_pri != n_esc:
        disagreements.append(
            CourseDisagreement(
                course=None,
                kind="call_count",
                details=(f"primary={n_pri}, escalated={n_esc}",),
                tract_label=tract_label,
            )
        )

    for idx in range(min(n_pri, n_esc)):
        pri = primary_calls[idx]
        esc = escalated_calls[idx]
        issues: list[str] = []

        if pri.course != esc.course:
            issues.append(f"course_num: primary={pri.course}, escalated={esc.course}")

        _compare_optional_float(
            "distance_ft", pri.distance_ft, esc.distance_ft, distance_tol_ft, issues
        )

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
        else:
            pri_dir_norm = _normalize_text_token(pri.direction_text)
            esc_dir_norm = _normalize_text_token(esc.direction_text)
            if pri_dir_norm != esc_dir_norm:
                issues.append(
                    f"direction_text: primary={pri.direction_text!r}, "
                    f"escalated={esc.direction_text!r}"
                )

        pri_curve = getattr(pri.curve_dir, "value", pri.curve_dir)
        esc_curve = getattr(esc.curve_dir, "value", esc.curve_dir)
        if pri_curve != esc_curve:
            issues.append(f"curve_dir: primary={pri_curve}, escalated={esc_curve}")

        pri_ctype = getattr(pri.curve_type, "value", pri.curve_type)
        esc_ctype = getattr(esc.curve_type, "value", esc.curve_type)
        if pri_ctype != esc_ctype:
            issues.append(f"curve_type: primary={pri_ctype}, escalated={esc_ctype}")

        _compare_optional_float("radius_ft", pri.radius_ft, esc.radius_ft, distance_tol_ft, issues)
        _compare_optional_float(
            "arc_length_ft", pri.arc_length_ft, esc.arc_length_ft, distance_tol_ft, issues
        )
        _compare_optional_float("delta_deg", pri.delta_deg, esc.delta_deg, azimuth_tol_deg, issues)
        _compare_optional_float(
            "chord_length_ft", pri.chord_length_ft, esc.chord_length_ft, distance_tol_ft, issues
        )

        if _normalize_text_token(pri.chord_bearing) != _normalize_text_token(esc.chord_bearing):
            issues.append(
                f"chord_bearing: primary={pri.chord_bearing!r}, escalated={esc.chord_bearing!r}"
            )
        if _normalize_text_token(pri.radial_bearing) != _normalize_text_token(esc.radial_bearing):
            issues.append(
                f"radial_bearing: primary={pri.radial_bearing!r}, escalated={esc.radial_bearing!r}"
            )
        if pri.non_tangent != esc.non_tangent:
            issues.append(f"non_tangent: primary={pri.non_tangent}, escalated={esc.non_tangent}")

        for flag_name in ("is_exception", "is_tie_in", "is_meander", "is_indefinite"):
            pri_flag = getattr(pri, flag_name)
            esc_flag = getattr(esc, flag_name)
            if pri_flag != esc_flag:
                issues.append(f"{flag_name}: primary={pri_flag}, escalated={esc_flag}")

        if issues:
            disagreements.append(
                CourseDisagreement(
                    course=pri.course,
                    kind="value_mismatch",
                    details=tuple(issues),
                    tract_label=tract_label,
                    primary_direction=pri.direction_text,
                    escalated_direction=esc.direction_text,
                    primary_distance_ft=pri.distance_ft,
                    escalated_distance_ft=esc.distance_ft,
                )
            )

    return disagreements


def compare_call_readings(
    primary_calls: Sequence[DeedCall],
    escalated_calls: Sequence[DeedCall],
    *,
    distance_tol_ft: float = DEFAULT_DISTANCE_TOL_FT,
    azimuth_tol_deg: float = DEFAULT_AZIMUTH_TOL_DEG,
    primary_tracts: Sequence[Tract] | None = None,
    escalated_tracts: Sequence[Tract] | None = None,
) -> list[CourseDisagreement]:
    """Return every course- and tract-level discrepancy between primary and escalated readings."""
    pri_tracts = list(primary_tracts) if primary_tracts else []
    esc_tracts = list(escalated_tracts) if escalated_tracts else []

    if pri_tracts or esc_tracts:
        disagreements: list[CourseDisagreement] = []
        if len(pri_tracts) != len(esc_tracts):
            disagreements.append(
                CourseDisagreement(
                    course=None,
                    kind="tract_count",
                    details=(f"primary={len(pri_tracts)}, escalated={len(esc_tracts)}",),
                )
            )
        for idx in range(min(len(pri_tracts), len(esc_tracts))):
            pri_t = pri_tracts[idx]
            esc_t = esc_tracts[idx]
            label = pri_t.label or esc_t.label or f"Tract {idx + 1}"
            meta_issues: list[str] = []
            pri_tt = getattr(pri_t.tract_type, "value", pri_t.tract_type)
            esc_tt = getattr(esc_t.tract_type, "value", esc_t.tract_type)
            if pri_tt != esc_tt:
                meta_issues.append(f"tract_type: primary={pri_tt}, escalated={esc_tt}")
            if pri_t.role_basis != esc_t.role_basis:
                meta_issues.append(
                    f"role_basis: primary={pri_t.role_basis}, escalated={esc_t.role_basis}"
                )
            if meta_issues:
                disagreements.append(
                    CourseDisagreement(
                        course=None,
                        kind="tract_metadata",
                        details=tuple(meta_issues),
                        tract_label=label,
                    )
                )
            disagreements.extend(
                _compare_flat_calls(
                    pri_t.calls,
                    esc_t.calls,
                    distance_tol_ft=distance_tol_ft,
                    azimuth_tol_deg=azimuth_tol_deg,
                    tract_label=label,
                )
            )
        return disagreements

    return _compare_flat_calls(
        primary_calls,
        escalated_calls,
        distance_tol_ft=distance_tol_ft,
        azimuth_tol_deg=azimuth_tol_deg,
    )


def select_escalation_outcome(
    *,
    primary_calls: Sequence[DeedCall],
    escalated_calls: Sequence[DeedCall],
    primary_results: ClosureResult | Sequence[ClosureResult],
    escalated_results: ClosureResult | Sequence[ClosureResult],
    disagreements: Sequence[CourseDisagreement],
    primary_tracts: Sequence[Tract] | None = None,
    escalated_tracts: Sequence[Tract] | None = None,
) -> tuple[Literal["primary", "escalated"], str]:
    """Deterministically choose between primary and escalated readings.

    Fail-closed invariants:
    - Never fabricates or merges individual courses from separate passes.
    - Never lets a truncated pass (empty calls, fewer tracts, or fewer calls)
      silently override a more complete primary reading.
    - Never selects an escalated pass that regresses closed or cleanly verified
      tracts relative to primary.
    """
    if primary_calls and not escalated_calls:
        return "primary", "escalated_empty_fallback_to_primary"

    pri_tracts = list(primary_tracts) if primary_tracts else []
    esc_tracts = list(escalated_tracts) if escalated_tracts else []
    if pri_tracts and len(esc_tracts) < len(pri_tracts):
        return "primary", "escalated_dropped_tracts_fallback_to_primary"

    if primary_calls and len(escalated_calls) < len(primary_calls):
        return "primary", "escalated_truncated_calls_fallback_to_primary"

    if not disagreements:
        return "primary", "readings_agree_confirmed_by_escalation"

    pri_list = _normalize_results(primary_results)
    esc_list = _normalize_results(escalated_results)
    pri_closed_count = sum(1 for r in pri_list if r.closure_passed)
    esc_closed_count = sum(1 for r in esc_list if r.closure_passed)
    pri_clean_count = sum(1 for r in pri_list if _result_is_clean(r))
    esc_clean_count = sum(1 for r in esc_list if _result_is_clean(r))

    if esc_closed_count < pri_closed_count or esc_clean_count < pri_clean_count:
        return "primary", "primary_preserved_escalated_regressed_verification"

    pri_all_closed = bool(pri_list) and pri_closed_count == len(pri_list)
    esc_all_closed = bool(esc_list) and esc_closed_count == len(esc_list)

    if esc_all_closed and not pri_all_closed:
        return "escalated", "escalated_passed_closure_where_primary_failed"

    if esc_closed_count > pri_closed_count or esc_clean_count > pri_clean_count:
        return "escalated", "escalated_improved_closure_with_disagreement_warning"

    return "escalated", "escalated_high_dpi_selected_with_disagreement_warning"
