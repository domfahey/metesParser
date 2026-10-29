"""Rectangular equal-fraction reference geometry, never legal PLSS subdivision."""

import base64
import hashlib
import json
import math
from typing import Any

from mp_models.plot import MapSource, VectorLayer
from mp_models.plss import PLSSDerivationRequest, PLSSDerivationResult

from .scene import validate_scene

LIMITATIONS = (
    "Computed reference geometry only; supplied authority and corner accuracy are not independently established.",
    "rectangular_aliquot_v1 divides supplied named SW→SE and SW→NW axes into equal fractions, outermost step first.",
    "This is not a surveyed legal subdivision or a BLM subdivision rule; no nominal section area is assumed.",
    "Rectangle consistency uses numerical roundoff tolerance only, not a survey accuracy tolerance.",
    "No canonical deed verification or verified-export eligibility is established.",
)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _hash(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def derive_plss(request: PLSSDerivationRequest) -> PLSSDerivationResult:
    """Reject malformed schemas, then return unsupported domain evidence without geometry."""
    request = PLSSDerivationRequest.model_validate(request.model_dump(mode="json"))
    dataset = request.dataset
    limitations = (
        LIMITATIONS
        + (() if dataset.source.source_date else ("Supplied source date is unknown.",))
        + (
            ()
            if dataset.source.data_base64
            else (
                "Supplied source bytes are unavailable; the declared source hash cannot be replayed here.",
            )
        )
    )
    common: dict[str, Any] = {
        "input_hash": _hash(request.model_dump(mode="json")),
        "dataset_hash": _hash(dataset.model_dump(mode="json")),
        "source_hash": dataset.source.sha256,
        "dataset_id": request.selected_dataset_id,
        "reference_id": request.selected_reference_id,
        "section": request.section,
        "rule": request.rule,
        "aliquot_steps": request.aliquot_steps,
        "limitations": limitations,
    }
    try:
        if request.selected_dataset_id != dataset.id:
            raise ValueError("selected dataset identity does not match supplied dataset")
        selected = [r for r in dataset.references if r.id == request.selected_reference_id]
        if len(selected) != 1:
            raise ValueError("selected reference identity is absent or ambiguous")
        ref = selected[0]
        if ref.section != request.section:
            raise ValueError("selected section identity does not match the exact reference")
        if ref.subdivision_class != "rectangular":
            raise ValueError(f"unsupported subdivision class: {ref.subdivision_class}")
        scene = dataset.scene
        if scene.kind != "projected" or scene.units == "unknown_ft" or scene.basis != "grid":
            raise ValueError(
                "supplied reference requires explicit projected grid CRS and known units"
            )
        validate_scene(scene)
        source = dataset.source
        if source.native_crs != scene.crs or source.native_units != scene.units:
            raise ValueError(
                "conflicting source CRS/units; supply already compatible reference coordinates"
            )
        if len(ref.corners) != 4 or {c.name for c in ref.corners} != {"SW", "SE", "NE", "NW"}:
            raise ValueError("four uniquely named supplied corners SW, SE, NE, NW are required")
        if any(c.source_id != source.id for c in ref.corners):
            raise ValueError("conflicting corner source identities")
        points = {c.name: c.xy for c in ref.corners}
        sw, se, ne, nw = points["SW"], points["SE"], points["NE"], points["NW"]
        u = (se[0] - sw[0], se[1] - sw[1])
        v = (nw[0] - sw[0], nw[1] - sw[1])
        width, height = math.hypot(*u), math.hypot(*v)
        cross = u[0] * v[1] - u[1] * v[0]
        magnitude = max(abs(x) for p in points.values() for x in p)
        tolerance = max(64 * math.ulp(magnitude), max(width, height) * 1e-12)
        if not all(math.isfinite(k) for k in (*u, *v, width, height, cross, tolerance)):
            raise ValueError("nonfinite reference geometry arithmetic")
        if min(width, height) <= 1024 * tolerance or cross <= 0:
            raise ValueError("degenerate or incorrectly ordered named section corners")
        if abs(u[0] * v[0] + u[1] * v[1]) > tolerance * max(width, height):
            raise ValueError("irregular reference: supplied axes are not orthogonal")
        if math.hypot(ne[0] - (sw[0] + u[0] + v[0]), ne[1] - (sw[1] + u[1] + v[1])) > tolerance:
            raise ValueError(
                "irregular reference: opposite supplied corners do not form a rectangle"
            )
        lo_x, hi_x, lo_y, hi_y = 0.0, 1.0, 0.0, 1.0
        for step in request.aliquot_steps:
            mid_x, mid_y = (lo_x + hi_x) / 2, (lo_y + hi_y) / 2
            if "E" in step:
                lo_x = mid_x
            if "W" in step:
                hi_x = mid_x
            if "N" in step:
                lo_y = mid_y
            if "S" in step:
                hi_y = mid_y
        if min(width * (hi_x - lo_x), height * (hi_y - lo_y)) <= 1024 * tolerance:
            raise ValueError("derived aliquot dimensions are below supported coordinate precision")
        ring = tuple(
            (sw[0] + a * u[0] + b * v[0], sw[1] + a * u[1] + b * v[1])
            for a, b in ((lo_x, lo_y), (hi_x, lo_y), (hi_x, hi_y), (lo_x, hi_y), (lo_x, lo_y))
        )
        area = cross * (hi_x - lo_x) * (hi_y - lo_y)
        if not math.isfinite(area) or area <= 0:
            raise ValueError("unrepresentable derived reference area")
        # Retain computational request bytes and both identities in existing map provenance.
        raw = canonical_bytes(request.model_dump(mode="json"))
        derived_source = MapSource(
            id=f"plss-source-{common['input_hash'][:16]}",
            label="Computed PLSS reference input",
            sha256=hashlib.sha256(raw).hexdigest(),
            data_base64=base64.b64encode(raw).decode(),
            native_crs=scene.crs,
            native_units=scene.units,
            source_date=source.source_date,
            feature_ids=(ref.id,),
            processing_history=(
                f"supplied source id={source.id} sha256={source.sha256}",
                f"dataset id={dataset.id} version={dataset.version} sha256={common['dataset_hash']}",
                f"request sha256={common['input_hash']}; rectangular_aliquot_v1; computed_reference_geometry",
                dataset.authority_citation,
            ),
        )
        layer = VectorLayer(
            id=f"plss-layer-{common['input_hash'][:16]}",
            label=f"Computed reference {ref.id}: {' / '.join(request.aliquot_steps)}",
            source_id=derived_source.id,
            scene_id=scene.id,
            geometry_type="Polygon",
            coordinates=(ring,),
            feature_id=ref.id,
        )
        if len({scene.id, source.id, derived_source.id, layer.id}) != 4:
            raise ValueError("scene and map source/layer identities must be globally unique")
        return PLSSDerivationResult(
            **common,
            availability="computed",
            ring=ring,
            area_scene_units_squared=area,
            scenes=(scene,),
            map_sources=(source, derived_source),
            vector_layers=(layer,),
        )
    except (ValueError, ArithmeticError) as exc:
        return PLSSDerivationResult(**common, availability="unsupported", reason=str(exc))
