"""Tests for Tract model."""

import pytest
from mp_models import DeedCall, TractType, Tract


class TestTractType:
    def test_main_value(self):
        assert TractType.MAIN == "main"

    def test_exception_value(self):
        assert TractType.EXCEPTION == "exception"

    def test_addition_value(self):
        assert TractType.ADDITION == "addition"

    def test_easement_value(self):
        assert TractType.EASEMENT == "easement"


class TestTract:
    def test_create_minimal_tract(self):
        tract = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=[])
        assert tract.label == "Tract 1"
        assert tract.tract_type == TractType.MAIN
        assert tract.calls == []
        assert tract.pob_description is None
        assert tract.stated_area_sq_ft is None
        assert tract.closure_result is None

    def test_create_tract_with_calls(self):
        call = DeedCall(
            course=1,
            direction_text="N 45\u00b000' E",
            distance_ft=100.0,
        )
        tract = Tract(
            label="Parcel A",
            tract_type=TractType.ADDITION,
            calls=[call],
            pob_description="at an iron pin",
            stated_area_sq_ft=5000.0,
        )
        assert len(tract.calls) == 1
        assert tract.pob_description == "at an iron pin"
        assert tract.stated_area_sq_ft == 5000.0

    def test_tract_is_frozen(self):
        tract = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=[])
        with pytest.raises(Exception):
            tract.label = "changed"  # type: ignore[misc]

    def test_tract_forbids_extra(self):
        with pytest.raises(Exception):
            Tract(label="X", tract_type=TractType.MAIN, calls=[], foo="bar")  # type: ignore[call-arg]


from mp_models import LegalDescription


class TestLegalDescriptionTracts:
    def test_tracts_default_empty(self):
        ld = LegalDescription()
        assert ld.tracts == []

    def test_all_calls_returns_flat_calls_when_no_tracts(self):
        call = DeedCall(course=1, direction_text="N 45\u00b000' E", distance_ft=100.0)
        ld = LegalDescription(calls=[call])
        assert ld.all_calls == [call]

    def test_all_calls_merges_tract_calls(self):
        c1 = DeedCall(course=1, direction_text="N 45\u00b000' E", distance_ft=100.0)
        c2 = DeedCall(course=2, direction_text="S 45\u00b000' E", distance_ft=200.0)
        t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=[c1])
        t2 = Tract(label="Tract 2", tract_type=TractType.MAIN, calls=[c2])
        ld = LegalDescription(tracts=[t1, t2])
        assert ld.all_calls == [c1, c2]

    def test_all_calls_prefers_tracts_over_calls(self):
        c1 = DeedCall(course=1, direction_text="N 45\u00b000' E", distance_ft=100.0)
        c2 = DeedCall(course=2, direction_text="S 45\u00b000' E", distance_ft=200.0)
        t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=[c2])
        ld = LegalDescription(calls=[c1], tracts=[t1])
        assert ld.all_calls == [c2]

    def test_num_calls_still_uses_calls_field(self):
        c1 = DeedCall(course=1, direction_text="N 45\u00b000' E", distance_ft=100.0)
        ld = LegalDescription(calls=[c1])
        assert ld.num_calls() == 1
