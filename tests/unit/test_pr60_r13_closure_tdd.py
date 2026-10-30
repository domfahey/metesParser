"""PR #60 round 13: chord-only traverses are computable; tangent check runs once per course."""

from __future__ import annotations

import mp_models
import mp_verify.checks as checks_mod
import mp_verify.closure as closure_mod
import pytest
from mp_verify.closure import verify_closure as package_verify

from metesparser import models as monolith_models
from metesparser.closure_checker import ClosureChecker

IMPLS = {
    "package": (mp_models, package_verify),
    "monolith": (monolith_models, ClosureChecker.verify_closure),
}


def _chord(m, course, chord_bearing, length=100.0, tangent=None):
    return m.DeedCall(
        course=course,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=tangent,
        distance_ft=length,
        curve_dir="right",
        radius_ft=500.0,
        chord_bearing=chord_bearing,
        chord_length_ft=length,
    )


def _square_of_chords(m):
    return [
        _chord(m, 1, "N 0°00'00\" E"),
        _chord(m, 2, "S 90°00'00\" E"),
        _chord(m, 3, "S 0°00'00\" E"),
        _chord(m, 4, "N 90°00'00\" W"),
    ]


@pytest.mark.parametrize("impl", IMPLS)
def test_chord_only_traverse_is_computable(impl):
    m, verify = IMPLS[impl]
    result = verify(_square_of_chords(m))
    assert not any("No computable traverse" in w for w in result.warnings)
    assert result.closure_passed


@pytest.mark.parametrize("impl", IMPLS)
def test_tangent_chord_issue_runs_once_per_chord_only_course(impl, monkeypatch):
    m, verify = IMPLS[impl]
    seen: list[int] = []
    real = checks_mod.tangent_chord_issue

    def spy(call):
        seen.append(call.course)
        return real(call)

    monkeypatch.setattr(checks_mod, "tangent_chord_issue", spy)
    monkeypatch.setattr(closure_mod, "tangent_chord_issue", spy)
    verify(_square_of_chords(m))
    for course in (1, 2, 3, 4):
        assert seen.count(course) == 1, seen
