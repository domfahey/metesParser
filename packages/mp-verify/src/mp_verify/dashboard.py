"""Deterministic dashboard stages; reading attestations remain separate from math."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from mp_models.comparison import ComparisonDescription, ComparisonRequest
from mp_models.dashboard import (
    DashboardBundle,
    DashboardCalculation,
    DashboardCourseGeometry,
    DashboardDescriptionComparison,
    DashboardDescriptionComparisonSpec,
    DashboardDiagnosis,
    DashboardManifest,
    DashboardResult,
    PreparedDashboard,
)
from mp_models.diagnostics import (
    ClosureDiagnosticRequest,
    DiagnosticCall,
    DiagnosticFrame,
    DiagnosticSourceRef,
    diagnostic_input_hash,
)
from mp_models.plot import DashboardPlots
from mp_models.plot_request import PlotCall, PlotRequest

from mp_verify import analyze_relative, verify_closure
from mp_verify.comparison import COMPARISON_VERSION, compare_descriptions
from mp_verify.diagnostics import diagnose_closure
from mp_verify.plot import build_dashboard_plots, prepare_plot
from mp_verify.scene import validate_scene

CALCULATOR_VERSION = "dashboard-1.1.0"
DIAGNOSTICS_VERSION = "closure-diagnostics-2"


def _json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _source_data(bundle: DashboardBundle) -> dict[str, Any]:
    data = bundle.model_dump(mode="json")
    return {
        key: data[key]
        for key in (
            "schema_version",
            "documents",
            "pages",
            "parcels",
            "occurrences",
            "calls",
            "evidence",
        )
    }


def _source_complete(bundle: DashboardBundle) -> bool:
    return (
        all(
            o.source_review_status == "reviewed" and o.reading_status == "read"
            for o in bundle.occurrences
        )
        and all(any(c.occurrence_id == o.id for c in bundle.calls) for o in bundle.occurrences)
        and all(c.reading_status == "certain" for c in bundle.calls)
        and all(p.reading_status == "read" for p in bundle.pages)
        and all(
            {p.number for p in bundle.pages if p.document_id == doc.id}
            == set(range(1, doc.expected_page_count + 1))
            for doc in bundle.documents
        )
    )


def map_stage(bundle: DashboardBundle) -> dict[str, Any]:
    """Keep map evidence outside the deed reading ledger and calculation hashes."""
    return {
        name: [item.model_dump(mode="json") for item in getattr(bundle, name, ())]
        for name in ("scenes", "map_sources", "vector_layers", "raster_layers")
    }


def _calculate(bundle: DashboardBundle, spec: DashboardCalculation) -> DashboardResult:
    records = tuple(c for c in bundle.calls if c.occurrence_id == spec.occurrence_id)
    occurrence = next(o for o in bundle.occurrences if o.id == spec.occurrence_id)
    complete = (
        occurrence.source_review_status == "reviewed"
        and occurrence.reading_status == "read"
        and bool(records)
        and all(c.reading_status == "certain" for c in records)
        and all(
            next(p for p in bundle.pages if p.id == page).reading_status == "read"
            for page in occurrence.page_ids
        )
    )
    base: dict[str, Any] = {
        "id": spec.id,
        "occurrence_id": spec.occurrence_id,
        "method": spec.method,
        "engine_status": "needs_review",
        "engine_verified": False,
        "verified_export_eligible": False,
        "source_review_complete": complete,
    }
    if spec.relative is not None:
        analysis = analyze_relative(spec.relative)
        result = analysis.model_dump(mode="json")
        fields = {
            key: result[key]
            for key in (
                "misclosure_ft",
                "misclosure_x_ft",
                "misclosure_y_ft",
                "area_sq_ft",
                "perimeter_ft",
                "precision_denominator",
                "stated_angle_sum_deg",
                "expected_angle_sum_deg",
                "computed_closing_angle_deg",
            )
        }
        return DashboardResult(
            **base,
            **fields,
            geometry_status=analysis.status,
            points=tuple(analysis.points),
            courses=tuple(
                DashboardCourseGeometry(
                    call_id=c.course_id,
                    local_azimuth_deg=c.local_azimuth_deg,
                    delta_x_ft=c.delta_x_ft,
                    delta_y_ft=c.delta_y_ft,
                )
                for c in analysis.courses
            ),
            warnings=tuple(issue.message for issue in analysis.issues)
            + (
                "Local geometry does not establish recorded bearings or authorize verified export.",
                "Area uses an implicit closing segment; open-traverse area is provisional.",
            ),
        )
    if not records or any(c.call is None for c in records):
        return DashboardResult(
            **base,
            geometry_status="blocked",
            warnings=("Unknown source calls block canonical calculation.",),
        )
    calls = [r.call for r in records if r.call is not None]
    verification = verify_closure(calls, stated_area_sq_ft=spec.stated_area_sq_ft or 0.0)
    # The existing engine can compute partial traverses. Never plot them as a full boundary.
    boundary = [
        r
        for r in records
        if r.call is not None and not r.call.is_tie_in and not r.call.is_exception
    ]
    known = bool(boundary) and all(
        r.call is not None and r.call.bearing_azimuth_deg_from_north is not None for r in boundary
    )
    engine_verified = verification.is_fully_verified()
    base.update(
        engine_status="checks_passed" if engine_verified else "needs_review",
        engine_verified=engine_verified,
        verified_export_eligible=engine_verified and complete and _source_complete(bundle),
        checks=tuple(verification.checks),
    )
    warnings = tuple(verification.warnings)
    if not complete:
        warnings += (
            "Source review incomplete or readings uncertain; numerical results remain conditional.",
        )
    if not known:
        return DashboardResult(
            **base,
            geometry_status="blocked",
            warnings=warnings + ("Incomplete recorded bearings block full boundary geometry.",),
        )
    if not verification.misclosure_available or len(verification.points) != len(boundary) + 1:
        # A broken chain yields fewer vertices than courses; never zip misaligned lists.
        return DashboardResult(
            **base,
            geometry_status="unresolved",
            warnings=warnings
            + ("A course could not be positioned; full boundary geometry is not determined.",),
        )
    geometry = []
    for record, a, b in zip(boundary, verification.points, verification.points[1:], strict=False):
        assert record.call is not None
        assert record.call.bearing_azimuth_deg_from_north is not None
        geometry.append(
            DashboardCourseGeometry(
                call_id=record.id,
                local_azimuth_deg=record.call.bearing_azimuth_deg_from_north,
                delta_x_ft=b.x - a.x,
                delta_y_ft=b.y - a.y,
            )
        )
    courses = tuple(geometry)
    perimeter_ft = verification.perimeter_ft if verification.perimeter_available else None
    misclosure_known = verification.misclosure_available
    denominator = (
        perimeter_ft / verification.misclosure_ft
        if perimeter_ft is not None and misclosure_known and verification.misclosure_ft > 0
        else None
    )
    if denominator is not None and not math.isfinite(denominator):
        denominator = None
    area_available = all(
        check.inputs.get("area_available") is not False
        for check in verification.checks
        if check.name == "area_reasonableness"
    )
    return DashboardResult(
        **base,
        geometry_status="analyzed",
        points=tuple(verification.points),
        courses=courses,
        misclosure_ft=verification.misclosure_ft if misclosure_known else None,
        misclosure_x_ft=verification.misclosure_x_ft if misclosure_known else None,
        misclosure_y_ft=verification.misclosure_y_ft if misclosure_known else None,
        area_sq_ft=verification.area_sq_ft if area_available else None,
        perimeter_ft=perimeter_ft,
        precision_denominator=denominator,
        warnings=warnings,
    )


def diagnostic_request_from_dashboard(
    bundle: DashboardBundle, spec: DashboardCalculation
) -> ClosureDiagnosticRequest | None:
    """Adapt exact canonical calls and source links for standalone-identical math.

    Unknown calls and relative constraints cannot become fabricated straight calls.
    """
    if spec.method != "canonical":
        return None
    records = tuple(c for c in bundle.calls if c.occurrence_id == spec.occurrence_id)
    if not records or any(c.call is None for c in records):
        return None
    calls = []
    for record in records:
        assert record.call is not None
        page = next(p for p in bundle.pages if p.id == record.page_id)
        document = next(d for d in bundle.documents if d.id == page.document_id)
        evidence = next((e for e in bundle.evidence if e.call_id == record.id), None)
        calls.append(
            DiagnosticCall(
                call_id=record.id,
                call=record.call,
                source_refs=(
                    DiagnosticSourceRef(
                        source_id=document.id,
                        source_sha256=document.sha256,
                        occurrence_id=record.occurrence_id,
                        page=page.number,
                        page_id=page.id,
                        crop_id=evidence.id if evidence is not None else None,
                        quote=record.quote,
                        uncertainty=record.reading_note
                        if record.reading_status != "certain"
                        else None,
                    ),
                ),
            )
        )
    return ClosureDiagnosticRequest(
        request_id=f"dashboard:{spec.id}",
        input_id=spec.id,
        input_sha256=diagnostic_input_hash(calls),
        calls=tuple(calls),
        frame=DiagnosticFrame.model_validate(spec.frame.model_dump(mode="json")),
    )


def _diagnose_dashboard(bundle: DashboardBundle, input_hash: str) -> tuple[DashboardDiagnosis, ...]:
    diagnoses = []
    for spec in bundle.calculations:
        request = diagnostic_request_from_dashboard(bundle, spec)
        baseline = diagnose_closure(request) if request is not None else None
        availability = (
            baseline.availability
            if baseline is not None
            else "unsupported"
            if spec.method == "relative"
            else "incomplete"
        )
        limitations = (
            baseline.limitations
            if baseline is not None
            else ("Relative constraints are unsupported by canonical straight-bearing diagnosis.",)
            if spec.method == "relative"
            else ("Unknown source calls block diagnosis; no partial residual was manufactured.",)
        )
        diagnoses.append(
            DashboardDiagnosis(
                calculation_id=spec.id,
                occurrence_id=spec.occurrence_id,
                calculation_input_hash=input_hash,
                availability=availability,
                baseline=baseline,
                limitations=limitations,
            )
        )
    return tuple(diagnoses)


def _comparison_request_from_dashboard(
    bundle: DashboardBundle,
    spec: DashboardDescriptionComparisonSpec,
    plots: DashboardPlots,
) -> tuple[ComparisonRequest, tuple[tuple[str, str, str], ...]]:
    """Adapt immutable source-owned calls, retaining validated placement lineage.

    Dashboard and standalone geometry have different provenance hash domains. A
    placement is rebound only after original validation and exact primitive/chain
    equality; both geometry identities remain explicit in placement_bindings.
    """
    calculations = {c.id: c for c in bundle.calculations}
    occurrences = {o.id: o for o in bundle.occurrences}
    pages = {p.id: p for p in bundle.pages}
    documents = {d.id: d for d in bundle.documents}
    geometries = {g.calculation_id: g for g in plots.geometries}
    placements = {p.id: p for p in plots.placements}
    descriptions = []
    bindings = []
    for calculation_id, basis, placement_id in (
        (spec.left_calculation_id, spec.left_bearing_basis, spec.left_placement_id),
        (spec.right_calculation_id, spec.right_bearing_basis, spec.right_placement_id),
    ):
        calculation = calculations[calculation_id]
        occurrence = occurrences[calculation.occurrence_id]
        records = tuple(c for c in bundle.calls if c.occurrence_id == occurrence.id)
        request = PlotRequest(
            title=occurrence.version_label or occurrence.id,
            calculation_id=calculation.id,
            foot_definition=calculation.frame.foot_definition,
            relative=calculation.relative,
            calls=tuple(
                PlotCall(
                    id=c.id,
                    call=c.call,
                    occurrence_id=c.occurrence_id,
                    page_id=c.page_id,
                    quote=c.quote,
                    source_reference=f"{documents[pages[c.page_id].document_id].source_name}: page {pages[c.page_id].number}; occurrence {occurrence.id}",
                )
                for c in records
            ),
        )
        placement = None
        if placement_id is not None:
            original = placements[placement_id]
            native = prepare_plot(request).geometry
            dashboard = geometries[calculation_id]
            if (native.primitives, native.chains, native.unresolved) != (
                dashboard.primitives,
                dashboard.chains,
                dashboard.unresolved,
            ):
                raise ValueError("dashboard and standalone comparison geometry differ")
            # Original binding was validated by build_dashboard_plots immediately
            # before this adapter. Rebind only the identical primitive geometry.
            placement = original.model_copy(update={"geometry_hash": native.geometry_hash})
            bindings.append((original.id, original.geometry_hash, native.geometry_hash))
        descriptions.append(
            ComparisonDescription(
                id=calculation.id, plot=request, bearing_basis=basis, placement=placement
            )
        )
    scene = next((scene for scene in bundle.scenes if scene.id == spec.scene_id), None)
    return ComparisonRequest(
        left=descriptions[0],
        right=descriptions[1],
        pairs=spec.pairs,
        tolerances=spec.tolerances,
        right_to_left_transform=spec.right_to_left_transform,
        scene=scene,
    ), tuple(bindings)


def _compare_dashboard(
    bundle: DashboardBundle, plots: DashboardPlots, input_hash: str
) -> tuple[DashboardDescriptionComparison, ...]:
    results = []
    for spec in bundle.description_comparison_specs:
        request, bindings = _comparison_request_from_dashboard(bundle, spec, plots)
        results.append(
            DashboardDescriptionComparison(
                id=spec.id,
                left_calculation_id=spec.left_calculation_id,
                right_calculation_id=spec.right_calculation_id,
                left_occurrence_id=next(
                    c.occurrence_id for c in bundle.calculations if c.id == spec.left_calculation_id
                ),
                right_occurrence_id=next(
                    c.occurrence_id
                    for c in bundle.calculations
                    if c.id == spec.right_calculation_id
                ),
                calculation_input_hash=input_hash,
                request=request,
                comparison=compare_descriptions(request),
                placement_bindings=bindings,
            )
        )
    return tuple(results)


def calculate_dashboard(bundle: DashboardBundle) -> PreparedDashboard:
    """Fresh deterministic calculation with no caller-supplied engine results."""
    bundle = DashboardBundle.model_validate(bundle.model_dump(mode="json"))
    for scene in bundle.scenes:
        validate_scene(scene)
    source = _source_data(bundle)
    source_hash = _hash(source)
    input_hash = _hash(
        {
            "source_review_hash": source_hash,
            "calculations": [c.model_dump(mode="json") for c in bundle.calculations],
            "calculator_version": CALCULATOR_VERSION,
        }
    )
    calculations = tuple(_calculate(bundle, spec) for spec in bundle.calculations)
    diagnostics = _diagnose_dashboard(bundle, input_hash)
    plots = build_dashboard_plots(bundle, calculations)
    description_comparisons = _compare_dashboard(bundle, plots, input_hash)
    plot_data = [g.model_dump(mode="json") for g in plots.geometries]
    maps = map_stage(bundle)
    placement_data = {
        "placements": [p.model_dump(mode="json") for p in plots.placements],
        "comparisons": [c.model_dump(mode="json") for c in plots.comparisons],
    }
    plot_input_hash = _hash({"calculation_input": input_hash, "builder": plots.builder_version})
    plot_output_hash = _hash(plot_data)
    map_input_hash = _hash(maps)
    placement_input_hash = _hash(
        {
            "geometry": plot_output_hash,
            "maps": map_input_hash,
            "placements": [p.model_dump(mode="json") for p in bundle.placements],
            "comparison_specs": [s.model_dump(mode="json") for s in bundle.comparison_specs],
            "builder": plots.builder_version,
        }
    )
    placement_output_hash = _hash(placement_data)
    presentation_hash = _hash(
        {
            "title": bundle.title,
            "presentation": bundle.presentation.model_dump(mode="json"),
            "scenarios": [s.model_dump(mode="json") for s in bundle.scenarios],
            "plot_view": bundle.plot_view.model_dump(mode="json") if bundle.plot_view else None,
            "plot_output_hash": plot_output_hash,
            "map_output_hash": map_input_hash,
            "placement_output_hash": placement_output_hash,
            "description_comparisons": [c.model_dump(mode="json") for c in description_comparisons],
        }
    )
    manifest = DashboardManifest(
        description_comparisons_input_hash=_hash(
            {
                "calculation_input_hash": input_hash,
                "specs": [s.model_dump(mode="json") for s in bundle.description_comparison_specs],
                "requests": [c.request.model_dump(mode="json") for c in description_comparisons],
                "placement_bindings": [c.placement_bindings for c in description_comparisons],
                "algorithm": COMPARISON_VERSION,
            }
        ),
        description_comparisons_output_hash=_hash(
            [c.model_dump(mode="json") for c in description_comparisons]
        ),
        diagnostics_input_hash=_hash(
            {"calculation_input_hash": input_hash, "algorithm": DIAGNOSTICS_VERSION}
        ),
        diagnostics_output_hash=_hash([d.model_dump(mode="json") for d in diagnostics]),
        calculator_version=CALCULATOR_VERSION,
        source_review_hash=source_hash,
        calculation_input_hash=input_hash,
        calculation_output_hash=_hash([r.model_dump(mode="json") for r in calculations]),
        presentation_hash=presentation_hash,
        source_review_complete=_source_complete(bundle),
        cache_reused=False,
        plot_input_hash=plot_input_hash,
        plot_output_hash=plot_output_hash,
        map_input_hash=map_input_hash,
        map_output_hash=map_input_hash,
        placement_input_hash=placement_input_hash,
        placement_output_hash=placement_output_hash,
    )
    return PreparedDashboard(
        bundle=bundle,
        calculations=calculations,
        manifest=manifest,
        plots=plots,
        diagnostics=diagnostics,
        description_comparisons=description_comparisons,
    )


def validate_prepared_dashboard(prepared: PreparedDashboard) -> PreparedDashboard:
    """Fresh deterministic validation for untrusted prepared payloads."""
    expected = calculate_dashboard(prepared.bundle)
    if (
        prepared.plots != expected.plots
        or prepared.diagnostics != expected.diagnostics
        or prepared.description_comparisons != expected.description_comparisons
        or prepared.calculations != expected.calculations
        or prepared.manifest.model_dump(exclude={"cache_reused"})
        != expected.manifest.model_dump(exclude={"cache_reused"})
    ):
        raise ValueError("Prepared dashboard results or hashes do not match deterministic inputs")
    return prepared
