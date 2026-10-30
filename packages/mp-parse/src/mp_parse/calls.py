"""Extract individual deed calls from legal descriptions.

Parses normalized text to create structured DeedCall objects.
Rule-based extraction -- no AI/LLM involved.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from bisect import bisect_left, bisect_right
from difflib import SequenceMatcher
from functools import lru_cache
from typing import NamedTuple

import structlog
from mp_bearing import (
    COMPASS_POINTS,
    QUADRANT_PATTERN,
    bearing_to_azimuth,
    calculate_curve_properties,
    cardinal_conflicts_bearing,
    degree_of_curvature_to_radius,
    due_cardinal_to_azimuth,
    parse_packed_dms,
    parse_quadrant_bearing,
    quadrant_to_azimuth,
)
from mp_models import (
    PARENTHETICAL_NOTE_PREFIX,
    PASSING_CALL_NOTE_PREFIX,
    RECORD_CALL_NOTE_PREFIX,
    SEPARATE_EASEMENT_NOTE_PREFIX,
    UNAPPLIED_EXCEPTION_NOTE_PREFIX,
    AuditContext,
    CallAudit,
    ConversionFactors,
    CurveDirection,
    CurveType,
    Decision,
    DeedCall,
    SkippedCourse,
    Tract,
    TractType,
    Transformation,
    split_notes,
)
from pydantic import ValidationError

from .metadata import (
    COURSE_LENGTH_AMBIGUOUS_NOTE,
    COURSE_LIST_MARKER,
    LENGTH_RUN,
    TIE_AFTER_PATTERN,
    TIE_BEFORE_PATTERN,
    CourseListAnalysis,
    _tie_clause_start,
    analyze_course_lists,
    course_length_phrase_span,
    detect_meander,
    extract_course_clause,
    extract_distance,
    extract_poc,
    extract_witness_trees,
    is_closure_to_pob,
    is_indefinite_call,
    read_course_length,
    read_standalone_inch_length,
    split_call_fragments,
    split_exception_clauses,
    strip_exception_spans,
    unlisted_course_lists,
)
from .monuments import (
    MONUMENT_PATTERNS,
    classify_monument,
    classify_monument_status,
)
from .normalizer import normalize_legal_description, standardize_cardinal_directions
from .numbers import COMMA_NUMBER, parse_comma_number
from .units import (
    LENGTH_NUMBER,
    LENGTH_UNIT,
    UNIT_TOKEN,
    VULGAR_FRACTIONS,
    normalize_unit_token,
    parse_number,
)

logger = structlog.get_logger(__name__)

_CARDINAL_ONLY_PATTERN = re.compile(
    r"(north|south|east|west|northeast|northwest|southeast|southwest|NE|NW|SE|SW)(?:erly|wardly)?",
    re.IGNORECASE,
)

# A decimal with a degree sign is read as packed DD.MM[SS[.s]] only when it has two
# decimals (minutes) or four or more (minutes, seconds, decimal seconds): "N 46.1631\u00b0 E"
# = 46\u00b016'31" (bug #43 tests pin these forms; no sample deed uses them). A one- or
# three-decimal value ("N 45.5\u00b0 E") cannot be minutes/seconds and may be decimal
# degrees, so it is never converted: azimuth stays None with
# AMBIGUOUS_DECIMAL_DEGREES_NOTE.
PACKED_DMS_PATTERN = re.compile(
    r"(N|S)\s+(\d{1,3}\.\d+)\u00b0\s*(E|W)",
    re.IGNORECASE,
)

AMBIGUOUS_DECIMAL_DEGREES_NOTE = "incomplete bearing - ambiguous decimal degrees"
_AMBIGUOUS_DECIMAL_DEGREES = re.compile(r"(?:N|S)\s+\d{1,3}\.(?:\d|\d{3})\u00b0\s*(?:E|W)", re.I)

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
    rf"{CURVE_WORD}\s+to\s+the\s+(left|right).*?radius\s+of\s+({LENGTH_NUMBER})\s*({LENGTH_UNIT})?.*?"
    rf"(?:delta\s+(?:angle\s+)?of\s+)?({COMMA_NUMBER})(?:\u00b0|\s+degrees?)(?:\s*({COMMA_NUMBER})(?:'|\s+minutes?))?(?:\s*({COMMA_NUMBER})(?:\"|\s+seconds?))?",
    re.IGNORECASE | re.DOTALL,
)


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


def _clean_validation_error(exc: ValidationError) -> ValueError:
    """Return a ValueError carrying only the validator messages of a pydantic error."""
    messages = [str(err.get("msg", "")).removeprefix("Value error, ") for err in exc.errors()]
    clean = ValueError("; ".join(m for m in messages if m) or "invalid course")
    clean.__cause__ = exc
    return clean


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
    rf"({LENGTH_NUMBER})\s*({LENGTH_UNIT})",
    re.IGNORECASE,
)
# A unitless number directly after an explicit curve-element label is that element
# in the deed's distance unit; an unlabelled unitless number is never a length.
_UNITLESS_LABELLED_LENGTH = re.compile(
    r"\b(?:(?P<arc>arc\s+(?:length|distance)|length\s+of\s+(?:(?:the|said)\s+)?arc)"
    r"|(?P<chord>chord\s+(?:length|distance))|(?P<radius>radius))"
    rf"(?:\s+(?:of|is|equal\s+to))?\s*[:=]?\s*(?P<value>{LENGTH_NUMBER})"
    rf"(?![\d\u00b0\u00ba]|[.,]\d|\s*(?:{LENGTH_UNIT}|[\u00b0\u00ba]|deg))",
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


def _curve_lengths(call_text: str, distance_unit: str = "feet") -> tuple[str, list[_CurveLength]]:
    """Classify every length in a curve call's boundary course text.

    Returns the normalized course text the spans refer to and the lengths in
    order. Precedence: chord/radial clause grammar, then the label directly
    before the length, then (unlabelled) a radius-point/center clause, else the
    course length. A unitless number directly after an explicit arc, chord or
    radius label (``_UNITLESS_LABELLED_LENGTH``) is that element in
    ``distance_unit``.
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
    # (start, end, value, unit as written, role from an explicit label)
    tokens: list[tuple[int, int, str, str | None, str | None]] = [
        (t.start(), t.end(), t.group(1), t.group(2), None) for t in _LENGTH_TOKEN.finditer(text)
    ]
    tokens += [
        (m.start("value"), m.end("value"), m.group("value"), None, role)
        for m in _UNITLESS_LABELLED_LENGTH.finditer(text)
        for role in ("arc", "chord", "radius")
        if m.group(role)
    ]
    tokens.sort()
    lengths: list[_CurveLength] = []
    previous_end = 0
    for token_start, token_end, value, unit_token, label_role in tokens:
        if any(start <= token_start < end for start, end in bearings):
            continue
        role = label_role or clause_roles.get(token_start)
        if role is None:
            window = max(previous_end, token_start - _LABEL_WINDOW)
            role = next(
                (name for name, label in _LENGTH_LABELS if label.search(text, window, token_start)),
                None,
            )
            if role is None:
                role = "radial" if token_start in element_starts else "course"
        unit = normalize_unit_token(unit_token, distance_unit)
        feet = ConversionFactors.convert_to_feet(parse_number(value), unit)
        lengths.append(_CurveLength(role, feet, unit, token_start, token_end))
        previous_end = token_end
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
    removed, so none is chosen. A straight course is extracted from
    ``_course_bearing``'s ``distance_text``; this raw text serves its audit only.
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
        # A fraction opens a course only with its unit ("North 1/2 of Section 5" is
        # an aliquot part, "Northerly 1/2 mile" a course).
        return bool(
            re.match(
                rf"\s+(?:{COMMA_NUMBER}(?:\s|$)|{LENGTH_NUMBER}\s*{LENGTH_UNIT})",
                remainder,
                re.IGNORECASE,
            )
        )
    return bool(parse_quadrant_bearing(direction) or due_cardinal_to_azimuth(direction) is not None)


_TRAILING_LEAD = re.compile(
    r"(?:subject\s+to|under\s+and\s+subject|being\s+(?:the\s+same|all\s+that)|together\s+with"
    r"|the\s+above\s+described|containing|excepting|reserving|said\s+premises)\b",
    re.IGNORECASE,
)
# A return to the point of beginning, wherever it stands in a fragment.
_CLOSING_PHRASE = re.compile(
    r"\bto\s+(?:the\s+)?(?:(?:first\s+mentioned|true|remote)\s+)?"
    r"(?:(?:point|place)(?:\s+(?:and|or)\s+place)?\s+of\s+)?beginning\b"
    r"|\bto\s+(?:the\s+)?(?:[TR]\.?)?P\.?O\.?B\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"\.(?=\s|$)|;")
_BLOCK_LEAD = re.compile(r"(?:BEGINNING|COMMENCING|POB|POINT)", re.IGNORECASE)
_BEGINNING_BLOCK = re.compile(r"\b(?:BEGINNING|COMMENCING)\s+(?:at|in|on|for|from)\b", re.I)
_COURSE_DISTANCE = re.compile(
    rf"{LENGTH_NUMBER}\s*{LENGTH_UNIT}",
    re.IGNORECASE,
)


def _states_complete_course(text: str) -> bool:
    """Return whether text states a bearing (or curve) together with a distance.

    A bearing too malformed to read still counts as stated, so its course fails closed.
    """
    if not _COURSE_DISTANCE.search(text):
        return False
    if re.search(r"\b(?:[NSEW])\s+\d", text, re.I) or CURVE_KEYWORD_PATTERN.search(text):
        return True
    try:
        return bool(extract_direction(text))
    except ValueError:
        return True


def _cut_closing_sentence(text: str) -> tuple[str, str] | None:
    """Split text after the sentence holding its last return to the point of beginning.

    Returns ``(head, tail)``, or None when there is no closing phrase or sentence end.
    """
    closings = list(_CLOSING_PHRASE.finditer(text))
    if not closings:
        return None
    sentence_end = _SENTENCE_END.search(text, closings[-1].end())
    if not sentence_end:
        return None
    return text[: sentence_end.end()], text[sentence_end.end() :].strip()


def _course_region(call_texts: list[str], *, starts_with_course: bool) -> range:
    """Return the indices of a tract's course fragments, cutting its closing course.

    The region starts at the first fragment (``starts_with_course``: the text
    begins with its first course or right after its BEGINNING/COMMENCING block),
    otherwise at the first fragment stating a complete course or following a
    BEGINNING/COMMENCING block. It ends at the closing course: the last fragment
    returning to the point of beginning anywhere in it, before any metadata lead
    ("Subject to", "BEING the same", ...); failing that, at that lead.

    The closing fragment is cut in place at the end of its closing sentence; a
    cut-off remainder stating a complete course (not a BEGINNING/COMMENCING tie)
    is kept as the next fragment.
    Fragments outside the region are not course material unless they state a
    complete course.
    """
    start = 0
    if not starts_with_course:
        start = next(
            (
                index + 1
                if _BEGINNING_BLOCK.search(text) and index + 1 < len(call_texts)
                else index
                for index, text in enumerate(call_texts)
                if _states_complete_course(text) or _BEGINNING_BLOCK.search(text)
            ),
            0,
        )
    lead_end = next(
        (
            index
            for index in range(start + 1, len(call_texts))
            if _TRAILING_LEAD.match(call_texts[index].lstrip())
        ),
        len(call_texts),
    )
    for index in range(lead_end - 1, start - 1, -1):
        text = call_texts[index]
        if not _CLOSING_PHRASE.search(text):
            continue
        cut = _cut_closing_sentence(text)
        if cut:
            head, tail = cut
            # As in split_into_calls, a BEGINNING/COMMENCING tie is not a course.
            keep_tail = tail and _states_complete_course(tail) and not _BLOCK_LEAD.match(tail)
            call_texts[index : index + 1] = [head, tail] if keep_tail else [head]
        return range(start, index + 1)
    return range(start, lead_end)


def _is_outside_region(region: range, index: int, call_text: str) -> bool:
    """Return whether a fragment is non-course text outside the course region.

    Text that states a complete course (bearing or curve plus distance) is never
    outside: it stays a recorded or raised course.
    """
    return index not in region and not _states_complete_course(call_text)


# The text a description drops as its BEGINNING/COMMENCING preamble is split as its
# courses are (``split_call_fragments``) and its bearings are read by the course
# parser's own pair reader (``_bearing_pairs``), so a course stated there is never
# lost: in its own clause it is extracted, joined to the BEGINNING clause it fails
# closed, and a tie locating the point is not a course.
_PREAMBLE_OPENER = re.compile(r"\b(?:BEGINNING|COMMENCING)\b", re.IGNORECASE)
_PREAMBLE_WORD = re.compile(r"^\s*(?:BEGINNING|COMMENCING|POB|POINT)\b", re.IGNORECASE)
# "<BEGINNING clause>, running <course>" / "... and running <course>".
_RUNNING_SEPARATOR = re.compile(r"(?:,|\band)\s+running\b[\s,;:]*", re.IGNORECASE)
# Locating wording earlier in a bearing's own comma clause ("distant 167.66 feet
# N 36° W along ...", "being distant ... on a bearing of S 32° E").
_LOCATING_BEFORE = re.compile(
    r"\b(?:being|distant|distance|measured|located|situated|lying|which\s+(?:is|lies))\b",
    re.IGNORECASE,
)
_CLAUSE_SEPARATOR = re.compile(r"[,;]")
_AND_JOINED = re.compile(r"[\s,]*(?:and|&)[\s,]*", re.IGNORECASE)
COURSE_IN_PREAMBLE_ERROR = "BEGINNING/COMMENCING clause states a course that is not extracted"


class _PreambleCourse(str):
    """A preamble fragment stating a course that cannot be separated from its clause."""


def _states_boundary_course(text: str) -> bool:
    """Return whether preamble ``text`` states a boundary course.

    A course is a complete boundary bearing pair as the course parser reads it
    (``_bearing_pairs``: a bearing with its length, not a tie or adjoiner pair).
    Preamble text locates its point, so a pair is also a tie when it follows a
    "said point being ..." clause (every later length locates that point, as in
    ``read_course_length``), when locating wording precedes it in its own comma
    clause, or when its clause runs "from" an object. Pairs joined by "and" share
    the role of the pair after them ("distant N 2° W 955 feet, and S 87° W 1782
    feet from the corner": both are ties).
    """
    if not _states_complete_course(text):
        return False
    reading = _scan_record_calls(text).reading
    normalized = _prepare_course_text(reading, extract_curve_info(reading)).normalized
    tie_from = _tie_clause_start(normalized)
    pairs = _bearing_pairs(normalized)
    tied_to_next = False
    for index in range(len(pairs) - 1, -1, -1):
        pair = pairs[index]
        opened = max(normalized.rfind(",", 0, pair.start), normalized.rfind(";", 0, pair.start))
        closed = _CLAUSE_SEPARATOR.search(normalized, pair.end)
        clause_end = closed.start() if closed else len(normalized)
        joined = index + 1 < len(pairs) and _AND_JOINED.fullmatch(
            normalized, pair.end, pairs[index + 1].start
        )
        is_tie = bool(
            not pair.boundary
            or pair.start >= tie_from
            or (joined and tied_to_next)
            or _LOCATING_BEFORE.search(normalized, opened + 1, pair.start)
            or re.search(r"\bfrom\b", normalized[pair.start : clause_end], re.IGNORECASE)
        )
        if pair.complete and not is_tie:
            return True
        tied_to_next = is_tie
    return False


def _locates_point(text: str) -> bool:
    """Return whether a preamble clause locates its point from an object."""
    return _tie_clause_start(text) <= len(text) or bool(re.search(r"\bfrom\b", text, re.I))


def _preamble_courses(fragment: str, *, opens_clause: bool) -> list[str]:
    """Return the course fragments held by text dropped as preamble.

    ``opens_clause`` marks a fragment opening with BEGINNING/COMMENCING/POB/POINT;
    otherwise the fragment is its own clause of the stripped preamble. A course in
    its own clause, or after "running", is returned as a course fragment; a course
    joined to the BEGINNING clause otherwise is returned as a ``_PreambleCourse``,
    which fails closed.
    """
    if not opens_clause:
        return [fragment] if _states_boundary_course(fragment) else []
    separator = _RUNNING_SEPARATOR.search(fragment)
    lead = fragment[: separator.start()] if separator else fragment
    courses: list[str] = []
    if _states_boundary_course(_PREAMBLE_WORD.sub("", lead, count=1)):
        courses.append(_PreambleCourse(lead.strip()))
    if separator:
        course = fragment[separator.end() :].strip()
        if course and _states_boundary_course(course):
            courses.append(course)
    return courses


def _course_fragments(preamble: str, body: str, course_lists: CourseListAnalysis) -> list[str]:
    """Return a tract's course fragments, with those held by its dropped preamble.

    ``preamble`` is the BEGINNING/COMMENCING clause stripped before the first
    THENCE; it and ``body`` are split by ``split_call_fragments``, and every
    fragment ``split_into_calls`` would drop is read by ``_preamble_courses``.
    """
    texts: list[str] = []
    # The preamble's clauses are not course lists (course-list detection runs once,
    # on the tract's courses); a numbered line still splits.
    pieces = (
        split_call_fragments(preamble, course_lists=unlisted_course_lists(preamble))
        if preamble
        else []
    )
    # After a clause locating the point from an object, later clauses may continue
    # that tie: through the last clause reaching the point of beginning they are the
    # tie; a course stated after them cannot be told from a tie, so it fails closed.
    locating = next((i for i, piece in enumerate(pieces) if _locates_point(piece.text)), None)
    closing = max(
        (i for i, piece in enumerate(pieces) if _CLOSING_PHRASE.search(piece.text)), default=-1
    )
    for index, fragment in enumerate(pieces):
        if locating is None or index <= locating or fragment.preamble:
            texts.extend(_preamble_courses(fragment.text, opens_clause=fragment.preamble))
        elif index > closing and _states_boundary_course(fragment.text):
            texts.append(_PreambleCourse(fragment.text))
    for fragment in split_call_fragments(body, course_lists=course_lists):
        if fragment.preamble:
            texts.extend(_preamble_courses(fragment.text, opens_clause=True))
        elif not COURSE_LIST_MARKER.fullmatch(fragment.text):
            texts.append(fragment.text)
    return texts


def _mark_commencement_tie_ins(
    calls: list[DeedCall], tract_text: str, first_course: int
) -> list[DeedCall]:
    """Mark courses from COMMENCING to the point of beginning as tie-ins.

    Only a description with a point of commencement has tie-ins. Nothing is marked
    when the first course reaching the point of beginning is the last course (it
    closes the boundary) or a course before it was skipped (a skipped course may
    be the real tie to the point of beginning): the boundary is never guessed.
    """
    poc = extract_poc(tract_text)
    if not poc or not calls:
        return calls
    marked = mark_tie_in_calls(calls, poc)
    ties = sum(call.is_tie_in for call in marked)
    contiguous = [c.course for c in calls[:ties]] == list(range(first_course, first_course + ties))
    if ties == len(calls) or not contiguous:
        return calls
    return marked


def _extract_calls_from_text(
    text: str,
    distance_unit: str = "feet",
    *,
    audit_context: AuditContext | None = None,
    strict: bool = True,
    course_start: int = 1,
    skipped_courses: list[SkippedCourse] | None = None,
    tract_label: str | None = None,
    normalize: bool = True,
    source_text: str | _SourceMap | None = None,
    split_easements: bool = True,
    boundary_notes: tuple[str, ...] = (),
) -> list[DeedCall]:
    """Extract all calls from normalized legal description text.

    Handles exception clauses (EXCEPT, LESS AND EXCEPT, ALSO, INCLUDING)
    and marks calls accordingly. Strip exceptions ("EXCEPTING the westerly 10
    feet thereof") and easements described by their own courses are set aside
    before courses are read (``_set_aside_non_boundary_text``): they never
    become boundary courses, and their verbatim wording is noted on the
    boundary's closing course.

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
        normalize: Normalize ``text`` first; callers passing already-normalized
            text set False so normalization runs exactly once.
        source_text: The text before normalization (or its ``_SourceMap`` when
            ``text`` is one tract of it); record-call notes are restored to its
            verbatim wording (``_restore_verbatim_records``). Defaults to ``text``
            when ``normalize`` is True.
        split_easements: Set aside easement descriptions; callers that already
            split them into easement tracts pass False.
        boundary_notes: Notes (already verbatim) for the closing course, recorded
            by a caller that set text aside before splitting tracts.

    Returns:
        List of DeedCall objects
    """
    normalized = normalize_legal_description(text) if normalize else text
    if source_text is None and normalize:
        source_text = text
    unblanked = normalized
    normalized, set_aside = _set_aside_non_boundary_text(normalized, easements=split_easements)
    source_map = (
        source_text
        if isinstance(source_text, _SourceMap)
        else _SourceMap(source_text, normalized)
        if source_text
        else None
    )
    if isinstance(source_text, _SourceMap):
        # ``text`` is one tract of the mapped description: search its source wording.
        notes_found = [
            (start, _verbatim_note(prefix + unblanked[start:end].strip(), source_text.source))
            for start, end, prefix in set_aside
        ]
    else:
        notes_found = _set_aside_notes(set_aside, unblanked, source_text)
    notes = [*boundary_notes, *(note for _, note in notes_found)]

    tracts = split_exception_clauses(normalized)

    calls: list[DeedCall] = []
    course_num = course_start

    for tract_text, is_exception_tract in tracts:
        clause_text = tract_text
        clause_first_call = len(calls)
        clause_first_course = course_num
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
        preamble = ""
        if thence_match and (has_beginning_preamble or not has_initial_course):
            opener = _PREAMBLE_OPENER.search(prefix)
            preamble = prefix[opener.start() :] if opener else ""
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
        # Text dropped as preamble is read too: a course there is never lost.
        call_texts = _course_fragments(preamble, tract_text, course_lists)
        starts_with_course = bool(has_beginning_preamble) or has_initial_course
        region = _course_region(call_texts, starts_with_course=starts_with_course)

        source_course = 0
        while source_course < len(call_texts):
            call_text = call_texts[source_course]
            source_course += 1
            if isinstance(call_text, _PreambleCourse):
                if strict:
                    raise ValueError(f"{COURSE_IN_PREAMBLE_ERROR}: {call_text!s}")
                _record_skipped_course(
                    str(call_text),
                    course=course_num,
                    source_course=source_course,
                    error_type="CourseInPreamble",
                    error=COURSE_IN_PREAMBLE_ERROR,
                    exc=None,
                    tract_label=tract_label,
                    audit_context=audit_context,
                    skipped_courses=skipped_courses,
                )
                course_num += 1
                continue
            try:
                call, raw_direction = _extract_call(
                    call_text, course=course_num, distance_unit=distance_unit
                )
            except (ValidationError, ValueError, TypeError) as exc:
                if isinstance(exc, ValidationError):
                    # Never leak a raw pydantic dump: keep the validator messages only.
                    exc = _clean_validation_error(exc)
                if isinstance(exc, MultipleCoursesError):
                    pieces = _split_multi_course_fragment(call_text)
                    if len(pieces) > 1:
                        # Each piece is one complete course; extract them in turn.
                        call_texts[source_course - 1 : source_course] = pieces
                        region = _course_region(call_texts, starts_with_course=starts_with_course)
                        source_course -= 1
                        continue
                if _is_outside_region(region, source_course - 1, call_text):
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
                # Text before the first or after the closing course (cover sheets,
                # exception lists, form text) is not course material, unless it
                # states a complete course.
                if _is_outside_region(region, source_course - 1, call_text):
                    continue
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

        calls[clause_first_call:] = _mark_commencement_tie_ins(
            calls[clause_first_call:], clause_text, clause_first_course
        )

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

    calls = _restore_verbatim_records(calls, normalized, source_map)
    return _with_boundary_notes(calls, notes)


def _blank_keeping_lines(text: str, start: int, end: int) -> str:
    """Replace ``text[start:end]`` with spaces, keeping line breaks and offsets."""
    return text[:start] + re.sub(r"[^\n]", " ", text[start:end]) + text[end:]


def _set_aside_non_boundary_text(
    text: str, *, easements: bool = True
) -> tuple[str, list[tuple[int, int, str]]]:
    """Blank strip exceptions, stated exceptions (and easement descriptions) out of ``text``.

    Returns the blanked text (same length, so offsets are kept) and, in text order,
    each set-aside item's span in ``text`` and note prefix. A strip exception states
    no course: reading it as one invents a course, and splitting on its EXCEPT makes
    it an exception traverse. A stated exception after a closed description that
    describes no traverse (``stated_exception_spans``) is likewise never read as a
    course. An easement described by its own courses is not part of the parcel
    boundary. Geometric exceptions are kept.
    """
    from .tracts import easement_description_spans, stated_clause_end, stated_exception_spans

    set_aside: list[tuple[int, int, str]] = []
    for start, strip_end, strip in strip_exception_spans(text):
        end = stated_clause_end(text, strip_end)
        lead = start
        while lead > 0 and text[lead - 1] in " \t,;":
            lead -= 1
        stop = end
        # "... beginning. EXCEPTING ... thereof." leaves no stray period behind.
        gap = len(text[end:]) - len(text[end:].lstrip())
        if text[:lead].rstrip().endswith(".") and text[end + gap : end + gap + 1] == ".":
            stop = end + gap + 1
        prefix = (
            SEPARATE_EASEMENT_NOTE_PREFIX
            if strip["original_text"].lower().startswith("subject")
            else UNAPPLIED_EXCEPTION_NOTE_PREFIX
        )
        set_aside.append((start, end, prefix))
        text = _blank_keeping_lines(text, lead, stop)
    for start, end in stated_exception_spans(text):
        set_aside.append((start, end, UNAPPLIED_EXCEPTION_NOTE_PREFIX))
        text = _blank_keeping_lines(text, start, end)
    if easements:
        for start, end in easement_description_spans(text):
            set_aside.append((start, end, SEPARATE_EASEMENT_NOTE_PREFIX))
            text = _blank_keeping_lines(text, start, end)
    return text, sorted(set_aside)


def _set_aside_notes(
    items: list[tuple[int, int, str]], text: str, source: str | None
) -> list[tuple[int, str]]:
    """Return each set-aside item's offset and note, in the wording of ``source``.

    ``text`` is the normalized text the items were found in (before blanking). The
    wording is carried to ``source`` token by token (``_SourceMap``); wording that
    cannot be carried is searched for in ``source`` (``_verbatim_note``).
    """
    if not items:
        return []
    mapping = _SourceMap(source, text) if source else None
    notes: list[tuple[int, str]] = []
    for start, end, prefix in items:
        wording = mapping.source_wording(start, end) if mapping is not None else None
        notes.append(
            (start, prefix + wording)
            if wording
            else (start, _verbatim_note(prefix + text[start:end].strip(), source or text))
        )
    return notes


def _verbatim_note(note: str, source: str) -> str:
    """Return ``note`` with its wording as ``source`` states it, when found exactly once."""
    prefix = next(
        p
        for p in (UNAPPLIED_EXCEPTION_NOTE_PREFIX, SEPARATE_EASEMENT_NOTE_PREFIX)
        if note.startswith(p)
    )
    tokens = _WORD_TOKEN.findall(note[len(prefix) :])
    if not tokens:
        return note
    pattern = re.compile(r"\s*".join(re.escape(token) for token in tokens), re.IGNORECASE)
    found = list(pattern.finditer(source))
    return prefix + found[0].group() if len(found) == 1 else note


def _with_boundary_notes(calls: list[DeedCall], notes: list[str]) -> list[DeedCall]:
    """Record ``notes`` on the boundary's closing course (the last non-exception call).

    Notes go before any record-call wording, which ``_noted_record_calls`` reads
    as the last parts of the notes.
    """
    if not notes:
        return calls
    if not calls:
        logger.warning(
            "Set-aside description text has no boundary course to note it on", notes=notes
        )
        return calls
    index = next(
        (i for i in range(len(calls) - 1, -1, -1) if not calls[i].is_exception), len(calls) - 1
    )
    existing = calls[index].notes or ""
    marker = "; " + RECORD_CALL_NOTE_PREFIX
    if existing.startswith(RECORD_CALL_NOTE_PREFIX):
        head, tail = "", existing
    elif marker in existing:
        split = existing.index(marker)
        head, tail = existing[:split], existing[split + 2 :]
    else:
        head, tail = existing, ""
    combined = "; ".join(part for part in (head, *notes, tail) if part)
    updated = calls[index].model_copy(update={"notes": combined})
    return [*calls[:index], updated, *calls[index + 1 :]]


_WORD_TOKEN = re.compile(r"[A-Za-z0-9]+|\S")
# Beyond this many tokens a source alignment is not attempted; notes keep their
# normalized wording.
_MAX_ALIGNED_TOKENS = 40000


class _SourceMap:
    """The source text of a description, aligned token by token with its normalized text.

    Normalization respaces and rewrites wording ("N 45° 10' E" -> "N 45°10' E"), so
    a normalized span is carried back to the source by the tokens on either side of
    it that normalization left alone, never by re-searching the source for its text.
    """

    def __init__(self, source: str, normalized: str) -> None:
        self.source = source
        self.normalized = normalized
        self._source_tokens = list(_WORD_TOKEN.finditer(source))
        self._tokens = list(_WORD_TOKEN.finditer(normalized))
        self._starts = [token.start() for token in self._tokens]
        self._ends = [token.end() for token in self._tokens]
        self._to_source: dict[int, int] = {}
        if max(len(self._tokens), len(self._source_tokens)) <= _MAX_ALIGNED_TOKENS:
            matcher = SequenceMatcher(
                None,
                [token.group().lower() for token in self._tokens],
                [token.group().lower() for token in self._source_tokens],
                autojunk=False,
            )
            for block in matcher.get_matching_blocks():
                for offset in range(block.size):
                    self._to_source[block.a + offset] = block.b + offset
        self._next_tract = 0

    def locate_tract(self, tract_text: str) -> int | None:
        """Return the offset of the next tract (in order) in the normalized text."""
        found = self.normalized.find(tract_text, self._next_tract)
        if found < 0:
            return None
        self._next_tract = found + max(len(tract_text), 1)
        return found

    def source_wording(self, start: int, end: int) -> str | None:
        """Return the source wording of the normalized span, or None when not carried."""
        first = bisect_left(self._starts, start)
        last = bisect_right(self._ends, end) - 1
        source_first = self._to_source.get(first)
        source_last = self._to_source.get(last)
        if first > last or source_first is None or source_last is None:
            return None
        if not 0 <= source_last - source_first <= 2 * (last - first) + 8:
            return None
        return self.source[
            self._source_tokens[source_first].start() : self._source_tokens[source_last].end()
        ]


def _restore_verbatim_records(
    calls: list[DeedCall], tract_text: str, source_map: _SourceMap | None
) -> list[DeedCall]:
    """Return ``calls`` with each noted record call in the wording of the source.

    Normalization respaces bearings ("N 45° 10' E" -> "N 45°10' E"); a record call's
    wording is kept as the deed wrote it. Each wording is searched, whole words only
    and in order, in its own tract's normalized text and carried back to the source
    through ``source_map``; one that cannot be carried (its edge tokens were rewritten
    by normalization) keeps its normalized wording.
    """
    base = source_map.locate_tract(tract_text) if source_map else None
    if source_map is None or base is None:
        return calls
    restored: list[DeedCall] = []
    position = 0
    for call in calls:
        noted = _noted_record_calls(call.notes)
        verbatim: list[str] = []
        for wording in noted:
            tokens = _WORD_TOKEN.findall(wording)
            pattern = r"\s*".join(re.escape(token) for token in tokens)
            if tokens and tokens[0][0].isalnum():
                pattern = r"(?<![A-Za-z0-9])" + pattern
            if tokens and tokens[-1][-1].isalnum():
                pattern += r"(?![A-Za-z0-9])"
            match = re.compile(pattern).search(tract_text, position) if tokens else None
            source = (
                source_map.source_wording(base + match.start(), base + match.end())
                if match
                else None
            )
            if match:
                position = match.end()
            verbatim.append(source if source is not None else wording)
        if verbatim != noted and call.notes:
            head = call.notes[: call.notes.index(RECORD_CALL_NOTE_PREFIX)]
            notes = head + "; ".join(RECORD_CALL_NOTE_PREFIX + text for text in verbatim)
            call = call.model_copy(update={"notes": notes})
        restored.append(call)
    return restored


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
    # Strip exceptions are set aside first: their EXCEPT never splits a tract.
    working, strips = _set_aside_non_boundary_text(normalized, easements=False)
    segments = split_into_tracts(working)

    # Single-tract fast path: preserve backward-compatible behavior
    if len(segments) == 1 and segments[0][2] == TractType.MAIN:
        flat_calls = _extract_calls_from_text(
            normalized,
            distance_unit,
            audit_context=audit_context,
            course_start=1,
            strict=strict,
            skipped_courses=skipped_courses,
            normalize=False,
            source_text=text,
        )
        return flat_calls, []

    source_map = _SourceMap(text, working)
    segment_notes = _notes_by_segment(working, segments, strips, normalized, text)

    # Multi-tract path
    all_calls: list[DeedCall] = []
    tract_objects: list[Tract] = []

    for (segment_text, label, tract_type), boundary_notes in zip(
        segments, segment_notes, strict=True
    ):
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
            normalize=False,
            source_text=source_map,
            split_easements=False,
            boundary_notes=boundary_notes,
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
        # An easement's legs are never part of a boundary: they stay on its tract.
        if tract_type != TractType.EASEMENT:
            all_calls.extend(tract_calls)

    return all_calls, tract_objects


def _notes_by_segment(
    text: str,
    segments: list[tuple[str, str, TractType]],
    strips: list[tuple[int, int, str]],
    normalized: str,
    source: str,
) -> list[tuple[str, ...]]:
    """Assign each set-aside strip and each easement tract to a boundary tract's notes.

    ``text`` is ``normalized`` with the strips blanked (same offsets). A note belongs
    to the nearest boundary (non-easement, preferably non-exception) tract starting
    before it, else to the first boundary tract. Its wording is that of ``source``.
    """
    starts: list[int] = []
    cursor = 0
    for segment_text, _, _ in segments:
        head = segment_text[:64]
        found = text.find(head, cursor)
        if found < 0:
            found = text.find(head)
        starts.append(found)
        if found >= 0:
            cursor = found + len(head)

    boundary = [i for i, (_, _, kind) in enumerate(segments) if kind != TractType.EASEMENT]

    def owner(position: int) -> int | None:
        before = [i for i in boundary if 0 <= starts[i] <= position]
        preferred = [i for i in before if segments[i][2] != TractType.EXCEPTION]
        if preferred or before:
            return (preferred or before)[-1]
        return boundary[0] if boundary else None

    located = list(strips)
    unlocated: list[tuple[int, str]] = []
    for i, (segment_text, _, kind) in enumerate(segments):
        if kind != TractType.EASEMENT:
            continue
        start = starts[i]
        if start >= 0 and text.startswith(segment_text, start):
            located.append((start, start + len(segment_text), SEPARATE_EASEMENT_NOTE_PREFIX))
        else:
            note = _verbatim_note(SEPARATE_EASEMENT_NOTE_PREFIX + segment_text, source)
            unlocated.append((start, note))
    items = _set_aside_notes(sorted(located), normalized, source) + unlocated
    notes: list[list[str]] = [[] for _ in segments]
    for position, note in sorted(items, key=lambda item: item[0]):
        index = owner(position)
        if index is None:
            logger.warning("Set-aside description text has no boundary tract", note=note)
            continue
        notes[index].append(note)
    return [tuple(group) for group in notes]


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


# A hyphen between degrees and minutes with marked minutes/seconds: ``N 45-30' 15" E``,
# ``N 45-30'-15" E``, ``S 10-15' W``. The minute mark makes the hyphen a degree
# separator; a number group after an identifier word ("Lot N 12-3' E") stays a label.
_HYPHEN_MARKED_DMS_BEARING = re.compile(
    r"\b([NS])\.?\s*(\d{1,3})\s*-\s*(\d{1,2})\s*(?:'|\u2019|\u2032)\s*-?\s*"
    r"(?:(\d{1,2}(?:\.\d+)?)\s*(?:\"|\u2033|\u201d|''|\u2019\u2019)\s*)?([EW])\b",
    re.IGNORECASE,
)


def _expand_hyphen_marked_dms(text: str) -> str:
    """Rewrite hyphenated degrees with marked minutes/seconds into symbols."""

    def _repl(m: re.Match[str]) -> str:
        if _ends_with(_IDENTIFIER_BEFORE, text, m.start()) or _ends_with(
            _DASHED_LABEL_BEFORE, text, m.start()
        ):
            return m.group(0)
        seconds = f'{m.group(4)}"' if m.group(4) else ""
        return f"{m.group(1).upper()} {m.group(2)}\u00b0{m.group(3)}'{seconds} {m.group(5).upper()}"

    return _HYPHEN_MARKED_DMS_BEARING.sub(_repl, text)


# Tabular curve notation: explicit upper-case labels ("R=", "L=", "\u0394=", "CB=",
# "CH="/"C=") are the spelled-out curve elements, read through the one shared
# curve-element grammar. A label is a whole token followed by "=" and, for a
# length/angle, a number (for CB, a bearing letter); "D=" (degree of curve) and
# "A=" (arc or area) are ambiguous and stay unread, as does any unlabelled value.
_CURVE_LABELS = (
    (r"R", "radius of ", r"(?=\.?\d)"),
    (r"L", "arc length of ", r"(?=\.?\d)"),
    (r"[\u0394\u2206]|Delta", "delta of ", r"(?=\.?\d)"),
    (r"CB", "chord bearing of ", r"(?=[NS](?![a-z]))"),
    (r"CH|C", "chord length of ", r"(?=\.?\d)"),
)
_CURVE_LABEL_PATTERNS = tuple(
    (re.compile(rf"(?<![\w.])(?-i:{label})\s*=\s*{ahead}"), words)
    for label, words, ahead in _CURVE_LABELS
)


def _expand_curve_labels(text: str) -> str:
    """Spell out tabular curve labels ("R=100'" -> "radius of 100'")."""
    for pattern, words in _CURVE_LABEL_PATTERNS:
        text = pattern.sub(words, text)
    return text


def _normalize_bearing_forms(text: str) -> str:
    """Rewrite every bearing form the parser accepts into abbreviated DMS."""
    return standardize_cardinal_directions(
        _expand_compact_dms(
            _expand_marked_dms(_expand_hyphen_marked_dms(_expand_curve_labels(text)))
        )
    )


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
# "C.B." (chord bearing) is the dotted abbreviation only; it opens a clause only
# when a bearing follows (``_CHORD_BEARING_LEAD``).
_CHORD_SUBJECT = r"(?:chord|C\.\s?B\.)"
_RADIAL_SUBJECT = (
    r"(?:radius\s+point|radius|radial(?:\s+(?:line|bearing))?"
    r"|cent(?:er|re)(?:\s+point)?(?:\s+of\s+(?:the|said)\s+curve)?)"
)
# The chord may state its length before the bearing ("a chord of 51.76 feet bearing
# N 45 E"), say "on a bearing of", and drop the verb when a quadrant bearing follows
# the subject (or the length phrase) directly ("chord N 45 E, 51.76 feet"). Without
# a bearing verb, a link ("of", "direction of", "brg.", "runs", ":" or "=") opens
# the clause only when a quadrant bearing follows it directly.
_BEARING_AHEAD = r"(?=(?:N|S|North|South)(?![a-z]))"
_CHORD_BEARING_LEAD = (
    rf"(?:{_CLAUSE_VERB}|on\s+(?:a\s+)?bearing\s+(?:of\s+)?"
    rf"|(?:direction|brgs?\.?)(?:\s+(?:of|is))?\s*{_BEARING_AHEAD}"
    rf"|(?:runs?|running)\s+{_BEARING_AHEAD}|of\s+{_BEARING_AHEAD}|{_BEARING_AHEAD})"
)
_CHORD_PREFIX_PATTERN = re.compile(
    rf"\b{_CHORD_SUBJECT}(?:\s+(?:length|distance))?(?:\s*[:=]\s*|\s+)"
    rf"(?:(?:of\s+)?(?P<chord_lead_len>{LENGTH_NUMBER})\s*(?P<chord_lead_unit>{LENGTH_UNIT})\.?\s*,?\s*"
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
    # The normalized course text without tie/adjoiner pairs, read for a straight
    # course's length (``read_course_length``).
    distance_text: str = ""


class _PreparedCourse(NamedTuple):
    """Boundary course text normalized for bearing reading, with its verbatim candidates."""

    normalized: str
    candidates: list[str]
    normalized_candidates: list[str]


def _prepare_course_text(
    call_text: str, curve_info: dict[str, float | str | None]
) -> _PreparedCourse:
    """Prepare the text every course bearing reading uses.

    Corner witnesses are cut off, and the course text and its verbatim bearing
    candidates are normalized together in one pass. Chord and
    radial/radius-point/center clauses (with their bearings) are then removed, so
    only a bearing describing the course itself remains. On a straight course, a
    radial clause naming the line being run ("along a radial line bearing ...")
    states the course bearing and is kept; one describing the radius point of a
    curve reached at the end of the line is removed. ``curve_info`` is
    ``extract_curve_info(call_text)``.
    """
    keep_line_radial = not _describes_curve(curve_info)
    course_text = _boundary_course_text(call_text)
    candidates = _verbatim_candidates(course_text, keep_line_radial=keep_line_radial)
    normalized, *normalized_candidates = _normalize_bearing_segments([course_text, *candidates])
    normalized = _without_reference_bearings(normalized, _CHORD_PREFIX_PATTERN)
    normalized = _without_reference_bearings(
        normalized, _RADIAL_PREFIX_PATTERN, keep_line_radial=keep_line_radial
    )
    return _PreparedCourse(normalized, candidates, normalized_candidates)


_CONCAVITY_DIRECTION = r"(?:north|south)(?:[\s-]*(?:east|west))?|east|west|NE|NW|SE|SW|[NSEW]"
_CONCAVITY_CLAUSE = re.compile(
    rf"\b(?:concave[d]?(?:\s+(?:to|toward|towards|facing)\s+(?:the\s+)?)?"
    rf"|whose\s+concave\s+side\s+(?:faces|is\s+(?:to|toward|towards))\s+(?:the\s+)?)"
    rf"\s*(?:{_CONCAVITY_DIRECTION})(?:erly|wardly)?\b",
    re.IGNORECASE,
)


def _course_bearing(call_text: str, curve_info: dict[str, float | str | None]) -> _CourseBearing:
    """Return the course (tangent) direction stated in the boundary course text.

    ``call_text`` is the fragment's reading text (``_scan_record_calls``), so record
    calls are already blanked. The text is prepared by ``_prepare_course_text``.
    When the fragment states a complete boundary course, tie and adjoiner pairs
    (``_bearing_pairs``) are removed before extraction, so they never replace the
    course. ``curve_info`` is ``extract_curve_info(call_text)``, computed once by
    the caller.
    """
    prepared = _prepare_course_text(call_text, curve_info)
    pairs = _bearing_pairs(prepared.normalized)
    courses = [pair for pair in pairs if pair.complete and pair.boundary]
    text = prepared.normalized
    others = [pair for pair in pairs if not pair.boundary]
    if courses:
        text = _without_pairs(text, others)
    # Concavity wording names the side of the curve's centre, never the travel direction.
    direction = extract_direction(_CONCAVITY_CLAUSE.sub(" ", text))
    return _CourseBearing(
        direction,
        _verbatim_course_direction(direction, prepared.candidates, prepared.normalized_candidates),
        len(courses),
        # Read with bearings normalized (a bearing's "30m" minutes is never a
        # length), without tie/adjoiner pairs, whose lengths are never course lengths.
        _without_pairs(prepared.normalized, others),
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


def _verbatim_bearing_matches(
    course_text: str, *, keep_line_radial: bool = False
) -> list[re.Match[str]]:
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
    return [m for m in _VERBATIM_BEARING.finditer(course_text) if m.start() not in excluded]


def _verbatim_candidates(course_text: str, *, keep_line_radial: bool = False) -> list[str]:
    """Return the deed's bearings in ``course_text``, skipping chord/radial openers."""
    return [
        m.group(0)
        for m in _verbatim_bearing_matches(course_text, keep_line_radial=keep_line_radial)
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
    rf"(?<=[\d{VULGAR_FRACTIONS}])(\s*{UNIT_TOKEN}\b\.?)\s+(?=(?:N|S|North|South)\.?\s*\d|due\s+(?:north|south|east|west)\b)",
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

    The text is read exactly as for the course bearing (record calls blanked by
    ``_scan_record_calls``, then ``_prepare_course_text``), so a record call or a
    curve's chord or radial bearing and length never count as a second course.
    """
    reading = _scan_record_calls(call_text).reading
    return _complete_courses(_prepare_course_text(reading, extract_curve_info(reading)).normalized)


# --- Bearing + distance pair roles ----------------------------------------------------
# Only a BOUNDARY pair is a course. A TIE locates a point ("said pin being N 30 E
# 2 feet from a stone", "a point distant S 10 W 50 feet from a monument"); an
# ADJOINER pair describes a neighbouring line ("which line bears S 45 E 300 feet").
# Their wording stays in the call text; they are only excluded from course reading.
# Record calls never reach this reading: they are blanked first (``_scan_record_calls``).
_ROLE_WINDOW = 120
# Shared with the course-length roles (``read_course_length``). "... 2 feet
# from|of <object>" is applied only to a pair after the first: a fragment's first
# pair is its course unless a prefix marks it.
_TIE_BEFORE = TIE_BEFORE_PATTERN
_LENGTH_RUN = LENGTH_RUN
_TIE_AFTER = TIE_AFTER_PATTERN
_ADJOINER_BEFORE = re.compile(
    r"(?:(?<![A-Za-z])(?:which|said|whose)\s+line\s+|\bthe\s+line\s+of\s+[^,;()]{1,80}?\s+)"
    r"(?:bears?|bearing|runs?)\s+(?:of\s+)?$",
    re.IGNORECASE,
)


class _BearingPair(NamedTuple):
    """A course-form bearing, the length stated after it (if any) and its role."""

    start: int
    end: int  # end of its length, or of the bearing without one
    complete: bool
    boundary: bool


def _in_parentheses(text: str, position: int) -> bool:
    """Return True when ``position`` is inside a parenthetical or bracketed group."""
    opened = max(text.rfind("(", 0, position), text.rfind("[", 0, position))
    return opened > max(text.rfind(")", 0, position), text.rfind("]", 0, position))


def _is_tie_or_adjoiner(text: str, start: int) -> bool:
    """Return True when the wording before ``start`` makes its pair a tie or adjoiner line."""
    before = text[max(0, start - _ROLE_WINDOW) : start]
    return bool(_ADJOINER_BEFORE.search(before) or _TIE_BEFORE.search(before))


def _bearing_pairs(text: str) -> list[_BearingPair]:
    """Return every course-form bearing in normalized course text with its role.

    A pair is complete when a length follows the bearing before the next bearing.
    ``text`` has had its record calls (``_scan_record_calls``) and its chord and
    radial clauses removed. A later BEGINNING/COMMENCING clause opens another
    description, whose bearings are ties to its point of beginning, so reading
    stops there.
    """
    preamble = _LATER_BEGINNING.search(text, 1)
    if preamble:
        text = text[: preamble.start()]
    bearings = _course_bearing_spans(text)
    ends = [start for start, _ in bearings[1:]] + [len(text)] if bearings else []
    pairs = []
    for index, ((start, bearing_end), segment_end) in enumerate(zip(bearings, ends, strict=True)):
        length = _LENGTH_TOKEN.search(text, bearing_end, segment_end)
        end = length.end() if length else bearing_end
        complete = length is not None
        boundary = not _is_tie_or_adjoiner(text, start) and (
            index == 0 or not (complete and _TIE_AFTER.match(text[end : end + _ROLE_WINDOW]))
        )
        pairs.append(_BearingPair(start, end, complete, boundary))
    return pairs


# --- Record calls ---------------------------------------------------------------------
# A RECORD call restates the course as an earlier deed, plan or record gave it: a
# bracketed group holding a course bearing or a labelled length ("(deed N 44 E)",
# "[N 44 E 99 feet deed]", "(recorded as 600.00 feet)"), or a pair or length
# labelled "(R)", "per deed" or "of record" beside the course's own value. Record
# calls are identified once per fragment (``_scan_record_calls``), before any
# bearing, tangent, chord, radial, length or curve element is read, and are blanked
# from the text every reading uses: a record value never becomes a course value, and
# a course that does not state a value itself fails closed (or stays cardinal only)
# under the usual rules. Their wording is kept verbatim in notes.
_RECORD_BEFORE = re.compile(
    r"(?<![A-Za-z])(?:per\s+(?:deed|record)|of\s+record|(?:(?:in|from|by|as\s+in)\s+(?:the\s+|said\s+)?"
    r"(?:prior|previous|former|earlier|original|old)\s+)?(?:deed|record)|[(\[]R[)\]])\s*[:=]?\s*$",
    re.IGNORECASE,
)
_RECORD_AFTER = re.compile(
    _LENGTH_RUN
    + r"(?:(?:per|by)\s+(?:deed|record)\b|of\s+record\b|(?P<mark>[(\[](?:R|record|deed)[)\]]))",
    re.IGNORECASE,
)
# A record mark straight after a bearing, before its length ("N 45 E (R) 100 feet").
_RECORD_MARK_AFTER = re.compile(r"\s*,?\s*[(\[](?:R|record|deed)[)\]]", re.IGNORECASE)
_MEASURED_AFTER = re.compile(r"\s*,?\s*[(\[](?:M|(?i:meas\.?|measured))[)\]]")
# Inside a bracketed group: a record word, or a trailing "R" ("(100 feet R)").
_GROUP_RECORD_WORD = re.compile(
    r"(?<![A-Za-z])(?:deeds?|rec|record(?:ed|s)?|formerly|(?:per|by)\s+(?:plan|plat|map|survey))"
    r"(?![A-Za-z])",
    re.IGNORECASE,
)
_GROUP_RECORD_LABEL = re.compile(r"(?<![A-Za-z])R\.?\s*$")
# One vocabulary for source labels: a plan, plat, map or survey word, or a lone "P"/"D",
# labelling a value at the end of the group ("(100 feet plan)", "(100 feet, plat)",
# "(100 feet P)") or opening it with a colon ("(plat: 100 feet)"). "see plan 12 feet"
# refers to a plan and is not a label.
_GROUP_SOURCE_LABEL = re.compile(
    r"(?<![A-Za-z])(?:plan|plat|map|survey|P|D)\.?\s*$|^\s*(?:plan|plat|map|survey)\s*[:=]",
    re.IGNORECASE,
)
_GROUP_SEE = re.compile(r"(?<![A-Za-z])see(?![A-Za-z])", re.IGNORECASE)
_GROUP_MEASURED_LABEL = re.compile(
    r"^\s*(?:M|(?i:meas\.?|measured))(?![A-Za-z])|(?<![A-Za-z])(?:M|(?i:meas\.?|measured))\s*$"
)
# A road width ("(formerly X Avenue - 100.00 feet wide)") is never a record call.
_GROUP_WIDTH = re.compile(r"(?<![A-Za-z])(?:wide|in\s+width)(?![A-Za-z])", re.IGNORECASE)
# The course's own direction word beside a labelled pair ("thence Northeasterly 100
# feet per deed N 44 E"): a compass word ending -erly/-ward(ly), a "due" direction,
# or a compass word opening the course. A line or road name ("the Westerly line of",
# "North Street") is not a direction.
_COURSE_DIRECTION_WORD = re.compile(
    r"(?:(?<![A-Za-z])(?:(?:north|south)(?:[\s-]*(?:east|west))?|east|west)"
    r"(?:erly|wardly|wards?)|\bdue\s+(?:north|south|east|west)"
    r"|(?:^|\bthence\b)\s*,?\s*(?:(?:north|south)(?:[\s-]*(?:east|west))?|east|west|N[EW]|S[EW]))"
    r"(?![A-Za-z])(?!\s+(?:lines?|sides?|corners?|boundary|edge|most|half|part|portion|end"
    r"|face|of|street|avenue|road|lane|drive)\b)",
    re.IGNORECASE,
)


class _RecordStatement(NamedTuple):
    """A bearing (with its length) or a lone length, labelled by the deed's wording."""

    start: int  # start of its wording: label, chord/radial opener or value
    end: int  # end of its wording: label, length or bearing
    length: tuple[int, int] | None
    kind: str  # "course", "chord" or "radial" for a bearing; "length" for a lone length
    label: str  # "record", "measured", "plain" or "other" (a tie or adjoiner line)


class _RecordScan(NamedTuple):
    """Course text with its record calls blanked, and their verbatim wording."""

    reading: str
    records: tuple[str, ...]
    # Each other bracketed group holding a length, verbatim, and whether it only
    # describes a feature (states no course-capable length: "(50 feet wide)").
    parentheticals: tuple[tuple[str, bool], ...] = ()
    # Spans of ``call_text`` that are the course's own readings, not an adjoiner: the
    # record calls and the measured groups, so ``along`` is built without them.
    drop_spans: tuple[tuple[int, int], ...] = ()


def _bracket_groups(text: str) -> list[tuple[int, int, bool]]:
    """Return top-level bracketed groups (nested-aware) as (start, end, closed).

    An unclosed group runs to the end of ``text``.
    """
    groups: list[tuple[int, int, bool]] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char in "([":
            if depth == 0:
                start = index
            depth += 1
        elif char in ")]" and depth:
            depth -= 1
            if depth == 0:
                groups.append((start, index + 1, True))
    if depth:
        groups.append((start, len(text), False))
    return groups


def _lengths_outside_bearings(text: str) -> list[re.Match[str]]:
    """Return the lengths in ``text`` that are not part of a bearing."""
    spans = [(m.start(), m.end()) for m in _VERBATIM_BEARING.finditer(text)]
    return [
        token
        for token in _LENGTH_TOKEN.finditer(text)
        if not any(start <= token.start() < end for start, end in spans)
    ]


def _measured_labels(inner: str, lengths: list[re.Match[str]]) -> list[tuple[int, int]]:
    """Return the measured labels ("M", "meas.") in a group, never a metre unit."""
    return [
        label.span()
        for label in _GROUP_MEASURED_LABEL.finditer(inner)
        if not any(token.start() <= label.start() < token.end() for token in lengths)
    ]


def _states_course_bearing(text: str) -> bool:
    """Return True when ``text`` holds a course bearing in the deed's own wording.

    Quadrant (any form), packed and due bearings count; a chord or radial clause
    bearing does not. The text is not normalized: normalization runs once per call.
    """
    return bool(
        _verbatim_bearing_matches(text, keep_line_radial=True)
        or PACKED_DMS_PATTERN.search(text)
        or _DUE_COURSE_BEARING.search(text)
    )


def _group_role(inner: str) -> str | None:
    """Return "record", "measured" or None for a bracketed group's inner text.

    A group holding a course bearing (quadrant, packed or due) restates the course
    (record) unless it is labelled measured; a group holding only lengths is a record
    call when a record word or a trailing "R" labels it, never a width. A chord or
    radial bearing is not a course bearing.
    """
    has_bearing = _states_course_bearing(inner)
    lengths = _lengths_outside_bearings(inner)
    if not (has_bearing or lengths):
        return None
    record = bool(
        _GROUP_RECORD_WORD.search(inner)
        or _GROUP_RECORD_LABEL.search(inner)
        or (_GROUP_SOURCE_LABEL.search(inner) and not _GROUP_SEE.search(inner))
    )
    if not record and _measured_labels(inner, lengths):
        return "measured"
    if has_bearing or (lengths and record and not _GROUP_WIDTH.search(inner)):
        return "record"
    return None


def _blank(text: str, start: int, end: int) -> str:
    """Replace ``text[start:end]`` with spaces, keeping every position."""
    return text[:start] + " " * (end - start) + text[end:]


def _reference_openers(text: str) -> dict[int, tuple[str, int]]:
    """Return bearing start -> (kind, opener start) for chord and radial clause bearings.

    A radial line being run ("along a radial line bearing ...") is the course itself.
    """
    openers: dict[int, tuple[str, int]] = {}
    for kind, prefix in (("chord", _CHORD_PREFIX_PATTERN), ("radial", _RADIAL_PREFIX_PATTERN)):
        for match in prefix.finditer(text):
            if kind == "radial" and _runs_along_radial(text, match.start()):
                continue
            clause_end = _CLAUSE_END.search(text, match.end())
            stop = clause_end.start() if clause_end else len(text)
            reference = _VERBATIM_BEARING.search(text, match.end(), stop)
            if reference:
                openers.setdefault(reference.start(), (kind, match.start()))
    return openers


def _record_label_after(
    text: str, end: int, next_bearing: int | None, *, mark_only: bool = False
) -> int | None:
    """Return the end of a record label describing the value that ends at ``end``.

    A word label running straight into the next bearing ("... 100 feet, per record
    N ...") introduces that bearing and does not describe the value before it.
    """
    suffix = _RECORD_AFTER.match(text[end : end + _ROLE_WINDOW])
    if not suffix or (mark_only and not suffix.group("mark")):
        return None
    if suffix.group("mark") or next_bearing is None:
        return end + suffix.end()
    return end + suffix.end() if text[end + suffix.end() : next_bearing].strip() else None


def _record_statements(text: str, limit: int) -> list[_RecordStatement]:
    """Return the bearings and labelled lone lengths of ``text`` before ``limit``.

    ``text`` has its record groups blanked. A bearing's length is the first length
    before the next bearing; its label is a record label before it or after its
    length ("(R)", "per deed", "of record"; "being ... of record" is a record call,
    not a tie), a tie or adjoiner prefix ("other"), a measured label after it
    ("(M)"), or none ("plain").
    """
    bearings = list(_VERBATIM_BEARING.finditer(text, 0, limit))
    openers = _reference_openers(text[:limit])
    statements: list[_RecordStatement] = []
    pair_lengths: set[int] = set()
    first_course = True
    for index, bearing in enumerate(bearings):
        next_bearing = bearings[index + 1].start() if index + 1 < len(bearings) else None
        kind, start = openers.get(bearing.start(), ("course", bearing.start()))
        length = _LENGTH_TOKEN.search(text, bearing.end(), next_bearing or limit)
        end = length.end() if length else bearing.end()
        if length:
            pair_lengths.add(length.start())
        before = text[max(0, start - _ROLE_WINDOW) : start]
        label = "plain"
        record_before = _RECORD_BEFORE.search(before)
        if record_before and statements and record_before.group(0).lstrip()[:1] in ("(", "["):
            # "N 45 W (R) N 45 10 W (M)", "N 45 W 100 feet (R) N 45 10 W (M)": a mark that
            # ends the previous record statement labels it, not this bearing.
            previous = statements[-1]
            if (
                previous.label == "record"
                and text[: previous.end].rstrip().endswith((")", "]"))
                and not text[previous.end : start].strip()
            ):
                record_before = None
        record_after = _record_label_after(text, end, next_bearing, mark_only=length is None)
        measured = _MEASURED_AFTER.match(text, end)
        record_mark = _RECORD_MARK_AFTER.match(text, bearing.end())
        if record_before:
            label, start = "record", start - (len(before) - record_before.start())
        elif record_mark and record_after is None:
            label, end = "record", record_mark.end()
        elif record_after is not None:
            label, end = "record", record_after
        elif kind == "course" and _is_tie_or_adjoiner(text, start):
            label = "other"
        elif measured:
            label, end = "measured", measured.end()
        elif (
            kind == "course"
            and not first_course
            and length
            and _TIE_AFTER.match(text[end : end + _ROLE_WINDOW])
        ):
            label = "other"
        first_course = first_course and kind != "course"
        statements.append(
            _RecordStatement(start, end, length.span() if length else None, kind, label)
        )
    for token in _lengths_outside_bearings(text[:limit]):
        if token.start() in pair_lengths or _in_parentheses(text, token.start()):
            continue
        following = next((b.start() for b in bearings if b.start() >= token.end()), None)
        record_after = _record_label_after(text, token.end(), following)
        measured = _MEASURED_AFTER.match(text, token.end())
        if record_after is not None:
            statements.append(
                _RecordStatement(token.start(), record_after, token.span(), "length", "record")
            )
        elif measured:
            statements.append(
                _RecordStatement(token.start(), measured.end(), token.span(), "length", "measured")
            )
    return statements


def _states_own_direction(text: str, limit: int, records: list[_RecordStatement]) -> bool:
    """Return True when ``text`` states a course direction word outside ``records``."""
    for record in records:
        text = _blank(text, record.start, record.end)
    for start, end, _closed in _bracket_groups(text):
        text = _blank(text, start, end)
    text = _CONCAVITY_CLAUSE.sub(lambda m: " " * len(m.group(0)), text[:limit])
    return bool(_COURSE_DIRECTION_WORD.search(text))


def _record_spans(
    text: str, limit: int, statements: list[_RecordStatement]
) -> list[tuple[int, int]]:
    """Return the spans of the labelled statements that are record calls.

    A record-labelled bearing is a record call beside another bearing of the same
    kind (course, chord or radial) that is unlabelled or measured; a record-labelled
    course bearing also beside the course's own direction word. A fragment's only
    labelled bearing is its course ("N 45 E 100 feet (R)"), except that beside a
    measured length its length alone is the record call ("100 feet (R) (100.05 feet
    M)"). A record-labelled lone length is a record call beside an unlabelled or
    measured course length.
    """
    spans: list[tuple[int, int]] = []
    measured_length = any(s.kind == "length" and s.label == "measured" for s in statements)
    for kind in ("course", "chord", "radial"):
        records = [s for s in statements if s.kind == kind and s.label == "record"]
        if not records:
            continue
        rivals = [s for s in statements if s.kind == kind and s.label in ("plain", "measured")]
        if rivals or (kind == "course" and _states_own_direction(text, limit, records)):
            # "N 45 E (R) 100.5 feet (M) N 46 E 100 feet": beside a rival with its
            # own length, the length after the mark is the record's, not the course's.
            rival_length = any(s.length for s in rivals)
            spans.extend(
                (
                    s.start,
                    s.length[1] if rival_length and s.length and s.length[0] >= s.end else s.end,
                )
                for s in records
            )
        elif kind == "course" and measured_length:
            spans.extend((s.length[0], s.end) for s in records if s.length)
    course_length = measured_length or any(
        s.kind == "course" and s.label in ("plain", "measured") and s.length for s in statements
    )
    if course_length:
        spans.extend(
            (s.start, s.end) for s in statements if s.kind == "length" and s.label == "record"
        )
    return spans


@lru_cache(maxsize=4096)
def _scan_record_calls(call_text: str) -> _RecordScan:
    """Identify the record calls of one course fragment before anything is read from it.

    Bracketed groups are found nested-aware: a record group (``_group_role``) is
    blanked whole; a measured group keeps its values and loses only its brackets
    and label. Labelled bearings and lone lengths outside groups are then read
    (``_record_statements``) and the record calls among them blanked
    (``_record_spans``). ``reading`` keeps every position of ``call_text``, so
    along/to and every other verbatim field still come from ``call_text``; bearing,
    tangent, chord, radial, length and curve elements are read only from
    ``reading``. ``records`` is each record call's wording, verbatim, in order.
    """
    course_text = _boundary_course_text(call_text)
    text = course_text
    spans: list[tuple[int, int]] = []
    measured_groups: list[tuple[int, int]] = []
    parentheticals: list[tuple[str, bool]] = []
    for start, end, closed in _bracket_groups(course_text):
        inner_start = start + 1
        inner = course_text[inner_start : end - 1 if closed else end]
        role = _group_role(inner)
        if role is None and _lengths_outside_bearings(inner):
            stated = read_course_length(inner)
            describes = stated.value == 0.0 and not stated.ambiguous
            parentheticals.append((call_text[start:end].strip(), describes))
        if role == "record":
            spans.append((start, end))
            text = _blank(text, start, end)
        elif role == "measured":
            text = _blank(text, start, inner_start)
            if closed:
                text = _blank(text, end - 1, end)
            for label_start, label_end in _measured_labels(inner, _lengths_outside_bearings(inner)):
                text = _blank(text, inner_start + label_start, inner_start + label_end)
            measured_groups.append((start, end))
    preamble = _LATER_BEGINNING.search(text, 1)
    limit = preamble.start() if preamble else len(text)
    statements = [
        statement._replace(label="measured")
        if statement.label == "plain"
        and any(start <= statement.start < end for start, end in measured_groups)
        else statement
        for statement in _record_statements(text, limit)
    ]
    statements += [
        _RecordStatement(token.start(), token.end(), token.span(), "length", "measured")
        for start, end in measured_groups
        for token in _lengths_outside_bearings(text[:end])
        if token.start() >= start and not any(s.length == token.span() for s in statements)
    ]
    labelled = _record_spans(text, limit, statements)
    for start, end in labelled:
        text = _blank(text, start, end)
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans + labelled):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    records = tuple(call_text[start:end].strip() for start, end in merged)
    return _RecordScan(
        text + call_text[len(course_text) :],
        records,
        tuple(parentheticals),
        tuple(sorted(merged + measured_groups)),
    )


def _parenthetical_notes(
    parentheticals: tuple[tuple[str, bool], ...],
    along: str | None,
    to: str | None,
    passing: tuple[str, ...] = (),
) -> list[str]:
    """Return the notes keeping each bracketed non-record length verbatim.

    A bracketed length that is not a record or measured call is never read as the
    course length (``_length_role``), so it must not vanish: an alternative length
    ("(calculated 101 feet)", "(see plan 12 feet)") is always noted; a description
    that states no course-capable length ("(50 feet wide)", "(crossing a 10 foot
    easement)") is noted only when the along/to wording does not keep it verbatim.
    """
    kept = " ".join(field for field in (along, to) if field)
    return [
        PARENTHETICAL_NOTE_PREFIX + wording
        for wording, describes in parentheticals
        # A bracketed passing call is noted once, as the passing call.
        if wording[1:-1].strip(" ,;.") not in passing and not (describes and wording in kept)
    ]


def _noted_record_calls(notes: str | None) -> list[str]:
    """Return the record-call wording kept in ``notes`` (always its last parts)."""
    if not notes:
        return []
    marker = "; " + RECORD_CALL_NOTE_PREFIX
    if notes.startswith(RECORD_CALL_NOTE_PREFIX):
        rest = notes[len(RECORD_CALL_NOTE_PREFIX) :]
    elif marker in notes:
        rest = notes[notes.index(marker) + len(marker) :]
    else:
        return []
    return rest.split(marker)


def _without_pairs(text: str, pairs: list[_BearingPair]) -> str:
    """Blank out ``pairs`` (bearing through length) in ``text``."""
    for pair in reversed(pairs):
        text = text[: pair.start] + " " + text[pair.end :]
    return text


def _complete_courses(text: str) -> tuple[int, bool]:
    """Return (complete boundary courses, has any course bearing) in normalized text.

    A complete course is a complete boundary pair (``_bearing_pairs``): a
    course-form bearing and its length that are not a tie or adjoiner call.
    """
    pairs = _bearing_pairs(text)
    return sum(1 for pair in pairs if pair.complete and pair.boundary), bool(pairs)


_COURSE_SEPARATOR = re.compile(r";|(?<=\S)\s+(?=THENCE\b)|,\s*(?=thence\b)", re.IGNORECASE)


def _course_segments(call_text: str) -> list[str]:
    """Cut a fragment at ';' and at a later THENCE into its candidate course segments."""
    return [piece.strip() for piece in _COURSE_SEPARATOR.split(call_text) if piece.strip()]


def _is_curve_segment(segment: str) -> bool:
    """Return True when a segment states a curve's own direction or radius."""
    info = extract_curve_info(segment)
    return info.get("direction") in ("left", "right") or info.get("radius_ft") is not None


def _segment_course_count(segment: str) -> int:
    """Complete courses in one segment: a curve counts as one even without a bearing."""
    complete = _boundary_course_reading(segment)[0]
    return max(complete, 1) if _is_curve_segment(segment) else complete


def _has_second_course(call_text: str) -> bool:
    """Return True when a curve fragment also holds a separate complete course.

    A curve states no bearing of its own course, so the bearing of a following
    straight course (a complete bearing and length in a segment without curve
    wording) or a further THENCE curve must not be read as its tangent.
    """
    segments = _course_segments(call_text)
    if len(segments) < 2:
        return False
    curves = [segment for segment in segments if _is_curve_segment(segment)]
    if not curves:
        return False
    if any(
        not CURVE_KEYWORD_PATTERN.search(segment) and _boundary_course_reading(segment)[0] >= 1
        for segment in segments
    ):
        return True
    return sum(1 for segment in curves[1:] if re.match(r"thence\b", segment, re.I)) >= 1


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
        piece
        for segment in _course_segments(call_text)
        for piece in _split_juxtaposed_courses(segment)
    ]
    pieces: list[str] = []
    pending = ""  # descriptive wording before the first course
    for segment in segments:
        if not segment.strip():
            continue
        complete, has_bearing = _boundary_course_reading(segment)
        complete = _segment_course_count(segment)
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


_BEGINNING_CLAUSE = re.compile(r"^\s*(BEGINNING|COMMENCING|POB)\b", re.IGNORECASE)


def _format_quadrant(cardinal1: str, degrees: float, cardinal2: str) -> str:
    """Quadrant bearing as stated: seconds kept, never rounded into the next degree/minute."""
    total = round(degrees * 3600, 2)
    deg, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if seconds == 0:
        return f"{cardinal1} {int(deg)}\u00b0{int(minutes):02d}' {cardinal2}"
    seconds_text = f"{seconds:05.2f}".rstrip("0").rstrip(".")
    return f"{cardinal1} {int(deg)}\u00b0{int(minutes):02d}'{seconds_text}\" {cardinal2}"


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
        The parsed DeedCall, or None only for a BEGINNING/COMMENCING/POB clause (no course).

    Raises:
        MultipleCoursesError: The text states more than one complete course.
        ValueError: No usable course is present (e.g. no readable bearing or direction,
            a zero or unread length, ambiguous length or an unsupported compound
            distance component); a dropped course is never reported as None.
    """
    try:
        call = _extract_call(call_text, course, distance_unit)[0]
    except ValidationError as exc:
        raise _clean_validation_error(exc) from exc
    if call is None and not _BEGINNING_CLAUSE.match(call_text):
        raise ValueError(
            "No usable course could be parsed (no readable direction, or a zero or "
            f"unread length): {call_text.strip()!r}"
        )
    return call


def _inch_course_length(course_text: str, direction: str) -> float | None:
    """Feet of a straight course stated wholly in inches directly after its bearing."""
    position = course_text.find(direction) if direction else -1
    if position < 0:
        return None
    return read_standalone_inch_length(course_text[position + len(direction) :])


def _adjoiner_wording(
    along: str,
    course_direction: str,
    course_distance_ft: float | None,
    records: tuple[str, ...] = (),
) -> str:
    """Return ``along`` without the course's own bearing and length.

    ``along`` is the deed's wording after "along"; on a straight course it can
    run on into the course itself ("Main Street (50 feet wide) N 45 E 100 feet").
    The course's own verbatim bearing and the length read as its distance are
    removed; everything else, parentheticals and record calls (``records``)
    included, stays as written.
    """
    # Record wording is never taken for the course's own bearing or length.
    located = along
    for record in records:
        position = located.find(record)
        if position >= 0:
            located = _blank(located, position, position + len(record))
    if course_direction:
        position = located.find(course_direction)
        while position >= 0 and _in_parentheses(along, position):
            position = located.find(course_direction, position + 1)
        if position >= 0:
            end = position + len(course_direction)
            gap = len(along[end:]) - len(along[end:].lstrip())
            length = _LENGTH_TOKEN.match(along, end + gap)
            if length:
                end = length.end()
            along = _blank(along, position, end)
            located = _blank(located, position, end)
    if course_distance_ft is not None:
        for token in reversed(list(_LENGTH_TOKEN.finditer(located))):
            if _in_parentheses(along, token.start()):
                continue
            reading = read_course_length(token.group(0))
            if reading.ambiguous or reading.value <= 0:
                continue
            converted = ConversionFactors.convert_to_feet(reading.value, reading.unit)
            if converted is not None and abs(converted - course_distance_ft) < 1e-6:
                # The length goes with its wording ("a distance of", "more or less").
                start, end = course_length_phrase_span(along, token.start(), token.end())
                along = along[:start] + " " + along[end:]
                break
    return re.sub(r"\s{2,}", " ", along).strip(" ,;.")


_N = r"(?:N|S|(?i:north|south))"
_EW = r"(?:E|W|(?i:east|west))"
_OUT_OF_RANGE_BEARING = re.compile(
    rf"\b{_N}\.?\s*(?P<deg>\d{{1,3}}(?:\.\d+)?)\s*(?P<sep>\u00b0|\u00ba|-|(?i:degrees?|deg\b\.?))"
    rf"(?P<rest>[^;,]{{0,40}}?)\s*(?<![A-Za-z]){_EW}(?![A-Za-z])"
)
_BEARING_PART = re.compile(
    r"\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<mark>['\u2032\u2019]|\"|\u2033|\u201d|(?i:minutes?|min\b\.?"
    r"|seconds?|sec\b\.?))?\s*-?"
)


def _has_out_of_range_bearing(text: str) -> bool:
    """Return True when ``text`` holds a quadrant bearing with an out-of-range component.

    One recogniser for letter or spelled cardinals, degree mark, hyphen or words, and
    any component: degrees above 90, or marked minutes or seconds of 60 or more. Bearing
    shape is required (cardinal, degrees with a mark, word or hyphen, optional minutes
    and seconds, cardinal), so "North 91 feet" and identifiers are not bearings, and an
    unmarked hyphen component alone never makes an identifier a bearing.
    """
    for match in _OUT_OF_RANGE_BEARING.finditer(text):
        rest = match.group("rest")
        parts: list[re.Match[str]] = []
        position = 0
        while position < len(rest.rstrip()):
            part = _BEARING_PART.match(rest, position)
            if part is None or part.end() == position:
                parts = []
                break
            parts.append(part)
            position = part.end()
        else:
            if len(parts) > 2:
                continue
            if float(match.group("deg")) > 90.0:
                return True
            for part in parts:
                if part.group("mark") and float(part.group("num")) >= 60.0:
                    return True
    return False


def _extract_call(
    call_text: str, course: int, distance_unit: str = "feet"
) -> tuple[DeedCall | None, str]:
    """Return ``extract_single_call``'s result with the parsed course direction.

    BEGINNING/POB clauses return before any curve or bearing work. Record calls are
    identified first (``_scan_record_calls``): every bearing, length and curve
    element is read from ``reading``, the text with them blanked, while along/to
    and the record wording come from the verbatim ``call_text``. Curve info is
    extracted once and shared with the course-bearing extraction.
    """
    if _BEGINNING_CLAUSE.match(call_text):
        return None, ""

    # Text after the closing sentence is not part of this course (recitals, ties),
    # but a complete course there must fail closed rather than be dropped.
    cut = _cut_closing_sentence(call_text)
    if cut:
        head, tail = cut
        if (
            tail
            and _states_complete_course(tail)
            and not _BLOCK_LEAD.match(tail)
            and not _TRAILING_LEAD.match(tail)
        ):
            raise MultipleCoursesError(MULTIPLE_COURSES_ERROR)
        call_text = head

    record_scan = _scan_record_calls(call_text)
    reading = record_scan.reading
    curve_info = extract_curve_info(reading, distance_unit)
    if _describes_curve(curve_info) and _has_second_course(reading):
        raise MultipleCoursesError(MULTIPLE_COURSES_ERROR)
    course_bearing = _course_bearing(reading, curve_info)
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
        bearing_quadrant = _format_quadrant(cardinal1, degrees, cardinal2)
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

    is_curve = _describes_curve(curve_info)
    if is_curve:
        course_text = _course_distance_text(reading, is_curve=True)
    else:
        course_text = course_bearing.distance_text
    length = read_course_length(course_text)
    if length.ambiguous:
        # Several course lengths: none is chosen, so the course fails closed.
        raise ValueError(COURSE_LENGTH_AMBIGUOUS_NOTE.format(values=", ".join(length.ambiguous)))
    distance, unit = length.value, length.unit
    if distance == 0:
        if re.search(
            rf"{LENGTH_NUMBER}\s+[A-Za-z]+(?:\s+[A-Za-z]+)?\s+and\s+{LENGTH_NUMBER}\s+[A-Za-z]+",
            course_text,
            re.IGNORECASE,
        ):
            raise ValueError("Unsupported component in compound course distance")
        # Only a length the course states as its own is its length: when every
        # stated length is a tie, offset, width or monument depth (or none is
        # stated) the course fails closed below, never taking the first "N feet".
        inches = None if is_curve else _inch_course_length(course_text, raw_direction)
        if inches is not None:
            distance, unit = inches, "feet"

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
    # A spiral's own "length" is its stated curve length (not R * delta): it is kept
    # in arc_length_ft and is the course distance; it never yields a circular value.
    elif (
        curve_info.get("arc_length_ft") is None
        and curve_info.get("curve_type") == "spiral"
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
        # A spiral's stated length is its curve length, not a circular arc: a stated
        # chord still positions it (as verification does).
        and (stated_arc is None or is_spiral)
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
    # A cardinal-only direction word that conflicts with the stated chord bearing.
    chord_azimuth = bearing_to_azimuth(chord_text) if isinstance(chord_text, str) else None
    direction_conflicts_chord = bool(
        chord_azimuth is not None
        and raw_direction
        and not parsed_bearing
        and not is_due_cardinal
        and _CARDINAL_ONLY_PATTERN.fullmatch(raw_direction.strip())
        and cardinal_conflicts_bearing(raw_direction, chord_azimuth)
    )
    if (
        chord_only
        and isinstance(chord_text, str)
        and curve_info.get("direction") in ("left", "right")
        and tangent_delta is not None
    ):
        chord_positioned = chord_azimuth is not None and not direction_conflicts_chord

    has_abbreviated_cardinal = bool(
        re.match(r"^\s*(?:THENCE\s+)?(?:N|S|E|W|NE|NW|SE|SW)\b", call_text, re.IGNORECASE)
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
        and not _has_out_of_range_bearing(reading)
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

    clause = extract_course_clause(call_text, record_scan.drop_spans)
    along, to = clause.along, clause.to
    if along and not is_curve:
        along = _adjoiner_wording(
            along, direction_text if raw_direction else "", distance_ft, record_scan.records
        )

    monument_type = classify_monument(to) if to else None
    monument_status = classify_monument_status(to or call_text)
    # Water wording is the course's own only before its destination and any later
    # "thence" ("to a stone on the bank of a creek, thence along the creek").
    is_meander = detect_meander(call_text[: clause.course_end])

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
    elif positioned_by_chord and is_spiral:
        tangent_notes.append("spiral positioned by its stated chord only")
    elif positioned_by_chord:
        tangent_notes.append("curve delta/arc not stated - positioned by chord only")
    if is_spiral and positioned_by_chord and not isinstance(stated_radius, float):
        tangent_notes.append("radius not stated")
    if direction_conflicts_chord and raw_direction:
        tangent_notes.append(
            f"stated direction ({raw_direction.strip().lower()}) conflicts with "
            f"chord bearing {chord_text}"
        )
    if chord_exceeds_diameter:
        tangent_notes.append("chord length exceeds twice the radius")
    tangent_note = "; ".join(tangent_notes)

    note_parts: list[str] = []
    if is_meander or "approximate" in call_text[: clause.clause_end].lower():
        note_parts.append("meander / approximate")
        if tangent_note:
            note_parts.append(tangent_note)
    elif tangent_note:
        note_parts.append(tangent_note)
    if cardinal_only and not chord_positioned:
        note_parts.append("incomplete bearing - cardinal only")
    elif not note_parts and not parsed_bearing and not is_due_cardinal:
        if _AMBIGUOUS_DECIMAL_DEGREES.fullmatch((raw_direction or "").strip()):
            note_parts.append(AMBIGUOUS_DECIMAL_DEGREES_NOTE)
        else:
            note_parts.append("incomplete bearing")
    # A stated chord or radial bearing that cannot be read is recorded verbatim, never
    # dropped; the course is then not cross-checked or chord-positioned.
    unread_chord = curve_info.get("chord_bearing_unread") if is_curve else None
    if isinstance(unread_chord, str):
        note_parts.append(f"chord bearing not read: {unread_chord!r}")
    unread_radial = curve_info.get("radial_bearing_unread") if is_curve else None
    if isinstance(unread_radial, str):
        note_parts.append(f"radial bearing not read: {unread_radial!r}")
    if arc_computed:
        note_parts.append(ARC_COMPUTED_NOTE)
    for key in ("radius_conflict_note", "length_ambiguity_note"):
        element_note = curve_info.get(key)
        if isinstance(element_note, str):
            note_parts.append(element_note)
    if length_not_determined:
        note_parts.append(LENGTH_NOT_DETERMINED_NOTE)
    note_parts.extend(_parenthetical_notes(record_scan.parentheticals, along, to, clause.passing))
    # A record call is never read as the course; keep its wording (always last).
    note_parts.extend(RECORD_CALL_NOTE_PREFIX + text for text in record_scan.records)
    # A passing call locates a point on the line; it is kept verbatim, never dropped.
    note_parts.extend(PASSING_CALL_NOTE_PREFIX + text for text in clause.passing)
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
        or re.search(r"\b[NS]\s+\d+\u00b0", reading)
        # An out-of-range bearing (letter or spelled cardinals, degree mark, hyphen or
        # words, any component) is an incomplete bearing; in-range forms are parsed.
        or _has_out_of_range_bearing(reading)
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
    # A stated, readable, non-conflicting chord bearing and length that positions the
    # course (chord-only curve within its diameter, or spiral) states its direction.
    # is_indefinite is not a CSV field, so it must stay False for such a course for the
    # text and CSV-import paths to agree.
    chord_states_direction = (
        positioned_by_chord
        and not chord_exceeds_diameter
        and chord_azimuth is not None
        and not direction_conflicts_chord
    )
    chord_only_unresolved = chord_only and not chord_positioned and not chord_states_direction
    # An unread chord bearing is recorded in notes only: is_indefinite is not a CSV
    # column, so flagging it here would make text and CSV verification disagree.
    is_indefinite = chord_only_unresolved or is_indefinite_call(
        direction_text,
        has_bearing=has_stated_tangent or chord_positioned or chord_states_direction,
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

    # Concavity alone does not state left/right without the direction of travel, so a
    # circular curve with no stated direction is rejected, never inferred.
    if curve_direction is None and curve_type != "spiral":
        stated = [
            name
            for name, value in (
                ("radius", radius_ft),
                ("delta", delta_deg),
                ("arc length", arc_length_ft),
                ("chord", chord_length_ft),
            )
            if value is not None
        ]
        if stated:
            raise ValueError(
                "curve direction (left/right) not stated; it cannot be inferred from "
                f"concavity (course states {', '.join(stated)})"
            )

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
    reading = _scan_record_calls(call_text).reading
    course_text = _course_distance_text(reading, is_curve=call.is_curve())
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

    # --- Record call decision ---
    # Read from the call's notes, so the audit names exactly the record calls kept there.
    for record_text in _noted_record_calls(call.notes):
        decisions.append(
            Decision(
                field="record_call",
                value=record_text,
                reason="record call present; excluded from the measured course, kept in notes",
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
        and cardinal_conflicts_bearing(
            raw_direction,
            bearing_to_azimuth(call.chord_bearing) if call.chord_bearing else None,
        )
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
        if len(packed_match.group(2).split(".")[1]) in (1, 3):
            return packed_match.group(0)  # ambiguous decimal degrees: never converted
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
    """Return the course length in feet stated in ``text``, read by length role.

    Accepts unit-word and foot-mark lengths ("125.26' along..."), exactly as
    ``read_course_length``: a tie, offset, width, monument depth or record length
    is never returned, nor a choice among several course lengths.

    Args:
        text: Call text

    Returns:
        Distance in feet (0.0 when the text states no single course length in feet)
    """
    reading = read_course_length(text)
    if reading.ambiguous or normalize_unit_token(reading.unit) != "feet":
        return 0.0
    return reading.value


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
    rf"({LENGTH_NUMBER})\s*({LENGTH_UNIT})",
    re.IGNORECASE,
)
_CHORD_LENGTH_IN_CLAUSE = re.compile(rf"({LENGTH_NUMBER})\s*({LENGTH_UNIT})", re.IGNORECASE)


# "D=30\u00b0" and "degree of curve 30\u00b0" state the degree of curvature (a radius
# measure), never the central angle.
_DEGREE_OF_CURVE_PREFIX = re.compile(
    r"(?:\bdegree\s+of\s+(?:curve|curvature)\s+(?:of\s+)?|(?<![\w.])D\s*=\s*)$",
    re.IGNORECASE,
)


def _is_bearing_degree(text: str, start: int) -> bool:
    """Return True when the degree value at ``start`` is part of a bearing."""
    return _ends_with(_BEARING_DEGREE_PREFIX, text, start)


def _is_degree_of_curve(text: str, start: int) -> bool:
    """Return True when the degree value at ``start`` is a degree of curvature."""
    return _ends_with(_DEGREE_OF_CURVE_PREFIX, text, start)


# "radius point bears N 10 E 500.00 feet": a length directly after a radial bearing,
# or labelled as the radius, is the radius (to the radius point or center). Any other
# label ("a distance of"), or a bare length after a comma, is not the radius.
_RADIAL_RADIUS_AFTER_BEARING = re.compile(
    r"(?:\s*,?\s*(?:(?:and|with)\s+)?(?:(?:a|the)\s+)?radius\s+(?:of\s+)?|\s*)"
    rf"({LENGTH_NUMBER})\s*({LENGTH_UNIT})",
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
        parse_number(length.group(1)), normalize_unit_token(length.group(2))
    )
    stated = curve_info.get("radius_ft")
    if not isinstance(stated, float):
        curve_info["radius_ft"] = radial_radius
    elif abs(stated - radial_radius) > max(0.01, 1e-3 * abs(stated)):
        curve_info["radius_conflict_note"] = RADIUS_CONFLICT_NOTE.format(
            stated=stated, radial=radial_radius
        )


_UNREAD_QUADRANT = re.compile(
    r"\s*((?:N|S|(?i:north|south))\b[^,;]{0,40}?\b(?:E|W|(?i:east|west))\b)"
)
_UNREAD_CLAUSE = re.compile(r"\s*([^,;]{1,60}?)\s*(?:\s+and\b|[,;]|$)", re.IGNORECASE)


def _stated_unread_bearing(clause: str) -> str | None:
    """Return the verbatim bearing wording a chord or radial clause states but is unread."""
    match = _UNREAD_QUADRANT.match(clause) or _UNREAD_CLAUSE.match(clause)
    text = match.group(1).strip() if match else ""
    return text or None


def extract_curve_info(text: str, distance_unit: str = "feet") -> dict[str, float | str | None]:
    """Extract curve information from call text.

    Every element length is converted to feet from its stated unit; a length
    stated without a unit is in ``distance_unit``.

    Args:
        text: Call text
        distance_unit: The deed's distance unit, for lengths stated without one

    Returns:
        Dict with curve properties (empty if no curve)
    """
    curve_info: dict[str, float | str | None] = {}
    text = _expand_curve_labels(text)

    if not CURVE_KEYWORD_PATTERN.search(text):
        return curve_info

    match = CURVE_PATTERN.search(text)
    if match and (
        _is_bearing_degree(text, match.start(4)) or _is_degree_of_curve(text, match.start(4))
    ):
        # The first degree value belongs to a bearing (e.g. the chord's), not
        # the central angle; only an explicitly labelled delta may be used.
        match = None
    if match:
        direction = match.group(1).lower()
        radius_raw = parse_number(match.group(2))
        radius_unit = normalize_unit_token(match.group(3), distance_unit)
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
            rf"radius\s+(?:of\s+)?({LENGTH_NUMBER})\s*({LENGTH_UNIT})?", text, re.IGNORECASE
        )
        if radius_match:
            radius_raw = parse_number(radius_match.group(1))
            radius_unit = normalize_unit_token(radius_match.group(2), distance_unit)
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
            unread = _stated_unread_bearing(text[chord_match.end() :])
            if unread:
                curve_info["chord_bearing_unread"] = unread
        if chord_match.group("chord_lead_len"):
            curve_info["chord_length_ft"] = ConversionFactors.convert_to_feet(
                parse_number(chord_match.group("chord_lead_len")),
                normalize_unit_token(chord_match.group("chord_lead_unit")),
            )
        elif chord_length:
            curve_info["chord_length_ft"] = ConversionFactors.convert_to_feet(
                parse_number(chord_length.group(1)),
                normalize_unit_token(chord_length.group(2)),
            )

    # The arc, and a chord stated without the chord-bearing grammar ("a chord
    # distance of 87.16 feet"), are read only from lengths labelled as such.
    course_text, lengths = _curve_lengths(text, distance_unit)
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
        else:
            unread = _stated_unread_bearing(text[radial_match.end() :])
            if unread:
                curve_info["radial_bearing_unread"] = unread

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


_INCOMPLETE_BEARING_NOTES = frozenset(
    {"incomplete bearing", "incomplete bearing - cardinal only", AMBIGUOUS_DECIMAL_DEGREES_NOTE}
)


def _without_incomplete_bearing_note(notes: str) -> str | None:
    """Return ``notes`` without its incomplete-bearing note, everything else verbatim.

    Verbatim deed wording (record calls, stated exceptions, ...) is kept whole, even
    when it holds "; " (``split_notes``).
    """
    parts = [part for part in split_notes(notes) if part and part not in _INCOMPLETE_BEARING_NOTES]
    return "; ".join(parts) or None


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
                # Clear the incomplete-bearing note; every other note stays intact.
                if call.notes:
                    updates["notes"] = _without_incomplete_bearing_note(call.notes)
                enriched.append(call.model_copy(update=updates))
            else:
                enriched.append(call)
        else:
            enriched.append(call)
    return enriched
