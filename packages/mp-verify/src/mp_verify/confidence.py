"""Call quality and overall confidence scoring.

- Per-call quality rating (high/medium/low) based on bearing completeness
  and monument permanence.
- Overall confidence score (0.0-1.0) weighted across closure, checks,
  bearings, quality, and warnings.
"""

from __future__ import annotations

from mp_models import ClosureResult, DeedCall
from mp_models.constants import PERMANENT_MONUMENTS

from .tangents import has_determined_direction


def score_call_quality(call: DeedCall) -> str:
    """Rate individual call quality as high/medium/low.

    Scoring logic:
    - low: direction not determined (no stated bearing and not fixed by stated
      curve elements) OR indefinite call
    - medium: complete bearing but has meander flag or non-permanent monument
    - high: complete bearing with permanent or no monument, no flags

    Args:
        call: DeedCall to score.

    Returns:
        "high", "medium", or "low".
    """
    if not has_determined_direction(call) or call.is_indefinite:
        return "low"

    if call.is_meander:
        return "medium"

    if call.monument_type and call.monument_type not in PERMANENT_MONUMENTS:
        return "medium"

    return "high"


def calculate_confidence_score(result: ClosureResult, calls: list[DeedCall]) -> float:
    """Calculate overall confidence score (0.0-1.0) for a closure result.

    Weighted components:
    - Closure quality (30%): based on misclosure distance and pass/fail
    - Verification checks (20%): angle + curve consistency
    - Bearing completeness (25%): ratio of calls with complete bearings
    - Call quality (15%): ratio of high-quality calls
    - Warning penalty (10%): deducted per warning

    Args:
        result: ClosureResult from verify_closure().
        calls: List of DeedCall objects.

    Returns:
        Score between 0.0 and 1.0 (inclusive).
    """
    if not calls:
        return 0.0

    # Closure quality (30%); an undetermined misclosure earns no closure credit.
    if not result.misclosure_available:
        closure_score = 0.0
    elif result.closure_passed:
        if result.misclosure_ft < 0.001:
            closure_score = 1.0
        elif result.misclosure_ft < 0.01:
            closure_score = 0.9
        elif result.misclosure_ft < 0.1:
            closure_score = 0.7
        else:
            closure_score = 0.5
    else:
        closure_score = max(0.0, 0.3 - result.misclosure_ft * 0.02)

    # Verification checks (20%)
    if result.checks:
        checks_passed = sum(
            check.status == "passed"
            for check in result.checks
            if check.name in {"interior_angles", "curve_consistency"}
        )
    else:
        checks_passed = sum([result.angle_check_passed, result.curve_consistency_passed])
    checks_score = checks_passed / 2.0

    # Bearing completeness (25%)
    complete = sum(1 for c in calls if has_determined_direction(c))
    bearing_score = complete / len(calls)

    # Call quality (15%)
    qualities = [score_call_quality(c) for c in calls]
    quality_weights = {"high": 1.0, "medium": 0.6, "low": 0.2}
    quality_score = sum(quality_weights[q] for q in qualities) / len(calls)

    # Warning penalty (10%)
    warning_score = max(0.0, 1.0 - len(result.warnings) * 0.2)

    weighted = (
        closure_score * 0.30
        + checks_score * 0.20
        + bearing_score * 0.25
        + quality_score * 0.15
        + warning_score * 0.10
    )

    return max(0.0, min(1.0, weighted))
