"""Extract individual deed calls from legal descriptions.

Parses normalized text to create structured DeedCall objects.
"""

import hashlib
import logging
import math
import re
from typing import NamedTuple

import structlog
from pydantic import ValidationError

from .bearing_converter import BearingConverter
from .models import (
    AuditContext,
    CallAudit,
    ConversionFactors,
    CurveDirection,
    CurveType,
    Decision,
    DeedCall,
    MonumentStatus,
    MonumentType,
    SkippedCourse,
    Transformation,
)
from .text_parser import (
    _COMMA_NUMBER,
    COURSE_LIST_MARKER,
    TextParser,
    analyze_course_lists,
    parse_comma_number,
)

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
    chord_az = BearingConverter.bearing_to_azimuth(chord_text)
    if word not in _CARDINAL_CENTRES or chord_az is None:
        return False
    centre, half_width = _CARDINAL_CENTRES[word]
    diff = abs((float(chord_az) - centre + 180.0) % 360.0 - 180.0)
    return diff > half_width + 1e-9


_UNIT_TOKEN = (
    r"(?:US\s+survey\s+(?:feet|foot)|feet|foot|ft|poles?|rods?|perches?|chains?|links?"
    r"|engineer\s+chains?|engineer\s+links?"
    r"|varas?|arpents?|toises?|furlongs?|meters?|miles?)"
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


_PACKED_DMS_BEARING = re.compile(r"(N|S)\s+(\d{1,3}\.\d+)°\s*(E|W)", re.IGNORECASE)

_COMPACT_DMS_BEARING = re.compile(
    r"\b([NS])\s*(\d{1,3})\s*(?:-|d\b|d(?=\d)|deg\.?|degrees?)\s*"
    r"(?:(\d{1,2})\s*(?:-|m\b|m(?=\d)|min\.?|minutes?)\s*)?"
    r"(?:(\d{1,2}(?:\.\d+)?)\s*(s\b|sec\.?|seconds?)?\s*)?([EW])\b",
    re.IGNORECASE,
)


# A number group right after an identifier word ("Lot N 12-3 E", "Route N 9-1 E")
# is a label, never a bearing.
_IDENTIFIER_BEFORE = re.compile(
    r"(?:(?<![A-Za-z])(?:lots?|blocks?|blk|routes?|rte|rt|highway|hwy|no|nos|number|unit"
    r"|parcel|tract|section|sec|map|plat|book|page|pg|sheet|phase|plan|instrument|deed"
    r"|file|exit|apt|suite|building|bldg)\.?|#)\s*$",
    re.IGNORECASE,
)
# Bare dashes ("N 45-30 E") carry no degree marker, so they are read as a bearing
# only where one is expected: text start, a clause boundary or a bearing keyword.
_DASHED_BEARING_CONTEXT = re.compile(
    r"(?:^|[,;:(]|(?<![A-Za-z])(?:thence|then|bears?|bearings?|courses?|running|runs?"
    r"|and|being|is|of|line|direction))\s*$",
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
        if not re.search(r"\d\s*[dms]", numbers, re.IGNORECASE) and not (
            _ends_with(_DASHED_BEARING_CONTEXT, text, m.start())
        ):
            return m.group(0)
        minute_value, second_value = m.group(3), m.group(4)
        if minute_value is None and second_value is not None and m.group(5) is None:
            # Two parts ("N 45-30 E", "N 45d 30 E"): the trailing number is minutes,
            # unless an explicit seconds marker says otherwise.
            minute_value, second_value = second_value, None
        minutes = f"{minute_value}'" if minute_value else ""
        seconds = f'{second_value}"' if second_value else ""
        return f"{m.group(1).upper()} {m.group(2)}°{minutes}{seconds} {m.group(6).upper()}"

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
    return TextParser.standardize_cardinal_directions(_expand_compact_dms(_expand_marked_dms(text)))


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
    rf"(?:(?:of\s+)?(?P<chord_lead_len>{_COMMA_NUMBER})\s*(?:feet|ft)\b\s*,?\s*"
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
    bearing = _PACKED_DMS_BEARING.search(text, start, end) if packed else None
    if bearing is None:
        bearing = BearingConverter.QUADRANT_PATTERN.search(text, start, end)
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
    rf"({_COMMA_NUMBER})\s*(?:feet|ft)\b",
    re.IGNORECASE,
)
_CHORD_LENGTH_IN_CLAUSE = re.compile(rf"({_COMMA_NUMBER})\s*(?:feet|ft)\b", re.IGNORECASE)


def _is_bearing_degree(text: str, start: int) -> bool:
    """Return True when the degree value at ``start`` is part of a bearing."""
    return _ends_with(_BEARING_DEGREE_PREFIX, text, start)


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
    for witness in TextParser.extract_witness_trees(call_text):
        position = lowered.find(witness.lower())
        if position >= 0:
            starts.append(position)
    if not starts:
        return call_text
    return call_text[: min(starts)]


_CURVE_GEOMETRY_KEYS = ("direction", "radius_ft", "delta_deg", "arc_length_ft", "chord_length_ft")


# --- Curve length roles -----------------------------------------------------------
# Every length in a curve call is classified by its own label (the words directly
# before it) or, for chord and radial clauses, by the clause grammar, and is stored
# only under that role: radius, chord, tangent (never stored), arc, or the course
# length. An unlabelled length inside a radius-point/center clause measures that
# element ("radial", never stored). A number directly after a degree sign is a
# bearing's minutes, never a length.
_LENGTH_TOKEN = re.compile(
    rf"(?<![\d.,\u00b0])(?<!\u00b0\s)({_COMMA_NUMBER})\s*({_UNIT_TOKEN}\b|'(?!'))",
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
        for pattern in (BearingConverter.QUADRANT_PATTERN, _PACKED_DMS_BEARING)
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


def _describes_curve(curve_info: dict[str, float | str | None]) -> bool:
    """Return True when extracted curve info states any curve geometry."""
    return any(curve_info.get(key) is not None for key in _CURVE_GEOMETRY_KEYS)


class _CourseBearing(NamedTuple):
    """The course direction of one call: ``direction`` parses, ``text`` is the deed's."""

    direction: str
    text: str


def _course_bearing(call_text: str, curve_info: dict[str, float | str | None]) -> _CourseBearing:
    """Return the course (tangent) direction stated in the boundary course text.

    Corner witnesses are cut off, and the course text and its verbatim bearing
    candidates are normalized together in one pass. Chord and
    radial/radius-point/center bearings are then removed *before* extraction, so
    only a bearing describing the course itself can be returned. On a straight
    course, a radial clause naming the line being run ("along a radial line
    bearing ...") states the course bearing and is kept; one describing the radius
    point of a curve reached at the end of the line is removed. ``curve_info`` is
    ``CallExtractor.extract_curve_info(call_text)``, computed once by the caller.
    """
    keep_line_radial = not _describes_curve(curve_info)
    course_text = _boundary_course_text(call_text)
    candidates = _verbatim_candidates(course_text, keep_line_radial=keep_line_radial)
    normalized, *normalized_candidates = _normalize_bearing_segments([course_text, *candidates])
    normalized = _without_reference_bearings(normalized, _CHORD_PREFIX_PATTERN)
    normalized = _without_reference_bearings(
        normalized, _RADIAL_PREFIX_PATTERN, keep_line_radial=keep_line_radial
    )
    direction = CallExtractor.extract_direction(normalized)
    return _CourseBearing(
        direction, _verbatim_course_direction(direction, candidates, normalized_candidates)
    )


# Any bearing form in the deed's own wording (symbols, words, dashes, d/m units).
# Possessive quantifiers keep long digit runs from backtracking.
_VERBATIM_BEARING = re.compile(
    r"(?<![A-Za-z])(?:North|South|N|S)\.?(?![A-Za-z])\s*+\d++(?:\.\d++)?"
    r"(?:\s*+(?:[°\u00ba'\u2032\u2019\"\u2033\u201d-]|degrees?(?![a-z])|deg(?![a-z])\.?"
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
    if not BearingConverter.parse_quadrant_bearing(direction):
        return direction
    for candidate, normalized in zip(candidates, normalized_candidates, strict=True):
        if CallExtractor.extract_direction(normalized) == direction:
            return candidate
    return direction


def _tangent_not_stated(call: DeedCall) -> bool:
    """Return True for a curve fixed by chord and delta whose tangent is not stated."""
    return (
        call.bearing_azimuth_deg_from_north is None
        and call.notes is not None
        and _TANGENT_NOT_STATED_NOTE in call.notes
    )


class MonumentClassifier:
    """Classify survey monument types from text descriptions."""

    MONUMENT_PATTERNS: list[tuple[str, MonumentType]] = [
        (r"\btxdot\b.*\bmonument\b", "txdot_monument"),
        (r"\bcapped\s+(?:iron\s+)?rod\b", "capped_rod"),
        (r"\bcapped\s+(?:iron\s+)?pin\b", "capped_pin"),
        (r"\bcapped\s+rebar\b", "capped_rod"),
        (r"\biron\s+rod\b", "iron_rod"),
        (r"\biron\s+pin\b", "iron_pin"),
        (r"\biron\s+pipe\b", "iron_pipe"),
        (r"\biron\s+stake\b", "iron_rod"),
        (r"\biron\s+monument\b", "iron_rod"),
        (r"\brebar\b", "rebar"),
        (r"\bpk\s+nail\b", "pk_nail"),
        (r"\b(?:mag|magnetic)\s+nail\b", "nail"),
        (r"\bnail\b", "nail"),
        (r"\bhub\s+(?:and|&)\s+tack\b", "hub_and_tack"),
        (r"\bmonitoring\s+well\b", "monitoring_well"),
        (r"\brailroad\s+(?:spike|tie)\b", "railroad_spike"),
        (r"\bgin\s+(?:spike|pole)\b", "railroad_spike"),
        (r"\bstone\s+monument\b", "stone"),
        (r"\bstone\b", "stone"),
        (r"\bconcrete\s+monument\b", "concrete"),
        (r"\bconcrete\b", "concrete"),
        (r"\bbrass\s+(?:cap|marker|monument)\b", "brass_cap"),
        (r"\bwooden\s+(?:post|stake)\b", "wooden_post"),
        (r"\bhedge\s+post\b", "wooden_post"),
        (r"\bwood\s+stake\b", "wooden_post"),
        (r"\blandscap(?:e|ing)\s+(?:rod|pin)\b", "iron_rod"),
        # Natural monuments — trees
        (
            r"\b(?:oak|hickory|elm|pine|walnut|sycamore|maple|beech|poplar|cedar|ash|birch|chestnut|cottonwood|willow|cypress)\b",
            "tree",
        ),
        (r"\btree\b", "tree"),
        # Natural monuments — rocks
        (r"\bboulder\b", "rock"),
        (r"\brock\s+outcrop\b", "rock"),
        (r"\bstanding\s+rock\b", "rock"),
        (r"\blarge\s+rock\b", "rock"),
        # Natural features — water/terrain
        (r"\b(?:stream|creek|river|brook|branch|run)\b", "natural_feature"),
        (r"\b(?:ridge|bluff|cliff|shoreline|lakeshore|shore)\b", "natural_feature"),
    ]

    @classmethod
    def classify_monument(cls, text: str) -> MonumentType | None:
        """Classify monument type from text description.

        Args:
            text: Text description (typically from 'to' field)

        Returns:
            Monument type literal or None if not found
        """
        if not text:
            return None

        text_lower = text.lower()

        for pattern, monument_type in cls.MONUMENT_PATTERNS:
            if re.search(pattern, text_lower):
                return monument_type

        if re.search(r"\bmonument\b", text_lower):
            return "other"

        return None

    MONUMENT_STATUS_PATTERNS: list[tuple[str, MonumentStatus]] = [
        (r"\bfd\b", "found"),
        (r"\bfnd\b", "found"),
        (r"\bfound\b", "found"),
        (r"\bset\b", "set"),
        (r"\bplaced\b", "set"),
    ]

    @classmethod
    def classify_monument_status(cls, text: str | None) -> MonumentStatus | None:
        """Classify whether monument status indicates found or set."""
        if not text:
            return None

        text_lower = text.lower()
        for pattern, status in cls.MONUMENT_STATUS_PATTERNS:
            if re.search(pattern, text_lower):
                return status

        return None


_ARC_COMPUTED_NOTE = "arc length not stated - course distance computed from radius and delta"
# A curve fixed by its stated chord bearing and delta (or arc and radius) with no
# stated tangent: the tangent is computed only inside verification, never stored.
_TANGENT_NOT_STATED_NOTE = (
    "tangent bearing not stated - curve positioned by chord and delta in verification"
)
_ARC_COMPUTED_RULE = "curve: distance is the arc computed from the stated radius and delta"
_LENGTH_NOT_DETERMINED_NOTE = "spiral length not stated - course distance not determined"
_LENGTH_NOT_DETERMINED_RULE = (
    "spiral: no arc, chord or course length stated; a spiral's length is not radius * delta"
)


# One curve-word spelling (curve/curved/curving) shared by every curve gate in this module.
_CURVE_WORD = r"curv(?:e|ed|ing)"
_CURVE_KEYWORD_PATTERN = re.compile(rf"\b(?:{_CURVE_WORD}|spiral|transition)\b", re.IGNORECASE)


def _distance_audit_source(call_text: str, call: DeedCall) -> tuple[str, str | None]:
    """Return the audited input and rule for the stored course distance."""
    if call.distance_ft is None:
        return (
            f"radius {call.radius_ft} feet, delta {call.delta_deg} deg (spiral)",
            _LENGTH_NOT_DETERMINED_RULE,
        )
    if (
        call.notes
        and _ARC_COMPUTED_NOTE in call.notes
        and call.radius_ft
        and call.delta_deg is not None
    ):
        return (
            f"radius {call.radius_ft} feet, delta {call.delta_deg} deg",
            _ARC_COMPUTED_RULE,
        )
    if call.is_chord_only_curve():
        return (
            f"{call.chord_length_ft} feet",
            "chord-only curve: distance is the stated chord length",
        )
    if call.arc_length_ft is not None and call.arc_length_ft == call.distance_ft:
        return f"{call.arc_length_ft} feet", None
    course_text = _course_distance_text(call_text, is_curve=call.is_curve())
    distance, unit = TextParser.extract_distance(course_text)
    if distance == 0:
        return call_text.strip(), None
    return f"{distance} {unit}", None


# "radius point bears N 10 E 500.00 feet": a length directly after a radial bearing,
# or labelled as the radius, is the radius (to the radius point or center). Any other
# label ("a distance of"), or a bare length after a comma, is not the radius.
_RADIAL_RADIUS_AFTER_BEARING = re.compile(
    r"(?:\s*,?\s*(?:(?:and|with)\s+)?(?:(?:a|the)\s+)?radius\s+(?:of\s+)?|\s*)"
    rf"({_COMMA_NUMBER})\s*({_UNIT_TOKEN})\b",
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


class CallExtractor:
    """Extract and structure deed calls from legal description text."""

    CURVE_PATTERN = re.compile(
        rf"{_CURVE_WORD}\s+to\s+the\s+(left|right).*?radius\s+of\s+({_COMMA_NUMBER})\s*({_UNIT_TOKEN})?.*?"
        rf"(?:delta\s+(?:angle\s+)?of\s+)?({_COMMA_NUMBER})(?:°|\s+degrees?)(?:\s*({_COMMA_NUMBER})(?:'|\s+minutes?))?(?:\s*({_COMMA_NUMBER})(?:\"|\s+seconds?))?",
        re.IGNORECASE | re.DOTALL,
    )

    @classmethod
    def _is_initial_course_prefix(cls, prefix: str) -> bool:
        """Return whether text before THENCE starts with a supported bearing."""
        candidate = re.sub(r"^\s*(?:(?:\(\d+\)|\d+[.)])\s*)?", "", prefix)
        if cls.PACKED_DMS_PATTERN.match(candidate):
            return True

        try:
            direction = cls.extract_direction(candidate)
        except ValueError:
            return False
        if not direction or not candidate.lstrip().lower().startswith(direction.lower()):
            return False
        if _CARDINAL_ONLY_PATTERN.fullmatch(direction):
            remainder = candidate.lstrip()[len(direction) :]
            return bool(re.match(rf"\s+{_COMMA_NUMBER}(?:\s|$)", remainder))
        return bool(
            BearingConverter.parse_quadrant_bearing(direction)
            or BearingConverter.due_cardinal_to_azimuth(direction) is not None
        )

    @classmethod
    def extract_calls(
        cls,
        text: str,
        distance_unit: str = "feet",
        *,
        audit_context: AuditContext | None = None,
        strict: bool = True,
        skipped_courses: list[SkippedCourse] | None = None,
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
                ``audit_context`` and/or ``skipped_courses``) with its course
                number reserved, and blocks verification given that record. With
                neither supplied it raises as in strict mode.
            skipped_courses: Optional list receiving non-strict skipped courses.

        Returns:
            List of DeedCall objects
        """
        normalized = TextParser.normalize_legal_description(text)

        tracts = TextParser.split_exception_clauses(normalized)

        calls: list[DeedCall] = []
        course_num = 1

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
            has_initial_course = bool(thence_match and cls._is_initial_course_prefix(prefix))
            if thence_match and (has_beginning_preamble or not has_initial_course):
                tract_text = tract_text[thence_match.start() :]

            # Course-list headers and enumerations are detected once per tract.
            course_lists = analyze_course_lists(tract_text)
            count_mismatches = course_lists.mismatches
            if strict and count_mismatches:
                declared, found = count_mismatches[0]
                raise ValueError(
                    f"Course-list header states {declared} courses but {found} were found: "
                    f"{tract_text.strip()!r}"
                )
            has_numbered_course_markers = course_lists.has_numbered_markers
            call_texts = [
                part
                for part in TextParser.split_into_calls(tract_text, course_lists=course_lists)
                if not COURSE_LIST_MARKER.fullmatch(part)
            ]

            for source_course, call_text in enumerate(call_texts, start=1):
                try:
                    call, raw_direction = cls._extract_call(
                        call_text, course=course_num, distance_unit=distance_unit
                    )
                except (ValidationError, ValueError, TypeError) as exc:
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
                        or cls.extract_direction(call_text)
                        or re.search(r"\b(?:[NSEW])\s+\d", call_text, re.I)
                        or _CURVE_KEYWORD_PATTERN.search(call_text)
                    ):
                        if strict:
                            raise ValueError(
                                f"Malformed course {source_course}: {call_text.strip()!r}"
                            )
                        _record_skipped_course(
                            call_text,
                            course=course_num,
                            source_course=source_course,
                            error_type="UnparsedCourse",
                            error="no computable course could be parsed",
                            exc=None,
                            audit_context=audit_context,
                            skipped_courses=skipped_courses,
                        )
                        course_num += 1
                    continue

                if is_exception_tract:
                    call = call.model_copy(update={"is_exception": True})
                calls.append(call)

                if audit_context is not None:
                    transformations, decisions, flags = cls._audit_single_call(
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

            for declared, found in count_mismatches:
                # Not silently accepted: a missing or extra course is recorded and
                # blocks closure, exactly as an unparsed course does.
                _record_skipped_course(
                    tract_text,
                    course=course_num,
                    source_course=len(call_texts) + 1,
                    error_type="CourseCountMismatch",
                    error=f"course-list header states {declared} courses but {found} were found",
                    exc=None,
                    audit_context=audit_context,
                    skipped_courses=skipped_courses,
                )
                course_num += 1

        return calls

    @classmethod
    def extract_single_call(
        cls,
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
        return cls._extract_call(call_text, course, distance_unit)[0]

    @classmethod
    def _extract_call(
        cls, call_text: str, course: int, distance_unit: str = "feet"
    ) -> tuple[DeedCall | None, str]:
        """Return ``extract_single_call``'s result with the parsed course direction.

        BEGINNING/POB clauses return before any curve or bearing work; otherwise curve
        info is extracted once and shared with the course-bearing extraction.
        """
        if re.match(r"^\s*(BEGINNING|COMMENCING|POB)\b", call_text, re.IGNORECASE):
            return None, ""

        curve_info = cls.extract_curve_info(call_text)
        course_bearing = _course_bearing(call_text, curve_info)
        raw_direction = course_bearing.direction
        # direction_text keeps the deed's wording; the normalized form is for parsing only.
        direction_text = course_bearing.text if raw_direction else call_text.strip()

        bearing_quadrant = None
        azimuth = None

        is_due_cardinal = False
        parsed_bearing = (
            BearingConverter.parse_quadrant_bearing(raw_direction) if raw_direction else None
        )
        if parsed_bearing:
            cardinal1, degrees, cardinal2 = parsed_bearing
            deg_int = int(degrees)
            minutes = (degrees - deg_int) * 60

            rounded_minutes = round(minutes)
            if rounded_minutes >= 60:
                rounded_minutes = 0
                deg_int += 1

            bearing_quadrant = f"{cardinal1} {deg_int}°{rounded_minutes:02d}' {cardinal2}"
            azimuth = BearingConverter.quadrant_to_azimuth(cardinal1, degrees, cardinal2)
        else:
            # Try "due {cardinal}" before giving up
            due_az = (
                BearingConverter.due_cardinal_to_azimuth(raw_direction) if raw_direction else None
            )
            if due_az is not None:
                azimuth = due_az
                is_due_cardinal = True
                bearing_quadrant = None
            else:
                bearing_quadrant = None
                azimuth = None

        course_text = _course_distance_text(call_text, is_curve=_describes_curve(curve_info))
        distance, unit = TextParser.extract_distance(course_text)
        if distance == 0:
            if re.search(
                rf"{_COMMA_NUMBER}\s+[A-Za-z]+(?:\s+[A-Za-z]+)?\s+and\s+{_COMMA_NUMBER}\s+[A-Za-z]+",
                course_text,
                re.IGNORECASE,
            ):
                raise ValueError("Unsupported component in compound course distance")
            distance = cls.extract_distance_alternate(course_text)
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
        # computes its tangents internally. Only an explicitly stated delta is stored
        # as delta_deg. Radius + chord without a stated delta or arc: nothing is
        # derived; the course is positioned by its chord only.
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
        # A stated tangent, chord bearing, chord and radius (no delta or arc) are kept
        # as stated: nothing is derived into delta_deg/arc_length_ft. The chord positions
        # the course; verification cross-checks the stated tangent, chord and radius.
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
            chord_positioned = (
                BearingConverter.bearing_to_azimuth(chord_text) is not None
                and not cardinal_conflict
            )

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
            and not TextParser.detect_meander(call_text)
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
                props = BearingConverter.calculate_curve_properties(radius_ft, delta_deg=delta_deg)
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

        along, to = TextParser.extract_along_to_fields(call_text)

        monument_type = MonumentClassifier.classify_monument(to) if to else None
        monument_status = MonumentClassifier.classify_monument_status(to or call_text)
        is_meander = TextParser.detect_meander(call_text)

        notes = ""
        cardinal_only = False
        if raw_direction and not parsed_bearing and not is_due_cardinal:
            if _CARDINAL_ONLY_PATTERN.fullmatch(raw_direction.strip()):
                cardinal_only = True

        tangent_notes: list[str] = []
        if chord_positioned:
            tangent_notes.append(_TANGENT_NOT_STATED_NOTE)
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
            note_parts.append(_ARC_COMPUTED_NOTE)
        for key in ("radius_conflict_note", "length_ambiguity_note"):
            element_note = curve_info.get(key)
            if isinstance(element_note, str):
                note_parts.append(element_note)
        if length_not_determined:
            note_parts.append(_LENGTH_NOT_DETERMINED_NOTE)
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
            or re.search(r"\b[NS]\s+\d+°", call_text)
        )
        if not has_direction_intent:
            payload = {
                "course": course,
                "distance_ft": distance_ft,
                "call_preview": _call_preview(call_text),
                "call_hash": _call_hash(call_text),
            }
            if _is_debug_logging_enabled():
                logger.warning(
                    "Rejecting bearingless non-curve call", **payload, call_text=call_text
                )
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
        is_indefinite = chord_only_unresolved or TextParser.is_indefinite_call(
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
            radial_bearing=(
                radial_bearing_value if isinstance(radial_bearing_value, str) else None
            ),
            is_meander=is_meander,
            is_tie_in=False,
            is_indefinite=is_indefinite,
            curve_type=curve_type,
            notes=notes if notes else None,
        )

        return call, raw_direction

    @classmethod
    def _audit_single_call(
        cls,
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
            parsed = BearingConverter.parse_quadrant_bearing(raw_direction)
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
            for pattern, _mtype in MonumentClassifier.MONUMENT_PATTERNS:
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
        is_due = (
            BearingConverter.due_cardinal_to_azimuth(raw_direction) is not None
            if raw_direction
            else False
        )
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

    PACKED_DMS_PATTERN = _PACKED_DMS_BEARING

    @classmethod
    def extract_direction(cls, text: str) -> str:
        """Extract direction/bearing from call text.

        Args:
            text: Call text

        Returns:
            Direction string (e.g., "S 56°40' W" or "southwesterly")
        """
        packed_match = cls.PACKED_DMS_PATTERN.search(text)
        quadrant_match = BearingConverter.QUADRANT_PATTERN.search(text)
        if quadrant_match and not packed_match:
            return quadrant_match.group(0)

        if packed_match:
            cardinal1 = packed_match.group(1).upper()
            packed_value = float(packed_match.group(2))
            cardinal2 = packed_match.group(3).upper()
            decimal_degrees = BearingConverter.parse_packed_dms(packed_value)
            total_seconds = round(decimal_degrees * 3600, 4)
            degree, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            seconds_text = f"{seconds:.4f}".rstrip("0").rstrip(".")
            if seconds < 10:
                seconds_text = f"0{seconds_text}"
            return f"{cardinal1} {int(degree)}°{int(minutes):02d}'{seconds_text}\" {cardinal2}"

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

        # Compound compass point check (32-point system) — must come before
        # simple cardinal check so "North by East" is not truncated to "North"
        compound_compass_names = sorted(
            [name for name in BearingConverter.COMPASS_POINTS if " " in name or "-" in name],
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

    @classmethod
    def extract_distance_alternate(cls, text: str) -> float:
        """Extract distance using alternate patterns.

        Some deeds use formats like "125.26' along..." instead of "125.26 feet".

        Args:
            text: Call text

        Returns:
            Distance value (0.0 if not found)
        """
        feet_match = re.search(rf"({_COMMA_NUMBER})\s*(?:feet|ft)\b", text, re.IGNORECASE)
        if feet_match:
            return parse_comma_number(feet_match.group(1))

        apostrophe_match = re.search(
            r"(?<!°)(\d+(?:\.\d+)?)\s*'(?=(?:\s+(?:along|to)\b|[.,;)]|$))",
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
                r"\d+°\s*\d+(?:\.\d+)?\s*\x27\s*$",
                prefix,
            ):
                return 0.0
            return float(apostrophe_match.group(1))

        return 0.0

    @classmethod
    def extract_curve_info(cls, text: str) -> dict[str, float | str | None]:
        """Extract curve information from call text.

        Args:
            text: Call text

        Returns:
            Dict with curve properties (empty if no curve)
        """
        curve_info: dict[str, float | str | None] = {}

        if not _CURVE_KEYWORD_PATTERN.search(text):
            return curve_info

        match = cls.CURVE_PATTERN.search(text)
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
            dir_match = re.search(rf"{_CURVE_WORD}\s+to\s+the\s+(left|right)", text, re.IGNORECASE)
            if dir_match:
                curve_info["direction"] = dir_match.group(1).lower()

            radius_match = re.search(
                rf"radius\s+(?:of\s+)?({_COMMA_NUMBER})\s*({_UNIT_TOKEN})?", text, re.IGNORECASE
            )
            if radius_match:
                radius_raw = parse_comma_number(radius_match.group(1))
                radius_unit = _normalize_unit_token(radius_match.group(2))
                curve_info["radius_ft"] = ConversionFactors.convert_to_feet(radius_raw, radius_unit)

            delta_match = re.search(
                r"(?:delta|central\s+angle)\s+(?:angle\s+)?(?:of\s+)?(\d+(?:\.\d+)?)(?:°|(?:\s+)?degrees?)(?:\s*(\d+(?:\.\d+)?)(?:'|\s+minutes?))?(?:\s*(\d+(?:\.\d+)?)(?:\"|\s+seconds?))?",
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

            # Degree of curvature → radius conversion
            doc_match = re.search(
                r"degree\s+of\s+(?:curve|curvature)\s+(?:of\s+)?"
                r"(\d+(?:\.\d+)?)(?:°|(?:\s+)?degrees?)"
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
                    curve_info["radius_ft"] = BearingConverter.degree_of_curvature_to_radius(
                        doc_deg
                    )

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
                curve_info["chord_length_ft"] = parse_comma_number(
                    chord_match.group("chord_lead_len")
                )
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

        if re.search(
            r"\b(?:non[-\s\u2010-\u2015\u2212]?tangent|not\s+tangent)\b", text, re.IGNORECASE
        ):
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

    @classmethod
    def mark_tie_in_calls(
        cls, calls: list[DeedCall], poc_description: str | None
    ) -> list[DeedCall]:
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
            if call.to and TextParser.is_closure_to_pob("to " + call.to):
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

    @classmethod
    def enrich_calls_with_azimuths(cls, calls: list[DeedCall]) -> list[DeedCall]:
        """Add azimuths to calls that have quadrant bearings but missing azimuths.

        Args:
            calls: List of DeedCall objects

        Returns:
            List of enriched DeedCall objects
        """
        enriched = []
        for call in calls:
            enriched.append(BearingConverter.enrich_call_with_azimuth(call))
        return enriched
