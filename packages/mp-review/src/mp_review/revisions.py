"""Deterministic drafts and immutable, retryable local revision publication.

No mutable latest pointer exists: completion can only publish its own revision ID.
A manifest is the commit record, written after every content-bound artifact.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

from mp_bearing.azimuth import (
    azimuth_to_quadrant,
    parse_packed_dms,
    parse_quadrant_bearing,
    quadrant_to_azimuth,
)
from mp_bearing.curves import calculate_curve_properties
from mp_models.comparison import ComparisonDescription, ComparisonRequest
from mp_models.corridor import CorridorRequest
from mp_models.dashboard import DashboardBundle, DashboardEdit
from mp_models.deed_call import DeedCall
from mp_models.plot import LinearUnit
from mp_models.plot_request import PlotCall, PlotRequest
from mp_models.relative import RelativeDescription
from mp_models.revisions import (
    DashboardRevision,
    PreparedRevision,
    PreparedRevisionCorridor,
    RevisionComparison,
    RevisionError,
    RevisionGeometry,
    RevisionManifest,
    RevisionPreparedCall,
    RevisionSourceChange,
    bind_baseline,
)
from mp_verify.checks import tangent_chord_issue
from mp_verify.comparison import compare_descriptions
from mp_verify.dashboard import _hash, _json
from mp_verify.plot import (
    prepare_plot,
    unit_factor,
    validate_prepared_plot,
)

from .dashboard import _load
from .json_input import parse_json


def _number(raw: str, field: str) -> float:
    text = raw.strip()
    if field == "bearing_azimuth_deg_from_north" and not re.fullmatch(
        r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text
    ):
        # Full-string admission prevents a valid substring hiding unresolved text.
        if not re.fullmatch(
            r"[NS]\s*\d+(?:\.\d+)?\s*(?:°|deg)?\s*(?:\d+(?:\.\d+)?\s*[\'′]\s*)?(?:\d+(?:\.\d+)?\s*[\"″]\s*)?[EW]",
            text,
            re.I,
        ):
            raise ValueError("Enter a complete quadrant bearing or decimal azimuth")
        parsed = parse_quadrant_bearing(text)
        if parsed is None or not 0 <= parsed[1] <= 90:
            raise ValueError("Invalid quadrant bearing")
        value = quadrant_to_azimuth(*parsed)
    else:
        if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text):
            raise ValueError("Enter a complete decimal number")
        value = float(text)
    if not math.isfinite(value):
        raise ValueError("Value must be finite")
    if field == "distance_ft" and value <= 0:
        raise ValueError("Distance must be positive")
    if field == "bearing_azimuth_deg_from_north" and not 0 <= value < 360:
        raise ValueError("Azimuth must be at least 0 and below 360")
    if field == "interior_angle_deg" and not 0 < value < 360:
        raise ValueError("Interior angle must be above 0 and below 360")
    return float(value)


def _angle(raw: dict[str, str], prefix: str = "bearing") -> float:
    value = raw.get(f"{prefix}_value", "")
    format = raw.get(f"{prefix}_format", "")
    if format == "decimal_azimuth":
        return _number(value, "bearing_azimuth_deg_from_north")
    if format == "quadrant_dms":
        if not re.fullmatch(r"[NS]\s*.+[EW]", value.strip(), re.I):
            raise ValueError("Quadrant DMS requires N/S and E/W")
        return _number(value, "bearing_azimuth_deg_from_north")
    if format in ("packed_dms_azimuth", "quadrant_packed_dms"):
        packed = _number(value, "packed_dms")
        angle = parse_packed_dms(packed)
        if format == "quadrant_packed_dms":
            quadrant_prefix = prefix.removesuffix("_bearing") + "_" if prefix != "bearing" else ""
            ns_field, ew_field = quadrant_prefix + "quadrant_ns", quadrant_prefix + "quadrant_ew"
            # Older drafts used one selector pair. An explicit partial/new pair
            # stays unresolved instead of borrowing the other cardinal value.
            if quadrant_prefix and ns_field not in raw and ew_field not in raw:
                ns_field, ew_field = "quadrant_ns", "quadrant_ew"
            ns, ew = raw.get(ns_field), raw.get(ew_field)
            if ns not in ("N", "S") or ew not in ("E", "W") or not 0 <= angle <= 90:
                raise ValueError("Packed quadrant requires N/S, E/W and angle within 90 degrees")
            return float(quadrant_to_azimuth(ns, angle, ew))
        if not 0 <= angle < 360:
            raise ValueError("Packed azimuth must be below 360 degrees")
        return float(angle)
    raise ValueError(f"Unsupported or missing {prefix} angle format")


def _quadrant_text(azimuth: float) -> str:
    """Serialize derived orientation for the shared quadrant-only string field.

    The shared formatter chooses cardinal labels; unrounded fractional seconds
    avoid its presentation-only DMS rounding changing redundant evidence.
    """
    azimuth %= 360.0
    label = azimuth_to_quadrant(azimuth)
    ns, ew = label[0], label[-1]
    angle = (
        (azimuth if ew == "E" else 360 - azimuth)
        if ns == "N"
        else (180 - azimuth if ew == "E" else azimuth - 180)
    )
    exact = Decimal(str(angle))
    degrees = int(exact)
    minute_value = (exact - degrees) * 60
    minutes = int(minute_value)
    seconds = (minute_value - minutes) * 60
    return f"{ns} {degrees}°{minutes}'{format(seconds, 'f')}\" {ew}"


def _distance(raw: str, unit: str, foot_definition: LinearUnit) -> float:
    value = _number(raw, "distance_ft")
    if unit == "feet":
        return value  # Native distance field: no foot-definition conversion.
    source_units: dict[str, LinearUnit] = {
        "meters": "m",
        "international_ft": "international_ft",
        "us_survey_ft": "us_survey_ft",
        "us_survey_feet": "us_survey_ft",
    }
    if unit in source_units:
        return value * unit_factor(source_units[unit], foot_definition)
    raise ValueError("Unsupported or unknown distance unit; retain raw draft")


def _structured_call(
    raw: dict[str, str], course: int, foot_definition: LinearUnit, inherited: float | None
) -> tuple[DeedCall | None, Literal["boundary", "tie_in", "reference", "omitted"]]:
    supported = {
        "geometry_type",
        "role",
        "orientation",
        "bearing_format",
        "bearing_value",
        "quadrant_ns",
        "quadrant_ew",
        "chord_quadrant_ns",
        "chord_quadrant_ew",
        "radial_quadrant_ns",
        "radial_quadrant_ew",
        "distance_value",
        "distance_unit",
        "curve_dir",
        "radius_value",
        "delta_value",
        "delta_format",
        "arc_length_value",
        "chord_length_value",
        "chord_bearing_value",
        "chord_bearing_format",
        "radial_bearing_value",
        "radial_bearing_format",
        "along",
        "to",
        "notes",
        "direction_text",
        "is_exception",
        "is_meander",
        "is_indefinite",
        "non_tangent",
        "curve_type",
        "monument_type",
        "monument_status",
        "quality",
        "is_tie_in",
    }
    if set(raw) - supported:
        raise ValueError(
            "Unsupported structured fields: " + ", ".join(sorted(set(raw) - supported))
        )
    role = raw.get("role", "")
    if role not in ("boundary", "tie_in", "reference", "omitted"):
        raise ValueError("Explicit supported course role required")
    if raw.get("radial_bearing_value", "").strip():
        raise ValueError(
            "Radial-bearing curve orientation is unsupported by this editor; retain source evidence"
        )
    kind = raw.get("geometry_type", "")
    if kind == "annotation":
        if role not in ("reference", "omitted"):
            raise ValueError("Annotation must be reference or intentionally omitted")
        if any(
            raw.get(k, "").strip()
            for k in (
                "bearing_value",
                "distance_value",
                "radius_value",
                "delta_value",
                "arc_length_value",
                "chord_length_value",
            )
        ):
            raise ValueError("Annotation cannot silently discard geometric input")
        return None, cast(Literal["boundary", "tie_in", "reference", "omitted"], role)
    if kind not in ("line", "circular_arc"):
        raise ValueError("Unsupported geometry type")
    bearing: float | None
    orientation = raw.get("orientation", "")
    if orientation == "inherited_tangent":
        if inherited is None or raw.get("bearing_value", "").strip():
            raise ValueError(
                "Inherited tangent requires adjacent supported geometry and no supplied bearing"
            )
        bearing = inherited
    elif orientation == "supplied":
        bearing = _angle(raw) if raw.get("bearing_value", "").strip() else None
        if bearing is None and kind == "line":
            raise ValueError("Line requires complete supplied bearing")
    else:
        raise ValueError("Explicit supplied or inherited_tangent orientation required")
    unit = raw.get("distance_unit", "")
    data: dict[str, Any] = {
        "course": course,
        "direction_text": raw.get("direction_text")
        or ("Structured line" if kind == "line" else "Structured circular arc"),
        "bearing_azimuth_deg_from_north": bearing,
        "is_tie_in": role == "tie_in",
    }
    for field in (
        "along",
        "to",
        "notes",
        "curve_type",
        "monument_type",
        "monument_status",
        "quality",
    ):
        if field in raw:
            data[field] = raw[field]
    for field in ("is_exception", "is_meander", "is_indefinite", "non_tangent", "is_tie_in"):
        if field in raw:
            if raw[field] not in ("true", "false"):
                raise ValueError(f"{field} requires explicit true or false")
            data[field] = raw[field] == "true"
    if data["is_tie_in"] != (role == "tie_in"):
        raise ValueError("Tie-in flag conflicts with explicit course role")
    if kind == "line":
        if any(
            raw.get(k, "").strip()
            for k in (
                "radius_value",
                "delta_value",
                "arc_length_value",
                "chord_length_value",
                "chord_bearing_value",
                "radial_bearing_value",
                "curve_dir",
            )
        ):
            raise ValueError("Line input cannot silently discard curve evidence")
        data["distance_ft"] = _distance(raw.get("distance_value", ""), unit, foot_definition)
    else:
        if raw.get("curve_dir") not in ("left", "right"):
            raise ValueError("Circular arc requires explicit left/right direction")
        radius = _distance(raw.get("radius_value", ""), unit, foot_definition)
        sweep = None
        if raw.get("delta_value", "").strip():
            if raw.get("delta_format") == "decimal_degrees":
                sweep = _number(raw["delta_value"], "delta_deg")
            elif raw.get("delta_format") == "packed_dms":
                sweep = parse_packed_dms(_number(raw["delta_value"], "delta_deg"))
            else:
                raise ValueError("Explicit supported central-angle format required")
            if not 0 < sweep < 360:
                raise ValueError("Full circles and multiple revolutions unsupported in call editor")
        arc = (
            _distance(raw["arc_length_value"], unit, foot_definition)
            if raw.get("arc_length_value", "").strip()
            else None
        )
        if sweep is None and arc is None:
            if not (
                raw.get("chord_bearing_value", "").strip()
                and raw.get("chord_length_value", "").strip()
            ):
                raise ValueError(
                    "Circular arc requires complete radius and sweep or arc length, "
                    "or a chord bearing and chord length"
                )
            # Chord-only curve: kept as stated and positioned by its chord; no delta,
            # arc or tangent is derived (minor/major arc is ambiguous).
            chord_length = _distance(raw["chord_length_value"], unit, foot_definition)
            if raw.get("distance_value", "").strip() and not math.isclose(
                _distance(raw["distance_value"], unit, foot_definition),
                chord_length,
                rel_tol=1e-6,
                abs_tol=0.01,
            ):
                raise ValueError("Curve distance conflicts with supplied chord length")
            data.update(
                radius_ft=radius,
                curve_dir=raw["curve_dir"],
                chord_length_ft=chord_length,
                chord_bearing=_quadrant_text(_angle(raw, "chord_bearing")),
                distance_ft=chord_length,
            )
            chord_call = DeedCall.model_validate(data)
            # A supplied start tangent must agree with the chord bearing, radius and
            # chord length (shared rounding-aware rule); never store a contradiction.
            issue = tangent_chord_issue(chord_call)
            if issue is not None:
                raise ValueError(issue)
            return chord_call, cast(Literal["boundary", "tie_in", "reference", "omitted"], role)
        properties = calculate_curve_properties(radius, delta_deg=sweep, arc_length_ft=arc)
        if not 0 < properties["delta_deg"] < 360:
            raise ValueError("Full circles and multiple revolutions unsupported in call editor")
        data.update(
            radius_ft=radius,
            curve_dir=raw["curve_dir"],
            delta_deg=sweep,
            arc_length_ft=arc,
            distance_ft=properties["arc_length_ft"],
        )
        if raw.get("distance_value", "").strip():
            distance = _distance(raw["distance_value"], unit, foot_definition)
            if not math.isclose(distance, properties["arc_length_ft"], rel_tol=1e-6, abs_tol=0.01):
                raise ValueError("Curve distance conflicts with supplied circular arc length")
            data["distance_ft"] = distance
        if raw.get("chord_length_value", "").strip():
            data["chord_length_ft"] = _distance(raw["chord_length_value"], unit, foot_definition)
        for field in ("chord_bearing", "radial_bearing"):
            if raw.get(field + "_value", "").strip():
                data[field] = _quadrant_text(_angle(raw, field))
    return DeedCall.model_validate(data), cast(
        Literal["boundary", "tie_in", "reference", "omitted"], role
    )


def _supported_geometry(geometry: RevisionGeometry) -> bool:
    """Complete geometry, or every course positioned with only chord-positioned courses undrawn."""
    plot = geometry.plot.geometry
    return plot.completeness == "complete" or (
        bool(plot.primitives) and all(u.positioned for u in plot.unresolved)
    )


def _ending_tangent(
    previous: list[RevisionPreparedCall], foot_definition: LinearUnit
) -> float | None:
    if not previous or previous[-1].role != "boundary" or previous[-1].call is None:
        return None
    # Every preceding displacement must resolve; never jump over excluded evidence.
    if any(c.role != "boundary" or c.call is None for c in previous):
        return None
    plot = prepare_plot(
        PlotRequest(
            title="Inherited orientation prerequisite",
            calls=tuple(PlotCall(id=c.id, call=c.call) for c in previous),
            foot_definition=foot_definition,
        )
    )
    if plot.geometry.completeness != "complete" or not plot.geometry.primitives:
        return None
    last = plot.geometry.primitives[-1]
    if last.kind == "arc":
        assert last.start_tangent_deg is not None and last.sweep_deg is not None
        return (
            last.start_tangent_deg + (1 if last.curve_dir == "right" else -1) * last.sweep_deg
        ) % 360
    return math.degrees(math.atan2(last.end[0] - last.start[0], last.end[1] - last.start[1])) % 360


def _prepare_calls(
    bundle: DashboardBundle,
    revision: DashboardRevision,
    values: dict[str, dict[str, Any]],
    errors: list[RevisionError],
) -> tuple[RevisionPreparedCall, ...]:
    records = {c.id: c for c in bundle.calls}
    edits = {e.call_id: e for e in revision.edits}
    pages = {p.id: p for p in bundle.pages}
    output = []
    for tract in revision.tracts:
        previous: list[RevisionPreparedCall] = []
        calculations = [c for c in bundle.calculations if c.occurrence_id == tract.occurrence_id]
        definitions = {c.frame.foot_definition for c in calculations}
        foot = next(iter(definitions)) if len(definitions) == 1 else "unknown_ft"
        removed = [
            e.call_id
            for e in revision.edits
            if e.occurrence_id == tract.occurrence_id and e.action == "remove"
        ]
        for index, cid in enumerate((*tract.call_order, *removed), 1):
            original = records.get(cid)
            edit = edits.get(cid)
            refs = edit.source_refs if edit else ()
            status: Literal["recorded", "hypothetical", "source_correction"] = (
                "source_correction"
                if edit and revision.kind == "source_correction"
                else ("hypothetical" if edit else "recorded")
            )
            quote = (
                "\n".join(r.quote for r in refs) if refs else (original.quote if original else None)
            )
            page = (
                refs[0].page_id
                if refs
                else (
                    edit.page_id
                    if edit and edit.page_id
                    else (original.page_id if original else None)
                )
            )
            call = original.call if original else None
            role: Literal["boundary", "tie_in", "reference", "omitted"] = (
                "tie_in" if call and call.is_tie_in else "boundary"
            )
            if edit and edit.structured_input is not None and edit.action != "remove":
                try:
                    inherited = _ending_tangent(previous, foot)
                    if (
                        original is not None
                        and edit.structured_input.get("orientation") == "inherited_tangent"
                    ):
                        source_order = [
                            c.id for c in bundle.calls if c.occurrence_id == tract.occurrence_id
                        ]
                        source_index = source_order.index(cid)
                        if (
                            source_index == 0
                            or not previous
                            or previous[-1].id != source_order[source_index - 1]
                        ):
                            inherited = None
                    call, role = _structured_call(edit.structured_input, index, foot, inherited)
                except ValueError as exc:
                    call = None
                    errors.append(
                        RevisionError(call_id=cid, field="structured_input", message=str(exc))
                    )
            elif call is not None:
                data = call.model_dump(mode="json")
                data.update(
                    {k: v for k, v in values.get(cid, {}).items() if k != "interior_angle_deg"}
                )
                data["course"] = index
                call = DeedCall.model_validate(data)
            elif values.get(cid):
                errors.append(
                    RevisionError(
                        call_id=cid,
                        field="call",
                        message="Unresolved source call cannot accept numerical patches",
                    )
                )
            if edit is not None:
                document_id = edit.document_id
            else:
                assert original is not None
                document_id = pages[original.page_id].document_id
            prepared = RevisionPreparedCall(
                id=cid,
                occurrence_id=tract.occurrence_id,
                tract_id=tract.id,
                document_id=document_id,
                page_id=page,
                call=call,
                role=role,
                removed=cid in removed or tract.action == "remove",
                quote=quote,
                source_refs=refs,
                source_status=status,
                original_source=original.model_dump(mode="json") if original else None,
                raw_input=edit.structured_input
                if edit and edit.structured_input is not None
                else (edit.raw_fields if edit else None),
            )
            output.append(prepared)
            if not prepared.removed:
                previous.append(prepared)
    return tuple(output)


def _validate_identities(bundle: DashboardBundle, revision: DashboardRevision) -> None:
    if bind_baseline(bundle, revision.baseline.id) != revision.baseline:
        raise ValueError("Revision baseline hash mismatch")
    occurrences = {o.id: o for o in bundle.occurrences}
    calls = {c.id: c for c in bundle.calls}
    pages = {p.id: p for p in bundle.pages}
    evidence = {e.id: e for e in bundle.evidence}
    if {t.occurrence_id for t in revision.tracts} != set(occurrences):
        raise ValueError("Complete tract inventory required; use explicit remove")
    if revision.schema_version == "1.0" and any(
        e.structured_input is not None or e.action == "add" for e in revision.edits
    ):
        raise ValueError("Structured call editing requires revision schema 1.1")
    removed = {e.call_id for e in revision.edits if e.action == "remove"}
    for tract in revision.tracts:
        occurrence = occurrences[tract.occurrence_id]
        docs = {pages[p].document_id for p in occurrence.page_ids}
        own_calls = {c.id for c in bundle.calls if c.occurrence_id == occurrence.id}
        added_calls = {
            e.call_id
            for e in revision.edits
            if e.occurrence_id == occurrence.id and e.action == "add"
        }
        if revision.kind == "source_correction" and tract.action == "remove":
            raise ValueError(
                "Source correction tract removal requires separately supported source selection"
            )
        if tract.id != occurrence.parcel_id or set(tract.document_ids) != docs:
            raise ValueError("Tract document/parcel identity mismatch")
        # Removal is explicit even when an entire tract is removed.
        if set(tract.call_order) != (own_calls | added_calls) - removed:
            raise ValueError("Call identity mismatch; use explicit remove instead of missing input")
    tracts = {t.occurrence_id: t for t in revision.tracts}
    for edit in revision.edits:
        call = calls.get(edit.call_id)
        tombstone = edit.action == "remove" and call is None and edit.structured_input is not None
        if edit.action == "add" or tombstone:
            known_ids = {
                item.id
                for name in type(bundle).model_fields
                for item in (
                    getattr(bundle, name) if isinstance(getattr(bundle, name), tuple) else ()
                )
                if hasattr(item, "id")
            }
            if revision.schema_version not in ("1.1", "1.2") or edit.call_id in known_ids:
                raise ValueError(
                    "Added call/tombstone requires schema 1.1 or 1.2 and a distinct stable identity"
                )
            added_occurrence = occurrences.get(edit.occurrence_id)
            if (
                added_occurrence is None
                or added_occurrence.parcel_id != edit.tract_id
                or edit.document_id not in tracts[edit.occurrence_id].document_ids
            ):
                raise ValueError("Added call document/tract/occurrence identity mismatch")
        elif (
            call is None
            or call.occurrence_id != edit.occurrence_id
            or occurrences[edit.occurrence_id].parcel_id != edit.tract_id
            or pages[call.page_id].document_id != edit.document_id
        ):
            raise ValueError("Edited call document/tract/occurrence identity mismatch")
        if edit.page_id is not None and (
            edit.page_id not in occurrences[edit.occurrence_id].page_ids
            or pages[edit.page_id].document_id != edit.document_id
        ):
            raise ValueError("Unknown or cross-document source page")
        if tracts[edit.occurrence_id].action == "remove":
            raise ValueError("Removed tract cannot also contain call edits")
        for eid in edit.evidence_ids:
            ev = evidence.get(eid)
            if (
                ev is None
                or ev.occurrence_id != edit.occurrence_id
                or ev.call_id not in (None, edit.call_id)
            ):
                raise ValueError("Unknown or cross-call source evidence")
        for ref in edit.source_refs:
            if (
                ref.page_id not in occurrences[edit.occurrence_id].page_ids
                or pages[ref.page_id].document_id != edit.document_id
            ):
                raise ValueError("Unknown or cross-occurrence source page")
        if revision.kind == "source_correction" and (
            not edit.source_refs or not edit.rationale.strip()
        ):
            raise ValueError("Source corrections require page/quote source evidence and rationale")


def _parse_corridor_request(raw_request_json: str) -> CorridorRequest:
    from .relative import _invalid_number, _unique_object

    payload = parse_json(
        raw_request_json, object_pairs_hook=_unique_object, parse_constant=_invalid_number
    )
    return CorridorRequest.model_validate(payload)


def _corridor_identity(request: CorridorRequest) -> tuple[Any, ...]:
    centerline = request.centerline

    def source_identity(reference: Any) -> tuple[Any, ...]:
        return (
            reference.source_id,
            reference.source_sha256,
            reference.occurrence_id,
            reference.page,
            reference.page_id,
            reference.crop_id,
            reference.span_id,
        )

    return (
        request.id,
        centerline.calculation_id,
        tuple(
            sorted(
                (call.id, call.occurrence_id, call.page_id, call.source_reference)
                for call in centerline.calls
            )
        ),
        tuple(sorted(width.id for width in request.widths)),
        tuple(
            sorted(
                (
                    width.id,
                    tuple(sorted(source_identity(ref) for ref in width.source_refs)),
                )
                for width in request.widths
            )
        ),
        tuple(sorted(source_identity(ref) for ref in request.construction_source_refs)),
    )


def _validate_corridor_inventory(
    revision: DashboardRevision, parent: PreparedRevision | None
) -> None:
    current = {corridor.id: corridor for corridor in revision.corridors}
    for corridor in revision.corridors:
        if corridor.action == "retain":
            try:
                request = _parse_corridor_request(corridor.raw_request_json)
            except (ValueError, TypeError, KeyError):
                continue
            if request.id != corridor.id:
                raise ValueError("Corridor request ID must match its stable revision ID")
    if parent is None:
        if revision.parent_revision_id is None and any(
            corridor.action == "remove" for corridor in revision.corridors
        ):
            raise ValueError("Corridor removal requires a parent corridor definition")
        return
    previous = {corridor.id: corridor for corridor in parent.revision.corridors}
    if not previous:
        if any(corridor.action == "remove" for corridor in revision.corridors):
            raise ValueError("Corridor removal requires a parent corridor definition")
        return
    if revision.schema_version != "1.2":
        raise ValueError("Parent corridor inventory requires revision schema 1.2")
    missing = set(previous) - set(current)
    if missing:
        raise ValueError("Revision corridor inventory is incomplete; use explicit remove")
    for corridor_id, old in previous.items():
        new = current[corridor_id]
        if new.action == "remove":
            if new.raw_request_json != old.raw_request_json:
                raise ValueError("Corridor removal tombstone must retain the original definition")
            continue
        if old.action == "remove":
            raise ValueError("Removed corridor identity cannot be reused")
        try:
            old_request = _parse_corridor_request(old.raw_request_json)
            new_request = _parse_corridor_request(new.raw_request_json)
        except (ValueError, TypeError, KeyError):
            # An incomplete edit remains an isolated draft; it cannot be delivered.
            continue
        if new_request.id != new.id or _corridor_identity(old_request) != _corridor_identity(
            new_request
        ):
            raise ValueError("Corridor identity or centerline provenance cannot be rebound")


def _prepare_corridors(revision: DashboardRevision) -> tuple[PreparedRevisionCorridor, ...]:
    from mp_verify.corridor import analyze_corridor, validate_corridor_result

    output = []
    for entry in revision.corridors:
        if entry.action == "remove":
            continue
        try:
            request = _parse_corridor_request(entry.raw_request_json)
            if request.id != entry.id:
                raise ValueError("Corridor request ID must match its stable revision ID")
            result = validate_corridor_result(analyze_corridor(request))
            supported = result.availability == "supported"
            output.append(
                PreparedRevisionCorridor(
                    id=entry.id,
                    state="computed" if supported else "draft",
                    request=request,
                    result=result,
                    reasons=() if supported else result.limitations[-1:],
                )
            )
        except (ValueError, TypeError, KeyError) as exc:
            output.append(
                PreparedRevisionCorridor(
                    id=entry.id,
                    state="draft",
                    reasons=(str(exc),),
                )
            )
    return tuple(output)


def _plots(
    bundle: DashboardBundle,
    revision: DashboardRevision | None,
    values: dict[str, dict[str, Any]],
    prepared_calls: tuple[RevisionPreparedCall, ...] = (),
) -> tuple[RevisionGeometry, ...]:
    tracts = {t.occurrence_id: t for t in revision.tracts} if revision else {}
    records = {c.id: c for c in bundle.calls}
    output = []
    for calculation in bundle.calculations:
        tract = tracts.get(calculation.occurrence_id)
        if tract and tract.action == "remove":
            continue
        order = (
            tract.call_order
            if tract
            else tuple(c.id for c in bundle.calls if c.occurrence_id == calculation.occurrence_id)
        )
        if not order:
            raise ValueError("No calls remain for retained tract")
        plot_calls = []
        prepared_by_id = {c.id: c for c in prepared_calls}
        for cid in order:
            if cid in prepared_by_id:
                item = prepared_by_id[cid]
                if item.removed or item.role in ("reference", "omitted"):
                    continue
                plot_calls.append(
                    PlotCall(
                        id=cid,
                        call=item.call,
                        occurrence_id=item.occurrence_id,
                        page_id=item.page_id,
                        quote=item.quote or "",
                    )
                )
            else:
                record = records[cid]
                plot_calls.append(
                    PlotCall(
                        id=cid,
                        call=record.call,
                        occurrence_id=record.occurrence_id,
                        page_id=record.page_id,
                        quote=record.quote,
                    )
                )
        relative = calculation.relative
        if relative is not None:
            data = relative.model_dump(mode="json")
            if order != tuple(c.course_id for c in relative.courses) or (
                revision
                and any(
                    e.structured_input is not None
                    for e in revision.edits
                    if e.occurrence_id == calculation.occurrence_id
                )
            ):
                raise ValueError("Relative call remove/reorder requires fresh explicit constraints")
            for course in data["courses"]:
                edits = values.get(course["course_id"], {})
                if "bearing_azimuth_deg_from_north" in edits:
                    raise ValueError(
                        "Recorded-bearing edit cannot replace a relative angular constraint"
                    )
                if "distance_ft" in edits:
                    course["distance_ft"] = edits["distance_ft"]
                if "interior_angle_deg" in edits:
                    matches = [
                        c
                        for c in data["constraints"]
                        if c["kind"] == "interior" and c["to_course"] == course["course_id"]
                    ]
                    if len(matches) != 1:
                        raise ValueError("Angle edit requires one explicit interior constraint")
                    matches[0]["angle_deg"] = edits["interior_angle_deg"]
            relative = RelativeDescription.model_validate(data)
        elif any("interior_angle_deg" in values.get(cid, {}) for cid in order):
            raise ValueError("Angle edit requires an explicit relative interior constraint")
        plot = prepare_plot(
            PlotRequest(
                title=revision.label if revision else bundle.title,
                calculation_id=calculation.id,
                calls=tuple(plot_calls),
                foot_definition=calculation.frame.foot_definition,
                relative=relative,
            )
        )
        output.append(
            RevisionGeometry(
                revision_id=revision.id if revision else "baseline",
                calculation_id=calculation.id,
                plot=plot,
            )
        )
    return tuple(output)


def _comparisons(
    bundle: DashboardBundle, revision: DashboardRevision, geometry: tuple[RevisionGeometry, ...]
) -> tuple[RevisionComparison, ...]:
    plots = {g.calculation_id: g.plot for g in geometry}
    output = []
    for spec in bundle.description_comparison_specs:
        try:
            if spec.left_placement_id or spec.right_placement_id or spec.scene_id:
                raise ValueError(
                    "Revised geometry invalidates placement-dependent comparison; fresh placement required"
                )
            if spec.left_calculation_id not in plots or spec.right_calculation_id not in plots:
                raise ValueError(
                    "Current draft or removed tract has no current geometry to compare"
                )
            request = ComparisonRequest(
                left=ComparisonDescription(
                    id=spec.left_calculation_id,
                    plot=plots[spec.left_calculation_id].request,
                    bearing_basis=spec.left_bearing_basis,
                ),
                right=ComparisonDescription(
                    id=spec.right_calculation_id,
                    plot=plots[spec.right_calculation_id].request,
                    bearing_basis=spec.right_bearing_basis,
                ),
                pairs=spec.pairs,
                tolerances=spec.tolerances,
                right_to_left_transform=spec.right_to_left_transform,
            )
            output.append(
                RevisionComparison(
                    id=spec.id, revision_id=revision.id, comparison=compare_descriptions(request)
                )
            )
        except ValueError as exc:
            output.append(
                RevisionComparison(id=spec.id, revision_id=revision.id, unavailable_reason=str(exc))
            )
    return tuple(output)


def import_revision(
    bundle: DashboardBundle,
    payload: DashboardRevision | dict[str, Any] | str | bytes,
    *,
    expected_revision_id: str | None = None,
    expected_generation: int | None = None,
    last_valid: PreparedRevision | None = None,
) -> PreparedRevision:
    """Validate an envelope; domain-invalid form values remain an exact recoverable draft."""
    if isinstance(payload, (str, bytes)):
        from .relative import _invalid_number, _unique_object

        payload = parse_json(
            payload, object_pairs_hook=_unique_object, parse_constant=_invalid_number
        )
    if isinstance(payload, DashboardRevision):
        payload = payload.model_dump(mode="json")
    revision = DashboardRevision.model_validate(payload)
    if expected_revision_id is not None and revision.id != expected_revision_id:
        raise ValueError("Save revision identity is stale or mismatched")
    if expected_generation is not None and revision.generation != expected_generation:
        raise ValueError("Save generation is stale or mismatched")
    _validate_identities(bundle, revision)
    values: dict[str, dict[str, Any]] = {}
    errors = []
    parsed = []
    source_changes = []
    records = {c.id: c for c in bundle.calls}
    for edit in revision.edits:
        if edit.action == "remove" or edit.structured_input is not None:
            continue
        numeric: dict[str, Any] = {}
        for field, raw in edit.raw_fields.items():
            if field == "notes":
                numeric[field] = raw
                continue
            try:
                numeric[field] = _number(raw, field)
            except ValueError as exc:
                errors.append(RevisionError(call_id=edit.call_id, field=field, message=str(exc)))
        values[edit.call_id] = numeric
        geometry_edits = {k: v for k, v in numeric.items() if k != "notes"}
        if geometry_edits:
            parsed.append(
                DashboardEdit(
                    call_id=edit.call_id,
                    rationale=edit.rationale or "Unresolved draft rationale",
                    evidence_ids=edit.evidence_ids,
                    **geometry_edits,
                )
            )
    prepared_calls = _prepare_calls(bundle, revision, values, errors)
    if revision.kind == "source_correction":
        prepared_by_id = {c.id: c for c in prepared_calls}
        for edit in revision.edits:
            old = records.get(edit.call_id)
            current_call = prepared_by_id[edit.call_id]
            source_changes.append(
                RevisionSourceChange(
                    call_id=edit.call_id,
                    previous_quote=old.quote if old else "",
                    revised_quote="\n".join(ref.quote for ref in edit.source_refs),
                    previous_call=old.call if old else None,
                    revised_call=None if edit.action == "remove" else current_call.call,
                    source_refs=edit.source_refs,
                )
            )
    fallback: tuple[RevisionGeometry, ...] = ()
    if last_valid is not None:
        if (
            last_valid.revision.baseline != revision.baseline
            or revision.parent_revision_id != last_valid.revision.id
        ):
            raise ValueError("Last-valid geometry must belong to the explicit parent revision")
    _validate_corridor_inventory(revision, last_valid)
    corridor_results = _prepare_corridors(revision)
    if last_valid is not None:
        candidates = last_valid.current_geometry or last_valid.last_valid_geometry
        for geometry in candidates:
            validate_prepared_plot(geometry.plot)
        fallback = candidates
    else:
        try:
            fallback = tuple(
                g.model_copy(update={"revision_id": revision.baseline.id})
                for g in _plots(bundle, None, {})
                if _supported_geometry(g)
            )
        except ValueError:
            pass  # Baseline itself can have unresolved geometry.
    current: tuple[RevisionGeometry, ...] = ()
    if not errors:
        try:
            current = _plots(bundle, revision, values, prepared_calls)
            if not all(_supported_geometry(g) for g in current):
                raise ValueError("Current revision geometry is incomplete or unsupported")
        except ValueError as exc:
            errors.append(RevisionError(field="geometry", message=str(exc)))
    return PreparedRevision(
        revision=revision,
        state="draft" if errors else "parsed",
        errors=tuple(errors),
        parsed_edits=tuple(parsed),
        prepared_calls=prepared_calls,
        current_geometry=current if not errors else (),
        last_valid_geometry=fallback,
        source_changes=tuple(source_changes),
        comparisons=_comparisons(bundle, revision, current if not errors else ()),
        corridor_results=corridor_results,
    )


def _write_once(path: Path, content: bytes) -> None:
    """Atomic no-replace link, with exact-content retry and durable directory entries."""
    if path.is_symlink():
        raise ValueError("Symlink revision artifact refused")
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"Immutable revision artifact conflict: {path.name}")
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != content:
                raise ValueError(f"Immutable revision artifact conflict: {path.name}") from None
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _revision_payload(revision: DashboardRevision) -> dict[str, Any]:
    payload = revision.model_dump(mode="json")
    if revision.schema_version in {"1.0", "1.1"}:
        payload.pop("corridors", None)
    return payload


def _prepared_revision_payload(prepared: PreparedRevision) -> dict[str, Any]:
    payload = prepared.model_dump(mode="json")
    if prepared.revision.schema_version in {"1.0", "1.1"}:
        payload.pop("corridor_results", None)
        payload["revision"].pop("corridors", None)
    return payload


def _artifacts(bundle: DashboardBundle, prepared: PreparedRevision) -> dict[str, Any]:
    revision_payload = _revision_payload(prepared.revision)
    artifacts = {
        "pending.json": {
            "revision_id": prepared.revision.id,
            "generation": prepared.revision.generation,
            "revision_hash": _hash(revision_payload),
            "revision": revision_payload,
        },
        "revision.json": revision_payload,
        "prepared-revision.json": _prepared_revision_payload(prepared),
    }
    if prepared.revision.schema_version == "1.2":
        results = {item.id: item for item in prepared.corridor_results}
        artifacts["corridors.json"] = {
            "revision_id": prepared.revision.id,
            "generation": prepared.revision.generation,
            "corridors": [
                {
                    "id": item.id,
                    "action": item.action,
                    "raw_request_json": item.raw_request_json,
                    "prepared": results[item.id].model_dump(mode="json")
                    if item.id in results
                    else None,
                }
                for item in prepared.revision.corridors
            ],
        }
    for tract in prepared.revision.tracts:
        artifacts[f"tract-{tract.occurrence_id}.json"] = {
            "tract": tract.model_dump(mode="json"),
            "edits": [
                e.model_dump(mode="json")
                for e in prepared.revision.edits
                if e.occurrence_id == tract.occurrence_id
            ],
        }
    if prepared.revision.kind == "source_correction":
        artifacts["correction-evidence.json"] = {
            "schema_version": "1.0",
            "kind": "supplied-correction-excerpts",
            "baseline": prepared.revision.baseline.model_dump(mode="json"),
            "revision_id": prepared.revision.id,
            "source_review_status": "unreviewed",
            "state": prepared.state,
            "changes": [c.model_dump(mode="json") for c in prepared.source_changes],
        }
        revised = []
        for call in prepared.prepared_calls:
            if call.removed:
                continue
            data = (
                dict(call.original_source)
                if call.original_source
                else {
                    "id": call.id,
                    "occurrence_id": call.occurrence_id,
                    "page_id": call.page_id,
                    "quote": call.quote or "",
                    "reading_status": "uncertain",
                    "reading_note": "Supplied transcription correction; source review required",
                }
            )
            data.update(call=call.call.model_dump(mode="json") if call.call else None)
            if call.source_status == "source_correction":
                data.update(
                    quote=call.quote or "",
                    page_id=call.page_id,
                    reading_status="uncertain",
                    reading_note="Supplied transcription correction; source review required",
                )
            revised.append(data)
        artifacts["source-calls.json"] = {
            "revision_id": prepared.revision.id,
            "canonical_verification": "not_requested",
            "state": prepared.state,
            "original_calls": [c.model_dump(mode="json") for c in bundle.calls],
            "revised_calls": revised if prepared.state == "parsed" else None,
            "prepared_calls": [c.model_dump(mode="json") for c in prepared.prepared_calls],
            "source_review_status": "unreviewed",
            "baseline": prepared.revision.baseline.model_dump(mode="json"),
        }
    return artifacts


def publish_revision(
    bundle: DashboardBundle,
    payload: DashboardRevision | dict[str, Any] | str | bytes,
    output_dir: Path | str,
    *,
    expected_revision_id: str | None = None,
    expected_generation: int | None = None,
) -> dict[str, Any]:
    """Publish an immutable revision; failed/incomplete attempts can retry exact input."""
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "operation": "save-revision",
        "status": "error",
        "save_state": "failed",
        "errors": [],
        "artifacts": {},
    }
    try:
        # Validate before any writes. Parent lookup supplies independently labeled fallback.
        prepared = import_revision(
            bundle,
            payload,
            expected_revision_id=expected_revision_id,
            expected_generation=expected_generation,
        )
        revision = prepared.revision
        result.update(revision_id=revision.id, generation=revision.generation)
        root = Path(output_dir)
        if root.is_symlink():
            raise ValueError("Revision store must not be a symlink")
        root.mkdir(parents=True, exist_ok=True)
        if revision.parent_revision_id:
            parent = load_revision(bundle, root / revision.parent_revision_id)
            prepared = import_revision(bundle, revision, last_valid=parent)
        directory = root / revision.id
        if directory.is_symlink():
            raise ValueError("Revision directory must not be a symlink")
        directory.mkdir(exist_ok=True)
        _write_once(
            directory / "pending.json",
            _json(
                {
                    "revision_id": revision.id,
                    "generation": revision.generation,
                    "revision_hash": _hash(_revision_payload(revision)),
                    "revision": _revision_payload(revision),
                }
            ).encode("utf-8"),
        )
        artifacts = _artifacts(bundle, prepared)
        hashes = {}
        for name, data in artifacts.items():
            content = _json(data).encode("utf-8")
            _write_once(directory / name, content)
            hashes[name] = hashlib.sha256(content).hexdigest()
        manifest = {
            "schema_version": "1.0",
            "save_state": "published",
            "revision_id": revision.id,
            "generation": revision.generation,
            "baseline": revision.baseline.model_dump(mode="json"),
            "revision_hash": _hash(_revision_payload(revision)),
            "artifacts": hashes,
        }
        _write_once(directory / "manifest.json", _json(manifest).encode("utf-8"))
        result.update(
            status="needs_review",
            save_state="published",
            state=prepared.state,
            manifest=str(directory / "manifest.json"),
            artifacts={name: str(directory / name) for name in hashes},
            draft_errors=[e.model_dump(mode="json") for e in prepared.errors],
            exportable=False,
            canonical_status_changed=False,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result["errors"].append(str(exc))
    return result


def load_revision(
    bundle: DashboardBundle, directory: Path | str, *, _visited: frozenset[str] = frozenset()
) -> PreparedRevision:
    """Require a complete manifest and replay every artifact from the baseline."""
    path = Path(directory)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Revision directory unavailable or unsafe")
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Revision publication incomplete: manifest is missing")
    if manifest_path.is_symlink():
        raise ValueError("Unsafe revision manifest")
    manifest = _load(manifest_path)
    try:
        manifest = RevisionManifest.model_validate(manifest).model_dump(mode="json")
    except ValueError as exc:
        raise ValueError("Malformed revision manifest schema") from exc
    for name, digest in manifest["artifacts"].items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]*\.json", name):
            raise ValueError("Unsafe revision artifact name")
        artifact = path / name
        if artifact.is_symlink() or not artifact.is_file():
            raise ValueError("Revision publication incomplete or unsafe artifact")
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != digest:
            raise ValueError("Revision artifact hash mismatch")
    revision = DashboardRevision.model_validate(_load(path / "revision.json"))
    if (
        revision.id != manifest["revision_id"]
        or revision.generation != manifest["generation"]
        or revision.baseline.model_dump(mode="json") != manifest["baseline"]
        or _hash(_revision_payload(revision)) != manifest["revision_hash"]
    ):
        raise ValueError("Revision manifest identity/hash mismatch")
    if revision.id in _visited or len(_visited) > 100:
        raise ValueError("Revision parent cycle or excessive chain")
    parent = None
    if revision.parent_revision_id:
        parent = load_revision(
            bundle, path.parent / revision.parent_revision_id, _visited=_visited | {revision.id}
        )
    fresh = import_revision(bundle, revision, last_valid=parent)
    expected = _artifacts(bundle, fresh)
    if set(expected) != set(manifest["artifacts"]):
        raise ValueError("Revision manifest artifact inventory mismatch")
    for name, data in expected.items():
        if _json(data).encode("utf-8") != (path / name).read_bytes():
            raise ValueError("Revision artifact differs from fresh deterministic replay")
    return fresh
