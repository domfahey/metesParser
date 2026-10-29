"""Pure source-linked plot construction, separate from verification and export."""

from __future__ import annotations

import hashlib
import json
import math
from typing import TYPE_CHECKING, TypedDict

from mp_bearing import (  # type: ignore[import-untyped]
    bearing_to_azimuth,
    calculate_curve_properties,
    calculate_deltas,
)
from mp_models.plot import (
    XY,
    DashboardPlots,
    LinearUnit,
    PlotComparison,
    PlotGeometry,
    PlotPlacement,
    PlotPrimitive,
    PlotResidual,
    PlotScene,
    PlotUnresolved,
    PointCorrespondence,
)
from mp_models.plot_request import PlotCall, PlotRequest, PreparedPlot

if TYPE_CHECKING:
    from mp_models.dashboard import DashboardBundle, DashboardCalculation, DashboardResult
    from mp_models.deed_call import DeedCall

PLOT_BUILDER_VERSION = "plot-1.0.1"


class _Source(TypedDict):
    call_id: str
    occurrence_id: str | None
    page_id: str | None


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _finite(point: XY) -> XY:
    if not all(math.isfinite(v) for v in point):
        raise ValueError("nonfinite plot arithmetic")
    return point


# Deeds state angles to whole arcseconds (+/-0.5" each for tangent, chord and
# delta, i.e. up to ~1.25" combined); 1.5" absorbs that rounding while
# arcminute-scale disagreement remains rejected.
TANGENT_CHORD_TOLERANCE_DEG = 1.5 / 3600


def _arc(call: DeedCall, start: XY, source: _Source) -> PlotPrimitive:
    if call.radius_ft is None or call.curve_dir is None:
        raise ValueError("curve radius and direction unresolved")
    props = calculate_curve_properties(
        call.radius_ft, delta_deg=call.delta_deg, arc_length_ft=call.arc_length_ft
    )
    sweep = props["delta_deg"]
    if sweep <= 0 or sweep > 360:
        raise ValueError("curve sweep unresolved or unsupported")
    # Check every redundant supplied element before drawing an arc.
    for field in ("delta_deg", "arc_length_ft", "chord_length_ft"):
        supplied = getattr(call, field)
        if supplied is not None and not math.isclose(
            supplied, props[field], rel_tol=1e-6, abs_tol=0.01
        ):
            raise ValueError(f"inconsistent curve element: {field}")
    sign = 1 if call.curve_dir == "right" else -1
    if call.chord_bearing is not None:
        chord = bearing_to_azimuth(call.chord_bearing)
        if chord is None:
            raise ValueError("curve chord orientation unresolved")
        tangent = (chord - sign * sweep / 2) % 360
        if call.bearing_azimuth_deg_from_north is not None and not call.non_tangent:
            residual = (tangent - call.bearing_azimuth_deg_from_north + 180) % 360 - 180
            if abs(residual) > TANGENT_CHORD_TOLERANCE_DEG:
                raise ValueError("inconsistent tangent and chord angular evidence")
    elif call.bearing_azimuth_deg_from_north is not None and not call.non_tangent:
        tangent = call.bearing_azimuth_deg_from_north
    else:
        raise ValueError("curve starting orientation unresolved")
    dx, dy = calculate_deltas(tangent + sign * 90, call.radius_ft)
    center = _finite((start[0] + dx, start[1] + dy))
    dx, dy = calculate_deltas(tangent + sign * sweep / 2, props["chord_length_ft"])
    end = _finite((start[0] + dx, start[1] + dy))
    return PlotPrimitive(
        kind="arc",
        **source,
        start=start,
        end=end,
        center=center,
        radius_ft=call.radius_ft,
        sweep_deg=sweep,
        curve_dir=call.curve_dir,
        start_tangent_deg=tangent,
        length_ft=props["arc_length_ft"],
    )


def _build_geometry(
    records: tuple[PlotCall, ...],
    *,
    calculation_id: str,
    occurrence_id: str | None,
    calculation_data: object,
    record_data: list[object],
    origin: XY = (0.0, 0.0),
    relative: dict[str, float] | None = None,
    area_sq_ft: float | None = None,
    analytic_area: bool = False,
    require_representable: bool = False,
) -> PlotGeometry:
    """Shared source-linked line/arc prefix builder for dashboards and standalone plots."""
    primitives = []
    unresolved = []
    reasons = []
    current = origin
    stopped = False
    for record in records:
        call = record.call
        if call is not None and call.is_tie_in:
            reasons.append(f"{record.id}: tie-in excluded from boundary")
            continue
        reason = None
        if stopped:
            reason = "unpositioned after unresolved displacement"
        elif call is None:
            reason = "unknown source call"
        elif call.curve_type == "spiral":
            reason = "spiral geometry unsupported; no line or circular arc assumed"
        elif call.is_exception or call.is_meander:
            reason = "exception/meander connectivity unsupported"
        elif relative is not None and record.id not in relative:
            reason = "relative constraints unresolved or inconsistent"
        source: _Source = {
            "call_id": record.id,
            "occurrence_id": record.occurrence_id,
            "page_id": record.page_id,
        }
        if reason is None and call is not None:
            try:
                if call.is_curve():
                    primitive = _arc(call, current, source)
                else:
                    bearing = (
                        relative[record.id]
                        if relative is not None and record.id in relative
                        else call.bearing_azimuth_deg_from_north
                    )
                    if bearing is None or call.is_indefinite:
                        raise ValueError(
                            "incomplete bearing - cardinal only or unresolved orientation"
                        )
                    dx, dy = calculate_deltas(bearing, call.distance_ft)
                    end = _finite((current[0] + dx, current[1] + dy))
                    primitive = PlotPrimitive(
                        kind="line", **source, start=current, end=end, length_ft=call.distance_ft
                    )
                if require_representable:
                    expected = primitive.length_ft
                    if primitive.kind == "arc":
                        assert primitive.radius_ft is not None and primitive.sweep_deg is not None
                        expected = (
                            2
                            * primitive.radius_ft
                            * abs(math.sin(math.radians(primitive.sweep_deg) / 2))
                        )
                    actual = math.hypot(
                        primitive.end[0] - current[0], primitive.end[1] - current[1]
                    )
                    if abs(actual - expected) > min(1e-6, primitive.length_ft * 1e-6):
                        raise ValueError("plot coordinates lose displacement precision")
                primitives.append(primitive)
                current = primitive.end
            except (ValueError, OverflowError) as exc:
                reason = str(exc)
        if reason is not None:
            stopped = True
            unresolved.append(PlotUnresolved(call_id=record.id, reason=reason))
    complete = bool(primitives) and not unresolved
    content = {
        "builder_version": PLOT_BUILDER_VERSION,
        "calculation": calculation_data,
        "calls": record_data,
        "primitives": [p.model_dump(mode="json") for p in primitives],
        "unresolved": [u.model_dump(mode="json") for u in unresolved],
    }
    return PlotGeometry(
        id=calculation_id,
        calculation_id=calculation_id,
        occurrence_id=occurrence_id,
        frame_id=f"{calculation_id}:native",
        geometry_hash=_hash(content),
        primitives=tuple(primitives),
        unresolved=tuple(unresolved),
        chains=(tuple(p.call_id for p in primitives),) if primitives else (),
        completeness="complete" if complete else "partial" if primitives else "unresolved",
        reasons=tuple(reasons),
        misclosure_ft=math.hypot(current[0] - origin[0], current[1] - origin[1])
        if complete
        else None,
        area_sq_ft=(_analytic_area(tuple(primitives), origin) if analytic_area else area_sq_ft)
        if complete
        else None,
        perimeter_ft=sum(p.length_ft for p in primitives) if complete else None,
    )


def _analytic_area(primitives: tuple[PlotPrimitive, ...], origin: XY) -> float:
    # Translate before products; include the implicit final-to-origin segment.
    signed = 0.0
    for primitive in primitives:
        ax, ay = primitive.start[0] - origin[0], primitive.start[1] - origin[1]
        bx, by = primitive.end[0] - origin[0], primitive.end[1] - origin[1]
        signed += (ax * by - ay * bx) / 2
        if primitive.kind == "arc":
            assert primitive.radius_ft is not None and primitive.sweep_deg is not None
            theta = math.radians(primitive.sweep_deg)
            sign = 1 if primitive.curve_dir == "left" else -1
            signed += sign * primitive.radius_ft**2 * (theta - math.sin(theta)) / 2
    if not math.isfinite(signed):
        raise ValueError("nonfinite plot area arithmetic")
    return abs(signed)


def _geometry(
    bundle: DashboardBundle, spec: DashboardCalculation, result: DashboardResult | None
) -> PlotGeometry:
    records = tuple(c for c in bundle.calls if c.occurrence_id == spec.occurrence_id)
    return _build_geometry(
        tuple(
            PlotCall(id=r.id, call=r.call, occurrence_id=r.occurrence_id, page_id=r.page_id)
            for r in records
        ),
        calculation_id=spec.id,
        occurrence_id=spec.occurrence_id,
        calculation_data=spec.model_dump(mode="json"),
        record_data=[r.model_dump(mode="json") for r in records],
        origin=spec.relative.frame.origin if spec.relative is not None else (0.0, 0.0),
        relative=(
            {c.call_id: c.local_azimuth_deg for c in result.courses}
            if result and result.geometry_status == "analyzed"
            else {}
        )
        if spec.method == "relative"
        else None,
        area_sq_ft=result.area_sq_ft if result else None,
    )


def prepare_plot(request: PlotRequest) -> PreparedPlot:
    """Revalidate supplied calls and derive advisory local geometry, with no source claims."""
    from .relative import analyze_relative

    request = PlotRequest.model_validate(request.model_dump(mode="json"))
    relative = None
    if request.relative is not None:
        result = analyze_relative(request.relative)
        headings = {c.course_id: c.local_azimuth_deg for c in result.courses}
        relative = {
            record.id: headings[course.course_id]
            for record, course in zip(request.calls, request.relative.courses, strict=True)
            if result.status == "analyzed" and course.course_id in headings
        }
    geometry = _build_geometry(
        request.calls,
        calculation_id=request.calculation_id,
        occurrence_id=None,
        calculation_data=request.model_dump(mode="json", exclude={"calls", "title"}),
        record_data=[r.model_dump(mode="json") for r in request.calls],
        origin=request.relative.frame.origin if request.relative is not None else (0.0, 0.0),
        relative=relative,
        analytic_area=True,
        require_representable=True,
    )
    return PreparedPlot(
        request=request, geometry=geometry, input_hash=_hash(request.model_dump(mode="json"))
    )


def validate_prepared_plot(prepared: PreparedPlot) -> PreparedPlot:
    """Reject stale or forged cached geometry before rendering or sharing it."""
    validated = PreparedPlot.model_validate(prepared.model_dump(mode="json"))
    fresh = prepare_plot(validated.request)
    if validated != fresh:
        raise ValueError("Prepared plot does not match freshly calculated input geometry")
    return fresh


def validate_plot_placement(
    geometry: PlotGeometry,
    placement: PlotPlacement,
    scene: PlotScene,
    *,
    native_units: LinearUnit,
    orientation_supported: bool,
    allow_unknown_units: bool = False,
) -> None:
    """Bind placement to fresh geometry and reject unsupported units or precision."""
    if placement.scenario_id is not None:
        raise ValueError("scenario placements are derived from frozen baselines, not source inputs")
    if placement.geometry_hash != geometry.geometry_hash:
        raise ValueError(
            f"stale placement {placement.id}: geometry hash changed; revalidation required"
        )
    if placement.status != "unplaced" and not (
        allow_unknown_units and native_units == "unknown_ft"
    ):
        factor = unit_factor(native_units, scene.units)
        for primitive in geometry.primitives:
            points = [primitive.start, primitive.end]
            if primitive.kind == "arc":
                points.extend(arc_point(primitive, t) for t in (0.25, 0.5, 0.75))
                if primitive.center is not None:
                    points.append(primitive.center)
            transformed = [
                transform_point(
                    p,
                    placement,
                    native_units=native_units,
                    scene_units=scene.units,
                )
                for p in points
            ]
            angle = math.radians(placement.rotation_deg % 360)
            tolerance = min(1e-5, primitive.length_ft * factor * 1e-6)
            a, ta = points[0], transformed[0]
            for b, tb in zip(points[1:], transformed[1:], strict=True):
                dx, dy = (b[0] - a[0]) * factor, (b[1] - a[1]) * factor
                expected = (
                    dx * math.cos(angle) + dy * math.sin(angle),
                    -dx * math.sin(angle) + dy * math.cos(angle),
                )
                if (
                    max(abs((tb[0] - ta[0]) - expected[0]), abs((tb[1] - ta[1]) - expected[1]))
                    > tolerance
                ):
                    raise ValueError(
                        "placement cannot represent primitive vectors without precision loss"
                    )
    if placement.status == "referenced" and (
        scene.kind != "projected" or scene.basis == "local" or not orientation_supported
    ):
        raise ValueError(
            "referenced placement requires supported projected position and documented orientation basis"
        )


def build_dashboard_plots(
    bundle: DashboardBundle, calculations: tuple[DashboardResult, ...]
) -> DashboardPlots:
    """Derive honest source-linked prefixes; never use zipped verifier vertices."""
    results = {r.id: r for r in calculations}
    geometries = tuple(_geometry(bundle, s, results.get(s.id)) for s in bundle.calculations)
    by_id = {g.calculation_id: g for g in geometries}
    specs = {s.id: s for s in bundle.calculations}
    scenes = {s.id: s for s in bundle.scenes}
    for placement in bundle.placements:
        geometry = by_id[placement.calculation_id]
        validate_plot_placement(
            geometry,
            placement,
            scenes[placement.scene_id],
            native_units=specs[placement.calculation_id].frame.foot_definition,
            orientation_supported=specs[placement.calculation_id].frame.basis != "arbitrary_local",
        )
    placements = {p.id: p for p in bundle.placements}
    comparisons = []
    for comparison in bundle.comparison_specs:
        placement = placements[comparison.placement_id]
        native_units = specs[placement.calculation_id].frame.foot_definition
        scene_units = scenes[placement.scene_id].units
        result = compare_points(
            placement,
            comparison.correspondences,
            native_units=native_units,
            scene_units=scene_units,
        )
        comparisons.append(result.model_copy(update={"comparison_id": comparison.id}))
    return DashboardPlots(
        builder_version=PLOT_BUILDER_VERSION,
        geometries=geometries,
        placements=bundle.placements,
        comparisons=tuple(comparisons),
    )


def arc_point(primitive: PlotPrimitive, fraction: float) -> XY:
    """Sample an analytic arc for display only, preserving its actual circular shape."""
    if primitive.kind != "arc" or primitive.center is None or primitive.sweep_deg is None:
        raise ValueError("arc_point requires an arc")
    if not math.isfinite(fraction) or not 0 <= fraction <= 1:
        raise ValueError("fraction must be in [0,1]")
    angle = math.radians(primitive.sweep_deg * fraction) * (
        1 if primitive.curve_dir == "left" else -1
    )
    x, y = primitive.start[0] - primitive.center[0], primitive.start[1] - primitive.center[1]
    return _finite(
        (
            primitive.center[0] + x * math.cos(angle) - y * math.sin(angle),
            primitive.center[1] + x * math.sin(angle) + y * math.cos(angle),
        )
    )


def unit_factor(native_units: LinearUnit, scene_units: LinearUnit) -> float:
    """Declared unit conversion only; never a fitted ground/grid scale factor."""
    if native_units not in {
        "international_ft",
        "us_survey_ft",
        "m",
        "unknown_ft",
    } or scene_units not in {"international_ft", "us_survey_ft", "m", "unknown_ft"}:
        raise ValueError("unsupported linear units")
    if native_units == scene_units:
        return 1.0
    factors = {"international_ft": 0.3048, "us_survey_ft": 1200 / 3937, "m": 1.0}
    if native_units not in factors or scene_units not in factors:
        raise ValueError("unknown foot definition blocks comparison with declared map units")
    return factors[native_units] / factors[scene_units]


def transform_point(
    point: XY,
    placement: PlotPlacement,
    *,
    native_units: LinearUnit = "unknown_ft",
    scene_units: LinearUnit = "unknown_ft",
) -> XY:
    """Clockwise rotation, explicit unit conversion, then scene-unit translation."""
    _finite(point)
    factor = unit_factor(native_units, scene_units)
    angle = math.radians(placement.rotation_deg % 360)
    x, y = point
    offset = (
        (x * math.cos(angle) + y * math.sin(angle)) * factor,
        (-x * math.sin(angle) + y * math.cos(angle)) * factor,
    )
    transformed = _finite(
        (offset[0] + placement.translation[0], offset[1] + placement.translation[1])
    )
    # A closed traverse can retain ~1e-14 trigonometric residue at its origin.
    # Primitive-vector checks below the stage boundary retain the length-relative gate.
    tolerance = min(1e-5, max(1e-9, math.hypot(*offset) * 1e-6))
    if (
        max(
            abs((transformed[0] - placement.translation[0]) - offset[0]),
            abs((transformed[1] - placement.translation[1]) - offset[1]),
        )
        > tolerance
    ):
        raise ValueError("translation loses coordinate precision; choose a representable placement")
    return transformed


def compare_points(
    placement: PlotPlacement,
    correspondences: tuple[PointCorrespondence, ...],
    *,
    native_units: LinearUnit = "unknown_ft",
    scene_units: LinearUnit = "unknown_ft",
) -> PlotComparison:
    """Named scene residuals, never survey accuracy or deed closure."""
    if "unknown_ft" in (native_units, scene_units):
        return PlotComparison(
            placement_id=placement.id,
            status="not_comparable",
            reason="explicit foot definitions required for map residual comparison",
        )
    if placement.status == "unplaced" or not correspondences:
        return PlotComparison(
            placement_id=placement.id,
            status="not_comparable",
            reason="explicit placement and named correspondences required",
        )
    if len({c.id for c in correspondences}) != len(correspondences):
        raise ValueError("point correspondence IDs must be unique")
    try:
        residuals = []
        for pair in correspondences:
            point = transform_point(
                pair.deed_point, placement, native_units=native_units, scene_units=scene_units
            )
            dx, dy = _finite((pair.map_point[0] - point[0], pair.map_point[1] - point[1]))
            residuals.append(PlotResidual(id=pair.id, dx=dx, dy=dy, norm=math.hypot(dx, dy)))
        rms = math.hypot(*(r.norm for r in residuals)) / math.sqrt(len(residuals))
        return PlotComparison(
            placement_id=placement.id,
            status="compared",
            residuals=tuple(residuals),
            rms=rms,
            maximum=max(r.norm for r in residuals),
        )
    except ValueError as exc:
        return PlotComparison(placement_id=placement.id, status="not_comparable", reason=str(exc))


def derive_scenario_placement(
    placement: PlotPlacement, geometry_hash: str, scenario_id: str
) -> PlotPlacement:
    """Bind unchanged transform to scenario geometry, retaining baseline evidence."""
    data = placement.model_dump()
    data.update(
        id=f"{placement.id}:{scenario_id}",
        geometry_hash=geometry_hash,
        scenario_id=scenario_id,
        baseline_geometry_hash=placement.geometry_hash,
        baseline_placement_id=placement.id,
    )
    return PlotPlacement.model_validate(data)
