"""Extract individual deed calls from legal descriptions.

Parses normalized text to create structured DeedCall objects.
Rule-based extraction -- no AI/LLM involved.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import NamedTuple

import structlog
from mp_bearing import (
    COMPASS_POINTS,
    QUADRANT_PATTERN,
    bearing_to_azimuth,
    calculate_curve_properties,
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
    SkippedCourse,
    Tract,
    Transformation,
)
from pydantic import ValidationError

from .metadata import (
    COURSE_LIST_MARKER,
    analyze_course_lists,
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

# A cardinal-only word in a curve course describes the overall direction of travel,
# i.e. the chord. Sector rule: northeast/southeast/southwest/northwest accept chord
# azimuths within 45 degrees of their centre (the quadrant, edges inclusive);
# north/east/south/west accept within 67.5 degrees of theirs.
_CARDINAL_CENTRES = {
    "north": (0.0, 67.5),
    "northeast": (45.0, 45.0),
    "east": (90.0, 67.5),
    "southeast": (135.0, 45.0),
    "south": (180.0, 67.5),
    "southwest": (225.0, 45.0),
    "west": (270.0, 67.5),
    "northwest": (315.0, 45.0),
}
_CARDINAL_ABBREVIATIONS = {
    "ne": "northeast",
    "nw": "northwest",
    "se": "southeast",
    "sw": "southwest",
}


def _cardinal_conflicts_chord(cardinal_text: str, chord_text: str | None) -> bool:
    """True when a cardinal-only word lies outside its sector around the chord azimuth."""
    if not chord_text:
        return False
    word = re.sub(r"(?:erly|wardly)$", "", cardinal_text.strip().lower())
    word = _CARDINAL_ABBREVIATIONS.get(word, word)
    chord_az = bearing_to_azimuth(chord_text)
    if word not in _CARDINAL_CENTRES or chord_az is None:
        return False
    centre, half_width = _CARDINAL_CENTRES[word]
    diff = abs((float(chord_az) - centre + 180.0) % 360.0 - 180.0)
    return diff > half_width + 1e-9


_UNIT_TOKEN = (
    r"(?:US\s+survey\s+(?:feet|foot)|engineer\s+chains?|engineer\s+links?"
    r"|feet|foot|ft|poles?|rods?|perches?|chains?|links?"
    r"|varas?|arpents?|toises?|furlongs?|meters?|miles?)"
)

PACKED_DMS_PATTERN = re.compile(
    r"(N|S)\s+(\d{1,3}\.\d+)\u00b0\s*(E|W)",
    re.IGNORECASE,
)

ARC_COMPUTED_NOTE = "arc length not stated - course distance computed from radius and delta"
# A curve fixed by its stated chord bearing and delta (or arc and radius) with no
# stated tangent: the tangent is computed only inside verification, never stored.
TANGENT_NOT_STATED_NOTE = (
    "tangent bearing not stated - curve positioned by chord and delta in verification"
)
ARC_COMPUTED_RULE = "curve: distance is the arc computed from the stated radius and delta"
LENGTH_NOT_DETERMINED_NOTE = "spiral length not stated - course distance not determined"
LENGTH_NOT_DETERMINED_RULE = (
    "spiral: no arc, chord or course length stated; a spiral's length is not radius * delta"
)

# One curve-word spelling (curve/curved/curving) shared by every curve gate in this module.
CURVE_WORD = r"curv(?:e|ed|ing)"
CURVE_KEYWORD_PATTERN = re.compile(rf"\b(?:{CURVE_WORD}|spiral|transition)\b", re.IGNORECASE)

CURVE_PATTERN = re.compile(
    rf"{CURVE_WORD}\s+to\s+the\s+(left|right).*?radius\s+of\s+({COMMA_NUMBER})\s*({_UNIT_TOKEN})?.*?"
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


def _record_skipped_course(
    call_text: str,
    *,
    course: int,
    source_course: int,
    error_type: str,
    error: str,
    exc: BaseException | None,
    tract_label: str | None,
    audit_context: AuditContext | None,
    skipped_courses: list[SkippedCourse] | None,
) -> None:
    """Record a course non-strict extraction could not parse; never drop it silently.

    With nowhere to record the skip, verification could not learn of it, so the
    course is rejected exactly as in strict mode.
    """
    if audit_context is None and skipped_courses is None:
        raise ValueError(
            f"Malformed course {source_course}: {call_text.strip()!r}: {error}; "
            "skipped course not recorded (pass audit_context or skipped_courses)"
        ) from exc
    skip = SkippedCourse(
        course=course,
        source_course=source_course,
        source_excerpt=call_text,
        error_type=error_type,
        error=error,
        tract_label=tract_label,
    )
    payload = {
        "course": course,
        "call_preview": _call_preview(call_text),
        "call_hash": _call_hash(call_text),
        "error": error,
        "error_type": error_type,
    }
    if _is_debug_logging_enabled():
        logger.warning("Skipping malformed call", **payload, call_text=call_text, exc_info=exc)
    else:
        logger.warning("Skipping malformed call", **payload)
    if audit_context is not None:
        audit_context.skipped_courses.append(skip)
    if skipped_courses is not None:
        skipped_courses.append(skip)


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


# --- Curve length roles -----------------------------------------------------------
# Every length in a curve call is classified by its own label (the words directly
# before it) or, for chord and radial clauses, by the clause grammar, and is stored
# only under that role: radius, chord, tangent (never stored), arc, or the course
# length. An unlabelled length inside a radius-point/center clause measures that
# element ("radial", never stored). A number directly after a degree sign is a
# bearing's minutes, never a length.
_LENGTH_TOKEN = re.compile(
    rf"(?<![\d.,\u00b0])(?<!\u00b0\s)({COMMA_NUMBER})\s*({_UNIT_TOKEN}\b|'(?!'))",
    re.IGNORECASE,
)
_LABEL_WINDOW = 64
_LENGTH_LABELS = (
    (
        "arc",
        re.compile(
            r"\b(?:arc(?:\s+(?:length|distance))?|length\s+of\s+(?:(?:the|said)\s+)?(?:arc|curve)"
            r"|distance\s+along\s+(?:(?:the|said)\s+)?(?:arc|curve)|curve\s+length)"
            r"(?:\s+(?:of|is))?\s*=?\s*$",
            re.IGNORECASE,
        ),
    ),
    (
        "chord",
        re.compile(
            r"\b(?:long\s+)?chord(?:\s+(?:length|distance))?(?:\s+(?:of|is))?\s*=?\s*$",
            re.IGNORECASE,
        ),
    ),
    (
        "tangent",
        re.compile(
            r"\btangent(?:\s+(?:length|distance))?(?:\s+(?:of|is))?\s*=?\s*$", re.IGNORECASE
        ),
    ),
    (
        "radius",
        re.compile(
            r"\bradius(?:\s+(?:length|distance))?(?:\s+(?:of|is|equal\s+to))?\s*=?\s*$",
            re.IGNORECASE,
        ),
    ),
    ("course", re.compile(r"\b(?:distance|length)(?:\s+(?:of|is))?\s*$", re.IGNORECASE)),
)
# A "center" is a curve element only as the center point or the center of the
# (said) curve/circle (the shared radial grammar). "center line", "centerline" and
# "center of Route 9 / the road" describe a physical line or road, not the curve.
_CENTER_ELEMENT = r"cent(?:er|re)(?!(?:[-\s]*line)\b)(?:\s+point\b|(?!\s+of\b)|\s+of\s+(?:the|said)\s+(?:curve|circle)\b)"
_RADIAL_ELEMENT_PATTERN = re.compile(
    r"\b(?:radius\s+point|radial(?:\s+(?:line|bearing))?|" + _CENTER_ELEMENT + r")\b",
    re.IGNORECASE,
)
# Components of one compound course length ("1 chain and 21 links").
_COMPOUND_JOINER = re.compile(r"(?:\s+and\s+|\s*,\s*|\s+)")
CURVE_LENGTH_AMBIGUOUS_NOTE = "curve length ambiguous: {values}"


class _CurveLength(NamedTuple):
    """One length in a curve call, with the role its label gives it."""

    role: str
    feet: float
    unit: str
    start: int
    end: int


def _length_unit(token: re.Match[str]) -> str:
    return "feet" if token.group(2) == "'" else _normalize_unit_token(token.group(2))


def _clause_roles(text: str) -> dict[int, str]:
    """Return token start -> role for lengths placed by the chord and radial grammar.

    Mirrors ``extract_curve_info``: the chord length is the chord's lead length,
    the length right after the chord bearing, or (without a bearing) the first
    length in the chord clause; the radius is a length directly after a radial
    bearing (``_RADIAL_RADIUS_AFTER_BEARING``).
    """
    roles: dict[int, str] = {}
    chord = _CHORD_PREFIX_PATTERN.search(text)
    if chord:
        if chord.group("chord_lead_len"):
            roles[chord.start("chord_lead_len")] = "chord"
        else:
            bearing, clause_end = _reference_bearing(text, chord.end(), packed=False)
            if bearing:
                length = _CHORD_LENGTH_AFTER_BEARING.match(text, bearing.end())
            else:
                length = _CHORD_LENGTH_IN_CLAUSE.search(text, chord.end(), clause_end)
            if length:
                roles[length.start(1)] = "chord"
    radial = _RADIAL_PREFIX_PATTERN.search(text)
    if radial:
        bearing, _ = _reference_bearing(text, radial.end(), packed=False)
        if bearing:
            length = _RADIAL_RADIUS_AFTER_BEARING.match(text, bearing.end())
            if length:
                roles[length.start(1)] = "radius"
    return roles


def _curve_lengths(call_text: str) -> tuple[str, list[_CurveLength]]:
    """Classify every length in a curve call's boundary course text.

    Returns the normalized course text the spans refer to and the lengths in
    order. Precedence: chord/radial clause grammar, then the label directly
    before the length, then (unlabelled) a radius-point/center clause, else the
    course length.
    """
    text = _normalize_bearing_forms(_boundary_course_text(call_text))
    bearings = [
        (m.start(), m.end())
        for pattern in (QUADRANT_PATTERN, PACKED_DMS_PATTERN)
        for m in pattern.finditer(text)
    ]
    clause_roles = _clause_roles(text)
    element_starts = set()
    for subject in _RADIAL_ELEMENT_PATTERN.finditer(text):
        first = _LENGTH_TOKEN.search(text, subject.end())
        if first and not _CLAUSE_END.search(text, subject.end(), first.start()):
            element_starts.add(first.start())
    lengths: list[_CurveLength] = []
    previous_end = 0
    for token in _LENGTH_TOKEN.finditer(text):
        if any(start <= token.start() < end for start, end in bearings):
            continue
        role = clause_roles.get(token.start())
        if role is None:
            window = max(previous_end, token.start() - _LABEL_WINDOW)
            role = next(
                (
                    name
                    for name, label in _LENGTH_LABELS
                    if label.search(text, window, token.start())
                ),
                None,
            )
            if role is None:
                role = "radial" if token.start() in element_starts else "course"
        unit = _length_unit(token)
        feet = ConversionFactors.convert_to_feet(parse_comma_number(token.group(1)), unit)
        lengths.append(_CurveLength(role, feet, unit, token.start(), token.end()))
        previous_end = token.end()
    return text, lengths


def _course_length_groups(text: str, lengths: list[_CurveLength]) -> list[list[_CurveLength]]:
    """Group course lengths; adjacent components in different units form one length."""
    groups: list[list[_CurveLength]] = []
    previous: _CurveLength | None = None
    for length in lengths:
        if length.role == "course":
            if (
                groups
                and previous is groups[-1][-1]
                and previous.unit != length.unit
                and _COMPOUND_JOINER.fullmatch(text, previous.end, length.start)
            ):
                groups[-1].append(length)
            else:
                groups.append([length])
        previous = length
    return groups


def _ambiguous_course_lengths(text: str, lengths: list[_CurveLength]) -> list[str] | None:
    """Return the course lengths as written when several are stated and none is the arc."""
    if any(length.role == "arc" for length in lengths):
        return None
    groups = _course_length_groups(text, lengths)
    if len(groups) < 2:
        return None
    return [text[group[0].start : group[-1].end] for group in groups]


def _course_distance_text(call_text: str, *, is_curve: bool) -> str:
    """Return the text a course distance is read from.

    Corner witnesses are cut off (``_boundary_course_text``). For a curve, every
    length not classified as the course length (``_curve_lengths``) is removed,
    so a radius, chord, tangent or radial length is never read as the course
    length. Several course lengths without a stated arc are ambiguous and are all
    removed, so none is chosen.
    """
    if not is_curve:
        return _boundary_course_text(call_text)
    text, lengths = _curve_lengths(call_text)
    ambiguous = _ambiguous_course_lengths(text, lengths) is not None
    for length in reversed(lengths):
        if length.role != "course" or ambiguous:
            text = text[: length.start] + " " + text[length.end :]
    return text


def _is_initial_course_prefix(prefix: str) -> bool:
    """Return whether text before THENCE starts with a supported bearing."""
    candidate = re.sub(r"^\s*(?:(?:\(\d+\)|\d+[.)])\s*)?", "", prefix)
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


def _extract_calls_from_text(
    text: str,
    distance_unit: str = "feet",
    *,
    audit_context: AuditContext | None = None,
    strict: bool = True,
    course_start: int = 1,
    skipped_courses: list[SkippedCourse] | None = None,
    tract_label: str | None = None,
) -> list[DeedCall]:
    """Extract all calls from normalized legal description text.

    Handles exception clauses (EXCEPT, LESS AND EXCEPT, ALSO, INCLUDING)
    and marks calls accordingly.

    Args:
        text: Normalized legal description text (should already be normalized)
        distance_unit: Primary distance unit (feet, poles, etc.)
        audit_context: Optional audit context for recording parsing decisions
        strict: Raise with course context when a geometric course is malformed.
            Otherwise the course is recorded as a ``SkippedCourse`` (in
            ``audit_context`` and/or ``skipped_courses``) with its course number
            reserved; with neither supplied it raises as in strict mode.
        skipped_courses: Optional list receiving non-strict skipped courses.
        tract_label: Tract label recorded on skipped courses.

    Returns:
        List of DeedCall objects
    """
    normalized = normalize_legal_description(text)

    tracts = split_exception_clauses(normalized)

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
        has_initial_course = bool(thence_match and _is_initial_course_prefix(prefix))
        if thence_match and (has_beginning_preamble or not has_initial_course):
            tract_text = tract_text[thence_match.start() :]

        # Course-list headers and enumerations are detected once per tract.
        course_lists = analyze_course_lists(tract_text)
        count_mismatches = list(
            zip(course_lists.mismatches, course_lists.mismatch_headers, strict=True)
        )
        if strict and count_mismatches:
            (declared, found), header_text = count_mismatches[0]
            raise ValueError(
                f"Course-list header {header_text!r} states {declared} courses "
                f"but {found} were found"
            )
        has_numbered_course_markers = course_lists.has_numbered_markers
        call_texts = [
            part
            for part in split_into_calls(tract_text, course_lists=course_lists)
            if not COURSE_LIST_MARKER.fullmatch(part)
        ]

        source_course = 0
        while source_course < len(call_texts):
            call_text = call_texts[source_course]
            source_course += 1
            try:
                call, raw_direction = _extract_call(
                    call_text, course=course_num, distance_unit=distance_unit
                )
            except (ValidationError, ValueError, TypeError) as exc:
                if isinstance(exc, MultipleCoursesError):
                    pieces = _split_multi_course_fragment(call_text)
                    if len(pieces) > 1:
                        # Each piece is one complete course; extract them in turn.
                        call_texts[source_course - 1 : source_course] = pieces
                        source_course -= 1
                        continue
                if strict:
                    raise ValueError(
                        f"Malformed course {source_course}: {call_text.strip()!r}: {exc}"
                    ) from exc
                _record_skipped_course(
                    call_text,
                    course=course_num,
                    source_course=source_course,
                    error_type=type(exc).__name__,
                    error=str(exc),
                    exc=exc,
                    tract_label=tract_label,
                    audit_context=audit_context,
                    skipped_courses=skipped_courses,
                )
                # Reserve the course number so the gap stays visible downstream.
                course_num += 1
                continue

            if call is None:
                explicit_course = has_thence_marker or has_numbered_course_markers
                if (
                    explicit_course
                    or extract_direction(call_text)
                    or re.search(r"\b(?:[NSEW])\s+\d", call_text, re.I)
                    or CURVE_KEYWORD_PATTERN.search(call_text)
                ):
                    if strict:
                        raise ValueError(f"Malformed course {source_course}: {call_text.strip()!r}")
                    _record_skipped_course(
                        call_text,
                        course=course_num,
                        source_course=source_course,
                        error_type="UnparsedCourse",
                        error="no computable course could be parsed",
                        exc=None,
                        tract_label=tract_label,
                        audit_context=audit_context,
                        skipped_courses=skipped_courses,
                    )
                    course_num += 1
                continue

            if is_exception_tract:
                call = call.model_copy(update={"is_exception": True})
            calls.append(call)

            if audit_context is not None:
                transformations, decisions, flags = _audit_single_call(
                    call_text, call, raw_direction
                )
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

        for (declared, found), header_text in count_mismatches:
            # Not silently accepted: a missing or extra course is recorded and
            # blocks closure, exactly as an unparsed course does. The record names
            # the header (its excerpt), not a course; its number is reserved after
            # the tract's courses.
            _record_skipped_course(
                header_text,
                course=course_num,
                source_course=len(call_texts) + 1,
                error_type="CourseCountMismatch",
                error=(
                    f"course-list header {header_text!r} states {declared} courses "
                    f"but {found} were found"
                ),
                exc=None,
                tract_label=tract_label,
                audit_context=audit_context,
                skipped_courses=skipped_courses,
            )
            course_num += 1

    return calls


def extract_calls(
    text: str,
    distance_unit: str = "feet",
    *,
    audit_context: AuditContext | None = None,
    strict: bool = True,
    skipped_courses: list[SkippedCourse] | None = None,
) -> tuple[list[DeedCall], list[Tract]]:
    """Extract all calls from normalized legal description text.

    Handles multi-tract deeds (TRACT markers, multiple BEGINNINGs,
    EXCEPT/ALSO clauses) and marks calls accordingly.

    Args:
        text: Normalized legal description text (should already be normalized)
        distance_unit: Primary distance unit (feet, poles, etc.)
        audit_context: Optional audit context for recording parsing decisions
        strict: Raise with course context when a geometric course is malformed.
            Otherwise each unparsed course is recorded as a ``SkippedCourse`` in
            ``audit_context`` and/or ``skipped_courses`` (and on its ``Tract``),
            keeps its course number, and blocks verification given that record.
            With neither supplied, an unparsed course raises as in strict mode.
        skipped_courses: Optional list receiving non-strict skipped courses.

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
            normalized,
            distance_unit,
            audit_context=audit_context,
            course_start=1,
            strict=strict,
            skipped_courses=skipped_courses,
        )
        return flat_calls, []

    # Multi-tract path
    all_calls: list[DeedCall] = []
    tract_objects: list[Tract] = []

    for segment_text, label, tract_type in segments:
        recordable = audit_context is not None or skipped_courses is not None
        tract_skips: list[SkippedCourse] = []
        tract_calls = _extract_calls_from_text(
            segment_text,
            distance_unit,
            audit_context=audit_context,
            course_start=1,
            strict=strict,
            skipped_courses=tract_skips if recordable else None,
            tract_label=label,
        )
        if skipped_courses is not None:
            skipped_courses.extend(tract_skips)

        if not tract_calls and strict:
            raise ValueError(f"Tract {label!r} has no computable calls")
        # A tract whose every course was skipped is kept so its skips block it.
        if not tract_calls and not tract_skips:
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
            skipped_courses=tract_skips,
        )
        tract_objects.append(tract)
        all_calls.extend(tract_calls)

    return all_calls, tract_objects


_COMPACT_DMS_BEARING = re.compile(
    r"\b([NS])\s*(\d{1,3})\s*(?:-|d\b|d(?=\d)|deg\.?|degrees?)\s*"
    r"(?:(\d{1,2})\s*(?:-|m\b|m(?=\d)|min\.?|minutes?)\s*)?"
    r"(?:(\d{1,2}(?:\.\d+)?)\s*(s\b|sec\.?|seconds?)?\s*)?([EW])\b",
    re.IGNORECASE,
)


# A number group right after an identifier word ("Lot N 12-3 E", "Route N 9-1 E")
# is a label, never a bearing.
_IDENTIFIER_WORDS = (
    r"(?:lots?|blocks?|blk|routes?|rte|rt|highway|hwy|no|nos|number|unit"
    r"|parcel|tract|section|sec|map|plat|book|page|pg|sheet|phase|plan|instrument|deed"
    r"|file|exit|apt|suite|building|bldg)"
)
_IDENTIFIER_BEFORE = re.compile(
    r"(?:(?<![A-Za-z])" + _IDENTIFIER_WORDS + r"\.?|#)\s*$",
    re.IGNORECASE,
)
# Bare dashes ("N 45-30 E") carry no degree marker. They are a bearing after any
# word except an identifier and its label ("Parcel A N 12-3 E", "Section 12 N 1-2 E",
# "Book 1234 Page N 12-3 E"), which is a number group, never a bearing.
_DASHED_LABEL_BEFORE = re.compile(
    r"(?:(?<![A-Za-z])" + _IDENTIFIER_WORDS + r"\.?|#)[ \t]{0,3}(?:[A-Z]|\d{1,6}[A-Za-z]?)\s*$",
    re.IGNORECASE,
)
# Historical name: the dashed-group context check is now this identifier denylist.
_DASHED_BEARING_CONTEXT = _DASHED_LABEL_BEFORE


# Longest word any ``_ends_with`` pattern needs before its trailing whitespace.
_TAIL_WORD_WINDOW = 24


def _ends_with(pattern: re.Pattern[str], text: str, end: int) -> bool:
    """Return True when ``pattern`` (ending in ``\\s*$``) matches ``text`` just before ``end``.

    Equivalent to ``pattern.search(text[:end])`` for patterns whose non-space part
    is at most ``_TAIL_WORD_WINDOW`` characters, but only a bounded tail is
    scanned, so per-match checks stay linear in the text length. ``^`` still
    means the real start of ``text`` and lookbehinds still see earlier text.
    """
    word_end = end
    while word_end > 0 and text[word_end - 1].isspace():
        word_end -= 1
    return bool(pattern.search(text, max(0, word_end - _TAIL_WORD_WINDOW), end))


def _expand_compact_dms(text: str) -> str:
    """Rewrite dashed or d/m bearings (``N 45-30-00 E``, ``N 45d30m E``) with symbols."""

    def _repl(m: re.Match[str]) -> str:
        if _ends_with(_IDENTIFIER_BEFORE, text, m.start()):
            return m.group(0)
        numbers = text[m.start(2) : m.start(6)]
        if not re.search(r"\d\s*[dms]", numbers, re.IGNORECASE) and (
            _ends_with(_DASHED_LABEL_BEFORE, text, m.start())
        ):
            return m.group(0)
        minute_value, second_value = m.group(3), m.group(4)
        if minute_value is None and second_value is not None and m.group(5) is None:
            # Two parts ("N 45-30 E", "N 45d 30 E"): the trailing number is minutes,
            # unless an explicit seconds marker says otherwise.
            minute_value, second_value = second_value, None
        minutes = f"{minute_value}'" if minute_value else ""
        seconds = f'{second_value}"' if second_value else ""
        return f"{m.group(1).upper()} {m.group(2)}\u00b0{minutes}{seconds} {m.group(6).upper()}"

    return _COMPACT_DMS_BEARING.sub(_repl, text)


# Every degree/minute/second marker may be combined with any other (``North 34 degrees
# 02' 00" West``). Each number must carry its own marker, so a unit is never guessed.
# A marker may run straight into the closing cardinal (``North 45\u00b030'East``) but
# never into another word.
_MARK_END = r"(?!(?!(?:East|West|E|W)\b)[a-z])"
_DEG_MARK = rf"(?:\u00b0|\u00ba|\u02da|degrees?|deg\.?|d){_MARK_END}"
_MIN_MARK = rf"(?:'|\u2019|\u2032|minutes?|min\.?|m){_MARK_END}"
_SEC_MARK = rf"(?:\"|\u2033|\u201d|''|\u2019\u2019|seconds?|sec\.?|s){_MARK_END}"
_MARKED_DMS_BEARING = re.compile(
    rf"\b(N|S|North|South)\.?\s*(\d{{1,3}})\s*{_DEG_MARK}\s*"
    rf"(?:(\d{{1,2}})\s*{_MIN_MARK}\s*)?"
    rf"(?:(\d{{1,2}}(?:\.\d+)?)\s*{_SEC_MARK}\s*)?(E|W|East|West)\b",
    re.IGNORECASE,
)


def _expand_marked_dms(text: str) -> str:
    """Rewrite bearings with any mix of degree/minute/second markers into symbols."""

    def _repl(m: re.Match[str]) -> str:
        minutes = f"{m.group(3)}'" if m.group(3) else ""
        seconds = f'{m.group(4)}"' if m.group(4) else ""
        return (
            f"{m.group(1)[0].upper()} {m.group(2)}\u00b0{minutes}{seconds} {m.group(5)[0].upper()}"
        )

    return _MARKED_DMS_BEARING.sub(_repl, text)


def _normalize_bearing_forms(text: str) -> str:
    """Rewrite every bearing form the parser accepts into abbreviated DMS."""
    return standardize_cardinal_directions(_expand_compact_dms(_expand_marked_dms(text)))


# Joins texts for a single normalization pass. No bearing pattern spans NUL, and "("
# is a clause boundary, so each later text is read exactly as if it stood alone.
_SEGMENT_BREAK = "\x00("


def _normalize_bearing_segments(segments: list[str]) -> list[str]:
    """Normalize several texts in one pass; each result equals normalizing it alone.

    Only the first segment may contain ``_SEGMENT_BREAK``.
    """
    joined = _normalize_bearing_forms(_SEGMENT_BREAK.join(segments))
    return joined.rsplit(_SEGMENT_BREAK, len(segments) - 1)


# Chord and radial clauses share one grammar: SUBJECT [LINK] VERB, followed by a
# bearing in any course form (``_reference_bearing``). A stated chord is never the
# tangent; a radial clause gives the bearing toward the curve's center, never the
# course tangent.
_CLAUSE_LINK = r"(?:(?:of|to)\s+which|which|that|whose)\s+"
# "lies"/"is" are too common to open a clause unless a bearing follows directly.
_CLAUSE_VERB = (
    r"(?:(?:bears?|bearing)(?:\s+(?:of|is))?\s+"
    r"|(?:lies|is)\s+(?=(?:N|S|North|South)(?![a-z])))"
)
_CHORD_SUBJECT = r"chord"
_RADIAL_SUBJECT = (
    r"(?:radius\s+point|radius|radial(?:\s+(?:line|bearing))?"
    r"|cent(?:er|re)(?:\s+point)?(?:\s+of\s+(?:the|said)\s+curve)?)"
)
# The chord may state its length before the bearing ("a chord of 51.76 feet bearing
# N 45 E"), say "on a bearing of", and drop the verb when a quadrant bearing follows
# the subject (or the length phrase) directly ("chord N 45 E, 51.76 feet").
_CHORD_BEARING_LEAD = (
    rf"(?:{_CLAUSE_VERB}|on\s+(?:a\s+)?bearing\s+(?:of\s+)?"
    r"|(?=(?:N|S|North|South)(?![a-z])))"
)
_CHORD_PREFIX_PATTERN = re.compile(
    rf"\b{_CHORD_SUBJECT}(?:\s+(?:length|distance))?\s+"
    rf"(?:(?:of\s+)?(?P<chord_lead_len>{COMMA_NUMBER})\s*(?:feet|ft)\b\s*,?\s*"
    r"(?:and\s+)?(?:(?:an?|the)\s+)?)?"
    rf"(?:{_CLAUSE_LINK})?{_CHORD_BEARING_LEAD}",
    re.IGNORECASE,
)
_RADIAL_PREFIX_PATTERN = re.compile(
    rf"\b{_RADIAL_SUBJECT}\s+(?:{_CLAUSE_LINK})?{_CLAUSE_VERB}"
    r"|\bradial\s+(?:line|bearing)\s+of\s+",
    re.IGNORECASE,
)
# Deed says the curve is tangent ("tangent to the last course", "tangent curve", "being
# tangent"); "non-tangent"/"not tangent" is excluded.
_TANGENT_STATEMENT_PATTERN = re.compile(
    r"(?<!non[-\s\u2010-\u2015\u2212])(?<!non)(?<!not\s)\btangent\s+(?:to\s+(?:the\s+)?(?:last|preceding|previous|prior)\s+course"
    r"|curve)\b|\bbeing\s+tangent\b",
    re.IGNORECASE,
)


_CLAUSE_END = re.compile(r"[,;]")


def _reference_bearing(
    text: str, start: int, *, packed: bool = True
) -> tuple[re.Match[str] | None, int]:
    """Return the bearing a clause opened at ``start`` introduces, and the clause end.

    ``text`` must be normalized (``_normalize_bearing_forms``). The bearing is the
    first course-form bearing within the clause (up to the next comma or
    semicolon); decimal seconds are kept whole. ``packed`` also accepts packed
    DMS ("N 45.3000\u00b0 E"), which only course stripping needs; stored chord
    and radial bearings stay in quadrant form.
    """
    clause_end = _CLAUSE_END.search(text, start)
    end = clause_end.start() if clause_end else len(text)
    bearing = PACKED_DMS_PATTERN.search(text, start, end) if packed else None
    if bearing is None:
        bearing = QUADRANT_PATTERN.search(text, start, end)
    return bearing, end


# "along (a | the | said) radial line ...": the radial line is the course itself.
_ALONG_RADIAL_PATTERN = re.compile(r"\balong\s+(?:(?:a|the|said)\s+)?$", re.IGNORECASE)


def _runs_along_radial(text: str, start: int) -> bool:
    """Return True when the radial clause at ``start`` names the line being run."""
    return _ends_with(_ALONG_RADIAL_PATTERN, text, start)


def _without_reference_bearings(
    text: str, prefix: re.Pattern[str], *, keep_line_radial: bool = False
) -> str:
    """Remove every ``prefix`` clause together with the bearing it introduces.

    The bearing is searched only within the clause (up to the next comma or
    semicolon); if none is recognised the clause itself is dropped so its
    direction words cannot be read as the course bearing. ``text`` must already
    be normalized (``_normalize_bearing_forms``). With ``keep_line_radial``, a
    clause naming the radial line being run (``_runs_along_radial``) is kept.
    """
    position = 0
    while True:
        match = prefix.search(text, position)
        if not match:
            return text
        if keep_line_radial and _runs_along_radial(text, match.start()):
            position = match.end()
            continue
        bearing, clause_end = _reference_bearing(text, match.end())
        cut = bearing.end() if bearing else clause_end
        text = text[: match.start()] + " " + text[cut:]
        position = match.start()


_CURVE_GEOMETRY_KEYS = ("direction", "radius_ft", "delta_deg", "arc_length_ft", "chord_length_ft")


def _describes_curve(curve_info: dict[str, float | str | None]) -> bool:
    """Return True when extracted curve info states any curve geometry."""
    return any(curve_info.get(key) is not None for key in _CURVE_GEOMETRY_KEYS)


class _CourseBearing(NamedTuple):
    """The course direction of one call: ``direction`` parses, ``text`` is the deed's."""

    direction: str
    text: str
    complete_courses: int = 0


def _course_bearing(call_text: str, curve_info: dict[str, float | str | None]) -> _CourseBearing:
    """Return the course (tangent) direction stated in the boundary course text.

    Corner witnesses are cut off, and the course text and its verbatim bearing
    candidates are normalized together in one pass. Chord and
    radial/radius-point/center bearings are then removed *before* extraction, so
    only a bearing describing the course itself can be returned. On a straight
    course, a radial clause naming the line being run ("along a radial line
    bearing ...") states the course bearing and is kept; one describing the radius
    point of a curve reached at the end of the line is removed. ``curve_info`` is
    ``extract_curve_info(call_text)``, computed once by the caller.
    """
    keep_line_radial = not _describes_curve(curve_info)
    course_text = _boundary_course_text(call_text)
    candidates = _verbatim_candidates(course_text, keep_line_radial=keep_line_radial)
    normalized, *normalized_candidates = _normalize_bearing_segments([course_text, *candidates])
    normalized = _without_reference_bearings(normalized, _CHORD_PREFIX_PATTERN)
    normalized = _without_reference_bearings(
        normalized, _RADIAL_PREFIX_PATTERN, keep_line_radial=keep_line_radial
    )
    direction = extract_direction(normalized)
    return _CourseBearing(
        direction,
        _verbatim_course_direction(direction, candidates, normalized_candidates),
        _complete_courses(normalized)[0],
    )


# Any bearing form in the deed's own wording (symbols, words, dashes, d/m units).
# Possessive quantifiers keep long digit runs from backtracking.
_VERBATIM_BEARING = re.compile(
    r"(?<![A-Za-z])(?:North|South|N|S)\.?(?![A-Za-z])\s*+\d++(?:\.\d++)?"
    r"(?:\s*+(?:[\u00b0\u00ba'\u2032\u2019\"\u2033\u201d-]|degrees?(?![a-z])|deg(?![a-z])\.?"
    r"|d(?![a-z])|minutes?(?![a-z])|min(?![a-z])\.?|m(?![a-z])|seconds?(?![a-z])"
    r"|sec(?![a-z])\.?|s(?![a-z])|\d++(?:\.\d++)?))*+"
    r"\s*+,?\s*+(?:East|West|E|W)(?![A-Za-z])",
    re.IGNORECASE,
)


def _verbatim_candidates(course_text: str, *, keep_line_radial: bool = False) -> list[str]:
    """Return the deed's bearings in ``course_text``, skipping chord/radial openers.

    With ``keep_line_radial``, the bearing of a radial line being run is kept.
    """
    excluded: set[int] = set()
    for prefix in (_CHORD_PREFIX_PATTERN, _RADIAL_PREFIX_PATTERN):
        for match in prefix.finditer(course_text):
            if (
                keep_line_radial
                and prefix is _RADIAL_PREFIX_PATTERN
                and _runs_along_radial(course_text, match.start())
            ):
                continue
            rest = course_text[match.end() :]
            clause_end = re.search(r"[,;]", rest)
            clause = rest[: clause_end.start()] if clause_end else rest
            reference = _VERBATIM_BEARING.search(clause)
            if reference:
                excluded.add(match.end() + reference.start())
    return [
        match.group(0)
        for match in _VERBATIM_BEARING.finditer(course_text)
        if match.start() not in excluded
    ]


def _verbatim_course_direction(
    direction: str, candidates: list[str], normalized_candidates: list[str]
) -> str:
    """Return the deed's own wording for the parsed course ``direction``.

    ``direction`` comes from normalized text and is used only for parsing. The
    first candidate whose normalized form equals it is returned verbatim; other
    directions (due/compass words, unparsed bearings) are returned unchanged.
    """
    if not parse_quadrant_bearing(direction):
        return direction
    for candidate, normalized in zip(candidates, normalized_candidates, strict=True):
        if extract_direction(normalized) == direction:
            return candidate
    return direction


class MultipleCoursesError(ValueError):
    """One call fragment states more than one complete boundary course."""


MULTIPLE_COURSES_ERROR = "fragment contains multiple courses"
_DUE_COURSE_BEARING = re.compile(r"\bdue\s+(?:north|south|east|west|[NSEW])\b", re.IGNORECASE)
_LEADING_ENUMERATOR = re.compile(r"^\s*(?:\((?:\d{1,3}|[A-Za-z])\)|\d{1,3}[.)])\s")
# Two courses written back to back ("N 45 E 100 feet S 45 W 100 feet", one per line
# before normalization): a course length followed, with only whitespace between,
# by the next course's bearing.
_JUXTAPOSED_COURSE_BOUNDARY = re.compile(
    rf"(?<=\d)(\s*{_UNIT_TOKEN}\b\.?)\s+(?=(?:N|S|North|South)\.?\s*\d|due\s+(?:north|south|east|west)\b)",
    re.IGNORECASE,
)


_LATER_BEGINNING = re.compile(r"\b(?:BEGINNING|COMMENCING)\s+(?:at|on|in)\b", re.IGNORECASE)


def _course_bearing_spans(text: str) -> list[tuple[int, int]]:
    """Non-overlapping course-form bearings (quadrant, packed DMS, due) in normalized text."""
    spans = sorted(
        (m.start(), m.end())
        for pattern in (QUADRANT_PATTERN, PACKED_DMS_PATTERN, _DUE_COURSE_BEARING)
        for m in pattern.finditer(text)
    )
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start < merged[-1][1]:
            continue
        merged.append((start, end))
    return merged


def _boundary_course_reading(call_text: str) -> tuple[int, bool]:
    """Return (complete boundary courses, has any course bearing) in one call fragment.

    The text is read exactly as for the course bearing (``_course_bearing``):
    corner witnesses are cut off and chord and radial clauses (bearing and its
    clause) are removed, so a curve's chord or radial bearing and length never
    count as a second course.
    """
    keep_line_radial = not _describes_curve(extract_curve_info(call_text))
    text = _normalize_bearing_forms(_boundary_course_text(call_text))
    text = _without_reference_bearings(text, _CHORD_PREFIX_PATTERN)
    text = _without_reference_bearings(
        text, _RADIAL_PREFIX_PATTERN, keep_line_radial=keep_line_radial
    )
    return _complete_courses(text)


def _complete_courses(text: str) -> tuple[int, bool]:
    """Return (complete courses, has any course bearing) in normalized course text.

    A complete course is a course-form bearing followed by a length before the
    next bearing. ``text`` has had its chord and radial clauses removed. A later
    BEGINNING/COMMENCING clause opens another description, whose bearings are ties
    to its point of beginning, so counting stops there.
    """
    preamble = _LATER_BEGINNING.search(text, 1)
    if preamble:
        text = text[: preamble.start()]
    bearings = _course_bearing_spans(text)
    if not bearings:
        return 0, False
    ends = [start for start, _ in bearings[1:]] + [len(text)]
    complete = sum(
        1
        for (_, bearing_end), segment_end in zip(bearings, ends, strict=True)
        if _LENGTH_TOKEN.search(text, bearing_end, segment_end)
    )
    return complete, bool(bearings)


def _split_juxtaposed_courses(segment: str) -> list[str]:
    """Split ``segment`` where one course's length runs straight into the next bearing.

    Only bare courses split: every piece must state exactly one length, so a
    length belonging to a tie ("distant 10 feet S 27 E running ... 158 feet") is
    never taken for the end of a course.
    """
    pieces = []
    start = 0
    for boundary in _JUXTAPOSED_COURSE_BOUNDARY.finditer(segment):
        pieces.append(segment[start : boundary.end(1)])
        start = boundary.end()
    pieces.append(segment[start:])
    if len(pieces) > 1 and any(_length_count(piece) != 1 for piece in pieces):
        return [segment]
    return pieces


def _length_count(text: str) -> int:
    """Lengths stated in ``text`` outside its bearings."""
    normalized = _normalize_bearing_forms(text)
    bearings = _course_bearing_spans(normalized)
    return sum(
        1
        for token in _LENGTH_TOKEN.finditer(normalized)
        if not any(start <= token.start() < end for start, end in bearings)
    )


def _split_multi_course_fragment(call_text: str) -> list[str]:
    """Split a fragment holding several complete courses when that is safe.

    Called only for a fragment ``_extract_call`` rejected with
    ``MultipleCoursesError``. Pieces are cut at ';' and where one course's length runs straight into the
    next bearing (``_JUXTAPOSED_COURSE_BOUNDARY``). Safe means every piece is
    itself exactly one complete course, apart from
    pieces with no bearing and no length (descriptive wording, kept with the
    course before it). A piece opening with an enumerator the course-list
    detector did not accept (out of sequence), or one with a bearing but no
    complete course, is never split off; the fragment is then returned whole and
    stays rejected.
    """
    segments = [
        piece for segment in call_text.split(";") for piece in _split_juxtaposed_courses(segment)
    ]
    pieces: list[str] = []
    pending = ""  # descriptive wording before the first course
    for segment in segments:
        if not segment.strip():
            continue
        complete, has_bearing = _boundary_course_reading(segment)
        if complete == 0 and not has_bearing and not _LENGTH_TOKEN.search(segment):
            if pieces:
                pieces[-1] += ";" + segment
            else:
                pending += segment + ";"
            continue
        if complete != 1 or _LEADING_ENUMERATOR.match(segment):
            return [call_text]
        pieces.append(pending + segment if not pieces else segment.strip())
        pending = ""
    return [piece.strip() for piece in pieces] if len(pieces) >= 2 else [call_text]


def extract_single_call(
    call_text: str,
    course: int,
    distance_unit: str = "feet",
) -> DeedCall | None:
    """Extract a single call from text.

    Args:
        call_text: Text for one call
        course: Course number
        distance_unit: Primary distance unit

    Returns:
        DeedCall object or None if parsing fails
    """
    return _extract_call(call_text, course, distance_unit)[0]


def _extract_call(
    call_text: str, course: int, distance_unit: str = "feet"
) -> tuple[DeedCall | None, str]:
    """Return ``extract_single_call``'s result with the parsed course direction.

    BEGINNING/POB clauses return before any curve or bearing work; otherwise curve
    info is extracted once and shared with the course-bearing extraction.
    """
    if re.match(r"^\s*(BEGINNING|COMMENCING|POB)\b", call_text, re.IGNORECASE):
        return None, ""

    curve_info = extract_curve_info(call_text)
    course_bearing = _course_bearing(call_text, curve_info)
    if course_bearing.complete_courses >= 2:
        # Never keep only the first of several courses.
        raise MultipleCoursesError(MULTIPLE_COURSES_ERROR)
    raw_direction = course_bearing.direction
    # direction_text keeps the deed's wording; the normalized form is for parsing only.
    direction_text = course_bearing.text if raw_direction else call_text.strip()

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

    course_text = _course_distance_text(call_text, is_curve=_describes_curve(curve_info))
    distance, unit = extract_distance(course_text)
    if distance == 0:
        if re.search(
            rf"{COMMA_NUMBER}\s+[A-Za-z]+(?:\s+[A-Za-z]+)?\s+and\s+{COMMA_NUMBER}\s+[A-Za-z]+",
            course_text,
            re.IGNORECASE,
        ):
            raise ValueError("Unsupported component in compound course distance")
        distance = extract_distance_alternate(course_text)
        unit = distance_unit

    distance_ft: float | None = ConversionFactors.convert_to_feet(distance, unit)

    # The one course length stated on a circular curve with a stated radius is its
    # stated arc, kept as stated (never replaced by R * delta) so verification can
    # cross-check radius, delta and arc. It then counts exactly as a labelled arc.
    if (
        curve_info.get("arc_length_ft") is None
        and isinstance(curve_info.get("radius_ft"), float)
        and curve_info.get("curve_type") != "spiral"
        and distance_ft is not None
        and distance_ft > 0.0
    ):
        curve_info["arc_length_ft"] = distance_ft

    # The tangent azimuth is only what the course text states (chord and radial
    # clauses were removed before extraction); it is never derived. A curve with a
    # stated chord bearing, direction and delta (or arc and radius) but no tangent
    # keeps bearing_azimuth None: verification positions it by chord and delta and
    # computes its tangents internally. Only an explicitly stated delta is stored as
    # delta_deg. Radius + chord without a stated delta or arc: nothing is derived;
    # the course is positioned by its chord only.
    has_stated_tangent = parsed_bearing is not None or is_due_cardinal
    chord_text = curve_info.get("chord_bearing")
    chord_only = isinstance(chord_text, str) and not has_stated_tangent
    curve_delta = curve_info.get("delta_deg")
    # A spiral's chord deflection is not delta / 2, so no circular value (tangent,
    # delta from arc, arc from radius and delta) is ever derived for a spiral.
    is_spiral = curve_info.get("curve_type") == "spiral"
    tangent_delta: float | None = (
        curve_delta if isinstance(curve_delta, float) and not is_spiral else None
    )
    stated_radius = curve_info.get("radius_ft")
    stated_arc = curve_info.get("arc_length_ft")
    stated_chord = curve_info.get("chord_length_ft")
    if (
        tangent_delta is None
        and not is_spiral
        and isinstance(stated_radius, float)
        and stated_radius > 0.0
        and isinstance(stated_arc, float)
        and stated_arc > 0.0
    ):
        tangent_delta = math.degrees(stated_arc / stated_radius)
    # A stated tangent, chord bearing, chord and radius (no delta or arc) are kept as
    # stated: nothing is derived into delta_deg/arc_length_ft. The chord positions the
    # course; verification cross-checks the stated tangent, chord and radius.
    tangent_and_chord = (
        has_stated_tangent
        and azimuth is not None
        and not curve_info.get("non_tangent")
        and isinstance(chord_text, str)
    )
    positioned_by_chord = (
        tangent_delta is None
        and stated_arc is None
        and (isinstance(stated_radius, float) or is_spiral)
        and isinstance(chord_text, str)
        and isinstance(stated_chord, float)
        and stated_chord > 0.0
    )
    chord_exceeds_diameter = (
        positioned_by_chord
        and isinstance(stated_chord, float)
        and isinstance(stated_radius, float)
        and stated_chord > 2.0 * abs(stated_radius)
    )
    # Fixed by stated chord bearing, direction and delta/arc (not stored as a tangent).
    chord_positioned = False
    cardinal_conflict = False
    if (
        chord_only
        and isinstance(chord_text, str)
        and curve_info.get("direction") in ("left", "right")
        and tangent_delta is not None
    ):
        cardinal_conflict = bool(
            raw_direction
            and not parsed_bearing
            and not is_due_cardinal
            and _CARDINAL_ONLY_PATTERN.fullmatch(raw_direction.strip())
            and _cardinal_conflicts_chord(raw_direction, chord_text)
        )
        chord_positioned = bearing_to_azimuth(chord_text) is not None and not cardinal_conflict

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
        return None, raw_direction

    arc_length_ft = curve_info.get("arc_length_ft")
    arc_computed = False
    if isinstance(arc_length_ft, float) and arc_length_ft > 0.0:
        distance_ft = arc_length_ft
    elif (
        curve_info.get("radius_ft") is not None
        and curve_info.get("delta_deg") is not None
        and not is_spiral
        and (distance_ft is None or distance_ft <= 0.0)
    ):
        radius_ft = curve_info.get("radius_ft")
        delta_deg = curve_info.get("delta_deg")
        if isinstance(radius_ft, float) and isinstance(delta_deg, float):
            props = calculate_curve_properties(radius_ft, delta_deg=delta_deg)
        else:
            raise ValueError("Curve info missing numeric radius/delta")
        # The required course length is the arc fixed by the stated radius and
        # delta. It is disclosed as computed; the unstated arc and chord are never
        # stored, so verification has no derived element to cross-check.
        arc_length_ft = props["arc_length_ft"]
        if arc_length_ft is None:
            raise ValueError("Curve props missing arc length")
        if arc_length_ft > 0.0:
            distance_ft = arc_length_ft
            arc_computed = True
    elif positioned_by_chord and isinstance(stated_chord, float):
        # Chord-only curve: its course distance is the stated chord, never the
        # radius (the first distance in the text) or a derived arc.
        distance_ft = stated_chord

    # A spiral stated without an arc, chord or course length has no determinable
    # length (it is not R * delta): the course is kept with its distance not
    # determined, so it is neither given an invented length nor dropped.
    length_not_determined = (
        distance_ft is not None
        and distance_ft <= 0.0
        and is_spiral
        and stated_arc is None
        and stated_chord is None
    )
    if length_not_determined:
        distance_ft = None
    elif distance_ft is None or distance_ft <= 0.0:
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

    tangent_notes: list[str] = []
    if chord_positioned:
        tangent_notes.append(TANGENT_NOT_STATED_NOTE)
        if cardinal_only and raw_direction:
            tangent_notes.append(
                f"stated direction is cardinal only ({raw_direction.strip().lower()})"
            )
    elif is_spiral and not has_stated_tangent:
        tangent_notes.append("spiral tangent not stated - not derived")
    elif chord_only and not positioned_by_chord:
        tangent_notes.append("tangent bearing not stated - chord bearing only")
    if positioned_by_chord and tangent_and_chord:
        tangent_notes.append("curve positioned by stated tangent and chord; arc not stated")
    elif positioned_by_chord:
        tangent_notes.append("curve delta/arc not stated - positioned by chord only")
    if is_spiral and positioned_by_chord and not isinstance(stated_radius, float):
        tangent_notes.append("spiral positioned by stated chord; radius not stated")
    if cardinal_conflict and raw_direction:
        tangent_notes.append(
            f"stated direction ({raw_direction.strip().lower()}) conflicts with "
            f"chord bearing {chord_text}"
        )
    if chord_exceeds_diameter:
        tangent_notes.append("chord length exceeds twice the radius")
    tangent_note = "; ".join(tangent_notes)

    note_parts: list[str] = []
    if is_meander or "approximate" in call_text.lower():
        note_parts.append("meander / approximate")
        if tangent_note:
            note_parts.append(tangent_note)
    elif tangent_note:
        note_parts.append(tangent_note)
    if cardinal_only and not chord_positioned:
        note_parts.append("incomplete bearing - cardinal only")
    elif not note_parts and not parsed_bearing and not is_due_cardinal:
        note_parts.append("incomplete bearing")
    if arc_computed:
        note_parts.append(ARC_COMPUTED_NOTE)
    for key in ("radius_conflict_note", "length_ambiguity_note"):
        element_note = curve_info.get(key)
        if isinstance(element_note, str):
            note_parts.append(element_note)
    if length_not_determined:
        note_parts.append(LENGTH_NOT_DETERMINED_NOTE)
    notes = "; ".join(note_parts)

    if distance_ft is not None and distance_ft <= 0.0:
        return None, raw_direction

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
        return None, raw_direction

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

    # A tangent-less curve not fixed by its chord bearing and delta is indefinite.
    chord_only_unresolved = chord_only and not chord_positioned
    is_indefinite = chord_only_unresolved or is_indefinite_call(
        direction_text,
        has_bearing=has_stated_tangent or chord_positioned,
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

    return call, raw_direction


def _tangent_not_stated(call: DeedCall) -> bool:
    """Return True for a curve fixed by chord and delta whose tangent is not stated."""
    return (
        call.bearing_azimuth_deg_from_north is None
        and call.notes is not None
        and TANGENT_NOT_STATED_NOTE in call.notes
    )


def _distance_audit_source(call_text: str, call: DeedCall) -> tuple[str, str | None]:
    """Return the audited input and rule for the stored course distance."""
    if call.distance_ft is None:
        return (
            f"radius {call.radius_ft} feet, delta {call.delta_deg} deg (spiral)",
            LENGTH_NOT_DETERMINED_RULE,
        )
    if (
        call.notes
        and ARC_COMPUTED_NOTE in call.notes
        and call.radius_ft
        and call.delta_deg is not None
    ):
        return (
            f"radius {call.radius_ft} feet, delta {call.delta_deg} deg",
            ARC_COMPUTED_RULE,
        )
    if call.is_chord_only_curve():
        return (
            f"{call.chord_length_ft} feet",
            "chord-only curve: distance is the stated chord length",
        )
    if call.arc_length_ft is not None and call.arc_length_ft == call.distance_ft:
        return f"{call.arc_length_ft} feet", None
    course_text = _course_distance_text(call_text, is_curve=call.is_curve())
    distance, unit = extract_distance(course_text)
    if distance == 0:
        return call_text.strip(), None
    return f"{distance} {unit}", None


def _audit_single_call(
    call_text: str,
    call: DeedCall,
    raw_direction: str,
) -> tuple[list[Transformation], list[Decision], list[str]]:
    """Build audit data for a successfully parsed call.

    This is a pure function that inspects the parsed call and original text
    to construct transformation, decision, and flag lists for the audit trail.

    Args:
        call_text: Original text of the call
        call: The successfully parsed DeedCall
        raw_direction: The normalized course direction the call was parsed from

    Returns:
        Tuple of (transformations, decisions, flags)
    """
    transformations: list[Transformation] = []
    decisions: list[Decision] = []
    flags: list[str] = []

    # --- Bearing transformation ---
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

    tangent_not_stated = _tangent_not_stated(call)

    # --- Distance transformation ---
    # Record the source the stored distance actually came from, never the first
    # distance in the text (which for a curve is the radius).
    distance_input, distance_rule = _distance_audit_source(call_text, call)
    transformations.append(
        Transformation(
            step="extract_distance",
            input=distance_input,
            output="not determined" if call.distance_ft is None else str(call.distance_ft),
            rule=distance_rule,
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
    elif tangent_not_stated:
        decisions.append(
            Decision(
                field="bearing_azimuth_deg_from_north",
                value="none",
                reason=(
                    f"tangent bearing not stated; chord bearing {call.chord_bearing} and "
                    "delta/arc kept as stated for verification, no tangent derived"
                ),
                confidence=1.0,
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

    if tangent_not_stated and cardinal_only:
        flags.append("cardinal_only_direction")
    elif not is_due and (cardinal_only or (raw_direction and not call.bearing_quadrant)):
        flags.append("incomplete_bearing")
    if (
        cardinal_only
        and not tangent_not_stated
        and call.bearing_azimuth_deg_from_north is None
        and _cardinal_conflicts_chord(raw_direction, call.chord_bearing)
    ):
        flags.append("cardinal_chord_conflict")

    if call.is_indefinite:
        flags.append("indefinite")

    if call.is_meander:
        flags.append("meander")

    if call.distance_ft is None:
        flags.append("distance_not_determined")

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
        return quadrant_match.group(0)

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


_BEARING_DEGREE_PREFIX = re.compile(
    r"(?:\b(?:N|S|north|south)\.?\s*|\b(?:bears?|bearing|azimuth)\s+(?:of\s+)?)$",
    re.IGNORECASE,
)


# A chord length follows its bearing directly ("N 45\u00b0 E, 51.76 feet", "... and a
# chord length of 100 feet"); without a recognised bearing, the first distance in the
# chord clause is its length. An arc length is never read as the chord.
_CHORD_LENGTH_AFTER_BEARING = re.compile(
    r"\s*,?\s*(?:(?:and|for)\s+)?(?:(?:a|the)\s+)?"
    r"(?:chord\s+(?:length|distance)\s+of\s+|distance\s+of\s+)?"
    rf"({COMMA_NUMBER})\s*(?:feet|ft)\b",
    re.IGNORECASE,
)
_CHORD_LENGTH_IN_CLAUSE = re.compile(rf"({COMMA_NUMBER})\s*(?:feet|ft)\b", re.IGNORECASE)


def _is_bearing_degree(text: str, start: int) -> bool:
    """Return True when the degree value at ``start`` is part of a bearing."""
    return _ends_with(_BEARING_DEGREE_PREFIX, text, start)


# "radius point bears N 10 E 500.00 feet": a length directly after a radial bearing,
# or labelled as the radius, is the radius (to the radius point or center). Any other
# label ("a distance of"), or a bare length after a comma, is not the radius.
_RADIAL_RADIUS_AFTER_BEARING = re.compile(
    r"(?:\s*,?\s*(?:(?:and|with)\s+)?(?:(?:a|the)\s+)?radius\s+(?:of\s+)?|\s*)"
    rf"({COMMA_NUMBER})\s*({_UNIT_TOKEN})\b",
    re.IGNORECASE,
)
RADIUS_CONFLICT_NOTE = (
    "radius conflict: radius of {stated:g} ft stated; radial bearing clause gives "
    "{radial:g} ft (stated radius kept)"
)


def _apply_radial_length(
    curve_info: dict[str, float | str | None], radial_text: str, bearing_end: int
) -> None:
    """Read the radius from the length following a radial bearing (never overrides)."""
    length = _RADIAL_RADIUS_AFTER_BEARING.match(radial_text, bearing_end)
    if not length:
        return
    radial_radius = ConversionFactors.convert_to_feet(
        parse_comma_number(length.group(1)), _normalize_unit_token(length.group(2))
    )
    stated = curve_info.get("radius_ft")
    if not isinstance(stated, float):
        curve_info["radius_ft"] = radial_radius
    elif abs(stated - radial_radius) > max(0.01, 1e-3 * abs(stated)):
        curve_info["radius_conflict_note"] = RADIUS_CONFLICT_NOTE.format(
            stated=stated, radial=radial_radius
        )


def extract_curve_info(text: str) -> dict[str, float | str | None]:
    """Extract curve information from call text.

    Args:
        text: Call text

    Returns:
        Dict with curve properties (empty if no curve)
    """
    curve_info: dict[str, float | str | None] = {}

    if not CURVE_KEYWORD_PATTERN.search(text):
        return curve_info

    match = CURVE_PATTERN.search(text)
    if match and _is_bearing_degree(text, match.start(4)):
        # The first degree value belongs to a bearing (e.g. the chord's), not
        # the central angle; only an explicitly labelled delta may be used.
        match = None
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

        # Only stated elements are stored; an unstated arc or chord stays None.
        curve_info = {
            "direction": direction,
            "radius_ft": radius,
            "delta_deg": delta_deg,
        }

    else:
        dir_match = re.search(rf"{CURVE_WORD}\s+to\s+the\s+(left|right)", text, re.IGNORECASE)
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
            r"(?:delta|central\s+angle)\s+(?:angle\s+)?(?:of\s+)?(\d+(?:\.\d+)?)(?:\u00b0|(?:\s+)?degrees?)(?:\s*(\d+(?:\.\d+)?)(?:'|\s+minutes?))?(?:\s*(\d+(?:\.\d+)?)(?:\"|\s+seconds?))?",
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

    chord_match = _CHORD_PREFIX_PATTERN.search(text)
    if chord_match:
        chord_text = _normalize_bearing_forms(text[chord_match.end() :])
        chord_bearing, chord_clause_end = _reference_bearing(chord_text, 0, packed=False)
        if chord_bearing:
            curve_info["chord_bearing"] = chord_bearing.group(0)
            # The chord length is the distance stated right after the chord bearing.
            chord_length = _CHORD_LENGTH_AFTER_BEARING.match(chord_text, chord_bearing.end())
        else:
            chord_length = _CHORD_LENGTH_IN_CLAUSE.search(chord_text, 0, chord_clause_end)
        if chord_match.group("chord_lead_len"):
            curve_info["chord_length_ft"] = parse_comma_number(chord_match.group("chord_lead_len"))
        elif chord_length:
            curve_info["chord_length_ft"] = parse_comma_number(chord_length.group(1))

    # The arc, and a chord stated without the chord-bearing grammar ("a chord
    # distance of 87.16 feet"), are read only from lengths labelled as such.
    course_text, lengths = _curve_lengths(text)
    for role, key in (("arc", "arc_length_ft"), ("chord", "chord_length_ft")):
        labelled = next((length for length in lengths if length.role == role), None)
        if labelled is not None and curve_info.get(key) is None:
            curve_info[key] = labelled.feet

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

    # Non-tangent/radial data describes a curve; a straight course that names the
    # next curve's radius point must not carry it (the clause is still stripped
    # from the course text, and stays in the verbatim call text).
    if not _describes_curve(curve_info):
        return curve_info

    ambiguous = _ambiguous_course_lengths(course_text, lengths)
    if ambiguous:
        curve_info["length_ambiguity_note"] = CURVE_LENGTH_AMBIGUOUS_NOTE.format(
            values=", ".join(ambiguous)
        )

    if re.search(r"\b(?:non[-\s\u2010-\u2015\u2212]?tangent|not\s+tangent)\b", text, re.IGNORECASE):
        curve_info["non_tangent"] = True

    radial_match = _RADIAL_PREFIX_PATTERN.search(text)
    if radial_match:
        # A stated radius point is evidence of a non-tangent curve only when the deed
        # does not also call the curve tangent.
        if not _TANGENT_STATEMENT_PATTERN.search(text):
            curve_info["non_tangent"] = True
        radial_text = _normalize_bearing_forms(text[radial_match.end() :])
        radial_bearing_match, _ = _reference_bearing(radial_text, 0, packed=False)
        if radial_bearing_match:
            curve_info["radial_bearing"] = radial_bearing_match.group(0)
            _apply_radial_length(curve_info, radial_text, radial_bearing_match.end())

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

    if pob_index is None:
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
