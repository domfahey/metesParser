"""Deterministic dashboard stages; reading attestations remain separate from math."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from mp_models.dashboard import (
    DashboardBundle,
    DashboardCalculation,
    DashboardCourseGeometry,
    DashboardManifest,
    DashboardResult,
    PreparedDashboard,
)

from mp_verify import analyze_relative, verify_closure
from mp_verify.plot import build_dashboard_plots
from mp_verify.scene import validate_scene

CALCULATOR_VERSION = "dashboard-1.0.2"


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
    denominator = (
        verification.perimeter_ft / verification.misclosure_ft
        if verification.misclosure_ft > 0
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
        misclosure_ft=verification.misclosure_ft,
        misclosure_x_ft=verification.misclosure_x_ft,
        misclosure_y_ft=verification.misclosure_y_ft,
        area_sq_ft=verification.area_sq_ft if area_available else None,
        perimeter_ft=verification.perimeter_ft,
        precision_denominator=denominator,
        warnings=warnings,
    )


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
    plots = build_dashboard_plots(bundle, calculations)
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
        }
    )
    manifest = DashboardManifest(
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
        bundle=bundle, calculations=calculations, manifest=manifest, plots=plots
    )


def validate_prepared_dashboard(prepared: PreparedDashboard) -> PreparedDashboard:
    """Fresh deterministic validation for untrusted prepared payloads."""
    expected = calculate_dashboard(prepared.bundle)
    if (
        prepared.plots != expected.plots
        or prepared.calculations != expected.calculations
        or prepared.manifest.model_dump(exclude={"cache_reused"})
        != expected.manifest.model_dump(exclude={"cache_reused"})
    ):
        raise ValueError("Prepared dashboard results or hashes do not match deterministic inputs")
    return prepared
