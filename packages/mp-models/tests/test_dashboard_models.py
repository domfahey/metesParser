"""Validation and referential-integrity tests for DashboardBundle and dashboard models."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest
from mp_models.dashboard import (
    DashboardBundle,
    DashboardCalculation,
    DashboardCall,
    DashboardDiagnosis,
    DashboardEdit,
    DashboardEvidence,
    DashboardFrame,
    DashboardOccurrence,
    DashboardPage,
    DashboardResult,
)
from mp_models.deed_call import DeedCall
from mp_models.diagnostics import (
    ClosureDiagnosticRequest,
    ClosureDiagnostics,
    DiagnosticCall,
    DiagnosticFrame,
    diagnostic_input_hash,
)
from mp_models.relative import (
    LocalFrame,
    RelativeCourse,
    RelativeDescription,
    RelativeSource,
)
from pydantic import ValidationError

FIXTURE = Path(__file__).parents[2] / "mp-review/tests/fixtures/dashboard-absolute.json"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
PNG_URI = "data:image/png;base64," + base64.b64encode(PNG).decode()
PNG_SHA = hashlib.sha256(PNG).hexdigest()


def _base_bundle() -> dict:
    return json.loads(FIXTURE.read_text())


def _v11_bundle() -> dict:
    data = _base_bundle()
    data["schema_version"] = "1.1"
    data["scenes"] = [
        {"id": "scene-1", "name": "Local", "kind": "local", "units": "international_ft"}
    ]
    data["map_sources"] = [{"id": "src-1", "label": "Context", "sha256": "a" * 64}]
    data["vector_layers"] = [
        {
            "id": "layer-1",
            "label": "Parcel",
            "source_id": "src-1",
            "scene_id": "scene-1",
            "geometry_type": "Polygon",
            "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
        }
    ]
    return data


class TestDashboardLeafModels:
    def test_page_and_evidence_embedded_image_validation(self):
        # Valid embedded PNG with matching SHA256.
        p = DashboardPage(id="p1", document_id="d1", number=1, image=PNG_URI, image_sha256=PNG_SHA)
        assert p.image_sha256 == PNG_SHA
        ev = DashboardEvidence(
            id="e1",
            occurrence_id="o1",
            page_id="p1",
            label="crop",
            image=PNG_URI,
            image_sha256=PNG_SHA,
            bounds_px=(0, 0, 10, 10),
        )
        assert ev.bounds_px == (0, 0, 10, 10)

        # Invalid scheme, invalid base64, mismatched magic bytes, wrong hash, hash without image.
        with pytest.raises(ValidationError, match="PNG, JPEG or WebP data URIs"):
            DashboardPage(id="p1", document_id="d1", number=1, image="https://example.com/a.png")
        with pytest.raises(ValidationError, match="invalid image base64"):
            DashboardPage(id="p1", document_id="d1", number=1, image="data:image/png;base64,A")
        with pytest.raises(ValidationError, match="does not match MIME type"):
            DashboardPage(
                id="p1",
                document_id="d1",
                number=1,
                image="data:image/jpeg;base64," + base64.b64encode(PNG).decode(),
                image_sha256=PNG_SHA,
            )
        with pytest.raises(ValidationError, match="SHA256 missing or incorrect"):
            DashboardPage(id="p1", document_id="d1", number=1, image=PNG_URI, image_sha256="0" * 64)
        with pytest.raises(ValidationError, match="image hash requires an image"):
            DashboardPage(id="p1", document_id="d1", number=1, image_sha256=PNG_SHA)

        # Same hash & crop bounds checks on DashboardEvidence.
        with pytest.raises(ValidationError, match="SHA256 missing or incorrect"):
            DashboardEvidence(
                id="e1",
                occurrence_id="o1",
                page_id="p1",
                label="x",
                image=PNG_URI,
                image_sha256="0" * 64,
            )
        with pytest.raises(ValidationError, match="image hash requires an image"):
            DashboardEvidence(
                id="e1", occurrence_id="o1", page_id="p1", label="x", image_sha256=PNG_SHA
            )
        with pytest.raises(ValidationError, match="crop bounds"):
            DashboardEvidence(
                id="e1", occurrence_id="o1", page_id="p1", label="x", bounds_px=(-1, 0, 10, 10)
            )

    def test_occurrence_call_calculation_edit_result_and_diagnosis_invariants(self):
        # Reviewed occurrence requires read reading_status.
        with pytest.raises(ValidationError, match="read reading_status"):
            DashboardOccurrence(
                id="o1",
                parcel_id="pa1",
                version_label="v1",
                page_ids=("p1",),
                transcript="text",
                reading_status="uncertain",
                source_review_status="reviewed",
            )

        call_obj = DeedCall(
            course=1, direction_text="N", bearing_azimuth_deg_from_north=0.0, distance_ft=10.0
        )
        with pytest.raises(ValidationError, match="require a reading_note"):
            DashboardCall(
                id="c1",
                occurrence_id="o1",
                page_id="p1",
                quote="N 10 ft",
                reading_status="uncertain",
            )
        with pytest.raises(ValidationError, match="quote must not be blank"):
            DashboardCall(
                id="c1",
                occurrence_id="o1",
                page_id="p1",
                quote="   ",
                reading_status="certain",
                call=call_obj,
            )
        with pytest.raises(ValidationError, match="certain reading requires a parsed call"):
            DashboardCall(
                id="c1", occurrence_id="o1", page_id="p1", quote="N 10 ft", reading_status="certain"
            )
        with pytest.raises(ValidationError, match="unknown readings must retain an unknown call"):
            DashboardCall(
                id="c1",
                occurrence_id="o1",
                page_id="p1",
                quote="N 10 ft",
                reading_status="unknown",
                reading_note="smudged",
                call=call_obj,
            )

        # DashboardCalculation method/frame consistency.
        src = RelativeSource(reference="p1", quote="q")
        rel = RelativeDescription(
            frame=LocalFrame(
                name="LocalA", first_azimuth_deg=0.0, origin=(0.0, 0.0), orientation="cw"
            ),
            courses=tuple(
                RelativeCourse(course_id=f"c{i}", distance_ft=10.0, source=src) for i in (1, 2, 3)
            ),
            constraints=(),
        )
        with pytest.raises(ValidationError, match="needs relative input and arbitrary_local"):
            DashboardCalculation(
                id="calc",
                occurrence_id="o1",
                method="relative",
                frame=DashboardFrame(basis="recorded_bearings", name="LocalA"),
                relative=rel,
            )
        with pytest.raises(ValidationError, match="frame name must match"):
            DashboardCalculation(
                id="calc",
                occurrence_id="o1",
                method="relative",
                frame=DashboardFrame(basis="arbitrary_local", name="Other"),
                relative=rel,
            )
        with pytest.raises(ValidationError, match="canonical calculation uses recorded bearings"):
            DashboardCalculation(
                id="calc",
                occurrence_id="o1",
                method="canonical",
                frame=DashboardFrame(basis="arbitrary_local", name="Other"),
            )

        # DashboardEdit must change at least one field.
        with pytest.raises(ValidationError, match="must change a value"):
            DashboardEdit(call_id="c1", rationale="no-op")

        # Relative DashboardResult cannot promote verification status.
        with pytest.raises(ValidationError, match="cannot promote canonical engine status"):
            DashboardResult(
                id="r1",
                occurrence_id="o1",
                method="relative",
                engine_status="checks_passed",
                engine_verified=False,
                verified_export_eligible=False,
                geometry_status="analyzed",
            )

        # DashboardDiagnosis availability mismatch & missing limitations.
        with pytest.raises(ValidationError, match="requires explicit limitations"):
            DashboardDiagnosis(
                calculation_id="c1",
                occurrence_id="o1",
                calculation_input_hash="a" * 64,
                availability="unsupported",
            )
        dcall = DiagnosticCall(call_id="c1", call=call_obj)
        dreq = ClosureDiagnosticRequest(
            request_id="req",
            input_id="inp",
            input_sha256=diagnostic_input_hash([dcall]),
            calls=(dcall,),
            frame=DiagnosticFrame(name="Rec"),
        )
        req_sha = hashlib.sha256(
            json.dumps(dreq.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        diag_base = ClosureDiagnostics(
            request=dreq,
            request_sha256=req_sha,
            input_sha256=dreq.input_sha256,
            availability="unsupported",
        )
        with pytest.raises(ValidationError, match="availability differs from its baseline"):
            DashboardDiagnosis(
                calculation_id="c1",
                occurrence_id="o1",
                calculation_input_hash="a" * 64,
                availability="supported",
                baseline=diag_base,
            )


class TestDashboardBundleReferentialIntegrity:
    def test_document_page_occurrence_call_and_evidence_reference_errors(self):
        # Global ID uniqueness.
        d = _base_bundle()
        d["parcels"][0]["id"] = d["documents"][0]["id"]
        with pytest.raises(ValidationError, match="globally unique"):
            DashboardBundle.model_validate(d)

        # Page references unknown doc, exceeds expected_page_count, duplicate page number.
        d = _base_bundle()
        d["pages"][0]["document_id"] = "missing-doc"
        with pytest.raises(ValidationError, match="unknown document"):
            DashboardBundle.model_validate(d)

        d = _base_bundle()
        d["pages"][0]["number"] = d["documents"][0]["expected_page_count"] + 1
        with pytest.raises(ValidationError, match="exceeds document expected page count"):
            DashboardBundle.model_validate(d)

        d = _base_bundle()
        d["documents"][0]["expected_page_count"] = 2
        dup_page = copy.deepcopy(d["pages"][0])
        dup_page["id"] = "page-dup"
        d["pages"].append(dup_page)
        with pytest.raises(ValidationError, match="duplicate document page number"):
            DashboardBundle.model_validate(d)

        # Occurrence unknown parcel/page, duplicate page_ids, cross-document pages.
        d = _base_bundle()
        d["occurrences"][0]["parcel_id"] = "missing-parcel"
        with pytest.raises(ValidationError, match="unknown parcel or page"):
            DashboardBundle.model_validate(d)

        d = _base_bundle()
        d["occurrences"][0]["page_ids"] = [d["pages"][0]["id"], d["pages"][0]["id"]]
        with pytest.raises(ValidationError, match="page IDs must be unique"):
            DashboardBundle.model_validate(d)

        d = _base_bundle()
        doc2 = copy.deepcopy(d["documents"][0])
        doc2["id"] = "doc-2"
        page2 = copy.deepcopy(d["pages"][0])
        page2["id"] = "page-2"
        page2["document_id"] = "doc-2"
        d["documents"].append(doc2)
        d["pages"].append(page2)
        d["occurrences"][0]["page_ids"] = [d["pages"][0]["id"], "page-2"]
        with pytest.raises(ValidationError, match="belong to one document"):
            DashboardBundle.model_validate(d)

        # Call references cross-occurrence page.
        d = _base_bundle()
        d["calls"][0]["page_id"] = "missing-page"
        with pytest.raises(ValidationError, match="unknown or cross-occurrence page"):
            DashboardBundle.model_validate(d)

        # Evidence references unknown page or unknown/cross-occurrence call.
        d = _base_bundle()
        d["evidence"] = [
            {
                "id": "ev-1",
                "occurrence_id": d["occurrences"][0]["id"],
                "page_id": "missing-page",
                "label": "crop",
            }
        ]
        with pytest.raises(ValidationError, match="unknown or cross-occurrence page"):
            DashboardBundle.model_validate(d)

        d = _base_bundle()
        d["evidence"] = [
            {
                "id": "ev-1",
                "occurrence_id": d["occurrences"][0]["id"],
                "page_id": d["pages"][0]["id"],
                "call_id": "missing-call",
                "label": "crop",
            }
        ]
        with pytest.raises(ValidationError, match="unknown or cross-occurrence call"):
            DashboardBundle.model_validate(d)

    def test_calculation_relative_and_scenario_reference_errors(self):
        # Unknown occurrence in calculation.
        d = _base_bundle()
        d["calculations"][0]["occurrence_id"] = "missing-occ"
        with pytest.raises(ValidationError, match="unknown occurrence"):
            DashboardBundle.model_validate(d)

        # Duplicate course number within occurrence.
        d = _base_bundle()
        d["calls"][1]["call"]["course"] = d["calls"][0]["call"]["course"]
        with pytest.raises(ValidationError, match="course numbers must be unique"):
            DashboardBundle.model_validate(d)

        # Build a valid relative calculation bundle to mutate each relative invariant.
        def _rel_bundle() -> dict:
            b = _base_bundle()
            occ = b["occurrences"][0]
            page_id = occ["page_ids"][0]
            occ["transcript"] = " ".join(c["quote"] for c in b["calls"]) + " right angle"
            b["calculations"][0] = {
                "id": "calc-rel",
                "occurrence_id": occ["id"],
                "method": "relative",
                "frame": {"basis": "arbitrary_local", "name": "Local"},
                "relative": {
                    "frame": {
                        "name": "Local",
                        "first_azimuth_deg": 0.0,
                        "origin": [0.0, 0.0],
                        "orientation": "cw",
                    },
                    "courses": [
                        {
                            "course_id": c["id"],
                            "distance_ft": c["call"]["distance_ft"],
                            "recorded_bearing_azimuth_deg_from_north": c["call"][
                                "bearing_azimuth_deg_from_north"
                            ],
                            "source": {"reference": c["id"], "quote": c["quote"]},
                        }
                        for c in b["calls"]
                    ],
                    "constraints": [
                        {
                            "constraint_id": "k1",
                            "kind": "interior",
                            "from_course": b["calls"][0]["id"],
                            "to_course": b["calls"][1]["id"],
                            "angle_deg": 90.0,
                            "source": {"reference": page_id, "quote": "right angle"},
                        }
                    ],
                },
            }
            b["scenarios"] = []
            return b

        validated = DashboardBundle.model_validate(_rel_bundle())
        assert validated.calculations[0].method == "relative"
        assert validated.calculations[0].relative is not None
        assert len(validated.calculations[0].relative.courses) == len(validated.calls)

        b = _rel_bundle()
        b["calculations"][0]["relative"]["courses"] = b["calculations"][0]["relative"]["courses"][
            :-1
        ]
        with pytest.raises(ValidationError, match="match occurrence call IDs in order"):
            DashboardBundle.model_validate(b)

        b = _rel_bundle()
        b["calculations"][0]["relative"]["constraints"][0]["source"]["reference"] = "missing-ref"
        with pytest.raises(ValidationError, match="unknown or cross-occurrence source"):
            DashboardBundle.model_validate(b)

        b = _rel_bundle()
        b["calculations"][0]["relative"]["constraints"][0]["source"]["quote"] = "not in transcript"
        with pytest.raises(ValidationError, match="constraint quote is not supported"):
            DashboardBundle.model_validate(b)

        b = _rel_bundle()
        b["calculations"][0]["relative"]["courses"][0]["source"]["reference"] = b["calls"][1]["id"]
        with pytest.raises(ValidationError, match="reference its own call or page"):
            DashboardBundle.model_validate(b)

        b = _rel_bundle()
        b["calculations"][0]["relative"]["courses"][0]["source"]["quote"] = "invented wording"
        with pytest.raises(ValidationError, match="course quote is not supported"):
            DashboardBundle.model_validate(b)

        b = _rel_bundle()
        b["calls"][0]["call"]["is_tie_in"] = True
        with pytest.raises(ValidationError, match="known straight boundary call distances"):
            DashboardBundle.model_validate(b)

        b = _rel_bundle()
        b["calculations"][0]["relative"]["courses"][0]["distance_ft"] += 1.0
        with pytest.raises(ValidationError, match="preserve recorded distances and bearings"):
            DashboardBundle.model_validate(b)

        # Scenario validation errors: unknown calc, unknown/cross call, duplicate call edit, unknown/cross evidence.
        d = _base_bundle()
        d["scenarios"] = [
            {
                "id": "sc1",
                "label": "S",
                "calculation_id": "missing-calc",
                "edits": [{"call_id": d["calls"][0]["id"], "distance_ft": 50.0, "rationale": "r"}],
            }
        ]
        with pytest.raises(ValidationError, match="unknown calculation"):
            DashboardBundle.model_validate(d)

        calc_id = d["calculations"][0]["id"]
        d["scenarios"][0]["calculation_id"] = calc_id
        d["scenarios"][0]["edits"][0]["call_id"] = "missing-call"
        with pytest.raises(ValidationError, match="unknown or cross-occurrence call"):
            DashboardBundle.model_validate(d)

        d["scenarios"][0]["edits"] = [
            {"call_id": d["calls"][0]["id"], "distance_ft": 50.0, "rationale": "r"},
            {"call_id": d["calls"][0]["id"], "distance_ft": 60.0, "rationale": "r2"},
        ]
        with pytest.raises(ValidationError, match="call edits must be unique"):
            DashboardBundle.model_validate(d)

        d["scenarios"][0]["edits"] = [
            {
                "call_id": d["calls"][0]["id"],
                "distance_ft": 50.0,
                "rationale": "r",
                "evidence_ids": ["missing-ev"],
            }
        ]
        with pytest.raises(ValidationError, match="unknown evidence"):
            DashboardBundle.model_validate(d)

        # Cross-occurrence evidence on scenario edit.
        other_occ = copy.deepcopy(d["occurrences"][0])
        other_occ["id"] = "occ-other"
        d["occurrences"].append(other_occ)
        d["evidence"] = [
            {
                "id": "ev-other",
                "occurrence_id": "occ-other",
                "page_id": d["pages"][0]["id"],
                "label": "other",
            }
        ]
        d["scenarios"][0]["edits"][0]["evidence_ids"] = ["ev-other"]
        with pytest.raises(ValidationError, match="cross-occurrence evidence"):
            DashboardBundle.model_validate(d)

    def test_v11_placement_description_comparison_and_plot_view_reference_errors(self):
        d = _v11_bundle()
        calc_id = d["calculations"][0]["id"]

        # Placement referencing unknown scene/calc and unknown/cross-calc scenario.
        d["placements"] = [
            {
                "id": "pl-1",
                "calculation_id": "missing-calc",
                "geometry_hash": "a" * 64,
                "scene_id": "scene-1",
                "rationale": "r",
            }
        ]
        with pytest.raises(ValidationError, match="unknown calculation or scene"):
            DashboardBundle.model_validate(d)

        d["placements"][0]["calculation_id"] = calc_id
        d["placements"][0].update(
            scenario_id="missing-sc",
            baseline_geometry_hash="b" * 64,
            baseline_placement_id="pl-0",
        )
        with pytest.raises(ValidationError, match="unknown or cross-occurrence scenario"):
            DashboardBundle.model_validate(d)

        # Description comparison specs errors.
        d = _v11_bundle()
        calc2 = copy.deepcopy(d["calculations"][0])
        calc2["id"] = "calc-2"
        d["calculations"].append(calc2)
        d["placements"] = [
            {
                "id": "pl-1",
                "calculation_id": calc_id,
                "geometry_hash": "a" * 64,
                "scene_id": "scene-1",
                "rationale": "r",
            }
        ]
        tol = {
            "length": 0.5,
            "displacement": 0.5,
            "position": 0.5,
            "linear_unit": "international_ft",
            "bearing_deg": 0.5,
            "source_references": ["review"],
        }
        basis = {"label": "Grid", "identity": "NAD83", "source_references": ["p1"]}
        spec = {
            "id": "dc-1",
            "left_calculation_id": calc_id,
            "right_calculation_id": calc_id,
            "left_bearing_basis": basis,
            "right_bearing_basis": basis,
            "tolerances": tol,
        }
        d["description_comparison_specs"] = [spec]
        with pytest.raises(ValidationError, match="distinct calculations"):
            DashboardBundle.model_validate(d)

        spec["right_calculation_id"] = "calc-2"
        spec["scene_id"] = "missing-scene"
        with pytest.raises(ValidationError, match="unknown scene"):
            DashboardBundle.model_validate(d)

        spec["scene_id"] = "scene-1"
        pair = {
            "id": "pair-1",
            "left": {"call_ids": [d["calls"][0]["id"]], "direction": "forward"},
            "right": {"call_ids": [d["calls"][0]["id"]], "direction": "forward"},
        }
        spec["pairs"] = [pair, copy.deepcopy(pair)]
        with pytest.raises(ValidationError, match="pair IDs must be unique"):
            DashboardBundle.model_validate(d)

        spec["pairs"] = [pair]
        spec["right_placement_id"] = "pl-1"  # belongs to calc_id, not calc-2
        with pytest.raises(ValidationError, match="unknown or cross-calculation placement"):
            DashboardBundle.model_validate(d)

        # plot_view referencing unknown layers in visible_layer_ids and opacity.
        d = _v11_bundle()
        d["plot_view"] = {"visible_layer_ids": ["missing-layer"]}
        with pytest.raises(ValidationError, match="view references unknown layer"):
            DashboardBundle.model_validate(d)

        d["plot_view"] = {"opacity": [["missing-layer", 0.5]]}
        with pytest.raises(ValidationError, match="view opacity references unknown layer"):
            DashboardBundle.model_validate(d)
