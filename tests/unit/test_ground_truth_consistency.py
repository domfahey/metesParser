"""Internal consistency of the sample-deed ground truths.

Each ground truth records its deed's legal description and the courses read from it. These
checks catch a course that disagrees with its own description or with itself; they do not
establish that the description matches the recorded deed (the PDF checks did that).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import pytest
from mp_models import DeedCall
from mp_verify import verify_closure

SAMPLE_DEEDS = Path(__file__).resolve().parents[2] / "sample_deeds"
GROUND_TRUTHS = sorted(SAMPLE_DEEDS.glob("*.ground_truth.json"))

_QUADRANT = re.compile(
    r"([NS])\s*(\d{1,3})°\s*(?:(\d{1,2})')?\s*(?:(\d{1,2}(?:\.\d+)?)\")?\s*([EW])"
)
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


def _quadrant_azimuth(quadrant: str) -> float | None:
    match = _QUADRANT.search(quadrant)
    if not match:
        return None
    first, degrees, minutes, seconds, second = match.groups()
    angle = int(degrees) + int(minutes or 0) / 60 + float(seconds or 0) / 3600
    return {"NE": angle, "SE": 180 - angle, "SW": 180 + angle, "NW": 360 - angle}[first + second]


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
        assert min(difference, 360 - difference) < 0.02, f"course {call['course']}"


@pytest.mark.parametrize("path", GROUND_TRUTHS, ids=_ids(GROUND_TRUTHS))
def test_azimuth_is_in_range(path):
    for call in _load(path).get("expected_calls") or []:
        azimuth = call.get("bearing_azimuth_deg_from_north")
        assert azimuth is None or 0 <= azimuth < 360, f"course {call['course']}"


@pytest.mark.parametrize("path", GROUND_TRUTHS, ids=_ids(GROUND_TRUTHS))
def test_straight_course_distance_appears_in_the_description(path):
    """A misprinted course is printed as its printed_distance_ft."""
    gt = _load(path)
    legal = _squash(gt.get("expected_legal_description") or "")
    for call in gt.get("expected_calls") or []:
        if call.get("curve_dir") or not legal:
            continue
        distance = call.get("printed_distance_ft", call["distance_ft"])
        whole_feet = re.search(rf"\b{int(distance)}\s*(?:feet|ft|')", legal)
        assert any(form in legal for form in _printed_forms(distance)) or whole_feet, (
            f"course {call['course']}: {distance}"
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
def test_printed_value_differs_from_the_intended_one(path):
    for call in _load(path).get("expected_calls") or []:
        if "printed_distance_ft" in call:
            assert call["printed_distance_ft"] != call["distance_ft"], f"course {call['course']}"
        if "printed_bearing_azimuth_deg_from_north" in call:
            assert (
                call["printed_bearing_azimuth_deg_from_north"]
                != call["bearing_azimuth_deg_from_north"]
            ), f"course {call['course']}"


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
    and isinstance((_load(path).get("expected_closure") or {}).get("misclosure_ft"), int | float)
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
    result = verify_closure(
        [
            DeedCall(**{key: value for key, value in call.items() if key in _CLOSURE_FIELDS})
            for call in calls
        ]
    )
    assert result.misclosure_ft == pytest.approx(stored["misclosure_ft"], abs=0.002)
    if isinstance(stored.get("area_sq_ft"), int | float):
        assert result.area_sq_ft == pytest.approx(stored["area_sq_ft"], abs=1.0)
