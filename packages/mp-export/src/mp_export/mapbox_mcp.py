"""Pure vector handoff for the pinned Mapbox MCP render tool."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from mp_models.dashboard import PreparedDashboard
from mp_models.webmap import StandaloneWebMapInput, WebMapArtifact
from mp_verify.webmap import validate_web_map_artifact

ADAPTER_VERSION = "mapbox-mcp-1.0.0"
UPSTREAM_CONTRACT_SHA = "6ee4589df5433234969bc525d9342bb7210a529f"
MAX_PAYLOAD_BYTES = 48 * 1024
_PROPERTIES = (
    "kind",
    "calculation_id",
    "call_id",
    "occurrence_id",
    "page_id",
    "source_id",
    "layer_id",
    "geometry_hash",
    "placement_hash",
    "placement_id",
    "placement_status",
    "completeness",
)
_LAYERS = (
    (
        "parcel_context",
        "parcel-context",
        "fill",
        "Supplied parcel context",
        "#9333ea",
        {"fill-color": "#9333ea", "fill-opacity": 0.15, "fill-outline-color": "#9333ea"},
    ),
    (
        "recorded_course",
        "recorded-courses",
        "line",
        "Recorded courses",
        "#2563eb",
        {"line-color": "#2563eb", "line-width": 3},
    ),
    (
        "closure_gap",
        "closure-gaps",
        "line",
        "Closure gap (annotation)",
        "#dc2626",
        {"line-color": "#dc2626", "line-width": 2, "line-dasharray": [2, 2]},
    ),
    (
        "pob",
        "points-of-beginning",
        "circle",
        "Point of beginning",
        "#16a34a",
        {"circle-color": "#16a34a", "circle-radius": 5},
    ),
)


def _compact(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_compact(value)).hexdigest()


def build_mapbox_mcp_handoff(
    prepared: PreparedDashboard | StandaloneWebMapInput,
    artifact: WebMapArtifact,
    *,
    style: str = "standard",
) -> dict[str, Any]:
    """Copy validated geographic vectors without projection or provider activation.

    The conservative budget includes upstream's default empty markers array.
    Oversized evidence is refused whole, never simplified or truncated.
    """
    if not isinstance(style, str) or style not in {"standard", "standard-satellite"}:
        raise ValueError("Unsupported Mapbox MCP base style")
    artifact = validate_web_map_artifact(prepared, artifact)
    omissions = [item.model_dump(mode="json") for item in artifact.unavailable]
    omissions.extend(
        {
            "item_id": raster.id,
            "kind": "raster",
            "code": "mcp_raster_omitted",
            "reason": "Raster remains in the existing online/offline review viewer.",
        }
        for raster in artifact.rasters
    )
    layers: list[dict[str, Any]] = []
    legend: list[dict[str, Any]] = []
    for kind, layer_id, layer_type, label, color, paint in _LAYERS:
        features = []
        for feature in artifact.features:
            if feature.properties.kind != kind:
                continue
            props = feature.properties.model_dump(mode="json")
            features.append(
                {
                    "type": "Feature",
                    "id": feature.id,
                    "geometry": feature.geometry.model_dump(mode="json"),
                    "properties": {
                        key: props[key] for key in _PROPERTIES if props[key] is not None
                    },
                }
            )
        if features:
            layers.append(
                {
                    "id": layer_id,
                    "type": layer_type,
                    "data": {"type": "FeatureCollection", "features": features},
                    "paint": json.loads(_compact(paint)),
                }
            )
            legend.append({"label": label, "color": color, "opacity": 1})
    availability = "partial" if layers and omissions else "ready" if layers else "unavailable"
    summary = "Visualization only; no verified status is granted."
    if availability == "partial":
        summary += " Partial evidence: unavailable items are omitted."
    elif availability == "unavailable":
        summary += " No geographic vector evidence is available for this handoff."
    if any(f.properties.placement_status == "approximate" for f in artifact.features):
        summary += " Deed placement is approximate."
    if artifact.rasters:
        summary += (
            " Raster scans are omitted; use the existing review viewer for scans and source pages."
        )
    arguments = (
        {"summary": summary, "baseStyle": style, "layers": layers, "legend": legend}
        if layers
        else None
    )
    if arguments is not None and len(_compact({**arguments, "markers": []})) > MAX_PAYLOAD_BYTES:
        omissions.append(
            {
                "item_id": artifact.scene_id,
                "kind": "scene",
                "code": "payload_too_large",
                "reason": "Vector payload exceeds the conservative 48 KiB budget; no geometry was sent or simplified.",
            }
        )
        arguments = None
        availability = "unavailable"
        summary += " MCP handoff unavailable: vector payload exceeds the size budget."
    return {
        "schema_version": "1.0",
        "status": "needs_review",
        "verified_export_eligible": False,
        "availability": availability,
        "summary": summary,
        "tool_name": "render_map_tool",
        "arguments": arguments,
        "arguments_sha256": _digest(arguments) if arguments is not None else None,
        "omissions": omissions,
        "provenance": {
            "input_hashes": dict(artifact.input_hashes),
            "artifact_sha256": _digest(artifact.model_dump(mode="json")),
            "upstream_contract_sha": UPSTREAM_CONTRACT_SHA,
            "adapter_version": ADAPTER_VERSION,
            "scene_id": artifact.scene_id,
            "counts": {
                "vector_features": len(artifact.features),
                "layers": len(layers),
                "omitted_rasters": len(artifact.rasters),
                "unavailable_items": len(artifact.unavailable),
            },
        },
    }
