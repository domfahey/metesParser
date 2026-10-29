"""Advisory sensitivity math; never corrects calls or grants verification."""

from __future__ import annotations

import math
from typing import Any

from mp_models.diagnostics import (
    CallSensitivity,
    ClosureDiagnosticRequest,
    ClosureDiagnostics,
    DiagnosticResidual,
    DiagnosticVector,
    QuantizationBound,
    _diagnostic_hash,
)

ARCSECOND_RADIANS = math.pi / 648000


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


def diagnose_closure(request: ClosureDiagnosticRequest) -> ClosureDiagnostics:
    """Compute a fresh endpoint and separate unit sensitivities for supported calls.

    Absolute projections rank distance and bearing categories separately; opposing
    courses can explain the same residual. No candidate is identified as an error.
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
    for item in boundary:
        call = item.call
        if (
            call.is_curve()
            or call.curve_type is not None
            or call.non_tangent
            or call.radial_bearing
            or call.chord_bearing
        ):
            unsupported.append(f"{item.call_id}: curve")
        if call.is_meander:
            unsupported.append(f"{item.call_id}: meander")
        if call.is_exception:
            unsupported.append(f"{item.call_id}: exception_boundary")
        if call.bearing_azimuth_deg_from_north is None:
            incomplete.append(f"{item.call_id}: unresolved_bearing")
        if call.is_indefinite:
            incomplete.append(f"{item.call_id}: indefinite_call")
    if len(boundary) < 3:
        incomplete.append("At least three complete boundary courses are required.")
    if common["excluded_call_ids"]:
        limitations.append("Explicit commencement tie-ins are excluded from the boundary residual.")
    if unsupported or incomplete:
        return ClosureDiagnostics(
            **common,
            availability="unsupported" if unsupported else "incomplete",
            limitations=tuple(limitations + unsupported + incomplete),
        )

    quantization = None
    try:
        perimeter = math.fsum(c.call.distance_ft for c in boundary)
        if request.precision is not None:
            half_distance = request.precision.distance_increment_ft / 2
            half_angle = request.precision.bearing_increment_arcsec * ARCSECOND_RADIANS / 2
            # Triangle inequality bounds simultaneous distance and bearing rounding.
            bound = math.fsum(
                half_distance
                + (item.call.distance_ft + half_distance) * 2 * math.sin(half_angle / 2)
                for item in boundary
            )
            if not math.isfinite(bound):
                raise ArithmeticError("nonfinite quantization bound")
            quantization = QuantizationBound(assumptions=request.precision, endpoint_bound_ft=bound)
    except ArithmeticError:
        return ClosureDiagnostics(
            **common,
            availability="unsupported",
            limitations=tuple(limitations + ["Calculation exceeds finite arithmetic limits."]),
        )

    derivatives = []
    east = []
    north = []
    for item in boundary:
        call = item.call
        assert call.bearing_azimuth_deg_from_north is not None
        theta = math.radians(call.bearing_azimuth_deg_from_north)
        sine, cosine = math.sin(theta), math.cos(theta)
        east.append(call.distance_ft * sine)
        north.append(call.distance_ft * cosine)
        derivatives.append((sine, cosine, call.distance_ft * cosine, -call.distance_ft * sine))
    e, n = math.fsum(east), math.fsum(north)
    magnitude = math.hypot(e, n)
    # Numerical resolution only; never passed to verify_closure or exporters.
    threshold = 32 * math.ulp(perimeter)
    ranking = magnitude > threshold
    distance_projections = []
    angle_projections = []
    if ranking:
        u_e, u_n = e / magnitude, n / magnitude
        distance_projections = [abs(math.fsum((a * u_e, b * u_n))) for a, b, _, _ in derivatives]
        angle_projections = [
            abs(math.fsum((a * u_e, b * u_n))) * ARCSECOND_RADIANS for _, _, a, b in derivatives
        ]
        distance_ranks, angle_ranks = _ranks(distance_projections), _ranks(angle_projections)
    else:
        distance_ranks = angle_ranks = []
        limitations.append("Residual direction ranking unavailable at numerical zero residual.")
    sensitivities = tuple(
        CallSensitivity(
            call_id=item.call_id,
            source_refs=item.source_refs,
            distance_derivative=DiagnosticVector(east=a, north=b),
            angle_derivative_per_radian=DiagnosticVector(east=c, north=d),
            angle_derivative_per_arcsecond=DiagnosticVector(
                east=c * ARCSECOND_RADIANS, north=d * ARCSECOND_RADIANS
            ),
            distance_projection_abs=distance_projections[i] if ranking else None,
            angle_projection_abs_per_arcsecond=angle_projections[i] if ranking else None,
            distance_rank=distance_ranks[i] if ranking else None,
            angle_rank=angle_ranks[i] if ranking else None,
        )
        for i, (item, (a, b, c, d)) in enumerate(zip(boundary, derivatives, strict=True))
    )
    return ClosureDiagnostics(
        **common,
        availability="supported",
        residual=DiagnosticResidual(east_ft=e, north_ft=n, magnitude_ft=magnitude),
        sensitivities=sensitivities,
        limitations=tuple(limitations),
        ranking_available=ranking,
        numerical_zero_threshold_ft=threshold,
        quantization=quantization,
    )
