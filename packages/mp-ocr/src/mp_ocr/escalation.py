"""Deterministic closure-triggered escalation policy and disagreement reporting.

Decides when an independent blind high-DPI image re-read should run, compares
course-level and tract-level outputs between primary and escalated passes, and
applies fail-closed selection rules without ever fabricating or blending
measurements.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from mp_models import (
    DESCRIPTION_ROLES_NOTE,
    EASEMENT_TRACT_NOTE,
    EXCEPTION_TRACT_NOTE,
    INVALID_STATED_AREA_NOTE_PREFIX,
    RIGHTS_RESERVED_NOTE_PREFIX,
    SEPARATE_EASEMENT_NOTE_PREFIX,
    UNAPPLIED_EXCEPTION_NOTE_PREFIX,
    ClosureResult,
    DeedCall,
    Tract,
    split_notes,
)

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

_SIMPLE_BEARING_RE = re.compile(
    r"^\s*(?P<ns>North|South|[NS])\.?\s*"
    r"(?P<deg>\d{1,2}(?:\.\d+)?)\s*(?:°|º|deg(?:rees?)?\.?)\s*"
    r"(?:(?P<min>\d{1,2})\s*(?:'|\u2019|\u2032|min(?:utes?)?\.?)\s*"
    r"(?:(?P<sec>\d{1,2}(?:\.\d+)?)\s*(?:\"|''|\u201d|\u2033|sec(?:onds?)?\.?)?\s*)?)?"
    r"(?P<ew>East|West|[EW])\.?\s*$",
    re.IGNORECASE,
)
_DUE_BEARING_AZIMUTH: dict[str, float] = {
    "due north": 0.0,
    "due n": 0.0,
    "due east": 90.0,
    "due e": 90.0,
    "due south": 180.0,
    "due s": 180.0,
    "due west": 270.0,
    "due w": 270.0,
}

_EMBEDDED_BEARING_STRIP_RE = re.compile(
    r"\b(?:North|South|[NS])\.?\s*\d{1,2}(?:\.\d+)?\s*(?:°|º|deg(?:rees?)?\.?)"
    r"(?:\s*\d{1,2}\s*(?:'|\u2019|\u2032|min(?:utes?)?\.?)"
    r"(?:\s*\d{1,2}(?:\.\d+)?\s*(?:\"|''|\u201d|\u2033|sec(?:onds?)?\.?)?)?)?"
    r"\s*(?:East|West|[EW])\.?\b",
    re.IGNORECASE,
)
_CARDINAL_WORD_RE = re.compile(
    r"\b(?P<card>north(?:east|west)?|south(?:east|west)?|east|west)(?:erly|wardly)?\b",
    re.IGNORECASE,
)

_TAIL_NOTE_EXACT_CATEGORIES: dict[str, str] = {
    DESCRIPTION_ROLES_NOTE.lower(): "description_roles",
    EASEMENT_TRACT_NOTE.lower(): "easement_tract",
    EXCEPTION_TRACT_NOTE.lower(): "exception_tract",
}
_TAIL_NOTE_PREFIX_CATEGORIES: tuple[tuple[str, str], ...] = (
    (UNAPPLIED_EXCEPTION_NOTE_PREFIX.lower(), "unapplied_exception"),
    (INVALID_STATED_AREA_NOTE_PREFIX.lower(), "invalid_stated_area"),
    (SEPARATE_EASEMENT_NOTE_PREFIX.lower(), "separate_easement"),
    (RIGHTS_RESERVED_NOTE_PREFIX.lower(), "rights_reserved"),
)
_BLOCKING_TAIL_NOTE_CATEGORIES: frozenset[str] = frozenset(
    {
        "description_roles",
        "easement_tract",
        "exception_tract",
        "unapplied_exception",
        "invalid_stated_area",
        "separate_easement",
    }
)


def tail_note_categories(calls: Sequence[DeedCall]) -> set[str]:
    """Return the set of distinct deed/tail blocking or reservation note categories on *calls*."""
    categories: set[str] = set()
    for call in calls:
        for note in split_notes(call.notes):
            lowered = note.strip().lower()
            exact_cat = _TAIL_NOTE_EXACT_CATEGORIES.get(lowered)
            if exact_cat is not None:
                categories.add(exact_cat)
                continue
            for prefix, cat in _TAIL_NOTE_PREFIX_CATEGORIES:
                if lowered.startswith(prefix):
                    categories.add(cat)
                    break
    return categories


def _effective_single_area(top_area: float | None, tracts: Sequence[Tract]) -> float | None:
    """Resolve effective stated area for single-parcel comparisons across top-level or sole tract."""
    if top_area is not None:
        return top_area
    if len(tracts) == 1:
        return tracts[0].stated_area_sq_ft
    return None


def _has_dropped_area(
    primary_stated_area_sq_ft: float | None,
    escalated_stated_area_sq_ft: float | None,
    pri_tracts: Sequence[Tract],
    esc_tracts: Sequence[Tract],
) -> bool:
    """Return True if escalation dropped primary stated area, respecting multi-tract per-tract storage."""
    if pri_tracts and esc_tracts:
        if any(
            pri_t.stated_area_sq_ft is not None and esc_t.stated_area_sq_ft is None
            for pri_t, esc_t in zip(pri_tracts, esc_tracts, strict=False)
        ):
            return True
    eff_pri = _effective_single_area(primary_stated_area_sq_ft, pri_tracts)
    if eff_pri is None:
        return False
    # Multi-tract escalated deeds intentionally store area on Tract objects rather than top-level.
    if len(esc_tracts) > 1 and escalated_stated_area_sq_ft is None:
        return not any(t.stated_area_sq_ft is not None for t in esc_tracts)
    eff_esc = _effective_single_area(escalated_stated_area_sq_ft, esc_tracts)
    return eff_esc is None


def is_escalated_subset_truncated(
    *,
    primary_calls: Sequence[DeedCall],
    escalated_calls: Sequence[DeedCall],
    primary_tracts: Sequence[Tract] | None = None,
    escalated_tracts: Sequence[Tract] | None = None,
    primary_stated_area_sq_ft: float | None = None,
    escalated_stated_area_sq_ft: float | None = None,
) -> bool:
    """Return True if an escalated subset dropped tracts, calls, stated area, or tail note categories."""
    pri_tracts = list(primary_tracts) if primary_tracts else []
    esc_tracts = list(escalated_tracts) if escalated_tracts else []
    if pri_tracts:
        if len(esc_tracts) < len(pri_tracts):
            return True
        for pri_t, esc_t in zip(pri_tracts, esc_tracts, strict=False):
            if pri_t.calls and len(esc_t.calls) < len(pri_t.calls):
                return True
    if primary_calls and len(escalated_calls) < len(primary_calls):
        return True
    if _has_dropped_area(
        primary_stated_area_sq_ft, escalated_stated_area_sq_ft, pri_tracts, esc_tracts
    ):
        return True
    if tail_note_categories(primary_calls) - tail_note_categories(escalated_calls):
        return True
    return False


def _extract_curve_cardinal(text: str | None) -> str | None:
    """Return canonical cardinal direction word outside embedded DMS bearings, or None."""
    if not text:
        return None
    stripped = _EMBEDDED_BEARING_STRIP_RE.sub(" ", text)
    match = _CARDINAL_WORD_RE.search(stripped)
    return match.group("card").lower() if match else None


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
            detail = f" (tract count: {joined})"
        elif self.kind == "tract_metadata":
            detail = f"{scope} (tract metadata: {joined})"
        elif self.kind == "call_count" or self.course is None:
            detail = f"{scope} (call count: {joined})"
        else:
            detail = f"{scope} on course {self.course} ({joined})"
        return f"OCR escalation disagreement{detail} — manual source verification required"


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


def _parse_bearing_azimuth_deg(text: str | None) -> float | None:
    """Parse a quadrant/due bearing string to clockwise azimuth from north, or None."""
    norm = _normalize_text_token(text)
    if norm is None:
        return None
    if norm in _DUE_BEARING_AZIMUTH:
        return _DUE_BEARING_AZIMUTH[norm]
    match = _SIMPLE_BEARING_RE.match(norm)
    if not match:
        return None
    ns = match.group("ns")[0].upper()
    ew = match.group("ew")[0].upper()
    deg_raw = match.group("deg")
    min_raw = match.group("min")
    sec_raw = match.group("sec")
    if min_raw is not None and "." in deg_raw:
        return None
    deg = float(deg_raw)
    mins = float(min_raw) if min_raw is not None else 0.0
    secs = float(sec_raw) if sec_raw is not None else 0.0
    if mins >= 60.0 or secs >= 60.0:
        return None
    angle = deg + mins / 60.0 + secs / 3600.0
    if angle > 90.0:
        return None
    if ns == "N" and ew == "E":
        return angle % 360.0
    if ns == "S" and ew == "E":
        return (180.0 - angle) % 360.0
    if ns == "S" and ew == "W":
        return (180.0 + angle) % 360.0
    return (360.0 - angle) % 360.0


def _compare_bearing_field(
    field_name: str,
    pri_text: str | None,
    esc_text: str | None,
    azimuth_tol_deg: float,
    issues: list[str],
) -> None:
    pri_az = _parse_bearing_azimuth_deg(pri_text)
    esc_az = _parse_bearing_azimuth_deg(esc_text)
    if pri_az is not None and esc_az is not None:
        if _angle_diff_deg(pri_az, esc_az) > azimuth_tol_deg:
            issues.append(f"{field_name}: primary={pri_text!r}, escalated={esc_text!r}")
        return
    if _normalize_text_token(pri_text) != _normalize_text_token(esc_text):
        issues.append(f"{field_name}: primary={pri_text!r}, escalated={esc_text!r}")


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
    """Return True when closure passed, no check failed/blocked, and no warnings exist."""
    if not res.closure_passed:
        return False
    if res.warnings:
        return False
    return not any(check.status in ("failed", "blocked") for check in res.checks)


def _failed_or_blocked_count(res: ClosureResult) -> int:
    return sum(1 for check in res.checks if check.status in ("failed", "blocked"))


def _is_non_boundary_result(res: ClosureResult, tract: Tract | None = None) -> bool:
    if tract is not None:
        tt = getattr(tract.tract_type, "value", tract.tract_type)
        if tt in ("easement", "exception"):
            return True
    return any(c.name == "non_boundary_tract" for c in res.checks)


def _has_curve_geometry(call: DeedCall) -> bool:
    return any(
        getattr(call, attr) is not None
        for attr in (
            "curve_dir",
            "radius_ft",
            "arc_length_ft",
            "delta_deg",
            "chord_length_ft",
            "chord_bearing",
        )
    )


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
    - ``"unverified"``: escalate when any tract did not pass closure, has any
      failed/blocked verification check, or carries unresolved warnings (e.g.,
      unapplied exceptions, unclosed exception loops, invalid stated area, or
      inferred description roles). Zero-call (lot/block) deeds with
      ``has_calls=False`` do not escalate.
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
            if res.warnings and not any(r.startswith(f"{prefix}:") for r in reasons):
                reasons.append(f"{prefix}: unverified warnings ({len(res.warnings)})")

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
        elif not (_has_curve_geometry(pri) and _has_curve_geometry(esc)):
            pri_dir_norm = _normalize_text_token(pri.direction_text)
            esc_dir_norm = _normalize_text_token(esc.direction_text)
            if pri_dir_norm != esc_dir_norm:
                issues.append(
                    f"direction_text: primary={pri.direction_text!r}, "
                    f"escalated={esc.direction_text!r}"
                )
        else:
            pri_card = _extract_curve_cardinal(pri.direction_text)
            esc_card = _extract_curve_cardinal(esc.direction_text)
            if pri_card != esc_card:
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

        _compare_bearing_field(
            "chord_bearing", pri.chord_bearing, esc.chord_bearing, azimuth_tol_deg, issues
        )
        _compare_bearing_field(
            "radial_bearing", pri.radial_bearing, esc.radial_bearing, azimuth_tol_deg, issues
        )
        if pri.non_tangent != esc.non_tangent:
            issues.append(f"non_tangent: primary={pri.non_tangent}, escalated={esc.non_tangent}")

        for flag_name in ("is_exception", "is_tie_in", "is_meander", "is_indefinite"):
            pri_flag = getattr(pri, flag_name)
            esc_flag = getattr(esc, flag_name)
            if pri_flag != esc_flag:
                issues.append(f"{flag_name}: primary={pri_flag}, escalated={esc_flag}")

        pri_notes = _normalize_text_token(pri.notes)
        esc_notes = _normalize_text_token(esc.notes)
        if pri_notes != esc_notes:
            issues.append(f"notes: primary={pri.notes!r}, escalated={esc.notes!r}")

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
    primary_stated_area_sq_ft: float | None = None,
    escalated_stated_area_sq_ft: float | None = None,
    primary_skipped_courses: Sequence[object] | None = None,
    escalated_skipped_courses: Sequence[object] | None = None,
) -> list[CourseDisagreement]:
    """Return every course- and tract-level discrepancy between primary and escalated readings."""
    pri_tracts = list(primary_tracts) if primary_tracts else []
    esc_tracts = list(escalated_tracts) if escalated_tracts else []
    disagreements: list[CourseDisagreement] = []

    # Single-parcel asymmetry (e.g. primary has 1 implicit tract while escalated has flat calls):
    # resolve effective area before top-level metadata comparison so matching sole-tract vs flat
    # area does not emit a spurious disagreement while drops and metadata diffs still surface.
    single_parcel_asymmetry = (
        len(pri_tracts) == 1 and not esc_tracts and bool(escalated_calls)
    ) or (len(esc_tracts) == 1 and not pri_tracts and bool(primary_calls))

    eff_pri_area = (
        _effective_single_area(primary_stated_area_sq_ft, pri_tracts)
        if single_parcel_asymmetry
        else primary_stated_area_sq_ft
    )
    eff_esc_area = (
        _effective_single_area(escalated_stated_area_sq_ft, esc_tracts)
        if single_parcel_asymmetry
        else escalated_stated_area_sq_ft
    )

    top_meta: list[str] = []
    if eff_pri_area is not None or eff_esc_area is not None:
        _compare_optional_float(
            "stated_area_sq_ft",
            eff_pri_area,
            eff_esc_area,
            distance_tol_ft,
            top_meta,
        )
    if primary_skipped_courses is not None or escalated_skipped_courses is not None:
        pri_skips = len(primary_skipped_courses or ())
        esc_skips = len(escalated_skipped_courses or ())
        if pri_skips != esc_skips:
            top_meta.append(f"skipped_courses: primary={pri_skips}, escalated={esc_skips}")
    if top_meta:
        disagreements.append(
            CourseDisagreement(
                course=None,
                kind="tract_metadata",
                details=tuple(top_meta),
            )
        )

    if single_parcel_asymmetry:
        sole_t = pri_tracts[0] if pri_tracts else esc_tracts[0]
        sole_is_pri = bool(pri_tracts)
        asym_meta: list[str] = []
        sole_tt = getattr(sole_t.tract_type, "value", sole_t.tract_type)
        if sole_tt != "main":
            asym_meta.append(
                f"tract_type: primary={sole_tt if sole_is_pri else 'main'}, "
                f"escalated={'main' if sole_is_pri else sole_tt}"
            )
        if sole_t.role_basis == "inferred":
            asym_meta.append(
                f"role_basis: primary={'inferred' if sole_is_pri else 'single'}, "
                f"escalated={'single' if sole_is_pri else 'inferred'}"
            )
        flat_skips_seq = escalated_skipped_courses if sole_is_pri else primary_skipped_courses
        sole_top_skips = primary_skipped_courses if sole_is_pri else escalated_skipped_courses
        if sole_t.skipped_courses and sole_top_skips is None:
            flat_skip_count = len(flat_skips_seq or ())
            if len(sole_t.skipped_courses) != flat_skip_count:
                asym_meta.append(
                    f"skipped_courses: "
                    f"primary={len(sole_t.skipped_courses) if sole_is_pri else flat_skip_count}, "
                    f"escalated={flat_skip_count if sole_is_pri else len(sole_t.skipped_courses)}"
                )
        if asym_meta:
            disagreements.append(
                CourseDisagreement(
                    course=None,
                    kind="tract_metadata",
                    details=tuple(asym_meta),
                    tract_label=sole_t.label or "Tract 1",
                )
            )
    if (pri_tracts or esc_tracts) and not single_parcel_asymmetry:
        if len(pri_tracts) != len(esc_tracts):
            disagreements.append(
                CourseDisagreement(
                    course=None,
                    kind="tract_count",
                    details=(f"primary={len(pri_tracts)}, escalated={len(esc_tracts)}",),
                )
            )
        paired_count = min(len(pri_tracts), len(esc_tracts))
        for idx in range(paired_count):
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
            _compare_optional_float(
                "stated_area_sq_ft",
                pri_t.stated_area_sq_ft,
                esc_t.stated_area_sq_ft,
                distance_tol_ft,
                meta_issues,
            )
            if len(pri_t.skipped_courses) != len(esc_t.skipped_courses):
                meta_issues.append(
                    f"skipped_courses: primary={len(pri_t.skipped_courses)}, "
                    f"escalated={len(esc_t.skipped_courses)}"
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
        if paired_count == 0 and (primary_calls or escalated_calls):
            disagreements.extend(
                _compare_flat_calls(
                    primary_calls,
                    escalated_calls,
                    distance_tol_ft=distance_tol_ft,
                    azimuth_tol_deg=azimuth_tol_deg,
                )
            )
        return disagreements

    disagreements.extend(
        _compare_flat_calls(
            primary_calls,
            escalated_calls,
            distance_tol_ft=distance_tol_ft,
            azimuth_tol_deg=azimuth_tol_deg,
        )
    )
    return disagreements


def _has_check(results: Sequence[ClosureResult], check_name: str) -> bool:
    return any(
        c.name == check_name and c.status in ("failed", "blocked")
        for r in results
        for c in r.checks
    )


def _has_quality_regression(
    pri_seq: Sequence[ClosureResult], esc_seq: Sequence[ClosureResult]
) -> bool:
    """Return True if aligned tracts in *esc_seq* regressed availability, checks, misclosure, or confidence."""
    pairs = list(zip(pri_seq, esc_seq, strict=False))
    if not pairs:
        return False
    pri_avail = sum(1 for p, _ in pairs if p.misclosure_available)
    esc_avail = sum(1 for _, e in pairs if e.misclosure_available)
    pri_bad_checks = sum(_failed_or_blocked_count(p) for p, _ in pairs)
    esc_bad_checks = sum(_failed_or_blocked_count(e) for _, e in pairs)
    if esc_avail < pri_avail or esc_bad_checks > pri_bad_checks:
        return True
    worse_misclosure = any(
        p.misclosure_available
        and e.misclosure_available
        and e.misclosure_ft > p.misclosure_ft + DEFAULT_DISTANCE_TOL_FT
        for p, e in pairs
    )
    worse_confidence = any(
        p.confidence_score is not None
        and e.confidence_score is not None
        and e.confidence_score < p.confidence_score - 1e-6
        for p, e in pairs
    )
    return worse_misclosure or worse_confidence


def select_escalation_outcome(
    *,
    primary_calls: Sequence[DeedCall],
    escalated_calls: Sequence[DeedCall],
    primary_results: ClosureResult | Sequence[ClosureResult],
    escalated_results: ClosureResult | Sequence[ClosureResult],
    disagreements: Sequence[CourseDisagreement],
    primary_tracts: Sequence[Tract] | None = None,
    escalated_tracts: Sequence[Tract] | None = None,
    primary_stated_area_sq_ft: float | None = None,
    escalated_stated_area_sq_ft: float | None = None,
) -> tuple[Literal["primary", "escalated"], str]:
    """Deterministically choose between primary and escalated readings.

    Fail-closed invariants:
    - Never fabricates or merges individual courses from separate passes.
    - Never lets a truncated pass (empty calls, fewer tracts, per-tract call
      drops, dropped stated area, or dropped blocking clauses) override primary.
    - Never selects an escalated pass that regresses any already-closed or
      cleanly verified tract, introduces ``description_roles_inferred``, or
      degrades misclosure/check/confidence quality.
    """
    if primary_calls and not escalated_calls:
        return "primary", "escalated_empty_fallback_to_primary"

    pri_tracts = list(primary_tracts) if primary_tracts else []
    esc_tracts = list(escalated_tracts) if escalated_tracts else []
    eff_pri_tract_count = len(pri_tracts) if pri_tracts else (1 if primary_calls else 0)
    eff_esc_tract_count = len(esc_tracts) if esc_tracts else (1 if escalated_calls else 0)
    if eff_pri_tract_count > 1 and eff_esc_tract_count < eff_pri_tract_count:
        return "primary", "escalated_dropped_tracts_fallback_to_primary"

    if primary_calls and len(escalated_calls) < len(primary_calls):
        return "primary", "escalated_truncated_calls_fallback_to_primary"

    if pri_tracts and esc_tracts:
        for pri_t, esc_t in zip(pri_tracts, esc_tracts, strict=False):
            if pri_t.calls and len(esc_t.calls) < len(pri_t.calls):
                return "primary", "escalated_truncated_calls_fallback_to_primary"

    if not disagreements:
        return "primary", "readings_agree_confirmed_by_escalation"

    pri_list = _normalize_results(primary_results)
    esc_list = _normalize_results(escalated_results)
    pri_boundary = [
        r
        for i, r in enumerate(pri_list)
        if not _is_non_boundary_result(r, pri_tracts[i] if i < len(pri_tracts) else None)
    ]
    esc_boundary = [
        r
        for i, r in enumerate(esc_list)
        if not _is_non_boundary_result(r, esc_tracts[i] if i < len(esc_tracts) else None)
    ]

    # Omission-reward guard: never let dropping stated area (including sole-tract asymmetry) or
    # blocking tail clauses (unapplied exceptions, invalid area, inferred roles, non-boundary notes)
    # win selection.
    dropped_area = _has_dropped_area(
        primary_stated_area_sq_ft, escalated_stated_area_sq_ft, pri_tracts, esc_tracts
    )
    dropped_blocking_notes = bool(
        (tail_note_categories(primary_calls) & _BLOCKING_TAIL_NOTE_CATEGORIES)
        - (tail_note_categories(escalated_calls) & _BLOCKING_TAIL_NOTE_CATEGORIES)
    )
    if dropped_area or dropped_blocking_notes:
        return "primary", "primary_preserved_escalated_regressed_verification"

    # Never select an escalated pass that introduces inferred-role blocking where primary had none.
    pri_roles_inferred = _has_check(pri_list, "description_roles_inferred")
    esc_roles_inferred = _has_check(esc_list, "description_roles_inferred")
    if esc_roles_inferred and not pri_roles_inferred:
        return "primary", "primary_preserved_escalated_regressed_verification"

    # Never let reclassifying a conveyed boundary tract as non-boundary masquerade as closure.
    if len(esc_boundary) < len(pri_boundary):
        return "primary", "primary_preserved_escalated_regressed_verification"

    # Pairwise tract regression guard over aligned prefixes (even when escalated adds extra tracts).
    for pri_seq, esc_seq in ((pri_list, esc_list), (pri_boundary, esc_boundary)):
        for pri_r, esc_r in zip(pri_seq, esc_seq, strict=False):
            if (pri_r.closure_passed and not esc_r.closure_passed) or (
                _result_is_clean(pri_r) and not _result_is_clean(esc_r)
            ):
                return "primary", "primary_preserved_escalated_regressed_verification"

    pri_closed_count = sum(1 for r in pri_boundary if r.closure_passed)
    esc_closed_count = sum(1 for r in esc_boundary if r.closure_passed)
    aligned_esc_boundary = esc_boundary[: len(pri_boundary)]
    aligned_esc_closed = sum(1 for r in aligned_esc_boundary if r.closure_passed)
    pri_clean_count = sum(1 for r in pri_boundary if _result_is_clean(r))
    esc_clean_count = sum(1 for r in esc_boundary if _result_is_clean(r))
    pri_total_closed = sum(1 for r in pri_list if r.closure_passed)
    esc_total_closed = sum(1 for r in esc_list if r.closure_passed)
    pri_total_clean = sum(1 for r in pri_list if _result_is_clean(r))
    esc_total_clean = sum(1 for r in esc_list if _result_is_clean(r))

    if (
        esc_closed_count < pri_closed_count
        or esc_clean_count < pri_clean_count
        or esc_total_closed < pri_total_closed
        or esc_total_clean < pri_total_clean
    ):
        return "primary", "primary_preserved_escalated_regressed_verification"

    # Never reward dropping a blocking check (roles_inferred / non_boundary_tract) when aligned
    # boundary closure did not actually improve.
    pri_non_boundary = _has_check(pri_list, "non_boundary_tract")
    esc_non_boundary = _has_check(esc_list, "non_boundary_tract")
    if aligned_esc_closed <= pri_closed_count and (
        (pri_roles_inferred and not esc_roles_inferred)
        or (pri_non_boundary and not esc_non_boundary)
    ):
        return "primary", "primary_preserved_escalated_regressed_verification"

    # Never let a spurious extra boundary tract mask quality regression on aligned primary tracts.
    if (
        len(esc_boundary) > len(pri_boundary)
        and pri_boundary
        and aligned_esc_closed <= pri_closed_count
        and _has_quality_regression(pri_boundary, esc_boundary)
    ):
        return "primary", "primary_preserved_escalated_regressed_verification"

    pri_all_closed = bool(pri_boundary) and pri_closed_count == len(pri_boundary)
    esc_all_closed = bool(esc_boundary) and esc_closed_count == len(esc_boundary)

    if esc_all_closed and not pri_all_closed and esc_closed_count > pri_closed_count:
        return "escalated", "escalated_passed_closure_where_primary_failed"

    if esc_closed_count > pri_closed_count or esc_clean_count > pri_clean_count:
        return "escalated", "escalated_improved_closure_with_disagreement_warning"

    if esc_total_closed > pri_total_closed:
        if pri_boundary and _has_quality_regression(pri_boundary, esc_boundary):
            return "primary", "primary_preserved_escalated_regressed_verification"
        return "escalated", "escalated_improved_closure_with_disagreement_warning"

    # Neither pass improved closed/clean counts: refuse escalated if it regressed quality.
    pri_q, esc_q = (
        (pri_list, esc_list)
        if (len(pri_list) == len(esc_list) or not pri_boundary)
        else (pri_boundary, esc_boundary)
    )
    if _has_quality_regression(pri_q, esc_q):
        return "primary", "primary_preserved_escalated_regressed_verification"

    return "escalated", "escalated_high_dpi_selected_with_disagreement_warning"
