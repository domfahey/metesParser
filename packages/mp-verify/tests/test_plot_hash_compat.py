"""Stored plot identities predate the unresolved ``positioned`` flag and must not change."""

import pytest
from mp_models.deed_call import DeedCall
from mp_models.plot import PlotUnresolved
from mp_models.plot_request import PlotCall, PlotRequest, PreparedPlot
from mp_verify.plot import prepare_plot, validate_prepared_plot

START = {
    "course": 1,
    "direction_text": "N 0 E",
    "bearing_azimuth_deg_from_north": 0,
    "distance_ft": 100,
}
INCOMPLETE = [
    START,
    {
        "course": 2,
        "direction_text": "southwesterly",
        "bearing_azimuth_deg_from_north": None,
        "distance_ft": 100,
        "notes": "incomplete bearing - cardinal only",
    },
]
CHORD_ONLY = [
    START,
    {
        "course": 2,
        "direction_text": "curve",
        "distance_ft": 50,
        "curve_dir": "right",
        "radius_ft": 100,
        "chord_bearing": "N 90°00' E",
        "chord_length_ft": 50,
        "is_indefinite": True,
    },
    {
        "course": 3,
        "direction_text": "S 0 E",
        "bearing_azimuth_deg_from_north": 180,
        "distance_ft": 100,
    },
]
# Values computed on the base branch (fix/code-review-2026-10-29) before the flag existed.
BASE = {
    "incomplete": (
        INCOMPLETE,
        "f8c5d6a42a4a702537f928c9596f50f48673300919c3ddf3759f3c46b8d06698",
        [
            {
                "call_id": "c2",
                "reason": "incomplete bearing - cardinal only or unresolved orientation",
            }
        ],
        False,
    ),
    "chord_only": (
        CHORD_ONLY,
        "1a7fd9b62f74e849d9322f97af6cac8e2ad20cf60d2e8bf80eba808f8d008b55",
        [
            {
                "call_id": "c2",
                "reason": "curve delta/arc not stated - arc not drawn; positioned by chord only",
            }
        ],
        True,
    ),
}


def _prepared(calls):
    return prepare_plot(
        PlotRequest(
            title="t",
            calls=tuple(
                PlotCall(id=f"c{i}", call=DeedCall.model_validate(c))
                for i, c in enumerate(calls, 1)
            ),
        )
    )


@pytest.mark.parametrize("name", sorted(BASE))
def test_geometry_hash_and_serialization_match_base(name):
    calls, digest, unresolved, positioned = BASE[name]
    geometry = _prepared(calls).geometry
    assert geometry.geometry_hash == digest
    assert [u.model_dump(mode="json") for u in geometry.unresolved] == unresolved
    assert [u.positioned for u in geometry.unresolved] == [positioned]


@pytest.mark.parametrize("name", sorted(BASE))
def test_legacy_stored_plot_without_flag_still_validates(name):
    calls, _, unresolved, positioned = BASE[name]
    stored = _prepared(calls).model_dump(mode="json")
    stored["geometry"]["unresolved"] = unresolved  # exactly as written before the flag
    legacy = PreparedPlot.model_validate(stored)
    assert [u.positioned for u in legacy.geometry.unresolved] == [positioned]
    assert validate_prepared_plot(legacy) == legacy


def test_arbitrary_reason_is_not_positioned():
    assert not PlotUnresolved(call_id="c1", reason="positioned by chord only").positioned
