"""Extract individual deed calls from legal descriptions.

Parses normalized text to create structured DeedCall objects.
Rule-based extraction -- no AI/LLM involved.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re

import structlog
from mp_bearing import (
    COMPASS_POINTS,
    QUADRANT_PATTERN,
    bearing_to_azimuth,
    calculate_curve_properties,
    calculate_deltas,
    degree_of_curvature_to_radius,
    due_cardinal_to_azimuth,
    parse_packed_dms,
    parse_quadrant_bearing,
    quadrant_to_azimuth,
)
from mp_models import (
    AuditContext,
    CallAudit,
    ConversionFactors,
    CurveDirection,
    CurveType,
    Decision,
    DeedCall,
    Tract,
    Transformation,
)
from pydantic import ValidationError

from .metadata import (
    UNSUPPORTED_COMPOUND_PATTERN,
    detect_meander,
    extract_along_to_fields,
    extract_distance,
    extract_witness_trees,
    is_closure_to_pob,
    is_indefinite_call,
    split_exception_clauses,
    split_into_calls,
)
from .monuments import (
    MONUMENT_PATTERNS,
    classify_monument,
    classify_monument_status,
)
from .normalizer import normalize_legal_description, standardize_cardinal_directions
from .numbers import COMMA_NUMBER, parse_comma_number

logger = structlog.get_logger(__name__)

_CARDINAL_ONLY_PATTERN = re.compile(
    r"(north|south|east|west|northeast|northwest|southeast|southwest|NE|NW|SE|SW)(?:erly|wardly)?",
    re.IGNORECASE,
)

_UNIT_TOKEN = (
    r"(?:US\s+survey\s+(?:feet|foot)|engineer\s+chains?|engineer\s+links?"
    r"|feet|foot|ft|poles?|rods?|perches?|chains?|links?"
    r"|varas?|arpents?|toises?|furlongs?|meters?|miles?)"
)

PACKED_DMS_PATTERN = re.compile(
    r"(N|S)\s+(\d{1,3}\.\d+)\u00b0\s*(E|W)",
    re.IGNORECASE,
)

CURVE_PATTERN = re.compile(
    rf"curve\s+to\s+the\s+(left|right).*?radius\s+of\s+({COMMA_NUMBER})\s*({_UNIT_TOKEN})?.*?"
    rf"(?:delta\s+(?:angle\s+)?of\s+)?({COMMA_NUMBER})(?:\u00b0|\s+degrees?)(?:\s*({COMMA_NUMBER})(?:'|\s+minutes?))?(?:\s*({COMMA_NUMBER})(?:\"|\s+seconds?))?",
    re.IGNORECASE | re.DOTALL,
)


def _normalize_unit_token(token: str | None) -> str:
    """Normalize a captured unit token to a ConversionFactors-compatible key."""
    if token is None:
        return "feet"
    t = " ".join(token.strip().lower().split())
    if t in ("ft", "feet", "foot", ""):
        return "feet"
    if t in ("pole", "poles"):
        return "poles"
    if t in ("rod", "rods"):
        return "rods"
    if t in ("perch", "perches"):
        return "perches"
    if t in ("chain", "chains"):
        return "chains"
    if t in ("link", "links"):
        return "links"
    if t in ("engineer chain", "engineer chains"):
        return "engineer_chains"
    if t in ("engineer link", "engineer links"):
        return "engineer_links"
    if t in ("us survey foot", "us survey feet"):
        return "us_survey_feet"
    if t in ("vara", "varas"):
        return "varas"
    if t in ("arpent", "arpents"):
        return "arpents"
    if t in ("toise", "toises"):
        return "toises"
    if t in ("furlong", "furlongs"):
        return "furlongs"
    if t in ("meter", "meters"):
        return "meters"
    if t in ("mile", "miles"):
        return "miles"
    return "feet"


# "...to a point corner to X, which last mentioned point is the place of beginning":
# the course ends at the true POB, so it and the courses before it (back to the
# previous closing course) are tie lines.
_RESTATED_POB_PATTERN = re.compile(
    r"\blast\s+mentioned\s+point\s+is\s+the\s+(?:place|point)\s+of\s+beginning\b",
    re.IGNORECASE,
)
_CLOSES_TO_POB_PATTERN = re.compile(
    r"\b(?:to|for)\s+(?:the\s+|a\s+)?(?:(?:point|place)\s+(?:and\s+place\s+)?of\s+)?beginning\b",
    re.IGNORECASE,
)


def _mark_restated_pob_tie_lines(calls: list[DeedCall], call_texts: list[str]) -> list[DeedCall]:
    """Mark courses leading to a restated place of beginning as tie lines."""
    segment_start = 0
    tie_end: tuple[int, int] | None = None
    for i, call_text in enumerate(call_texts):
        if _CLOSES_TO_POB_PATTERN.search(call_text):
            segment_start = i + 1
        elif _RESTATED_POB_PATTERN.search(call_text):
            tie_end = (segment_start, i)
    if tie_end is None:
        return calls
    start, end = tie_end
    return [
        call.model_copy(update={"is_tie_in": True}) if start <= i <= end else call
        for i, call in enumerate(calls)
    ]


# "said point being the following two courses and distances from the intersection":
# the first courses run from the reference point to the POB, so they are tie lines.
_PREAMBLE_TIE_COURSES_PATTERN = re.compile(
    r"\bbeing\s+the\s+following\s+(?:(\w+)(?:\s+\(\d+\))?\s+)?courses?\s+and\s+distances?\s+from\b",
    re.IGNORECASE,
)
_COUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}

# "Commencing at the corner of Lot 15; thence ... for the point of beginning; thence ...":
# the courses from the commencement point to the POB are tie lines.
_COMMENCEMENT_PATTERN = re.compile(r"\b(?:COMMENCING|STARTING)\s+at\b", re.IGNORECASE)


def _preamble_tie_course_count(preamble: str, call_texts: list[str]) -> int:
    """Return how many leading courses the preamble says lead to the POB.

    Without a count ("the following courses and distances from", or a commencement
    point), the tie courses end at the first course reaching the place of beginning while
    more courses follow.
    """
    match = _PREAMBLE_TIE_COURSES_PATTERN.search(preamble)
    if not match and not _COMMENCEMENT_PATTERN.search(preamble):
        return 0
    if match is None or match.group(1) is None:
        return next(
            (
                i + 1
                for i, text in enumerate(call_texts[:-1])
                if _CLOSES_TO_POB_PATTERN.search(text)
            ),
            0,
        )
    count = match.group(1).lower()
    return int(count) if count.isdigit() else _COUNT_WORDS.get(count, 0)


def _mark_preamble_tie_courses(calls: list[DeedCall], count: int) -> list[DeedCall]:
    """Mark the leading courses the preamble counts as tie lines."""
    if not count or count >= len(calls):
        return calls
    return [
        call.model_copy(update={"is_tie_in": True}) if i < count else call
        for i, call in enumerate(calls)
    ]


# "Commencing at the corner; thence along the South line 505.00 feet; thence ... to the point
# of beginning": when the point of beginning is never stated, the leading courses reaching it
# are found by closure: the fewest whose removal lets the remaining 3+ courses close.
_LOOSE_COMMENCEMENT_PATTERN = re.compile(r"\b(?:COMMENCING|STARTING)\b", re.IGNORECASE)
_INFERRED_TIE_TOLERANCE_FT = 0.01
_INFERRED_TIE_REASON = "tie course inferred from closure: the point of beginning is not stated"


def _straight_misclosure_ft(calls: list[DeedCall]) -> float | None:
    """Return the misclosure of straight courses, or None if a course is a curve or has no bearing."""
    dx = dy = 0.0
    for call in calls:
        azimuth = call.bearing_azimuth_deg_from_north
        if azimuth is None or call.curve_dir is not None:
            return None
        course_dx, course_dy = calculate_deltas(azimuth, call.distance_ft)
        dx += course_dx
        dy += course_dy
    return math.hypot(dx, dy)


def _inferred_tie_course_count(preamble: str, calls: list[DeedCall], call_texts: list[str]) -> int:
    """Return how many leading courses reach an unstated point of beginning, found by closure."""
    if not _LOOSE_COMMENCEMENT_PATTERN.search(preamble) or any(call.is_tie_in for call in calls):
        return 0
    if not call_texts or not _CLOSES_TO_POB_PATTERN.search(call_texts[-1]):
        return 0
    if any(_CLOSES_TO_POB_PATTERN.search(text) for text in call_texts[:-1]):
        return 0
    full = _straight_misclosure_ft(calls)
    if full is not None and full < _INFERRED_TIE_TOLERANCE_FT:
        return 0
    for count in range(1, len(calls) - 2):
        remainder = _straight_misclosure_ft(calls[count:])
        if remainder is not None and remainder < _INFERRED_TIE_TOLERANCE_FT:
            return count
    return 0


def _mark_inferred_tie_courses(
    calls: list[DeedCall], count: int, audits: list[CallAudit] | None
) -> list[DeedCall]:
    """Mark the leading courses as inferred tie lines, noting and auditing the inference."""
    for i in range(count):
        if audits is not None:
            audits[i] = audits[i].model_copy(
                update={
                    "decisions": [
                        *audits[i].decisions,
                        Decision(
                            field="is_tie_in",
                            value="true",
                            reason=_INFERRED_TIE_REASON,
                            alternatives=["false"],
                            confidence=0.8,
                        ),
                    ],
                    "flags": [*audits[i].flags, "tie_inferred_from_closure"],
                }
            )
    return [
        call.model_copy(
            update={
                "is_tie_in": True,
                "notes": "; ".join(filter(None, [call.notes, _INFERRED_TIE_REASON])),
            }
        )
        if i < count
        else call
        for i, call in enumerate(calls)
    ]


# "thence", "thence:" or "thence from the beginning point;" before the first numbered course
_STANDALONE_THENCE = (
    r"\s*THENCE(?:\s+from\s+the\s+(?:beginning\s+point|point\s+of\s+beginning))?\s*[:;]?\s*"
)

# "thence along the line of lands of X, the following two courses and distances;" introduces
# the next courses and carries none itself
_COURSE_INTRO_PATTERN = re.compile(
    r"\bthe\s+following\s+(?:\w+\s+)?(?:\(\d+\)\s+)?courses?(?:\s+and\s+distances?)?\s*[:;,.]?\s*$",
    re.IGNORECASE,
)

# "BEING Lot 1.01, Block 21 on the tax map ... Kings Highway East": with no THENCE, numbered
# course, distance, bearing or curve, a lot reference describes no courses.
_NUMBERED_COURSE_MARKER = re.compile(
    r"(?:^|\n)\s*(?:\(\d+\)|\([A-Za-z]\)|\d+[.)])\s+", re.MULTILINE
)
_COURSE_EVIDENCE = re.compile(
    rf"\bTHENCE\b|{COMMA_NUMBER}\s*(?:{_UNIT_TOKEN}\b|')"
    r"|\b[NS]\s*\d{1,3}\s*°|\bdue\s+(?:north|south|east|west)\b|\bcurv",
    re.IGNORECASE,
)


def _describes_no_courses(text: str) -> bool:
    """Return whether text is a lot reference with nothing that could be a course."""
    return not (_NUMBERED_COURSE_MARKER.search(text) or _COURSE_EVIDENCE.search(text))


def _call_preview(call_text: str, max_len: int = 120) -> str:
    """Return a compact single-line preview suitable for warning logs."""
    compact = " ".join(call_text.split())
    if len(compact) <= max_len:
        return compact
    return f"{compact[: max_len - 3]}..."


def _call_hash(call_text: str) -> str:
    """Stable short hash for correlating call text without logging full content."""
    return hashlib.sha256(call_text.encode("utf-8")).hexdigest()[:12]


def _is_debug_logging_enabled() -> bool:
    return logging.getLogger(__name__).isEnabledFor(logging.DEBUG)


# "...551.39 feet to a point on the Westerly line, said point also being a point on a
# non-tangential curve to the left": the endpoint lies on the next course's curve.
_ENDPOINT_ON_CURVE = re.compile(
    r",?\s*said\s+point\s+(?:also\s+)?being\s+(?:a\s+point\s+)?on\s+(?:a|the)\s+[^;]*?\bcurve\b.*",
    re.IGNORECASE | re.DOTALL,
)


def _boundary_course_text(call_text: str) -> str:
    """Remove bearing references that describe a corner instead of the course."""
    starts = [
        match.start()
        for match in re.finditer(
            r"\b(?:from\s+which|witness(?:\s+(?:tree|mark|corner))?|"
            r"reference\s+(?:tree|mark))\b",
            call_text,
            re.IGNORECASE,
        )
    ]
    lowered = call_text.lower()
    for witness in extract_witness_trees(call_text):
        position = lowered.find(witness.lower())
        if position >= 0:
            starts.append(position)
    if not starts:
        return call_text
    return call_text[: min(starts)]


def _is_initial_course_prefix(prefix: str) -> bool:
    """Return whether text before THENCE starts with a supported bearing."""
    candidate = re.sub(r"^\s*(?:(?:\(\d+\)|\([A-Za-z]\)|\d+[.)])\s*)?", "", prefix)
    if PACKED_DMS_PATTERN.match(candidate):
        return True

    try:
        direction = extract_direction(candidate)
    except ValueError:
        return False
    if not direction or not candidate.lstrip().lower().startswith(direction.lower()):
        return False
    if _CARDINAL_ONLY_PATTERN.fullmatch(direction):
        remainder = candidate.lstrip()[len(direction) :]
        return bool(re.match(rf"\s+{COMMA_NUMBER}(?:\s|$)", remainder))
    return bool(parse_quadrant_bearing(direction) or due_cardinal_to_azimuth(direction) is not None)


def _trailing_thence_course(prefix: str) -> str:
    """Return the course ending the preamble when courses end with "thence".

    "...Burnt Mill Road. N 40°41'31\" E a distance of 483.13 feet to a point thence;"
    """
    boundaries = list(re.finditer(r"[.;:]\s+|\n", prefix))
    tail = prefix[boundaries[-1].end() :] if boundaries else ""
    if not tail.strip():
        return ""
    return tail if _is_initial_course_prefix(tail) or _is_marked_bearing_course(tail) else ""


def _is_marked_bearing_course(text: str) -> bool:
    """Return whether text is a lettered/numbered course stating a bearing ("(A) Along X, N 73° W")."""
    if not re.match(r"\s*(?:\(\d+\)|\([A-Za-z]\)|\d+[.)])\s", text):
        return False
    try:
        direction = extract_direction(text)
    except ValueError:
        return False
    return bool(direction and parse_quadrant_bearing(direction))


def _extract_calls_from_text(
    text: str,
    distance_unit: str = "feet",
    *,
    audit_context: AuditContext | None = None,
    strict: bool = True,
    course_start: int = 1,
) -> list[DeedCall]:
    """Extract all calls from normalized legal description text.

    Handles exception clauses (EXCEPT, LESS AND EXCEPT, ALSO, INCLUDING)
    and marks calls accordingly.

    Args:
        text: Normalized legal description text (should already be normalized)
        distance_unit: Primary distance unit (feet, poles, etc.)
        audit_context: Optional audit context for recording parsing decisions
        strict: Raise with course context when a geometric course is malformed.

    Returns:
        List of DeedCall objects
    """
    # Callers pass normalized text; normalizing again is not idempotent (the
    # "and <bearing>" separator rule would then see already-converted bearings).
    tracts = split_exception_clauses(text)

    calls: list[DeedCall] = []
    course_num = course_start

    for tract_text, is_exception_tract in tracts:
        tract_calls: list[DeedCall] = []
        tract_call_texts: list[str] = []
        # Remove a recognized commencement/POB preamble. A description may
        # legitimately begin with its first course and introduce THENCE later.
        thence_match = re.search(r"\bTHENCE\b", tract_text, re.IGNORECASE)
        has_thence_marker = thence_match is not None
        prefix = tract_text[: thence_match.start()] if thence_match else ""
        # "(1) Along ..., N 32°22'34\" W, 41.23 feet to a point in same;" may come before the
        # first THENCE: the courses then start at the first numbered course.
        first_marker = re.search(
            r"(?:^|\n)\s*(?:\(\d+\)|\([A-Za-z]\)|\d+[.)])\s+", tract_text, re.MULTILINE
        )
        numbered_before_thence = bool(
            thence_match and first_marker and first_marker.start() < thence_match.start()
        )
        if numbered_before_thence and first_marker:
            prefix = tract_text[: first_marker.start()]
        if _describes_no_courses(tract_text):
            continue
        has_beginning_preamble = re.match(
            r"\s*(?:BEGINNING|COMMENCING|POINT\s+OF\s+BEGINNING|POB|TPOB|RPOB)\b",
            prefix,
            re.IGNORECASE,
        )
        has_initial_course = bool(thence_match and _is_initial_course_prefix(prefix))
        if (
            thence_match
            and not numbered_before_thence
            and (has_beginning_preamble or not has_initial_course)
        ):
            tract_text = _trailing_thence_course(prefix) + tract_text[thence_match.start() :]

        has_numbered_course_markers = bool(
            re.search(r"(?:^|\n)\s*(?:\(\d+\)|\([A-Za-z]\)|\d+[.)])\s+", tract_text, re.MULTILINE)
        )
        call_texts = split_into_calls(tract_text)

        for source_course, call_text in enumerate(call_texts, start=1):
            try:
                call = extract_single_call(
                    call_text, course=course_num, distance_unit=distance_unit
                )
            except (ValidationError, ValueError, TypeError) as exc:
                if strict:
                    raise ValueError(
                        f"Malformed course {source_course}: {call_text.strip()!r}: {exc}"
                    ) from exc
                payload = {
                    "course": course_num,
                    "call_preview": _call_preview(call_text),
                    "call_hash": _call_hash(call_text),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                }
                if _is_debug_logging_enabled():
                    logger.warning(
                        "Skipping malformed call",
                        **payload,
                        call_text=call_text,
                        exc_info=exc,
                    )
                else:
                    logger.warning("Skipping malformed call", **payload)
                continue

            if call is None:
                standalone_thence = re.fullmatch(
                    _STANDALONE_THENCE, call_text, re.I
                ) or _COURSE_INTRO_PATTERN.search(call_text)
                explicit_course = not standalone_thence and (
                    has_thence_marker or has_numbered_course_markers
                )
                if strict and (
                    explicit_course
                    or extract_direction(call_text)
                    or re.search(r"\b(?:[NSEW])\s+\d", call_text, re.I)
                    or re.search(r"\b(?:curv(?:e|ed|ing)|spiral|transition)\b", call_text, re.I)
                ):
                    raise ValueError(f"Malformed course {source_course}: {call_text.strip()!r}")
                continue

            if is_exception_tract:
                call = call.model_copy(update={"is_exception": True})
            tract_calls.append(call)
            tract_call_texts.append(call_text)

            if audit_context is not None:
                transformations, decisions, flags = _audit_single_call(call_text, call)
                audit_context.call_audits.append(
                    CallAudit(
                        course=course_num,
                        source_excerpt=call_text,
                        transformations=transformations,
                        decisions=decisions,
                        flags=flags,
                    )
                )

            course_num += 1

        tract_calls = _mark_preamble_tie_courses(
            tract_calls, _preamble_tie_course_count(prefix, tract_call_texts)
        )
        tract_calls = _mark_restated_pob_tie_lines(tract_calls, tract_call_texts)
        inferred_ties = _inferred_tie_course_count(prefix, tract_calls, tract_call_texts)
        if inferred_ties:
            audits = (
                audit_context.call_audits[len(audit_context.call_audits) - len(tract_calls) :]
                if audit_context is not None
                else None
            )
            tract_calls = _mark_inferred_tie_courses(tract_calls, inferred_ties, audits)
            if audit_context is not None and audits is not None:
                audit_context.call_audits[len(audit_context.call_audits) - len(tract_calls) :] = (
                    audits
                )
        calls.extend(tract_calls)

    return calls


def extract_calls(
    text: str,
    distance_unit: str = "feet",
    *,
    audit_context: AuditContext | None = None,
    strict: bool = True,
) -> tuple[list[DeedCall], list[Tract]]:
    """Extract all calls from normalized legal description text.

    Handles multi-tract deeds (TRACT markers, multiple BEGINNINGs,
    EXCEPT/ALSO clauses) and marks calls accordingly.

    Args:
        text: Normalized legal description text (should already be normalized)
        distance_unit: Primary distance unit (feet, poles, etc.)
        audit_context: Optional audit context for recording parsing decisions
        strict: Raise with course context when a geometric course is malformed.

    Returns:
        Tuple of (flat_calls, tracts).
        - For single-tract deeds: flat_calls populated, tracts is empty list.
        - For multi-tract deeds: flat_calls is the merged list, tracts has
          per-tract Tract objects with independent call lists.
    """
    from mp_models import Tract, TractType

    from .tracts import split_into_tracts

    normalized = normalize_legal_description(text)
    segments = split_into_tracts(normalized)

    # Single-tract fast path: preserve backward-compatible behavior
    if len(segments) == 1 and segments[0][2] == TractType.MAIN:
        flat_calls = _extract_calls_from_text(
            normalized, distance_unit, audit_context=audit_context, course_start=1, strict=strict
        )
        return flat_calls, []

    # Multi-tract path
    all_calls: list[DeedCall] = []
    tract_objects: list[Tract] = []

    for segment_text, label, tract_type in segments:
        tract_calls = _extract_calls_from_text(
            segment_text, distance_unit, audit_context=audit_context, course_start=1, strict=strict
        )

        # A lot reference ("LOT 48 EXCLUDING THAT PART ...") has no courses to compute.
        if not tract_calls and strict and not _describes_no_courses(segment_text):
            raise ValueError(f"Tract {label!r} has no computable calls")
        if not tract_calls:
            logger.warning(
                "Empty tract after extraction — segment dropped",
                tract_label=label,
                tract_type=tract_type.value,
                segment_length=len(segment_text),
                segment_preview=segment_text[:120],
            )
            continue

        if tract_type == TractType.EXCEPTION:
            tract_calls = [c.model_copy(update={"is_exception": True}) for c in tract_calls]

        tract = Tract(
            label=label,
            tract_type=tract_type,
            calls=tract_calls,
        )
        tract_objects.append(tract)
        all_calls.extend(tract_calls)

    return all_calls, tract_objects


def extract_single_call(
    call_text: str, course: int, distance_unit: str = "feet"
) -> DeedCall | None:
    """Extract a single call from text.

    Args:
        call_text: Text for one call
        course: Course number
        distance_unit: Primary distance unit

    Returns:
        DeedCall object or None if parsing fails
    """
    if re.match(r"^\s*(BEGINNING|COMMENCING|POB)\b", call_text, re.IGNORECASE):
        return None

    raw_direction = extract_direction(_boundary_course_text(call_text))
    direction_text = raw_direction if raw_direction else call_text.strip()

    bearing_quadrant = None
    azimuth = None

    is_due_cardinal = False
    parsed_bearing = parse_quadrant_bearing(raw_direction) if raw_direction else None
    if parsed_bearing:
        cardinal1, degrees, cardinal2 = parsed_bearing
        deg_int = int(degrees)
        minutes = (degrees - deg_int) * 60

        rounded_minutes = round(minutes)
        if rounded_minutes >= 60:
            rounded_minutes = 0
            deg_int += 1

        bearing_quadrant = f"{cardinal1} {deg_int}\u00b0{rounded_minutes:02d}' {cardinal2}"
        azimuth = quadrant_to_azimuth(cardinal1, degrees, cardinal2)
    else:
        # Try "due {cardinal}" before giving up
        due_az = due_cardinal_to_azimuth(raw_direction) if raw_direction else None
        if due_az is not None:
            azimuth = due_az
            is_due_cardinal = True
            bearing_quadrant = None  # no quadrant form for due-cardinal
        else:
            bearing_quadrant = None
            azimuth = None

    course_text = _boundary_course_text(call_text)
    distance, unit = extract_distance(course_text)
    if distance == 0:
        if UNSUPPORTED_COMPOUND_PATTERN.search(course_text):
            raise ValueError("Unsupported component in compound course distance")
        distance = extract_distance_alternate(course_text)
        unit = distance_unit

    distance_ft = ConversionFactors.convert_to_feet(distance, unit)

    curve_info = extract_curve_info(_ENDPOINT_ON_CURVE.sub("", call_text))

    has_abbreviated_cardinal = bool(
        re.match(r"^\s*(?:N|S|E|W|NE|NW|SE|SW)\b", call_text, re.IGNORECASE)
    )
    has_curve_geometry = any(
        curve_info.get(key) is not None
        for key in ("radius_ft", "delta_deg", "arc_length_ft", "chord_length_ft")
    )
    has_boundary_endpoint = bool(
        re.search(
            r"\bto\s+(?:(?:a|an|the)\s+)?(?:point|corner|pin|rod|monument|stone|stake)\b",
            call_text,
            re.IGNORECASE,
        )
    )
    if (
        not raw_direction
        and not has_abbreviated_cardinal
        and not has_curve_geometry
        and not has_boundary_endpoint
        and not detect_meander(call_text)
    ):
        return None

    arc_length_ft = curve_info.get("arc_length_ft")
    if isinstance(arc_length_ft, float) and arc_length_ft > 0.0:
        distance_ft = arc_length_ft
    elif curve_info.get("radius_ft") is not None and curve_info.get("delta_deg") is not None:
        radius_ft = curve_info.get("radius_ft")
        delta_deg = curve_info.get("delta_deg")
        if isinstance(radius_ft, float) and isinstance(delta_deg, float):
            props = calculate_curve_properties(radius_ft, delta_deg=delta_deg)
        else:
            raise ValueError("Curve info missing numeric radius/delta")
        arc_length_ft = props["arc_length_ft"]
        if arc_length_ft is None:
            raise ValueError("Curve props missing arc length")
        if arc_length_ft > 0.0:
            distance_ft = arc_length_ft
        curve_info.setdefault("arc_length_ft", props["arc_length_ft"])
        curve_info.setdefault("chord_length_ft", props["chord_length_ft"])

    if distance_ft <= 0.0:
        raise ValueError("Missing boundary course distance")

    along, to = extract_along_to_fields(call_text)

    monument_type = classify_monument(to) if to else None
    monument_status = classify_monument_status(to or call_text)
    is_meander = detect_meander(call_text)

    notes = ""
    cardinal_only = False
    if raw_direction and not parsed_bearing and not is_due_cardinal:
        if _CARDINAL_ONLY_PATTERN.fullmatch(raw_direction.strip()):
            cardinal_only = True

    if is_meander or "approximate" in call_text.lower():
        notes = "meander / approximate"
    elif not parsed_bearing and not is_due_cardinal:
        notes = "incomplete bearing - cardinal only" if cardinal_only else "incomplete bearing"

    if distance_ft <= 0.0:
        return None

    has_curve = bool(curve_info.get("direction") or curve_info.get("radius_ft"))
    has_direction_intent = bool(
        raw_direction
        or parsed_bearing
        or has_curve
        or along
        or is_meander
        or re.search(r"\b[NS]\s+\d+\u00b0", call_text)
    )
    if not has_direction_intent:
        payload = {
            "course": course,
            "distance_ft": distance_ft,
            "call_preview": _call_preview(call_text),
            "call_hash": _call_hash(call_text),
        }
        if _is_debug_logging_enabled():
            logger.warning("Rejecting bearingless non-curve call", **payload, call_text=call_text)
        else:
            logger.warning("Rejecting bearingless non-curve call", **payload)
        return None

    curve_dir = curve_info.get("direction")
    curve_direction: CurveDirection | None
    if curve_dir == "left":
        curve_direction = "left"
    elif curve_dir == "right":
        curve_direction = "right"
    else:
        curve_direction = None

    radius_value = curve_info.get("radius_ft")
    radius_ft = radius_value if isinstance(radius_value, float) else None

    delta_value = curve_info.get("delta_deg")
    delta_deg = delta_value if isinstance(delta_value, float) else None

    arc_length_value = curve_info.get("arc_length_ft")
    arc_length_ft = arc_length_value if isinstance(arc_length_value, float) else None

    chord_bearing_value = curve_info.get("chord_bearing")
    chord_bearing = chord_bearing_value if isinstance(chord_bearing_value, str) else None

    chord_length_value = curve_info.get("chord_length_ft")
    chord_length_ft = chord_length_value if isinstance(chord_length_value, float) else None

    radial_bearing_value = curve_info.get("radial_bearing")

    is_indefinite = is_indefinite_call(
        direction_text, has_bearing=parsed_bearing is not None or is_due_cardinal
    )

    curve_type_value = curve_info.get("curve_type")
    curve_type: CurveType | None = None
    if isinstance(curve_type_value, str):
        normalized_curve_type = curve_type_value.strip().lower()
        if normalized_curve_type == "simple":
            curve_type = "simple"
        elif normalized_curve_type == "compound":
            curve_type = "compound"
        elif normalized_curve_type == "reverse":
            curve_type = "reverse"
        elif normalized_curve_type == "spiral":
            curve_type = "spiral"
    if curve_direction is not None and curve_type is None:
        curve_type = "simple"

    call = DeedCall(
        course=course,
        direction_text=direction_text,
        bearing_quadrant=bearing_quadrant,
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance_ft,
        curve_dir=curve_direction,
        radius_ft=radius_ft,
        delta_deg=delta_deg,
        arc_length_ft=arc_length_ft,
        chord_bearing=chord_bearing,
        chord_length_ft=chord_length_ft,
        along=along if along else None,
        to=to if to else None,
        monument_type=monument_type,
        monument_status=monument_status,
        is_exception=False,
        non_tangent=bool(curve_info.get("non_tangent", False)),
        radial_bearing=(radial_bearing_value if isinstance(radial_bearing_value, str) else None),
        is_meander=is_meander,
        is_tie_in=False,
        is_indefinite=is_indefinite,
        curve_type=curve_type,
        notes=notes if notes else None,
    )

    return call


def _audit_single_call(
    call_text: str,
    call: DeedCall,
) -> tuple[list[Transformation], list[Decision], list[str]]:
    """Build audit data for a successfully parsed call.

    This is a pure function that inspects the parsed call and original text
    to construct transformation, decision, and flag lists for the audit trail.

    Args:
        call_text: Original text of the call
        call: The successfully parsed DeedCall

    Returns:
        Tuple of (transformations, decisions, flags)
    """
    transformations: list[Transformation] = []
    decisions: list[Decision] = []
    flags: list[str] = []

    # --- Bearing transformation ---
    raw_direction = extract_direction(_boundary_course_text(call_text))
    if raw_direction:
        transformations.append(
            Transformation(
                step="extract_bearing",
                input=raw_direction,
                output=call.bearing_quadrant or "none",
            )
        )

    # --- Azimuth transformation ---
    if call.bearing_quadrant and call.bearing_azimuth_deg_from_north is not None:
        parsed = parse_quadrant_bearing(raw_direction)
        rule_str = None
        if parsed:
            cardinal1, degrees, cardinal2 = parsed
            rule_str = f"quadrant_to_azimuth: {cardinal1} {degrees} {cardinal2}"
        transformations.append(
            Transformation(
                step="compute_azimuth",
                input=call.bearing_quadrant,
                output=str(call.bearing_azimuth_deg_from_north),
                rule=rule_str,
            )
        )

    # --- Distance transformation ---
    distance, unit = extract_distance(call_text)
    distance_input = f"{distance} {unit}" if distance > 0 else call_text.strip()
    transformations.append(
        Transformation(
            step="extract_distance",
            input=distance_input,
            output=str(call.distance_ft),
        )
    )

    # --- Monument classification transformation ---
    if call.to and call.monument_type:
        # Find which pattern matched
        matched_rule = None
        to_lower = call.to.lower()
        for pattern, _mtype in MONUMENT_PATTERNS:
            if re.search(pattern, to_lower):
                matched_rule = pattern
                break
        transformations.append(
            Transformation(
                step="classify_monument",
                input=call.to,
                output=call.monument_type,
                rule=matched_rule,
            )
        )

    # --- Bearing decision ---
    if call.bearing_azimuth_deg_from_north is not None:
        decisions.append(
            Decision(
                field="bearing_azimuth_deg_from_north",
                value=str(call.bearing_azimuth_deg_from_north),
                reason="exact quadrant bearing parsed",
                confidence=0.95,
            )
        )

    # --- Monument type decision ---
    if call.monument_type:
        confidence = 0.60 if call.monument_type == "other" else 0.90
        decisions.append(
            Decision(
                field="monument_type",
                value=call.monument_type,
                reason="keyword pattern match",
                confidence=confidence,
            )
        )

    # --- Monument status decision ---
    if call.monument_status:
        decisions.append(
            Decision(
                field="monument_status",
                value=call.monument_status,
                reason="explicit found/set keyword",
                confidence=0.95,
            )
        )

    # --- Flags ---
    is_due = due_cardinal_to_azimuth(raw_direction) is not None if raw_direction else False
    cardinal_only = False
    if raw_direction and not call.bearing_quadrant and not is_due:
        if _CARDINAL_ONLY_PATTERN.fullmatch(raw_direction.strip()):
            cardinal_only = True

    if not is_due and (cardinal_only or (raw_direction and not call.bearing_quadrant)):
        flags.append("incomplete_bearing")

    if call.is_indefinite:
        flags.append("indefinite")

    if call.is_meander:
        flags.append("meander")

    return transformations, decisions, flags


def extract_direction(text: str) -> str:
    """Extract direction/bearing from call text.

    Args:
        text: Call text

    Returns:
        Direction string (e.g., "S 56 deg 40' W" or "southwesterly")
    """
    packed_match = PACKED_DMS_PATTERN.search(text)
    quadrant_match = QUADRANT_PATTERN.search(text)
    if quadrant_match and not packed_match:
        return str(quadrant_match.group(0))

    if packed_match:
        cardinal1 = packed_match.group(1).upper()
        packed_value = float(packed_match.group(2))
        cardinal2 = packed_match.group(3).upper()
        decimal_degrees = parse_packed_dms(packed_value)
        total_seconds = round(decimal_degrees * 3600, 4)
        degree, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        seconds_text = f"{seconds:.4f}".rstrip("0").rstrip(".")
        if seconds < 10:
            seconds_text = f"0{seconds_text}"
        return f"{cardinal1} {int(degree)}\u00b0{int(minutes):02d}'{seconds_text}\" {cardinal2}"

    # "due {cardinal}" check -- must come before simple cardinal so "due North"
    # is captured as the full phrase, not truncated to "north".
    due_cardinal_match = re.search(
        r"\bdue\s+(north|south|east|west|N|S|E|W)\b",
        text,
        re.IGNORECASE,
    )
    if due_cardinal_match:
        return due_cardinal_match.group(0).lower()

    # "due {cardinal}" check -- must come before simple cardinal so "due North"
    # is captured as the full phrase, not truncated to "north".
    due_cardinal_match = re.search(
        r"\bdue\s+(north|south|east|west|N|S|E|W)\b",
        text,
        re.IGNORECASE,
    )
    if due_cardinal_match:
        return due_cardinal_match.group(0).lower()

    # Compound compass point check (32-point system) -- must come before
    # simple cardinal check so "North by East" is not truncated to "North"
    compound_compass_names = sorted(
        [name for name in COMPASS_POINTS if " " in name or "-" in name],
        key=len,
        reverse=True,
    )
    compound_compass_regex = (
        r"\b(" + "|".join(re.escape(name) for name in compound_compass_names) + r")\b"
    )
    compound_compass_match = re.search(compound_compass_regex, text, re.IGNORECASE)
    if compound_compass_match:
        return compound_compass_match.group(0).lower()

    cardinal_pattern = (
        r"\b(north(?:erly|wardly)?|south(?:erly|wardly)?|east(?:erly|wardly)?|west(?:erly|wardly)?|"
        r"northeast(?:erly|wardly)?|northwest(?:erly|wardly)?|southeast(?:erly|wardly)?|southwest(?:erly|wardly)?)\b"
    )

    cardinal_match = re.search(cardinal_pattern, text, re.IGNORECASE)
    if cardinal_match:
        return cardinal_match.group(0).lower()

    # Abbreviated cardinal directions (NW, SW, NE, SE) from LLM normalization
    abbrev_match = re.search(r"\b(NE|NW|SE|SW)\b", text, re.IGNORECASE)
    if abbrev_match:
        return abbrev_match.group(0).lower()

    return ""


def extract_distance_alternate(text: str) -> float:
    """Extract distance using alternate patterns.

    Some deeds use formats like "125.26' along..." instead of "125.26 feet".

    Args:
        text: Call text

    Returns:
        Distance value (0.0 if not found)
    """
    feet_match = re.search(rf"({COMMA_NUMBER})\s*(?:feet|ft)\b", text, re.IGNORECASE)
    if feet_match:
        return parse_comma_number(feet_match.group(1))

    apostrophe_match = re.search(
        r"(?<!\u00b0)(\d+(?:\.\d+)?)\s*'(?=(?:\s+(?:along|to)\b|[.,;)]|$))",
        text,
        re.IGNORECASE,
    )
    if apostrophe_match:
        prefix = text[: apostrophe_match.end()]
        if re.search(
            r"\b(?:NORTH|SOUTH|N|S)\s+\d{1,3}\s+\d+(?:\.\d+)?\s*\x27\s*$",
            prefix,
            re.IGNORECASE,
        ):
            return 0.0
        if re.search(
            r"\d+\u00b0\s*\d+(?:\.\d+)?\s*\x27\s*$",
            prefix,
        ):
            return 0.0
        return float(apostrophe_match.group(1))

    return 0.0


def extract_curve_info(text: str) -> dict[str, float | str | None]:
    """Extract curve information from call text.

    Args:
        text: Call text

    Returns:
        Dict with curve properties (empty if no curve)
    """
    curve_info: dict[str, float | str | None] = {}

    if not re.search(r"\b(?:curv(?:e|ed|ing)|spiral|transition)\b", text, re.IGNORECASE):
        return curve_info

    match = CURVE_PATTERN.search(text)
    if match:
        direction = match.group(1).lower()
        radius_raw = parse_comma_number(match.group(2))
        radius_unit = _normalize_unit_token(match.group(3))
        radius = ConversionFactors.convert_to_feet(radius_raw, radius_unit)
        delta_deg = parse_comma_number(match.group(4))

        if match.group(5):
            delta_deg += parse_comma_number(match.group(5)) / 60.0
        if match.group(6):
            delta_deg += parse_comma_number(match.group(6)) / 3600.0

        arc_length_match = re.search(
            rf"arc\s+(?:length|distance)\s+(?:of\s+)?({COMMA_NUMBER})\s*({_UNIT_TOKEN})?",
            text,
            re.IGNORECASE,
        )
        arc_length: float | None = None
        if arc_length_match:
            arc_raw = parse_comma_number(arc_length_match.group(1))
            arc_unit = _normalize_unit_token(arc_length_match.group(2))
            arc_length = ConversionFactors.convert_to_feet(arc_raw, arc_unit)

        props = calculate_curve_properties(radius, delta_deg=delta_deg)
        computed_arc_length = arc_length if arc_length is not None else props["arc_length_ft"]

        curve_info = {
            "direction": direction,
            "radius_ft": radius,
            "delta_deg": delta_deg,
            "arc_length_ft": computed_arc_length,
            "chord_length_ft": props["chord_length_ft"],
        }

    else:
        # "curve to the left", "curving to the right", "turning towards the left"
        dir_match = re.search(
            r"\b(?:curve|curving|turning)\s+(?:to|towards?)\s+the\s+(left|right)\b",
            text,
            re.IGNORECASE,
        )
        if dir_match:
            curve_info["direction"] = dir_match.group(1).lower()

        radius_match = re.search(
            rf"radius\s+(?:of\s+)?({COMMA_NUMBER})\s*({_UNIT_TOKEN})?", text, re.IGNORECASE
        )
        if radius_match:
            radius_raw = parse_comma_number(radius_match.group(1))
            radius_unit = _normalize_unit_token(radius_match.group(2))
            curve_info["radius_ft"] = ConversionFactors.convert_to_feet(radius_raw, radius_unit)

        delta_match = re.search(
            r"delta\s+(?:angle\s+)?(?:of\s+)?(\d+(?:\.\d+)?)(?:\u00b0|(?:\s+)?degrees?)(?:\s*(\d+(?:\.\d+)?)(?:'|\s+minutes?))?(?:\s*(\d+(?:\.\d+)?)(?:\"|\s+seconds?))?",
            text,
            re.IGNORECASE,
        )
        if delta_match:
            delta = float(delta_match.group(1))
            if delta_match.group(2):
                delta += float(delta_match.group(2)) / 60.0
            if delta_match.group(3):
                delta += float(delta_match.group(3)) / 3600.0

            curve_info["delta_deg"] = delta

        arc_match = re.search(
            rf"arc\s+(?:length|distance)\s+(?:of\s+)?({COMMA_NUMBER})\s*({_UNIT_TOKEN})?",
            text,
            re.IGNORECASE,
        )
        if arc_match:
            arc_raw = parse_comma_number(arc_match.group(1))
            arc_unit = _normalize_unit_token(arc_match.group(2))
            curve_info["arc_length_ft"] = ConversionFactors.convert_to_feet(arc_raw, arc_unit)

        # Degree of curvature -> radius conversion
        doc_match = re.search(
            r"degree\s+of\s+(?:curve|curvature)\s+(?:of\s+)?"
            r"(\d+(?:\.\d+)?)(?:\u00b0|(?:\s+)?degrees?)"
            r"(?:\s*(\d+(?:\.\d+)?)(?:'|\s+minutes?))?"
            r'(?:\s*(\d+(?:\.\d+)?)(?:"|\s+seconds?))?',
            text,
            re.IGNORECASE,
        )
        if doc_match and curve_info.get("radius_ft") is None:
            doc_deg = float(doc_match.group(1))
            if doc_match.group(2):
                doc_deg += float(doc_match.group(2)) / 60.0
            if doc_match.group(3):
                doc_deg += float(doc_match.group(3)) / 3600.0
            if doc_deg > 0:
                curve_info["radius_ft"] = degree_of_curvature_to_radius(doc_deg)

    radius_ft = curve_info.get("radius_ft")
    curve_delta_deg = curve_info.get("delta_deg")
    if isinstance(radius_ft, float) and isinstance(curve_delta_deg, float):
        props = calculate_curve_properties(radius_ft, delta_deg=curve_delta_deg)
        if curve_info.get("arc_length_ft") is None:
            curve_info["arc_length_ft"] = props["arc_length_ft"]
        curve_info.setdefault("chord_length_ft", props["chord_length_ft"])

    chord_bearing_match = re.search(
        r"(?:the\s+)?chord\s+(?:of\s+which\s+)?bears\s+(.+?)(?:,\s*(\d+(?:\.\d+)?)\s*(?:feet|ft))?(?:\s*$|\s*(?:to|along|;|\.))",
        text,
        re.IGNORECASE,
    )
    if chord_bearing_match:
        raw_chord_bearing = chord_bearing_match.group(1).strip().rstrip(",")
        normalized = standardize_cardinal_directions(raw_chord_bearing)
        bearing_match = QUADRANT_PATTERN.search(normalized)
        if bearing_match:
            curve_info["chord_bearing"] = bearing_match.group(0)
        if chord_bearing_match.group(2):
            curve_info["chord_length_ft"] = float(chord_bearing_match.group(2))

    if re.search(
        r"\b(?:point\s+of\s+compound\s+curvature|PCC|compound\s+curve)\b",
        text,
        re.IGNORECASE,
    ):
        curve_info["curve_type"] = "compound"
    elif re.search(
        r"\b(?:point\s+of\s+reverse\s+curvature|PRC|reverse\s+curve)\b",
        text,
        re.IGNORECASE,
    ):
        curve_info["curve_type"] = "reverse"
    elif re.search(
        r"\b(?:spiral\s+curve|transition\s+curve)\b",
        text,
        re.IGNORECASE,
    ):
        curve_info["curve_type"] = "spiral"

    if re.search(r"\bnon-?tangent\b", text, re.IGNORECASE):
        curve_info["non_tangent"] = True

    radial_match = re.search(
        r"radial\s+(?:line\s+)?bear(?:s|ing)\s+(?:of\s+)?(.+?)(?:,|\s*radius|\s*$)",
        text,
        re.IGNORECASE,
    )
    if radial_match:
        curve_info["non_tangent"] = True
        raw_radial = radial_match.group(1).strip()
        normalized_radial = standardize_cardinal_directions(raw_radial)
        radial_bearing_match = QUADRANT_PATTERN.search(normalized_radial)
        if radial_bearing_match:
            curve_info["radial_bearing"] = radial_bearing_match.group(0)

    return curve_info


def mark_tie_in_calls(calls: list[DeedCall], poc_description: str | None) -> list[DeedCall]:
    """Mark calls between POC and POB as tie-in calls.

    When a POC exists, calls before (and including) the first call whose
    'to' field references the Point of Beginning are marked as tie-in.

    Args:
        calls: List of DeedCall objects
        poc_description: POC description (None or empty means no POC)

    Calls already marked from their course text are kept, and a closing course is not a
    tie line: marking across the flat calls would otherwise reach into another tract.

    Returns:
        List of DeedCall objects with is_tie_in set appropriately
    """
    if not poc_description or any(call.is_tie_in for call in calls):
        return calls

    pob_index = None
    for i, call in enumerate(calls):
        if call.to and is_closure_to_pob("to " + call.to):
            pob_index = i
            break

    if pob_index is None or pob_index == len(calls) - 1:
        return calls

    result = []
    for i, call in enumerate(calls):
        if i <= pob_index:
            result.append(call.model_copy(update={"is_tie_in": True}))
        else:
            result.append(call)
    return result


def enrich_calls_with_azimuths(calls: list[DeedCall]) -> list[DeedCall]:
    """Add azimuths to calls that have quadrant bearings but missing azimuths.

    Also resolves 'due {cardinal}' directions that were not yet converted.
    When a due-cardinal azimuth is resolved, any "incomplete bearing" notes
    are cleared since the bearing is now complete.

    Args:
        calls: List of DeedCall objects

    Returns:
        List of enriched DeedCall objects
    """
    enriched = []
    for call in calls:
        if call.bearing_quadrant and call.bearing_azimuth_deg_from_north is None:
            azimuth = bearing_to_azimuth(call.bearing_quadrant)
            if azimuth is not None:
                enriched.append(call.model_copy(update={"bearing_azimuth_deg_from_north": azimuth}))
            else:
                enriched.append(call)
        elif call.bearing_azimuth_deg_from_north is None and call.direction_text:
            # Try due-cardinal enrichment for calls missed during initial extraction
            due_az = due_cardinal_to_azimuth(call.direction_text)
            if due_az is not None:
                updates: dict[str, object] = {
                    "bearing_azimuth_deg_from_north": due_az,
                }
                # Clear incomplete-bearing notes if present
                if call.notes and "incomplete" in call.notes:
                    updates["notes"] = None
                enriched.append(call.model_copy(update=updates))
            else:
                enriched.append(call)
        else:
            enriched.append(call)
    return enriched
