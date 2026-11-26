"""Tests for Tract model."""

import pytest
from mp_models import DeedCall, LegalDescription, Tract, TractType
from pydantic import ValidationError


class TestTract:
    def test_tract_type_values_match_contract(self):
        assert {member.value for member in TractType} == {
            "main",
            "exception",
            "addition",
            "easement",
        }

    def test_tract_is_frozen(self):
        tract = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=[])
        with pytest.raises(ValidationError, match="Instance is frozen"):
            tract.label = "changed"  # type: ignore[misc]

    def test_tract_forbids_extra(self):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            Tract(label="X", tract_type=TractType.MAIN, calls=[], foo="bar")  # type: ignore[call-arg]

    def test_tract_json_roundtrip(self):
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
        restored = Tract.model_validate_json(tract.model_dump_json())
        assert restored == tract


class TestLegalDescriptionTracts:
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

    def test_num_calls_with_flat_calls(self):
        c1 = DeedCall(course=1, direction_text="N 45\u00b000' E", distance_ft=100.0)
        ld = LegalDescription(calls=[c1])
        assert ld.num_calls() == 1

    def test_num_calls_with_tracts(self):
        c1 = DeedCall(course=1, direction_text="N 45\u00b000' E", distance_ft=100.0)
        c2 = DeedCall(course=2, direction_text="S 45\u00b000' E", distance_ft=200.0)
        t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=[c1])
        t2 = Tract(label="Tract 2", tract_type=TractType.MAIN, calls=[c2])
        ld = LegalDescription(tracts=[t1, t2])
        assert ld.num_calls() == 2


class TestTractRoleAndNonBoundaryGates:
    def _call(self, notes: str | None = None) -> DeedCall:
        return DeedCall(
            course=1,
            direction_text="N 45° E",
            bearing_azimuth_deg_from_north=45.0,
            distance_ft=100.0,
            notes=notes,
        )

    def test_mark_roles_review_and_mark_non_boundary_are_idempotent(self):
        from mp_models import (
            DESCRIPTION_ROLES_NOTE,
            EASEMENT_TRACT_NOTE,
            EXCEPTION_TRACT_NOTE,
            mark_non_boundary,
            mark_roles_review,
            non_boundary_marks,
            non_boundary_marks_detail,
        )

        c = self._call(notes="record call: 100 ft")
        marked = mark_roles_review([c])
        assert DESCRIPTION_ROLES_NOTE in (marked[0].notes or "")
        assert "record call: 100 ft" in (marked[0].notes or "")
        # Idempotent on second application.
        assert mark_roles_review(marked)[0].notes == marked[0].notes

        # Boundary tracts return unchanged; easement/exception attach their notes.
        assert mark_non_boundary([c], TractType.MAIN) == [c]
        e_marked = mark_non_boundary([c], TractType.EASEMENT)
        x_marked = mark_non_boundary([c], TractType.EXCEPTION)
        assert EASEMENT_TRACT_NOTE in (e_marked[0].notes or "")
        assert EXCEPTION_TRACT_NOTE in (x_marked[0].notes or "")
        assert non_boundary_marks([e_marked[0], x_marked[0]]) == ["easement", "exception"]
        detail = non_boundary_marks_detail(["easement", "exception"])
        assert "an easement tract and an exception tract" in detail

    def test_roles_need_review_covers_sole_inferred_multi_basis_and_marked_calls(self):
        from mp_models import mark_roles_review, roles_need_review, roles_review_detail

        c = self._call()
        # Sole MAIN with inferred role_basis needs review.
        sole_inferred = Tract(
            label="Parcel", tract_type=TractType.MAIN, role_basis="inferred", calls=[c]
        )
        reasons_sole = roles_need_review([sole_inferred])
        assert len(reasons_sole) == 1
        assert "sole description's parcel role is not established" in reasons_sole[0]

        # Sole EASEMENT with inferred role_basis uses _INFERRED_WHY.
        sole_ease = Tract(
            label="Ease", tract_type=TractType.EASEMENT, role_basis="inferred", calls=[c]
        )
        reasons_ease = roles_need_review([sole_ease])
        assert "easement-grant wording" in reasons_ease[0]

        # Multi-tract where one has role_basis="single" and another has None.
        t_single = Tract(label="T1", tract_type=TractType.MAIN, role_basis="single", calls=[c])
        t_none = Tract(label="T2", tract_type=TractType.ADDITION, role_basis=None, calls=[c])
        reasons_multi = roles_need_review([t_single, t_none])
        assert len(reasons_multi) == 2
        assert "marked the sole description" in reasons_multi[0]
        assert "role basis not recorded" in reasons_multi[1]
        assert "description roles need review:" in roles_review_detail(reasons_multi)

        # Flat calls carrying DESCRIPTION_ROLES_NOTE without tracts still trigger review.
        marked = mark_roles_review([c])
        reasons_flat = roles_need_review([], marked)
        assert len(reasons_flat) == 1
        assert "roles were not established" in reasons_flat[0]
