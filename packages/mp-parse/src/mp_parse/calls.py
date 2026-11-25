"""Extract individual deed calls from legal descriptions.

Parses normalized text to create structured DeedCall objects.
Rule-based extraction -- no AI/LLM involved.
"""

from __future__ import annotations

import hashlib
import logging
import re

import structlog
from mp_bearing import (
    COMPASS_POINTS,
    QUADRANT_PATTERN,
    bearing_to_azimuth,
    calculate_curve_properties,
    calculate_missing_curve_elements,
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
    TractType,
    Transformation,
)
from pydantic import ValidationError

from .metadata import (
    _COMMA_NUMBER,
    _DISTANCE_UNIT_ALIASES,
    _DISTANCE_UNIT_TOKEN,
    _UNSUPPORTED_DISTANCE_UNIT_TOKEN,
    CARDINAL_ONLY_PATTERN,
    detect_meander,
    extract_along_to_fields,
    extract_area_statement,
    extract_distance,
    extract_poc_and_pob,
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
from .numbers import parse_comma_number
from .tracts import split_into_tracts

logger = structlog.get_logger(__name__)

_CARDINAL_ONLY_PATTERN = CARDINAL_ONLY_PATTERN
_UNIT_TOKEN = rf"(?:{_DISTANCE_UNIT_TOKEN})"

PACKED_DMS_PATTERN = re.compile(
    r"(N|S)\s+(\d{1,3}\.\d+)\u00b0\s*(E|W)",
    re.IGNORECASE,
)

CURVE_PATTERN = re.compile(
    rf"curve\s+to\s+the\s+(left|right).*?radius\s+of\s+({_COMMA_NUMBER})\s*({_UNIT_TOKEN})?.*?"
    rf"(?:delta\s+(?:angle\s+)?of\s+)?({_COMMA_NUMBER})(?:\u00b0|\s+degrees?)(?:\s*({_COMMA_NUMBER})(?:'|\s+minutes?))?(?:\s*({_COMMA_NUMBER})(?:\"|\s+seconds?))?",
    re.IGNORECASE | re.DOTALL,
)

_CURVE_KEYWORD_RE = re.compile(r"\b(?:curve|spiral|transition)\b", re.IGNORECASE)
_DUE_CARDINAL_PATTERN = re.compile(
    r"\bdue\s+(north|south|east|west|N|S|E|W)\b",
    re.IGNORECASE,
)
_COMPOUND_COMPASS_NAMES = sorted(
    [name for name in COMPASS_POINTS if " " in name or "-" in name],
    key=len,
    reverse=True,
)
_COMPOUND_COMPASS_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(name) for name in _COMPOUND_COMPASS_NAMES) + r")\b",
    re.IGNORECASE,
)
_CARDINAL_PATTERN = re.compile(
    r"\b(north(?:erly|wardly)?|south(?:erly|wardly)?|east(?:erly|wardly)?|west(?:erly|wardly)?|"
    r"northeast(?:erly|wardly)?|northwest(?:erly|wardly)?|southeast(?:erly|wardly)?|southwest(?:erly|wardly)?)\b",
    re.IGNORECASE,
)
_ABBREV_CARDINAL_PATTERN = re.compile(r"\b(NE|NW|SE|SW)\b", re.IGNORECASE)

_CHORD_BEARING_PATTERN = re.compile(
    r"(?:the\s+)?chord\s+(?:of\s+which\s+)?bear(?:s|ing)\s+(?:of\s+)?(.+?)"
    rf"(?:,\s*({_COMMA_NUMBER})(?:\s*({_UNIT_TOKEN}))?)?"
    r"(?:\s*$|\s*(?:\bto\b|\balong\b|;|\.(?!\d)))",
    re.IGNORECASE,
)
_RADIAL_BEARING_PATTERN = re.compile(
    r"radial\s+(?:line\s+)?bear(?:s|ing)\s+(?:of\s+)?(.+?)"
    r"(?:,(?!\s*(?:\d+(?:\.\d+)?\s*(?:seconds?|minutes?)\b|(?:East|West)\b))|;|\.(?!\d)|\s*(?:radius|chord|arc|delta)\b|\s*$)",
    re.IGNORECASE,
)
_ARC_LENGTH_RE = re.compile(
    rf"arc\s+(?:length|distance)\s+(?:of\s+)?({_COMMA_NUMBER})\s*({_UNIT_TOKEN})?",
    re.IGNORECASE,
)
_CURVE_DIR_RE = re.compile(r"curve\s+to\s+the\s+(left|right)", re.IGNORECASE)
_RADIUS_RE = re.compile(
    rf"radius\s+(?:of\s+)?({_COMMA_NUMBER})\s*({_UNIT_TOKEN})?",
    re.IGNORECASE,
)
_DELTA_RE = re.compile(
    r"delta\s+(?:angle\s+)?(?:of\s+)?(\d+(?:\.\d+)?)(?:\u00b0|(?:\s+)?degrees?)(?:\s*(\d+(?:\.\d+)?)(?:'|\s+minutes?))?(?:\s*(\d+(?:\.\d+)?)(?:\"|\s+seconds?))?",
    re.IGNORECASE,
)
_DOC_RE = re.compile(
    r"degree\s+of\s+(?:curve|curvature)\s+(?:of\s+)?"
    r"(\d+(?:\.\d+)?)(?:\u00b0|(?:\s+)?degrees?)"
    r"(?:\s*(\d+(?:\.\d+)?)(?:'|\s+minutes?))?"
    r'(?:\s*(\d+(?:\.\d+)?)(?:"|\s+seconds?))?',
    re.IGNORECASE,
)
_FEET_ALT_RE = re.compile(rf"({_COMMA_NUMBER})\s*(?:feet|ft)\b", re.IGNORECASE)
_APOSTROPHE_ALT_RE = re.compile(
    rf"(?<![\d\u00b0])({_COMMA_NUMBER})\s*'(?=(?:\s+(?:along|to)\b|[.,;)]|$))",
    re.IGNORECASE,
)
_APOSTROPHE_OCR_PREFIX_RE = re.compile(
    r"\b(?:NORTH|SOUTH|N|S)\s+\d{1,3}\s+\d+(?:\.\d+)?\s*'\s*$",
    re.IGNORECASE,
)
_APOSTROPHE_DEG_PREFIX_RE = re.compile(r"\d+\u00b0\s*\d+(?:\.\d+)?\s*'\s*$")


_INLINE_TIE_IN_LEADIN = re.compile(
    r"\bfollowing\s+(?:\w+\s+)?courses?\s+and\s+distances?\s+from\b",
    re.IGNORECASE,
)

_FIRST_NUMBERED_CALL = re.compile(
    r"(?:(?:^|\n|;)\s*(?:THENCE\s*)?|\bTHENCE\s+)(?:\(1\)|1[.)])\s+",
    re.IGNORECASE | re.MULTILINE,
)

_SENTENCE_TO_BEARING_SPLIT = re.compile(
    r"([.;])\s+(?=(?:N|S)\s+\d{1,3}(?:\.\d+)?\s*\u00b0"
    r"|(?:North|South)\s+\d{1,3}(?:\.\d+)?\s+degrees?\b"
    r"|due\s+(?:north|south|east|west|N|S|E|W)\b)",
    re.IGNORECASE,
)


def _normalize_unit_token(token: str | None) -> str:
    """Normalize a captured unit token to a ConversionFactors-compatible key."""
    if not token:
        return "feet"
    return _DISTANCE_UNIT_ALIASES.get(" ".join(token.strip().lower().split()), "feet")


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


def _strip_non_course_bearings(call_text: str) -> str:
    """Remove radial bearing clauses so they are not misread as the course bearing."""
    return _RADIAL_BEARING_PATTERN.sub(" ", call_text)


def _format_bearing_quadrant(cardinal1: str, degrees: float, cardinal2: str) -> str:
    """Format parsed quadrant degrees into a DMS string, preserving non-zero seconds."""
    total_seconds = round(degrees * 3600.0, 4)
    deg_int, remainder = divmod(total_seconds, 3600.0)
    minutes, seconds = divmod(remainder, 60.0)
    if abs(seconds) < 0.0005:
        return f"{cardinal1} {int(deg_int)}\u00b0{int(minutes):02d}' {cardinal2}"
    seconds_text = f"{seconds:.4f}".rstrip("0").rstrip(".")
    if seconds < 10:
        seconds_text = f"0{seconds_text}"
    return f"{cardinal1} {int(deg_int)}\u00b0{int(minutes):02d}'{seconds_text}\" {cardinal2}"


def _safe_extract_direction(text: str) -> str:
    """Call extract_direction(), returning '' on malformed packed DMS."""
    try:
        return extract_direction(text)
    except ValueError:
        return ""


def _is_initial_course_prefix(prefix: str) -> bool:
    """Return whether text before THENCE starts with a supported bearing."""
    candidate = re.sub(r"^\s*(?:(?:\(\d+\)|\d+[.)])\s*)?", "", prefix)
    if PACKED_DMS_PATTERN.match(candidate):
        return True

    direction = _safe_extract_direction(candidate)
    if not direction or not candidate.lstrip().lower().startswith(direction.lower()):
        return False
    if _CARDINAL_ONLY_PATTERN.fullmatch(direction):
        remainder = candidate.lstrip()[len(direction) :]
        return bool(re.match(rf"\s+{_COMMA_NUMBER}(?:\s|$)", remainder))
    return bool(parse_quadrant_bearing(direction) or due_cardinal_to_azimuth(direction) is not None)


def _prepare_inline_tie_in_preamble(text: str) -> tuple[list[str], int, str] | None:
    """Split inline pre-numbered tie-in courses and numbered body separately.

    Some deeds encode tie-in courses before numbered traversal calls as:
    "thence ... to a point. South ... to the point of beginning; thence (1) ..."
    Splitting preamble and body separately prevents split_into_calls from choosing
    numbered mode over the preamble and strips the BEGINNING lead-in cleanly.
    """
    leadin_match = _INLINE_TIE_IN_LEADIN.search(text)
    if leadin_match is None:
        return None

    first_numbered = _FIRST_NUMBERED_CALL.search(text, leadin_match.end())
    if first_numbered is None:
        return None

    preamble = text[: first_numbered.start()]
    preamble_thence = re.search(r"\bTHENCE\b", preamble, re.IGNORECASE)
    if preamble_thence and not _is_initial_course_prefix(preamble[: preamble_thence.start()]):
        preamble = preamble[preamble_thence.start() :]

    expanded_preamble = _SENTENCE_TO_BEARING_SPLIT.sub(r"\1 THENCE ", preamble)
    preamble_call_texts = split_into_calls(expanded_preamble)
    if not preamble_call_texts:
        return None

    body = re.sub(r"^\s*;\s*", "", text[first_numbered.start() :])
    body = re.sub(
        r"^\s*THENCE\s*(?=\n\s*(?:\(1\)|1[.)])\s+)",
        "",
        body,
        flags=re.IGNORECASE,
    )
    body_call_texts = [
        call_text
        for call_text in split_into_calls(body)
        if not re.fullmatch(r"\s*THENCE\s*", call_text, re.IGNORECASE)
    ]
    return preamble_call_texts + body_call_texts, len(preamble_call_texts), body


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
        text: Normalized legal description text (already normalized)
        distance_unit: Primary distance unit (feet, poles, etc.)
        audit_context: Optional audit context for recording parsing decisions
        strict: Raise with course context when a geometric course is malformed.

    Returns:
        List of DeedCall objects
    """
    tracts = split_exception_clauses(text)

    calls: list[DeedCall] = []
    course_num = course_start

    for tract_text, is_exception_tract in tracts:
        # Remove a recognized commencement/POB preamble. A description may
        # legitimately begin with its first course and introduce THENCE later.
        thence_match = re.search(r"\bTHENCE\b", tract_text, re.IGNORECASE)
        has_thence_marker = thence_match is not None
        prefix = tract_text[: thence_match.start()] if thence_match else ""
        has_beginning_preamble = re.match(
            r"\s*(?:BEGINNING|COMMENCING|POINT\s+OF\s+BEGINNING|POB|TPOB|RPOB)\b",
            prefix,
            re.IGNORECASE,
        )
        has_initial_curve = bool(
            thence_match and not has_beginning_preamble and _CURVE_KEYWORD_RE.search(prefix)
        )
        has_initial_course = bool(
            thence_match and (_is_initial_course_prefix(prefix) or has_initial_curve)
        )
        inline_split = _prepare_inline_tie_in_preamble(tract_text)
        if inline_split is not None:
            call_texts, inline_tie_in_count, body_text = inline_split
            has_numbered_course_markers = bool(
                re.search(r"(?:^|\n)\s*(?:\(\d+\)|\d+[.)])\s+", body_text, re.MULTILINE)
            )
        else:
            inline_tie_in_count = 0
            if thence_match and (has_beginning_preamble or not has_initial_course):
                tract_text = tract_text[thence_match.start() :]
            elif not has_thence_marker:
                first_num = re.search(
                    r"(?:^|\n)\s*(?:\(\d+\)|\d+[.)])\s+",
                    tract_text,
                    re.MULTILINE,
                )
                if first_num:
                    num_prefix = tract_text[: first_num.start()]
                    if (
                        num_prefix.strip()
                        and not _is_initial_course_prefix(num_prefix)
                        and not _CURVE_KEYWORD_RE.search(num_prefix)
                        and (
                            re.search(
                                r"\b(?:BEGINNING|COMMENCING|POINT\s+OF\s+BEGINNING|POB|TRACT|PARCEL)\b",
                                num_prefix,
                                re.IGNORECASE,
                            )
                            or not _safe_extract_direction(num_prefix)
                        )
                    ):
                        tract_text = tract_text[first_num.start() :]

            has_numbered_course_markers = bool(
                re.search(r"(?:^|\n)\s*(?:\(\d+\)|\d+[.)])\s+", tract_text, re.MULTILINE)
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
                standalone_thence = re.fullmatch(r"\s*THENCE\s*", call_text, re.I)
                explicit_course = not standalone_thence and (
                    has_thence_marker or has_numbered_course_markers
                )
                if strict and (
                    explicit_course
                    or _safe_extract_direction(call_text)
                    or re.search(r"\b(?:[NSEW])\s+\d", call_text, re.I)
                    or _CURVE_KEYWORD_RE.search(call_text)
                ):
                    raise ValueError(f"Malformed course {source_course}: {call_text.strip()!r}")
                continue

            if source_course <= inline_tie_in_count:
                call = call.model_copy(update={"is_tie_in": True})

            if is_exception_tract:
                call = call.model_copy(update={"is_exception": True})
            calls.append(call)

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

        if not tract_calls:
            has_explicit_header = bool(
                re.match(r"^\s*(?:TRACT|PARCEL)\b", segment_text, re.IGNORECASE)
            )
            has_geometric_intent = bool(
                re.search(r"\bTHENCE\b", segment_text, re.IGNORECASE)
                or _safe_extract_direction(segment_text)
                or re.search(r"\b(?:[NSEW])\s+\d", segment_text, re.IGNORECASE)
                or _CURVE_KEYWORD_RE.search(segment_text)
                or re.search(r"(?:^|\n)\s*(?:\(\d+\)|\d+[.)])\s+", segment_text, re.MULTILINE)
            )
            if strict and (has_explicit_header or has_geometric_intent):
                raise ValueError(f"Tract {label!r} has no computable calls")
            logger.warning(
                "Empty tract after extraction — segment dropped",
                tract_label=label,
                tract_type=tract_type.value,
                segment_length=len(segment_text),
                segment_preview=segment_text[:120],
            )
            continue

        seg_poc, seg_pob = extract_poc_and_pob(segment_text)
        tract_calls = mark_tie_in_calls(tract_calls, poc_description=seg_poc or None)
        if tract_type == TractType.EXCEPTION:
            tract_calls = [c.model_copy(update={"is_exception": True}) for c in tract_calls]

        seg_area = extract_area_statement(segment_text)
        tract = Tract(
            label=label,
            tract_type=tract_type,
            calls=tract_calls,
            pob_description=seg_pob or None,
            stated_area_sq_ft=seg_area["value_sq_ft"] if seg_area else None,
        )
        tract_objects.append(tract)
        all_calls.extend(tract_calls)

    if len(tract_objects) == 1 and tract_objects[0].tract_type == TractType.MAIN:
        return all_calls, []

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

    course_text = _boundary_course_text(call_text)
    raw_direction = extract_direction(_strip_non_course_bearings(course_text))
    direction_text = raw_direction if raw_direction else call_text.strip()

    bearing_quadrant = None
    azimuth = None

    is_due_cardinal = False
    parsed_bearing = parse_quadrant_bearing(raw_direction) if raw_direction else None
    if parsed_bearing:
        cardinal1, degrees, cardinal2 = parsed_bearing
        bearing_quadrant = _format_bearing_quadrant(cardinal1, degrees, cardinal2)
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

    distance, unit = extract_distance(course_text)
    if distance == 0:
        if re.search(
            rf"(?:{_COMMA_NUMBER}\s+{_UNIT_TOKEN}\b\s+and\s+{_COMMA_NUMBER}\s+(?:{_UNSUPPORTED_DISTANCE_UNIT_TOKEN})\b"
            rf"|{_COMMA_NUMBER}\s+(?:{_UNSUPPORTED_DISTANCE_UNIT_TOKEN})\b\s+and\s+{_COMMA_NUMBER}\s+{_UNIT_TOKEN}\b)",
            course_text,
            re.IGNORECASE,
        ):
            raise ValueError("Unsupported component in compound course distance")
        distance = extract_distance_alternate(course_text)
        unit = "feet" if distance > 0 else distance_unit

    distance_ft = ConversionFactors.convert_to_feet(distance, unit)

    curve_info = extract_curve_info(call_text)
    is_meander = detect_meander(call_text)

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
        and not is_meander
    ):
        return None

    arc_length_ft = curve_info.get("arc_length_ft")
    if isinstance(arc_length_ft, float) and arc_length_ft > 0.0:
        distance_ft = arc_length_ft

    if distance_ft <= 0.0:
        raise ValueError("Missing boundary course distance")

    along, to = extract_along_to_fields(call_text)

    monument_type = classify_monument(to) if to else None
    monument_status = classify_monument_status(to or call_text)

    notes = ""
    cardinal_only = False
    if raw_direction and not parsed_bearing and not is_due_cardinal:
        if _CARDINAL_ONLY_PATTERN.fullmatch(raw_direction.strip()):
            cardinal_only = True

    if is_meander or "approximate" in call_text.lower():
        notes = "meander / approximate"
    elif not parsed_bearing and not is_due_cardinal:
        notes = "incomplete bearing - cardinal only" if cardinal_only else "incomplete bearing"

    has_curve = bool(curve_info.get("direction") or has_curve_geometry)
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
    course_text = _boundary_course_text(call_text)
    raw_direction = extract_direction(_strip_non_course_bearings(course_text))
    if raw_direction:
        transformations.append(
            Transformation(
                step="extract_bearing",
                input=raw_direction,
                output=call.bearing_quadrant or "none",
            )
        )

    is_due = due_cardinal_to_azimuth(raw_direction) is not None if raw_direction else False

    # --- Azimuth transformation ---
    if call.bearing_azimuth_deg_from_north is not None:
        if call.bearing_quadrant:
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
        elif is_due and raw_direction:
            transformations.append(
                Transformation(
                    step="compute_azimuth",
                    input=raw_direction,
                    output=str(call.bearing_azimuth_deg_from_north),
                    rule=f"due_cardinal_to_azimuth: {raw_direction}",
                )
            )

    # --- Distance transformation ---
    distance, unit = extract_distance(course_text)
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
        if matched_rule is None and call.monument_type == "other":
            matched_rule = r"\bmonument\b"
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
                reason=(
                    "due cardinal direction parsed"
                    if is_due and not call.bearing_quadrant
                    else "exact quadrant bearing parsed"
                ),
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


def _decode_packed_dms_match(packed_match: re.Match[str]) -> str:
    """Decode a PACKED_DMS_PATTERN match into standard DMS bearing string."""
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


def extract_direction(text: str) -> str:
    """Extract direction/bearing from call text.

    Args:
        text: Call text

    Returns:
        Direction string (e.g., "S 56 deg 40' W" or "southwesterly")
    """
    packed_match = PACKED_DMS_PATTERN.search(text)
    quadrant_match = QUADRANT_PATTERN.search(text)
    if quadrant_match and packed_match:
        if quadrant_match.start() <= packed_match.start():
            return quadrant_match.group(0)
        return _decode_packed_dms_match(packed_match)
    if quadrant_match:
        return quadrant_match.group(0)
    if packed_match:
        return _decode_packed_dms_match(packed_match)

    # "due {cardinal}" check -- must come before simple cardinal so "due North"
    # is captured as the full phrase, not truncated to "north".
    due_cardinal_match = _DUE_CARDINAL_PATTERN.search(text)
    if due_cardinal_match:
        return due_cardinal_match.group(0).lower()

    # Compound compass point check (32-point system) -- must come before
    # simple cardinal check so "North by East" is not truncated to "North"
    compound_compass_match = _COMPOUND_COMPASS_PATTERN.search(text)
    if compound_compass_match:
        return compound_compass_match.group(0).lower()

    cardinal_match = _CARDINAL_PATTERN.search(text)
    abbrev_match = _ABBREV_CARDINAL_PATTERN.search(text)
    if cardinal_match and abbrev_match:
        if cardinal_match.start() <= abbrev_match.start():
            return cardinal_match.group(0).lower()
        return abbrev_match.group(0).lower()
    if cardinal_match:
        return cardinal_match.group(0).lower()
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
    feet_match = _FEET_ALT_RE.search(text)
    if feet_match:
        return parse_comma_number(feet_match.group(1))

    for apostrophe_match in _APOSTROPHE_ALT_RE.finditer(text):
        prefix = text[: apostrophe_match.end()]
        if _APOSTROPHE_OCR_PREFIX_RE.search(prefix) or _APOSTROPHE_DEG_PREFIX_RE.search(prefix):
            continue
        return parse_comma_number(apostrophe_match.group(1))

    return 0.0


def extract_curve_info(text: str) -> dict[str, float | str | None]:
    """Extract curve information from call text.

    Args:
        text: Call text

    Returns:
        Dict with curve properties (empty if no curve)
    """
    curve_info: dict[str, float | str | None] = {}

    if not _CURVE_KEYWORD_RE.search(text):
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

        curve_info = {
            "direction": direction,
            "radius_ft": radius,
            "delta_deg": delta_deg,
        }
        arc_length_match = _ARC_LENGTH_RE.search(text)
        if arc_length_match:
            arc_raw = parse_comma_number(arc_length_match.group(1))
            arc_unit = _normalize_unit_token(arc_length_match.group(2))
            curve_info["arc_length_ft"] = ConversionFactors.convert_to_feet(arc_raw, arc_unit)

    else:
        dir_match = _CURVE_DIR_RE.search(text)
        if dir_match:
            curve_info["direction"] = dir_match.group(1).lower()

        radius_match = _RADIUS_RE.search(text)
        if radius_match:
            radius_raw = parse_comma_number(radius_match.group(1))
            radius_unit = _normalize_unit_token(radius_match.group(2))
            curve_info["radius_ft"] = ConversionFactors.convert_to_feet(radius_raw, radius_unit)

        delta_match = _DELTA_RE.search(text)
        if delta_match:
            delta = float(delta_match.group(1))
            if delta_match.group(2):
                delta += float(delta_match.group(2)) / 60.0
            if delta_match.group(3):
                delta += float(delta_match.group(3)) / 3600.0

            curve_info["delta_deg"] = delta

        arc_match = _ARC_LENGTH_RE.search(text)
        if arc_match:
            arc_raw = parse_comma_number(arc_match.group(1))
            arc_unit = _normalize_unit_token(arc_match.group(2))
            curve_info["arc_length_ft"] = ConversionFactors.convert_to_feet(arc_raw, arc_unit)

        # Degree of curvature -> radius conversion
        doc_match = _DOC_RE.search(text)
        if doc_match and curve_info.get("radius_ft") is None:
            doc_deg = float(doc_match.group(1))
            if doc_match.group(2):
                doc_deg += float(doc_match.group(2)) / 60.0
            if doc_match.group(3):
                doc_deg += float(doc_match.group(3)) / 3600.0
            if doc_deg > 0:
                curve_info["radius_ft"] = degree_of_curvature_to_radius(doc_deg)

    chord_bearing_match = _CHORD_BEARING_PATTERN.search(text)
    if chord_bearing_match:
        raw_chord_bearing = chord_bearing_match.group(1).strip().rstrip(",")
        normalized = standardize_cardinal_directions(raw_chord_bearing)
        bearing_match = QUADRANT_PATTERN.search(normalized)
        if bearing_match:
            curve_info["chord_bearing"] = bearing_match.group(0)
        if chord_bearing_match.group(2):
            chord_len = parse_comma_number(chord_bearing_match.group(2))
            chord_unit = _normalize_unit_token(chord_bearing_match.group(3))
            curve_info["chord_length_ft"] = ConversionFactors.convert_to_feet(chord_len, chord_unit)

    radius_ft = curve_info.get("radius_ft")
    curve_delta_deg = curve_info.get("delta_deg")
    arc_len_ft = curve_info.get("arc_length_ft")
    chord_len_ft = curve_info.get("chord_length_ft")
    provided_elements = sum(
        1 for v in (radius_ft, curve_delta_deg, arc_len_ft, chord_len_ft) if isinstance(v, float)
    )
    if isinstance(radius_ft, float) and isinstance(curve_delta_deg, float):
        props = calculate_curve_properties(radius_ft, delta_deg=curve_delta_deg)
        if curve_info.get("arc_length_ft") is None:
            curve_info["arc_length_ft"] = props["arc_length_ft"]
        curve_info.setdefault("chord_length_ft", props["chord_length_ft"])
    elif provided_elements >= 2:
        try:
            missing_props = calculate_missing_curve_elements(
                radius_ft=radius_ft if isinstance(radius_ft, float) else None,
                delta_deg=curve_delta_deg if isinstance(curve_delta_deg, float) else None,
                arc_length_ft=arc_len_ft if isinstance(arc_len_ft, float) else None,
                chord_length_ft=chord_len_ft if isinstance(chord_len_ft, float) else None,
            )
        except ValueError:
            missing_props = None
        if missing_props is not None:
            curve_info.setdefault("radius_ft", missing_props["radius_ft"])
            curve_info.setdefault("delta_deg", missing_props["delta_deg"])
            curve_info.setdefault("arc_length_ft", missing_props["arc_length_ft"])
            curve_info.setdefault("chord_length_ft", missing_props["chord_length_ft"])

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

    radial_match = _RADIAL_BEARING_PATTERN.search(text)
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

    Returns:
        List of DeedCall objects with is_tie_in set appropriately
    """
    if not poc_description:
        return calls

    pob_index = None
    for i, call in enumerate(calls):
        if call.to and is_closure_to_pob("to " + call.to):
            pob_index = i
            break

    if pob_index is None or pob_index >= len(calls) - 1:
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
    When an azimuth is resolved, any "incomplete bearing" notes
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
                updates: dict[str, object] = {
                    "bearing_azimuth_deg_from_north": azimuth,
                }
                if call.notes and "incomplete" in call.notes:
                    updates["notes"] = None
                enriched.append(call.model_copy(update=updates))
            else:
                enriched.append(call)
        elif call.bearing_azimuth_deg_from_north is None and call.direction_text:
            # Try due-cardinal enrichment for calls missed during initial extraction
            due_az = due_cardinal_to_azimuth(call.direction_text)
            if due_az is not None:
                updates = {
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
