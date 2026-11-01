"""Advisory sensitivity math; never corrects calls or grants verification."""

from __future__ import annotations

import math
from typing import Any, Literal

from mp_models.deed_call import DeedCall
from mp_models.diagnostics import (
    CallSensitivity,
    ClosureDiagnosticRequest,
    ClosureDiagnostics,
    CurveParameterSensitivity,
    DiagnosticResidual,
    DiagnosticVector,
    QuantizationBound,
    _diagnostic_hash,
)
from mp_models.plot import PlotPrimitive

from .plot import _arc
from .tangents import line_distance
from .traverse import effective_indefinite

ARCSECOND_RADIANS = math.pi / 648000
_Parameter = Literal["radius_ft", "sweep_radian", "start_tangent_radian"]
_DerivativeUnits = Literal["ft/ft", "ft/radian"]
_LineDerivatives = tuple[float, float, float, float]


def _ranks(values: list[float]) -> list[int]:
    """Dense descending ranks; floating-equivalent projections keep equal evidence tied."""
    groups: list[float] = []
    for value in sorted(values, reverse=True):
        if not groups or not math.isclose(value, groups[-1], rel_tol=1e-10, abs_tol=1e-12):
            groups.append(value)
    return [
        next(
            i
            for i, group in enumerate(groups, 1)
            if math.isclose(value, group, rel_tol=1e-10, abs_tol=1e-12)
        )
        for value in values
    ]


def _curve_evidence(call: DeedCall) -> bool:
    return (
        call.is_curve()
        or call.non_tangent
        or any(
            getattr(call, name) is not None
            for name in (
                "curve_type",
                "radial_bearing",
                "chord_bearing",
                "chord_length_ft",
                "arc_length_ft",
                "delta_deg",
            )
        )
    )


def _supported_circular_arc(call: DeedCall, call_id: str) -> PlotPrimitive:
    """Reuse plotting's redundant measurement and tangent/chord checks before analysis.

    Individual circular members of compound/reverse curves are supported. A stated
    radial bearing orients a non-tangent curve through the shared tangents rule.
    Full circles lack a distinct chord orientation in the shared plot contract.
    """
    if not call.is_curve():
        raise ValueError("partial curve evidence; radius, sweep and direction required")
    if call.curve_type == "spiral":
        raise ValueError("spiral geometry unsupported; no circular arc assumed")
    if call.delta_deg == 360:
        raise ValueError("full circles unsupported; require a distinct arc endpoint")
    primitive = _arc(call, (0.0, 0.0), {"call_id": call_id, "occurrence_id": None, "page_id": None})
    assert primitive.sweep_deg is not None
    if primitive.sweep_deg >= 360:
        raise ValueError("full circles unsupported; require a distinct arc endpoint")
    return primitive


def _curve_parameters(primitive: PlotPrimitive) -> tuple[CurveParameterSensitivity, ...]:
    assert primitive.radius_ft is not None and primitive.sweep_deg is not None
    assert primitive.start_tangent_deg is not None
    radius = primitive.radius_ft
    sweep = math.radians(primitive.sweep_deg)
    tangent = math.radians(primitive.start_tangent_deg)
    sign = 1 if primitive.curve_dir == "right" else -1
    e, n = primitive.end
    values: tuple[
        tuple[_Parameter, float, tuple[float, float], _DerivativeUnits, tuple[str, ...]], ...
    ] = (
        (
            "radius_ft",
            radius,
            (e / radius, n / radius),
            "ft/ft",
            ("sweep_radian", "start_tangent_radian", "curve_dir"),
        ),
        (
            "sweep_radian",
            sweep,
            (radius * math.sin(tangent + sign * sweep), radius * math.cos(tangent + sign * sweep)),
            "ft/radian",
            ("radius_ft", "start_tangent_radian", "curve_dir"),
        ),
        (
            "start_tangent_radian",
            tangent,
            (n, -e),
            "ft/radian",
            ("radius_ft", "sweep_radian", "curve_dir"),
        ),
    )
    return tuple(
        CurveParameterSensitivity(
            parameter=name,
            value=value,
            derivative=DiagnosticVector(east=vector[0], north=vector[1]),
            derivative_units=units,
            fixed_parameters=fixed,
            constraint="Independent geometric basis after validating every supplied observation; regenerate arc length, chord length and chord bearing together for perturbations. Sweep remains strictly between 0 and 2*pi; turn is fixed. Recorded observations are not changed.",
        )
        for name, value, vector, units, fixed in values
    )


def diagnose_closure(request: ClosureDiagnosticRequest) -> ClosureDiagnostics:
    """Compute fresh residuals and independent line/arc endpoint sensitivities.

    Rankings compare only the same parameter and unit, never error probabilities.
    Arc derivatives hold the other independent geometric parameters fixed, rather
    than inconsistently perturbing redundant recorded observations.
    """
    request = ClosureDiagnosticRequest.model_validate(request)
    common: dict[str, Any] = {
        "request": request,
        "request_sha256": _diagnostic_hash(request.model_dump(mode="json")),
        "input_sha256": request.input_sha256,
        "excluded_call_ids": tuple(c.call_id for c in request.calls if c.call.is_tie_in),
    }
    boundary = [c for c in request.calls if not c.call.is_tie_in]
    limitations = ["Advisory unit sensitivities are not corrections or error probabilities."]
    unsupported = []
    incomplete = []
    arcs = {}
    for item in boundary:
        call = item.call
        if _curve_evidence(call):
            try:
                arcs[item.call_id] = _supported_circular_arc(call, item.call_id)
            except (ValueError, ArithmeticError) as exc:
                unsupported.append(f"{item.call_id}: curve: {exc}")
        elif call.bearing_azimuth_deg_from_north is None:
            incomplete.append(f"{item.call_id}: unresolved_bearing")
        if call.is_meander:
            unsupported.append(f"{item.call_id}: meander")
        if call.is_exception:
            unsupported.append(f"{item.call_id}: exception_boundary")
        if effective_indefinite(call):
            incomplete.append(f"{item.call_id}: indefinite_call")
    minimum = 2 if arcs else 3
    if len(boundary) < minimum:
        incomplete.append(
            "At least two complete boundary courses are required for a curved boundary."
            if arcs
            else "At least three complete boundary courses are required."
        )
    if common["excluded_call_ids"]:
        limitations.append("Explicit commencement tie-ins are excluded from the boundary residual.")
    if unsupported or incomplete:
        return ClosureDiagnostics(
            **common,
            availability="unsupported" if unsupported else "incomplete",
            limitations=tuple(limitations + unsupported + incomplete),
        )

    quantization = None
    derivatives: list[_LineDerivatives | None] = []
    east = []
    north = []
    try:
        perimeter = math.fsum(
            arcs[c.call_id].length_ft if c.call_id in arcs else line_distance(c.call)
            for c in boundary
        )
        if request.precision is not None and arcs:
            limitations.append(
                "Quantization unavailable: line increments do not declare independent curve precision for radius and sweep."
            )
        elif request.precision is not None:
            half_distance = request.precision.distance_increment_ft / 2
            half_angle = request.precision.bearing_increment_arcsec * ARCSECOND_RADIANS / 2
            bound = math.fsum(
                half_distance
                + (line_distance(item.call) + half_distance) * 2 * math.sin(half_angle / 2)
                for item in boundary
            )
            if not math.isfinite(bound):
                raise ArithmeticError("nonfinite quantization bound")
            quantization = QuantizationBound(assumptions=request.precision, endpoint_bound_ft=bound)
        for item in boundary:
            if item.call_id in arcs:
                primitive = arcs[item.call_id]
                east.append(primitive.end[0])
                north.append(primitive.end[1])
                derivatives.append(None)
            else:
                call = item.call
                assert call.bearing_azimuth_deg_from_north is not None
                theta = math.radians(call.bearing_azimuth_deg_from_north)
                sine, cosine = math.sin(theta), math.cos(theta)
                distance = line_distance(call)
                east.append(distance * sine)
                north.append(distance * cosine)
                derivatives.append((sine, cosine, distance * cosine, -distance * sine))
        e, n = math.fsum(east), math.fsum(north)
        magnitude = math.hypot(e, n)
        if not all(math.isfinite(v) for v in (perimeter, e, n, magnitude)):
            raise ArithmeticError("nonfinite residual")
    except ArithmeticError:
        return ClosureDiagnostics(
            **common,
            availability="unsupported",
            limitations=tuple(limitations + ["Calculation exceeds finite arithmetic limits."]),
        )
    threshold = 32 * math.ulp(perimeter)
    ranking = magnitude > threshold
    if not ranking:
        limitations.append("Residual direction ranking unavailable at numerical zero residual.")
    unit_e, unit_n = (e / magnitude, n / magnitude) if ranking else (0.0, 0.0)
    line_indexes = [i for i, derivative in enumerate(derivatives) if derivative is not None]
    distance_projections = []
    angle_projections = []
    for i in line_indexes:
        derivative = derivatives[i]
        assert derivative is not None
        a, b, c, d = derivative
        distance_projections.append(abs(math.fsum((a * unit_e, b * unit_n))))
        angle_projections.append(abs(math.fsum((c * unit_e, d * unit_n))) * ARCSECOND_RADIANS)
    distance_ranks, angle_ranks = _ranks(distance_projections), _ranks(angle_projections)
    line_positions = {index: position for position, index in enumerate(line_indexes)}
    curve_rows = {id: _curve_parameters(primitive) for id, primitive in arcs.items()}
    if ranking:
        for column in range(3):
            projections = [
                abs(
                    math.fsum(
                        (
                            rows[column].derivative.east * unit_e,
                            rows[column].derivative.north * unit_n,
                        )
                    )
                )
                for rows in curve_rows.values()
            ]
            for (id, rows), projection, rank in zip(
                tuple(curve_rows.items()), projections, _ranks(projections), strict=True
            ):
                # Rebuild immutable parameter rows; never update the input observations.
                updated = list(rows)
                updated[column] = rows[column].model_copy(
                    update={"projection_abs": projection, "rank": rank}
                )
                curve_rows[id] = tuple(updated)
    sensitivities = []
    for i, item in enumerate(boundary):
        if item.call_id in arcs:
            sensitivities.append(
                CallSensitivity(
                    call_id=item.call_id,
                    source_refs=item.source_refs,
                    geometry_kind="arc",
                    curve_parameters=curve_rows[item.call_id],
                )
            )
            continue
        derivative = derivatives[i]
        assert derivative is not None
        a, b, c, d = derivative
        position = line_positions[i]
        sensitivities.append(
            CallSensitivity(
                call_id=item.call_id,
                source_refs=item.source_refs,
                distance_derivative=DiagnosticVector(east=a, north=b),
                angle_derivative_per_radian=DiagnosticVector(east=c, north=d),
                angle_derivative_per_arcsecond=DiagnosticVector(
                    east=c * ARCSECOND_RADIANS, north=d * ARCSECOND_RADIANS
                ),
                distance_projection_abs=distance_projections[position] if ranking else None,
                angle_projection_abs_per_arcsecond=angle_projections[position] if ranking else None,
                distance_rank=distance_ranks[position] if ranking else None,
                angle_rank=angle_ranks[position] if ranking else None,
            )
        )
    return ClosureDiagnostics(
        **common,
        availability="supported",
        residual=DiagnosticResidual(east_ft=e, north_ft=n, magnitude_ft=magnitude),
        sensitivities=tuple(sensitivities),
        limitations=tuple(limitations),
        ranking_available=ranking,
        numerical_zero_threshold_ft=threshold,
        quantization=quantization,
    )
