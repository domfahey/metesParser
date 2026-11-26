"""Internal consistency of the sample-deed ground truths.

Each ground truth records its deed's legal description and the courses read from it. These
checks catch a course that disagrees with its own description or with itself; they do not
establish that the description matches the recorded deed (the PDF checks did that).
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import TypeGuard

import pytest
from mp_models import DeedCall
from mp_verify import verify_closure

SAMPLE_DEEDS = Path(__file__).resolve().parents[2] / "sample_deeds"
GROUND_TRUTHS = sorted(SAMPLE_DEEDS.glob("*.ground_truth.json"))

_DEG_UNIT = r"(?:[°\u00ba]|deg(?:rees?)?\.?|d\.?(?![a-z]))"
_MIN_UNIT = r"(?:'(?!')|\u2019(?!\u2019)|\u2032|min(?:utes?)?\.?|m\.?(?![a-z]))"
_SEC_UNIT = r"(?:[\"\u201d\u2033]|''|\u2019\u2019|sec(?:onds?)?\.?|s\.?(?![a-z]))"

_QUADRANT = re.compile(
    rf"\b(?P<ns>North|South|N|S)(?![a-z])\.?\s*"
    rf"(?P<deg>\d{{1,3}})\s*{_DEG_UNIT}"
    rf"(?:\s*,?\s*(?P<min>\d{{1,2}})\.?\s*{_MIN_UNIT})?"
    rf"(?:\s*,?\s*(?P<sec>\d{{1,2}}(?:\.\d+)?)\s*{_SEC_UNIT})?"
    rf"\s*,?\s*(?P<ew>East|West|E|W)\b\.?",
    re.IGNORECASE,
)
_DUE_CARDINAL = re.compile(r"\bdue\s+(north|south|east|west)\b", re.IGNORECASE)
_DUE_CARDINAL_AZIMUTH = {"north": 0.0, "east": 90.0, "south": 180.0, "west": 270.0}
_OVERRIDE_PREFIXES = ("printed_", "intended_", "corrected_")
_CLOSURE_FIELDS = {
    "course",
    "direction_text",
    "bearing_quadrant",
    "bearing_azimuth_deg_from_north",
    "distance_ft",
    "curve_dir",
    "radius_ft",
    "delta_deg",
    "arc_length_ft",
    "chord_bearing",
    "chord_length_ft",
    "non_tangent",
    "along",
    "to",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _squash(text: str) -> str:
    return " ".join(text.split())


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _parse_direction(text: str) -> tuple[float, str] | None:
    """Parse a DMS or 'due <cardinal>' bearing into (azimuth_deg, description_regex)."""
    match = _QUADRANT.search(text)
    if match:
        ns = match.group("ns")[0].upper()
        ew = match.group("ew")[0].upper()
        deg = int(match.group("deg"))
        mins = int(match.group("min") or 0)
        secs_str = match.group("sec")
        secs = float(secs_str or 0.0)
        angle = deg + mins / 60 + secs / 3600
        if deg > 90 or mins >= 60 or secs >= 60 or angle > 90.0:
            return None
        azimuth = {"NE": angle, "SE": 180 - angle, "SW": 180 + angle, "NW": 360 - angle}[
            ns + ew
        ] % 360

        ns_pat = "(?:North|N)" if ns == "N" else "(?:South|S)"
        ew_pat = "(?:East|E)" if ew == "E" else "(?:West|W)"
        min_clause = rf"\s*,?\s*0?{mins}\.?\s*{_MIN_UNIT}"
        min_pat = rf"(?:{min_clause})?" if mins == 0 else min_clause
        if secs == 0:
            sec_clause = rf"\s*,?\s*0?0(?:\.0+)?\s*{_SEC_UNIT}"
            sec_pat = rf"(?:{sec_clause})?"
        elif secs.is_integer():
            sec_pat = rf"\s*,?\s*0?{int(secs)}(?:\.0+)?\s*{_SEC_UNIT}"
        else:
            assert secs_str is not None
            whole_part, frac_part = secs_str.split(".", 1)
            frac_trimmed = frac_part.rstrip("0")
            sec_pat = rf"\s*,?\s*0?{int(whole_part)}\.{re.escape(frac_trimmed)}0*\s*{_SEC_UNIT}"

        pattern = (
            rf"\b{ns_pat}(?![a-z])\.?\s*0?{deg}\s*{_DEG_UNIT}"
            rf"{min_pat}{sec_pat}\s*,?\s*{ew_pat}\b\.?"
        )
        return azimuth, pattern

    due_match = _DUE_CARDINAL.search(text)
    if due_match:
        cardinal = due_match.group(1).lower()
        return _DUE_CARDINAL_AZIMUTH[cardinal], rf"\bdue\s+{cardinal}\b"

    return None


def _quadrant_azimuth(quadrant: str) -> float | None:
    parsed = _parse_direction(quadrant)
    return parsed[0] if parsed is not None else None


def _printed_forms(distance: float) -> set[str]:
    """Ways a distance can be printed: 125, 125.0, 125.00, 125,00 or 1,250.00."""
    forms = set()
    for decimals in range(4):
        text = f"{distance:.{decimals}f}"
        if abs(float(text) - distance) > 1e-9:
            continue
        whole, _, fraction = text.partition(".")
        forms |= {text, text.replace(".", ",")}
        if len(whole) > 3:
            forms.add(f"{int(whole):,}" + (f".{fraction}" if fraction else ""))
    return forms


def _ids(paths: list[Path]) -> list[str]:
    return [path.name.removesuffix(".ground_truth.json") for path in paths]


@pytest.mark.parametrize("path", GROUND_TRUTHS, ids=_ids(GROUND_TRUTHS))
def test_azimuth_matches_quadrant_bearing(path):
    for call in _load(path).get("expected_calls") or []:
        quadrant = call.get("bearing_quadrant")
        azimuth = call.get("bearing_azimuth_deg_from_north")
        if not quadrant:
            continue
        assert azimuth is not None, f"course {call['course']}: {quadrant!r} without an azimuth"
        expected = _quadrant_azimuth(quadrant)
        assert expected is not None, f"course {call['course']}: unparsed {quadrant!r}"
        difference = abs(azimuth - expected) % 360
        assert min(difference, 360 - difference) <= 30.5 / 3600, f"course {call['course']}"


@pytest.mark.parametrize("path", GROUND_TRUTHS, ids=_ids(GROUND_TRUTHS))
def test_azimuth_is_in_range(path):
    for call in _load(path).get("expected_calls") or []:
        azimuth = call.get("bearing_azimuth_deg_from_north")
        assert azimuth is None or 0 <= azimuth < 360, f"course {call['course']}"


@pytest.mark.parametrize("path", GROUND_TRUTHS, ids=_ids(GROUND_TRUTHS))
def test_straight_course_distance_appears_in_the_description(path):
    """Every straight course's distance_ft appears verbatim in the legal description."""
    gt = _load(path)
    legal = _squash(gt.get("expected_legal_description") or "")
    for call in gt.get("expected_calls") or []:
        if call.get("curve_dir") or not legal:
            continue
        distance = call["distance_ft"]
        whole_feet = re.search(rf"\b{int(distance)}\s*(?:feet|ft|')", legal)
        assert any(form in legal for form in _printed_forms(distance)) or whole_feet, (
            f"course {call['course']}: {distance}"
        )


@pytest.mark.parametrize("path", GROUND_TRUTHS, ids=_ids(GROUND_TRUTHS))
def test_bearing_appears_in_the_description(path):
    """Every numeric bearing parses from direction_text, matches azimuth, and appears verbatim."""
    gt = _load(path)
    legal = _squash(gt.get("expected_legal_description") or "")
    for call in gt.get("expected_calls") or []:
        direction = call.get("direction_text") or ""
        azimuth = call.get("bearing_azimuth_deg_from_north")
        parsed = _parse_direction(direction)
        if azimuth is not None:
            assert parsed is not None, (
                f"course {call['course']}: numeric azimuth {azimuth} with unparsed "
                f"direction_text {direction!r}"
            )
            expected_azimuth, _ = parsed
            difference = abs(azimuth - expected_azimuth) % 360
            assert min(difference, 360 - difference) < 1e-6, (
                f"course {call['course']}: direction_text {direction!r} gives "
                f"{expected_azimuth:.8f}° but bearing_azimuth_deg_from_north is {azimuth}"
            )
        elif parsed is not None:
            raise AssertionError(
                f"course {call['course']}: parsed bearing {direction!r} without an azimuth"
            )
        if parsed is None or not legal:
            continue
        _, pattern = parsed
        assert re.search(pattern, legal, re.IGNORECASE), (
            f"course {call['course']}: {direction!r} not found in legal description"
        )


@pytest.mark.parametrize("path", GROUND_TRUTHS, ids=_ids(GROUND_TRUTHS))
def test_along_and_to_are_quoted_from_the_description(path):
    gt = _load(path)
    legal = _squash(gt.get("expected_legal_description") or "")
    for call in gt.get("expected_calls") or []:
        for field in ("along", "to"):
            value = call.get(field)
            if value and legal:
                assert _squash(value) in legal, f"course {call['course']} {field}: {value!r}"


@pytest.mark.parametrize("path", GROUND_TRUTHS, ids=_ids(GROUND_TRUTHS))
def test_pob_and_poc_are_quoted_from_the_description(path):
    gt = _load(path)
    legal = _squash(gt.get("expected_legal_description") or "")
    if not legal:
        return
    for field in ("expected_pob", "expected_poc"):
        value = gt.get(field)
        if value:
            assert _squash(value) in legal, f"{field} not found verbatim in legal description"


@pytest.mark.parametrize("path", GROUND_TRUTHS, ids=_ids(GROUND_TRUTHS))
def test_text_has_no_duplicate_words_or_line_break_hyphens(path):
    gt = _load(path)
    for field in ("expected_legal_description", "expected_normalized_text"):
        text = gt.get(field) or ""
        if not text:
            continue
        dup = re.search(r"\b([A-Za-z]{2,})\s+\1\b", text, re.IGNORECASE)
        assert dup is None, f"{field}: duplicate consecutive word {dup.group(0)!r}"
        broken = re.search(r"[A-Za-z]+-\n[A-Za-z]+", text)
        assert broken is None, f"{field}: unjoined line-break hyphen {broken.group(0)!r}"
        split_dir = re.search(
            r"\b(?:North|South)-(?:east|west)(?:erly|wardly)?\b"
            r"|\b(?:North|South)(?:east|west)-wardly\b",
            text,
            re.IGNORECASE,
        )
        assert split_dir is None, f"{field}: soft-hyphenated direction {split_dir.group(0)!r}"


@pytest.mark.parametrize("path", GROUND_TRUTHS, ids=_ids(GROUND_TRUTHS))
def test_curve_parameters_appear_in_description_and_are_consistent(path):
    gt = _load(path)
    legal = _squash(gt.get("expected_legal_description") or "")
    for call in gt.get("expected_calls") or []:
        radius = call.get("radius_ft")
        arc = call.get("arc_length_ft")
        delta = call.get("delta_deg")
        chord = call.get("chord_length_ft")
        distance = call.get("distance_ft")
        if arc is not None and distance is not None:
            assert abs(arc - distance) <= 1e-4, (
                f"course {call['course']}: distance_ft != arc_length_ft"
            )
        if legal:
            for field, value in (
                ("radius_ft", radius),
                ("arc_length_ft", arc),
                ("chord_length_ft", chord),
            ):
                if value is not None:
                    assert any(form in legal for form in _printed_forms(value)), (
                        f"course {call['course']} {field}: {value} not found in legal description"
                    )
        if radius is not None and arc is not None and delta is not None:
            expected_arc = radius * math.radians(delta)
            assert abs(expected_arc - arc) <= 0.05, (
                f"course {call['course']}: R*delta={expected_arc:.4f} != arc={arc}"
            )


@pytest.mark.parametrize("path", GROUND_TRUTHS, ids=_ids(GROUND_TRUTHS))
def test_ground_truth_records_printed_values_without_overrides(path):
    """Ground truths store verbatim transcribed deed values, never corrected substitutes."""
    for call in _load(path).get("expected_calls") or []:
        overrides = [key for key in call if key.startswith(_OVERRIDE_PREFIXES)]
        assert not overrides, f"course {call['course']}: unexpected override fields {overrides}"


@pytest.mark.parametrize("path", GROUND_TRUTHS, ids=_ids(GROUND_TRUTHS))
def test_call_count_assertion_matches_the_courses(path):
    gt = _load(path)
    assertion = (gt.get("critical_assertions") or {}).get("num_calls")
    if isinstance(assertion, dict):
        assert assertion["expected"] == len(gt.get("expected_calls") or [])


@pytest.mark.parametrize("path", GROUND_TRUTHS, ids=_ids(GROUND_TRUTHS))
def test_no_html_entities(path):
    assert not re.search(r"&(?:amp|lt|gt|quot|#\d+);", path.read_text(encoding="utf-8"))


def _single_figure(gt: dict) -> list[dict] | None:
    """Return the courses of a ground truth's only figure (tie courses excluded), if one."""
    figures: dict[str, list[dict]] = defaultdict(list)
    for call in gt.get("expected_calls") or []:
        if not call.get("is_tie_in"):
            figures[call.get("tract") or "all"].append(call)
    return next(iter(figures.values())) if len(figures) == 1 else None


# Ground truths storing one closure for one figure; multi-figure deeds note theirs per figure.
CLOSURE_CASES = [
    path
    for path in GROUND_TRUTHS
    if _single_figure(_load(path))
    and _is_number((_load(path).get("expected_closure") or {}).get("misclosure_ft"))
]


@pytest.mark.parametrize("path", CLOSURE_CASES, ids=_ids(CLOSURE_CASES))
def test_stored_closure_matches_the_courses(path):
    """The stored misclosure and area are recomputed from the courses."""
    gt = _load(path)
    stored = gt["expected_closure"]
    calls = _single_figure(gt) or []
    assert all(
        call.get("bearing_azimuth_deg_from_north") is not None or call.get("curve_dir")
        for call in calls
    ), "a misclosure is stored for courses without bearings"
    misclosure_ft = stored.get("misclosure_ft")
    assert _is_number(misclosure_ft), f"misclosure_ft must be numeric, got {misclosure_ft!r}"
    raw_tolerance = stored.get("misclosure_tolerance_ft", 0.01)
    tolerance = 0.01 if raw_tolerance is None else raw_tolerance
    assert _is_number(tolerance), f"misclosure_tolerance_ft must be numeric, got {tolerance!r}"
    result = verify_closure(
        [
            DeedCall(**{key: value for key, value in call.items() if key in _CLOSURE_FIELDS})
            for call in calls
        ],
        closure_tolerance_ft=tolerance,
    )
    assert result.misclosure_available, "misclosure_ft stored but misclosure is unavailable"
    assert result.misclosure_ft == pytest.approx(misclosure_ft, abs=0.002)
    assert stored["closure_passed"] == result.closure_passed
    perimeter_ft = stored.get("perimeter_ft")
    if perimeter_ft is not None:
        assert _is_number(perimeter_ft), f"perimeter_ft must be numeric, got {perimeter_ft!r}"
        assert result.perimeter_available, "perimeter_ft stored but perimeter is unavailable"
        assert result.perimeter_ft == pytest.approx(perimeter_ft, abs=0.05)
    area_sq_ft = stored.get("area_sq_ft")
    if area_sq_ft is not None:
        assert _is_number(area_sq_ft), f"area_sq_ft must be numeric, got {area_sq_ft!r}"
        assert result.area_available, "area_sq_ft stored but area is unavailable"
        assert result.area_sq_ft == pytest.approx(area_sq_ft, abs=0.05)
    area_acres = stored.get("area_acres")
    if area_acres is not None:
        assert _is_number(area_acres), f"area_acres must be numeric, got {area_acres!r}"
        assert result.area_available, "area_acres stored but area is unavailable"
        assert result.area_acres == pytest.approx(area_acres, abs=0.002)


def _write_gt(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / f"{name}.ground_truth.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _square_calls(closing_distance_ft: float = 100.0) -> list[dict]:
    return [
        {
            "course": 1,
            "direction_text": "N 0°00'00\" E",
            "bearing_quadrant": "N 0°00'00\" E",
            "bearing_azimuth_deg_from_north": 0.0,
            "distance_ft": 100.0,
        },
        {
            "course": 2,
            "direction_text": "N 90°00'00\" E",
            "bearing_quadrant": "N 90°00'00\" E",
            "bearing_azimuth_deg_from_north": 90.0,
            "distance_ft": 100.0,
        },
        {
            "course": 3,
            "direction_text": "S 0°00'00\" E",
            "bearing_quadrant": "S 0°00'00\" E",
            "bearing_azimuth_deg_from_north": 180.0,
            "distance_ft": 100.0,
        },
        {
            "course": 4,
            "direction_text": "S 90°00'00\" W",
            "bearing_quadrant": "S 90°00'00\" W",
            "bearing_azimuth_deg_from_north": 270.0,
            "distance_ft": closing_distance_ft,
        },
    ]


class TestBearingConsistencyChecks:
    """Synthetic regression tests for direction_text, azimuth, and description checks."""

    def test_spelled_out_bearing_missing_from_description_fails(self, tmp_path: Path) -> None:
        gt_path = _write_gt(
            tmp_path,
            "spelled_missing",
            {
                "expected_legal_description": (
                    "BEGINNING at a point; thence South 30 degrees 00 minutes 00 seconds East, "
                    "100.00 feet."
                ),
                "expected_calls": [
                    {
                        "course": 1,
                        "direction_text": "S 25 degrees 06 minutes 00 seconds E",
                        "bearing_quadrant": "S 25°06'00\" E",
                        "bearing_azimuth_deg_from_north": 154.9,
                        "distance_ft": 100.0,
                    }
                ],
            },
        )
        with pytest.raises(AssertionError):
            test_bearing_appears_in_the_description(gt_path)

    def test_spelled_out_bearing_matching_description_passes(self, tmp_path: Path) -> None:
        gt_path = _write_gt(
            tmp_path,
            "spelled_match",
            {
                "expected_legal_description": (
                    "BEGINNING at a point; thence South 25 degrees 06 minutes 00 seconds East, "
                    "100.00 feet."
                ),
                "expected_calls": [
                    {
                        "course": 1,
                        "direction_text": "S 25 degrees 06 minutes 00 seconds E",
                        "bearing_quadrant": "S 25°06'00\" E",
                        "bearing_azimuth_deg_from_north": 154.9,
                        "distance_ft": 100.0,
                    }
                ],
            },
        )
        test_bearing_appears_in_the_description(gt_path)

    @pytest.mark.parametrize("legal", ["BEGINNING at a point; thence Northerly 100 feet.", ""])
    def test_numeric_azimuth_with_unparseable_direction_text_fails(
        self, tmp_path: Path, legal: str
    ) -> None:
        gt_path = _write_gt(
            tmp_path,
            "unparseable_direction",
            {
                "expected_legal_description": legal,
                "expected_calls": [
                    {
                        "course": 1,
                        "direction_text": "Northerly",
                        "bearing_quadrant": "N 50°45'00\" E",
                        "bearing_azimuth_deg_from_north": 50.75,
                        "distance_ft": 100.0,
                    }
                ],
            },
        )
        with pytest.raises(AssertionError):
            test_bearing_appears_in_the_description(gt_path)

    @pytest.mark.parametrize(
        "legal",
        [
            "BEGINNING at a point; thence North 50 degrees 45 minutes 00 seconds East, 417.57 feet.",
            "",
        ],
    )
    def test_direction_text_diverging_from_azimuth_fails(self, tmp_path: Path, legal: str) -> None:
        gt_path = _write_gt(
            tmp_path,
            "azimuth_divergence",
            {
                "expected_legal_description": legal,
                "expected_calls": [
                    {
                        "course": 1,
                        "direction_text": "N 50°45'00\" E",
                        "bearing_quadrant": "N 56°45'00\" E",
                        "bearing_azimuth_deg_from_north": 56.75,
                        "distance_ft": 417.57,
                    }
                ],
            },
        )
        with pytest.raises(AssertionError):
            test_bearing_appears_in_the_description(gt_path)

    def test_due_cardinal_direction_text_is_checked(self, tmp_path: Path) -> None:
        ok_path = _write_gt(
            tmp_path,
            "due_ok",
            {
                "expected_legal_description": "BEGINNING at a point; thence due West 100 feet.",
                "expected_calls": [
                    {
                        "course": 1,
                        "direction_text": "due West",
                        "bearing_quadrant": None,
                        "bearing_azimuth_deg_from_north": 270.0,
                        "distance_ft": 100.0,
                    }
                ],
            },
        )
        test_bearing_appears_in_the_description(ok_path)

        wrong_az_path = _write_gt(
            tmp_path,
            "due_wrong_az",
            {
                "expected_legal_description": "BEGINNING at a point; thence due West 100 feet.",
                "expected_calls": [
                    {
                        "course": 1,
                        "direction_text": "due West",
                        "bearing_quadrant": None,
                        "bearing_azimuth_deg_from_north": 90.0,
                        "distance_ft": 100.0,
                    }
                ],
            },
        )
        with pytest.raises(AssertionError):
            test_bearing_appears_in_the_description(wrong_az_path)

        missing_desc_path = _write_gt(
            tmp_path,
            "due_missing_desc",
            {
                "expected_legal_description": "BEGINNING at a point; thence due East 100 feet.",
                "expected_calls": [
                    {
                        "course": 1,
                        "direction_text": "due West",
                        "bearing_quadrant": None,
                        "bearing_azimuth_deg_from_north": 270.0,
                        "distance_ft": 100.0,
                    }
                ],
            },
        )
        with pytest.raises(AssertionError):
            test_bearing_appears_in_the_description(missing_desc_path)

    def test_azimuth_360_wrap_passes(self, tmp_path: Path) -> None:
        gt_path = _write_gt(
            tmp_path,
            "wrap_360",
            {
                "expected_legal_description": (
                    "BEGINNING at a point; thence North 0 degrees 00 minutes 00 seconds West, "
                    "100.00 feet."
                ),
                "expected_calls": [
                    {
                        "course": 1,
                        "direction_text": "N 0°00'00\" W",
                        "bearing_quadrant": "N 0°00'00\" W",
                        "bearing_azimuth_deg_from_north": 0.0,
                        "distance_ft": 100.0,
                    }
                ],
            },
        )
        test_bearing_appears_in_the_description(gt_path)

    @pytest.mark.parametrize(
        ("direction_text", "azimuth", "legal_bearing"),
        [
            ("N 50°45' E", 50.75, "North 50 degrees 45 minutes 00 seconds East"),
            ("N 50°45'00\" E", 50.75, "North 50 degrees 45 minutes East"),
            ("N 50°00'00\" E", 50.0, "North 50 degrees East"),
            ("N 50° E", 50.0, "North 50 degrees 00 minutes 00 seconds East"),
            ("N 50°45'05.5\" E", 50.7515278, "North 50 degrees 45 minutes 5.5 seconds East"),
            ("N 50°45'5.5\" E", 50.7515278, "North 50 degrees 45 minutes 05.5 seconds East"),
            ("N 50°45'30\" E", 50.7583333, "N 50°45\u201930\u201d E"),
            ("N 50°45\u201930\u201d E", 50.7583333, "North 50 degrees 45 minutes 30 seconds East"),
            ("N 50°45'30\" E", 50.7583333, "N 50°45'30'' E"),
            ("N 50°45'30'' E", 50.7583333, "North 50 degrees 45 minutes 30 seconds East"),
            ("N 50°45'30\" E", 50.7583333, "N 50d 45m 30s E"),
            ("N 50d 45m 30s E", 50.7583333, "North 50 degrees 45 minutes 30 seconds East"),
            ("N 50°45'30\" E", 50.7583333, "N 50\u00ba45'30\" E"),
            ("N 50\u00ba45'30\" E", 50.7583333, "North 50 degrees 45 minutes 30 seconds East"),
        ],
    )
    def test_dms_formatting_variants_pass(
        self, tmp_path: Path, direction_text: str, azimuth: float, legal_bearing: str
    ) -> None:
        gt_path = _write_gt(
            tmp_path,
            "variant",
            {
                "expected_legal_description": f"BEGINNING at a point; thence {legal_bearing} 100 ft.",
                "expected_calls": [
                    {
                        "course": 1,
                        "direction_text": direction_text,
                        "bearing_quadrant": None,
                        "bearing_azimuth_deg_from_north": azimuth,
                        "distance_ft": 100.0,
                    }
                ],
            },
        )
        test_bearing_appears_in_the_description(gt_path)

    @pytest.mark.parametrize(
        ("direction_text", "azimuth", "legal_bearing"),
        [
            ("N 50°45' E", 50.75, "North 50 degrees 45 minutes 30 seconds East"),
            ("N 50°45'30\" E", 50.7583333, "North 50 degrees 45 minutes East"),
            ("N 50d 45m 30s E", 50.7583333, "South 10 degrees 00 minutes 00 seconds West"),
            ("N 50°45\u201930\u201d E", 50.7583333, "South 10 degrees 00 minutes 00 seconds West"),
            ("N 50°45'30'' E", 50.7583333, "South 10 degrees 00 minutes 00 seconds West"),
            ("N 50\u00ba45'30\" E", 50.7583333, "South 10 degrees 00 minutes 00 seconds West"),
        ],
    )
    def test_nonzero_seconds_or_variant_mismatch_fails(
        self, tmp_path: Path, direction_text: str, azimuth: float, legal_bearing: str
    ) -> None:
        gt_path = _write_gt(
            tmp_path,
            "sec_mismatch",
            {
                "expected_legal_description": f"BEGINNING at a point; thence {legal_bearing} 100 ft.",
                "expected_calls": [
                    {
                        "course": 1,
                        "direction_text": direction_text,
                        "bearing_quadrant": None,
                        "bearing_azimuth_deg_from_north": azimuth,
                        "distance_ft": 100.0,
                    }
                ],
            },
        )
        with pytest.raises(AssertionError):
            test_bearing_appears_in_the_description(gt_path)

    @pytest.mark.parametrize(
        ("direction_text", "legal"),
        [
            (
                "N 50°45'00\" E",
                "BEGINNING at a point; thence North 50 degrees 45 minutes 00 seconds East, 100 ft.",
            ),
            ("due West", "BEGINNING at a point; thence due West 100 ft."),
            ("N 50°45'00\" E", ""),
        ],
    )
    def test_parsed_bearing_without_azimuth_fails(
        self, tmp_path: Path, direction_text: str, legal: str
    ) -> None:
        gt_path = _write_gt(
            tmp_path,
            "missing_azimuth",
            {
                "expected_legal_description": legal,
                "expected_calls": [
                    {
                        "course": 1,
                        "direction_text": direction_text,
                        "bearing_quadrant": None,
                        "bearing_azimuth_deg_from_north": None,
                        "distance_ft": 100.0,
                    }
                ],
            },
        )
        with pytest.raises(AssertionError, match="without an azimuth"):
            test_bearing_appears_in_the_description(gt_path)

    @pytest.mark.parametrize(
        "bearing",
        [
            "N 95°00'00\" E",
            "N 90°00'01\" E",
            "N 45°60'00\" E",
            "N 45°75'00\" E",
            "N 45°00'60\" E",
            "N 45°00'75\" E",
        ],
    )
    def test_out_of_range_dms_is_rejected(self, bearing: str) -> None:
        assert _parse_direction(bearing) is None


class TestStoredClosureChecks:
    """Synthetic regression tests for closure_passed, tolerance, perimeter_ft, and area_acres."""

    def test_stale_closure_passed_fails(self, tmp_path: Path) -> None:
        gt_path = _write_gt(
            tmp_path,
            "stale_passed",
            {
                "expected_calls": _square_calls(),
                "expected_closure": {
                    "misclosure_ft": 0.0,
                    "area_sq_ft": 10000.0,
                    "area_acres": 0.2296,
                    "perimeter_ft": 400.0,
                    "closure_passed": False,
                },
            },
        )
        with pytest.raises(AssertionError):
            test_stored_closure_matches_the_courses(gt_path)

    def test_custom_misclosure_tolerance_is_respected(self, tmp_path: Path) -> None:
        base_closure = {
            "misclosure_ft": 0.03,
            "misclosure_tolerance_ft": 0.05,
            "area_sq_ft": 10000.0,
            "area_acres": 0.2296,
            "perimeter_ft": 399.97,
            "closure_passed": True,
        }
        gt_ok = _write_gt(
            tmp_path,
            "custom_tol_ok",
            {"expected_calls": _square_calls(99.97), "expected_closure": base_closure},
        )
        test_stored_closure_matches_the_courses(gt_ok)

        gt_bad = _write_gt(
            tmp_path,
            "custom_tol_bad",
            {
                "expected_calls": _square_calls(99.97),
                "expected_closure": {**base_closure, "closure_passed": False},
            },
        )
        with pytest.raises(AssertionError):
            test_stored_closure_matches_the_courses(gt_bad)

    def test_stale_perimeter_fails(self, tmp_path: Path) -> None:
        gt_path = _write_gt(
            tmp_path,
            "stale_perimeter",
            {
                "expected_calls": _square_calls(),
                "expected_closure": {
                    "misclosure_ft": 0.0,
                    "area_sq_ft": 10000.0,
                    "area_acres": 0.2296,
                    "perimeter_ft": 410.0,
                    "closure_passed": True,
                },
            },
        )
        with pytest.raises(AssertionError):
            test_stored_closure_matches_the_courses(gt_path)

    def test_stale_area_acres_fails(self, tmp_path: Path) -> None:
        gt_path = _write_gt(
            tmp_path,
            "stale_acres",
            {
                "expected_calls": _square_calls(),
                "expected_closure": {
                    "misclosure_ft": 0.0,
                    "area_sq_ft": 10000.0,
                    "area_acres": 0.50,
                    "perimeter_ft": 400.0,
                    "closure_passed": True,
                },
            },
        )
        with pytest.raises(AssertionError):
            test_stored_closure_matches_the_courses(gt_path)

    def test_unpositioned_curve_with_zero_misclosure_fails(self, tmp_path: Path) -> None:
        gt_path = _write_gt(
            tmp_path,
            "unpositioned_curve",
            {
                "expected_calls": [
                    {
                        "course": 1,
                        "direction_text": "curving to the right",
                        "bearing_azimuth_deg_from_north": None,
                        "distance_ft": 100.0,
                        "curve_dir": "right",
                        "radius_ft": 500.0,
                        "arc_length_ft": 100.0,
                    }
                ],
                "expected_closure": {
                    "misclosure_ft": 0.0,
                    "closure_passed": True,
                },
            },
        )
        with pytest.raises(AssertionError):
            test_stored_closure_matches_the_courses(gt_path)

    @pytest.mark.parametrize(
        ("field", "value", "closing_distance_ft", "base_misclosure_ft"),
        [
            ("misclosure_ft", False, 100.0, 0.0),
            ("misclosure_tolerance_ft", True, 99.5, 0.5),
            ("perimeter_ft", False, 100.0, 0.0),
            ("area_sq_ft", False, 100.0, 0.0),
            ("area_acres", False, 100.0, 0.0),
        ],
    )
    def test_boolean_numeric_closure_fields_fail(
        self,
        tmp_path: Path,
        field: str,
        value: bool,
        closing_distance_ft: float,
        base_misclosure_ft: float,
    ) -> None:
        closure: dict[str, object] = {
            "misclosure_ft": base_misclosure_ft,
            "area_sq_ft": 10000.0,
            "area_acres": 0.2296,
            "perimeter_ft": 300.0 + closing_distance_ft,
            "closure_passed": True,
        }
        closure[field] = value
        gt_path = _write_gt(
            tmp_path,
            f"bool_{field}",
            {"expected_calls": _square_calls(closing_distance_ft), "expected_closure": closure},
        )
        with pytest.raises(AssertionError, match="must be numeric"):
            test_stored_closure_matches_the_courses(gt_path)


class TestOverrideFieldChecks:
    """Synthetic regression tests banning printed_/intended_/corrected_ call override keys."""

    @pytest.mark.parametrize(
        "override_key",
        ["printed_distance_ft", "intended_distance_ft", "corrected_bearing"],
    )
    def test_override_prefix_keys_fail(self, tmp_path: Path, override_key: str) -> None:
        gt_path = _write_gt(
            tmp_path,
            f"override_{override_key}",
            {
                "expected_calls": [
                    {
                        "course": 1,
                        "direction_text": "N 0°00'00\" E",
                        "distance_ft": 100.0,
                        override_key: 99.0,
                    }
                ]
            },
        )
        with pytest.raises(AssertionError):
            test_ground_truth_records_printed_values_without_overrides(gt_path)


class TestAdditionalGroundTruthGuards:
    """Synthetic regression tests for POB/POC, duplicate words, hyphens, quadrants, and curves."""

    def test_pob_missing_from_legal_description_fails(self, tmp_path: Path) -> None:
        gt_path = _write_gt(
            tmp_path,
            "bad_pob",
            {
                "expected_legal_description": "BEGINNING at a point approved Dec 15, 1931.and adopted.",
                "expected_pob": "a point approved Dec 15, 1931 and adopted",
            },
        )
        with pytest.raises(AssertionError, match="expected_pob"):
            test_pob_and_poc_are_quoted_from_the_description(gt_path)

    def test_duplicate_word_in_normalized_text_fails(self, tmp_path: Path) -> None:
        gt_path = _write_gt(
            tmp_path,
            "dup_word",
            {
                "expected_legal_description": "BEGINNING at a PK nail found.",
                "expected_normalized_text": "BEGINNING at a pk nail nail found.",
            },
        )
        with pytest.raises(AssertionError, match="duplicate consecutive word"):
            test_text_has_no_duplicate_words_or_line_break_hyphens(gt_path)

    def test_unjoined_line_break_hyphen_fails(self, tmp_path: Path) -> None:
        gt_path = _write_gt(
            tmp_path,
            "broken_hyphen",
            {
                "expected_legal_description": "from the inter-\nsection of Main Street",
                "expected_normalized_text": "from the intersection of Main Street",
            },
        )
        with pytest.raises(AssertionError, match="unjoined line-break hyphen"):
            test_text_has_no_duplicate_words_or_line_break_hyphens(gt_path)

    def test_soft_hyphenated_direction_fails(self, tmp_path: Path) -> None:
        gt_path = _write_gt(
            tmp_path,
            "split_dir",
            {
                "expected_legal_description": "thence (1) Southwest-wardly 50 feet.",
                "expected_normalized_text": "thence (1) Southwest-wardly 50 feet.",
            },
        )
        with pytest.raises(AssertionError, match="soft-hyphenated direction"):
            test_text_has_no_duplicate_words_or_line_break_hyphens(gt_path)

    def test_truncated_bearing_quadrant_fails(self, tmp_path: Path) -> None:
        gt_path = _write_gt(
            tmp_path,
            "trunc_quad",
            {
                "expected_calls": [
                    {
                        "course": 1,
                        "direction_text": "S 71°54'50\" E",
                        "bearing_quadrant": "S 71°54' E",
                        "bearing_azimuth_deg_from_north": 108.08611111111111,
                        "distance_ft": 69.8,
                    }
                ]
            },
        )
        with pytest.raises(AssertionError):
            test_azimuth_matches_quadrant_bearing(gt_path)

    def test_curve_radius_missing_from_description_fails(self, tmp_path: Path) -> None:
        gt_path = _write_gt(
            tmp_path,
            "bad_curve",
            {
                "expected_legal_description": "curving right radius 500.00 feet arc 100.00 feet",
                "expected_calls": [
                    {
                        "course": 1,
                        "curve_dir": "right",
                        "radius_ft": 550.0,
                        "arc_length_ft": 100.0,
                        "distance_ft": 100.0,
                    }
                ],
            },
        )
        with pytest.raises(AssertionError, match="radius_ft"):
            test_curve_parameters_appear_in_description_and_are_consistent(gt_path)
