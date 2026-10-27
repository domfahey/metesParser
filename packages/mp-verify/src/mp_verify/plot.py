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
    PlotUnresolved,
    PointCorrespondence,
)

if TYPE_CHECKING:
    from mp_models.dashboard import DashboardBundle, DashboardCalculation, DashboardResult
    from mp_models.deed_call import DeedCall

PLOT_BUILDER_VERSION = "plot-1.0.1"


class _Source(TypedDict):
    call_id: str
    occurrence_id: str
    page_id: str


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _finite(point: XY) -> XY:
    if not all(math.isfinite(v) for v in point):
        raise ValueError("nonfinite plot arithmetic")
    return point


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
            if abs(residual) > 1e-6:
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


def _geometry(
    bundle: DashboardBundle, spec: DashboardCalculation, result: DashboardResult | None
) -> PlotGeometry:
    records = tuple(c for c in bundle.calls if c.occurrence_id == spec.occurrence_id)
    primitives = []
    unresolved = []
    reasons = []
    origin = spec.relative.frame.origin if spec.relative is not None else (0.0, 0.0)
    current = origin
    stopped = False
    relative = (
        {c.call_id: c for c in result.courses}
        if result and spec.method == "relative" and result.geometry_status == "analyzed"
        else {}
    )
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
        elif spec.method == "relative" and record.id not in relative:
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
                        relative[record.id].local_azimuth_deg
                        if record.id in relative
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
        "calculation": spec.model_dump(mode="json"),
        "calls": [r.model_dump(mode="json") for r in records],
        "primitives": [p.model_dump(mode="json") for p in primitives],
        "unresolved": [u.model_dump(mode="json") for u in unresolved],
    }
    return PlotGeometry(
        id=spec.id,
        calculation_id=spec.id,
        occurrence_id=spec.occurrence_id,
        frame_id=f"{spec.id}:native",
        geometry_hash=_hash(content),
        primitives=tuple(primitives),
        unresolved=tuple(unresolved),
        chains=(tuple(p.call_id for p in primitives),) if primitives else (),
        completeness="complete" if complete else "partial" if primitives else "unresolved",
        reasons=tuple(reasons),
        misclosure_ft=math.hypot(current[0] - origin[0], current[1] - origin[1])
        if complete
        else None,
        area_sq_ft=result.area_sq_ft if complete and result else None,
        perimeter_ft=sum(p.length_ft for p in primitives) if complete else None,
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
        if placement.scenario_id is not None:
            raise ValueError(
                "scenario placements are derived from frozen baselines, not source inputs"
            )
        if placement.geometry_hash != geometry.geometry_hash:
            raise ValueError(
                f"stale placement {placement.id}: geometry hash changed; revalidation required"
            )
        scene = scenes[placement.scene_id]
        spec = specs[placement.calculation_id]
        if placement.status != "unplaced":
            factor = unit_factor(spec.frame.foot_definition, scene.units)
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
                        native_units=spec.frame.foot_definition,
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
            scene.kind != "projected"
            or scene.basis == "local"
            or spec.frame.basis == "arbitrary_local"
        ):
            raise ValueError(
                "referenced placement requires supported projected position and documented orientation basis"
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
