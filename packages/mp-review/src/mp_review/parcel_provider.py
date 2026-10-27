"""Explicit NJOGIS assessment-parcel snapshots; never used as legal boundaries.

Official NJGIN parcels page links ArcGIS item 533599bbfbaa4748bf39faf1375a8a9c.
Endpoint and identifier schema inspected 2026-10-27. Schema is checked each fetch.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlencode
from urllib.request import urlopen

from .overlays import MAX_IMPORT_BYTES, import_overlay

SERVICE = "https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/Parcels_Composite_NJ_WM/FeatureServer/0"
FIELDS = ("OBJECTID", "PAMS_PIN", "PCL_MUN", "PCLBLOCK", "PCLLOT", "PCLQCODE", "PCLLASTUPD")
DISCLAIMER = (
    "Assessment/context evidence only: NJGIN parcels are not survey data or legal boundaries."
)


def _get(url: str, params: dict[str, Any]) -> bytes:
    with urlopen(url + "?" + urlencode(params), timeout=30) as response:
        raw = response.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValueError("Provider response exceeds 20 MiB limit")
    return cast(bytes, raw)


def fetch_njgin(
    *,
    municipality: str,
    block: str,
    lot: str,
    target_crs: str,
    qualifier: str | None = None,
    feature_id: str | None = None,
    fetch: Callable[[str, dict[str, Any]], bytes] | None = None,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Snapshot every exact official-code match; ambiguity requires explicit selection.

    First snapshot all matching object IDs, then paginate bounded ID batches. Every
    returned ID and selector must match; incomplete responses never select a parcel.
    """
    if not re.fullmatch(r"\d{4}", municipality):
        raise ValueError("municipality must be the four-digit official PCL_MUN code")
    for name, value in [("block", block), ("lot", lot), ("qualifier", qualifier)]:
        if value is not None and (
            (name != "qualifier" and not value.strip())
            or len(value) > 80
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError(f"Invalid {name} identifier")
    fetch = fetch or _get
    retrieved_at = retrieved_at or datetime.now(UTC).isoformat()
    responses: list[dict[str, Any]] = []
    retained_size = 0

    def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        nonlocal retained_size
        try:
            raw = fetch(url, params)
            retained_size += len(raw)
            if retained_size > MAX_IMPORT_BYTES:
                raise ValueError("Provider response exceeds import limit")
            value = json.loads(raw)
            if not isinstance(value, dict) or "error" in value:
                raise ValueError("Provider returned an error or malformed response")
        except (OSError, ValueError, TimeoutError) as exc:
            raise ValueError(f"NJGIN request failed: {exc}") from exc
        responses.append(
            {
                "url": url,
                "query": params,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "data_base64": base64.b64encode(raw).decode(),
            }
        )
        return cast(dict[str, Any], value)

    schema = request(SERVICE, {"f": "json"})
    names = {f.get("name") for f in schema.get("fields", []) if isinstance(f, dict)}
    sr = schema.get("extent", {}).get("spatialReference", {})
    wkid = sr.get("latestWkid", sr.get("wkid"))
    if (
        not set(FIELDS) <= names
        or schema.get("objectIdField") != "OBJECTID"
        or schema.get("geometryType") != "esriGeometryPolygon"
        or not isinstance(wkid, int)
    ):
        raise ValueError("NJGIN schema changed: identifier fields, polygon type, or CRS missing")
    try:
        page_size = min(int(schema.get("maxRecordCount", 100)), 100)
    except (ValueError, TypeError) as exc:
        raise ValueError("NJGIN schema invalid page size") from exc
    if page_size < 1:
        raise ValueError("NJGIN schema invalid page size")
    selectors = {"PCL_MUN": municipality, "PCLBLOCK": block, "PCLLOT": lot}
    if qualifier is not None:
        selectors["PCLQCODE"] = qualifier
    where = " AND ".join(
        f"{key} = '{value.replace(chr(39), chr(39) * 2)}'" for key, value in selectors.items()
    )
    id_response = request(
        SERVICE + "/query", {"f": "json", "where": where, "returnIdsOnly": "true"}
    )
    ids = id_response.get("objectIds")
    if "objectIds" not in id_response or id_response.get("objectIdFieldName") != "OBJECTID":
        raise ValueError("Incomplete provider object-ID snapshot")
    if ids is None:
        ids = []
    if (
        not isinstance(ids, list)
        or any(type(i) is not int or i < 0 for i in ids)
        or len(set(ids)) != len(ids)
        or len(ids) > 1000
        or id_response.get("exceededTransferLimit")
    ):
        raise ValueError("Incomplete/unsupported provider object-ID snapshot")
    ids = sorted(ids)
    features = []
    feature_responses: dict[str, dict[str, Any]] = {}
    for start in range(0, len(ids), page_size):
        chunk = ids[start : start + page_size]
        page = request(
            SERVICE + "/query",
            {
                "f": "geojson",
                "objectIds": ",".join(map(str, chunk)),
                "outFields": ",".join(FIELDS),
                "returnGeometry": "true",
                "outSR": "4326",
            },
        )
        values = page.get("features")
        if "crs" in page and page["crs"] not in (
            {"type": "name", "properties": {"name": "EPSG:4326"}},
            {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
            {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::4326"}},
        ):
            raise ValueError("Provider response CRS conflicts with requested WGS84 XY coordinates")
        if (
            page.get("type") != "FeatureCollection"
            or not isinstance(values, list)
            or page.get("exceededTransferLimit")
        ):
            raise ValueError("Incomplete provider geometry page")
        seen = []
        for feature in values:
            if not isinstance(feature, dict) or not isinstance(feature.get("properties"), dict):
                raise ValueError("Provider geometry feature schema changed")
            properties = feature.get("properties", {})
            object_id = properties.get("OBJECTID")
            if (
                type(object_id) is not int
                or object_id not in chunk
                or any(str(properties.get(key)) != value for key, value in selectors.items())
            ):
                raise ValueError("Provider returned a different parcel identifier/municipality")
            seen.append(object_id)
            feature = dict(feature)
            feature["id"] = str(object_id)
            features.append(feature)
            feature_responses[str(object_id)] = responses[-1]
        if sorted(seen) != chunk:
            raise ValueError("Incomplete or duplicate provider page")
    if features:
        # Ambiguous snapshots must still contain valid polygons; selection never
        # turns malformed provider geometry into usable map evidence.
        import_overlay(
            json.dumps({"type": "FeatureCollection", "features": features}).encode(),
            input_format="geojson",
            target_crs=target_crs,
            filename="njgin-candidates.geojson",
        )
    candidates = [
        {
            "object_id": str(f["properties"]["OBJECTID"]),
            **{key: f["properties"].get(key) for key in FIELDS[1:]},
        }
        for f in features
    ]
    selected = None
    if feature_id is not None:
        selected = next((f for f in features if f["id"] == feature_id), None)
        if selected is None:
            raise ValueError("Selected feature ID is not an exact query candidate")
    elif len(features) == 1:
        selected = features[0]
    overlay = None
    if selected:
        raw = json.dumps(
            {"type": "FeatureCollection", "features": [selected]}, sort_keys=True
        ).encode()
        imported = import_overlay(
            raw, input_format="geojson", target_crs=target_crs, filename="njgin-selected.geojson"
        )
        date = selected["properties"].get("PCLLASTUPD")
        source_date = (
            datetime.fromtimestamp(date / 1000, UTC).isoformat()
            if isinstance(date, (int, float))
            else None
        )
        source = imported.source.model_copy(
            update={
                "url": SERVICE,
                "provider": "NJOGIS / NJGIN",
                "retrieved_at": retrieved_at,
                "source_date": source_date,
                "sha256": feature_responses[selected["id"]]["sha256"],
                "data_base64": feature_responses[selected["id"]]["data_base64"],
                "processing_history": imported.source.processing_history
                + (
                    DISCLAIMER,
                    f"Native service CRS EPSG:{wkid}; requested RFC7946 WGS84 XY response; exact query: {where}",
                    json.dumps(
                        {
                            "retained_requests": [
                                {k: v for k, v in response.items() if k != "data_base64"}
                                for response in responses
                            ]
                        },
                        sort_keys=True,
                    ),
                ),
            }
        )
        overlay = replace(
            imported,
            source=source,
            original_bytes=base64.b64decode(feature_responses[selected["id"]]["data_base64"]),
        ).to_dict()
    return {
        "schema_version": "1.1",
        "status": "selected"
        if selected and feature_id is not None
        else "unique"
        if selected
        else "ambiguous"
        if features
        else "empty",
        "query": selectors,
        "service_url": SERVICE,
        "service_native_crs": f"EPSG:{wkid}",
        "retrieved_at": retrieved_at,
        "source_date": None if overlay is None else overlay["map_sources"][0]["source_date"],
        "disclaimer": DISCLAIMER,
        "candidates": candidates,
        "responses": responses,
        "overlay": overlay,
    }
