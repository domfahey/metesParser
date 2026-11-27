import json

import pytest
from mp_review.parcel_provider import fetch_njgin

SCHEMA = {
    "objectIdField": "OBJECTID",
    "geometryType": "esriGeometryPolygon",
    "extent": {"spatialReference": {"wkid": 102100, "latestWkid": 3857}},
    "maxRecordCount": 1,
    "fields": [
        {"name": n}
        for n in ("OBJECTID", "PAMS_PIN", "PCL_MUN", "PCLBLOCK", "PCLLOT", "PCLQCODE", "PCLLASTUPD")
    ],
}


def feature(i, municipality="0101"):
    return {
        "type": "Feature",
        "id": i,
        "properties": {
            "OBJECTID": i,
            "PAMS_PIN": f"{municipality}_1_2",
            "PCL_MUN": municipality,
            "PCLBLOCK": "1",
            "PCLLOT": "2",
            "PCLQCODE": "",
            "PCLLASTUPD": None,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[-74, 40], [-73.999, 40], [-73.999, 40.001], [-74, 40.001], [-74, 40]]
            ],
        },
    }


def client(ids=(7,), missing=False, wrong_muni=False):
    calls = []

    def get(url, params):
        calls.append((url, params))
        if not url.endswith("/query"):
            return json.dumps(SCHEMA).encode()
        if params.get("returnIdsOnly") == "true":
            return json.dumps({"objectIds": list(ids), "objectIdFieldName": "OBJECTID"}).encode()
        selected = int(params["objectIds"])
        return json.dumps(
            {
                "type": "FeatureCollection",
                "features": []
                if missing
                else [feature(selected, "0202" if wrong_muni else "0101")],
            }
        ).encode()

    return get, calls


def test_unique_query_retains_response_hash_and_provenance():
    get, calls = client()
    result = fetch_njgin(
        municipality="0101",
        block="1",
        lot="2",
        target_crs="EPSG:3857",
        fetch=get,
        retrieved_at="2026-10-27T00:00:00Z",
    )
    assert result["status"] == "unique"
    assert result["candidates"][0]["object_id"] == "7"
    assert result["responses"][0]["sha256"]
    assert result["overlay"]["map_sources"][0]["retrieved_at"] == "2026-10-27T00:00:00Z"
    assert "OWNER_NAME" not in calls[-1][1]["outFields"]
    assert "PCL_MUN = '0101'" in calls[1][1]["where"]
    assert result["source_date"] is None


def test_empty_ambiguous_and_explicit_selection():
    for ids, status in [((), "empty"), ((7, 8), "ambiguous")]:
        get, calls = client(ids)
        result = fetch_njgin(
            municipality="0101", block="1", lot="2", target_crs="EPSG:3857", fetch=get
        )
        assert result["status"] == status
        assert result["overlay"] is None
        assert len(calls) == 2 + len(ids)
    get, _ = client((7, 8))
    result = fetch_njgin(
        municipality="0101", block="1", lot="2", target_crs="EPSG:3857", fetch=get, feature_id="8"
    )
    assert result["status"] == "selected"
    assert result["overlay"]["vector_layers"][0]["feature_id"] == "8"


@pytest.mark.parametrize(
    ("option", "expected_error"),
    [
        ("missing", "Incomplete or duplicate provider page"),
        ("wrong_muni", "Provider returned a different parcel identifier/municipality"),
    ],
)
def test_incomplete_or_municipality_collision_rejected(option, expected_error):
    get, _ = client(**{option: True})
    with pytest.raises(ValueError, match=expected_error):
        fetch_njgin(municipality="0101", block="1", lot="2", target_crs="EPSG:3857", fetch=get)


def test_changed_schema_and_timeout_fail_closed():
    with pytest.raises(ValueError, match="schema"):
        fetch_njgin(
            municipality="0101", block="1", lot="2", target_crs="EPSG:3857", fetch=lambda *_: b"{}"
        )

    def timeout(*_):
        raise TimeoutError("timed out")

    with pytest.raises(ValueError, match="timed out"):
        fetch_njgin(municipality="0101", block="1", lot="2", target_crs="EPSG:3857", fetch=timeout)
    with pytest.raises(ValueError, match="municipality"):
        fetch_njgin(
            municipality="Springfield", block="1", lot="2", target_crs="EPSG:3857", fetch=timeout
        )


def test_missing_id_list_invalid_geometry_and_duplicate_pages_rejected():
    normal, _ = client((7, 8))

    def missing_ids(url, params):
        if params.get("returnIdsOnly"):
            return b"{}"
        return normal(url, params)

    with pytest.raises(ValueError, match="object-ID"):
        fetch_njgin(
            municipality="0101", block="1", lot="2", target_crs="EPSG:3857", fetch=missing_ids
        )

    def bad_geometry(url, params):
        result = json.loads(normal(url, params))
        if params.get("f") == "geojson":
            result["features"][0]["geometry"]["coordinates"] = [
                [[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]
            ]
        return json.dumps(result).encode()

    with pytest.raises(ValueError, match="degenerate ring has zero area"):
        fetch_njgin(
            municipality="0101", block="1", lot="2", target_crs="EPSG:3857", fetch=bad_geometry
        )


def test_provider_cannot_relabel_projected_response_as_geojson():
    normal, _ = client()

    def get(url, params):
        result = json.loads(normal(url, params))
        if params.get("f") == "geojson":
            result["crs"] = {"type": "name", "properties": {"name": "EPSG:3857"}}
        return json.dumps(result).encode()

    with pytest.raises(ValueError, match="CRS"):
        fetch_njgin(municipality="0101", block="1", lot="2", target_crs="EPSG:3857", fetch=get)


@pytest.mark.parametrize("qualifier", ["", " "])
def test_official_blank_qualifier_is_retained_exactly(qualifier):
    normal, calls = client()

    def get(url, params):
        result = json.loads(normal(url, params))
        if params.get("f") == "geojson":
            result["features"][0]["properties"]["PCLQCODE"] = qualifier
        return json.dumps(result).encode()

    result = fetch_njgin(
        municipality="0101",
        block="1",
        lot="2",
        qualifier=qualifier,
        target_crs="EPSG:3857",
        fetch=get,
    )
    assert result["status"] == "unique"
    assert result["query"]["PCLQCODE"] == qualifier
    assert f"PCLQCODE = '{qualifier}'" in calls[1][1]["where"]


def test_provider_http_helper_identifier_schema_and_response_guardrails(monkeypatch):
    import io

    import mp_review.parcel_provider as mod

    assert mod.MAX_IMPORT_BYTES == 20 * 1024 * 1024
    monkeypatch.setattr(mod, "MAX_IMPORT_BYTES", 1024)

    # _get() bounded read accepts small responses and rejects > limit
    monkeypatch.setattr(mod, "urlopen", lambda url, timeout=30: io.BytesIO(b'{"ok":true}'))
    assert mod._get("https://example.invalid/s", {"f": "json"}) == b'{"ok":true}'

    monkeypatch.setattr(
        mod, "urlopen", lambda url, timeout=30: io.BytesIO(b"a" * (mod.MAX_IMPORT_BYTES + 1))
    )
    with pytest.raises(ValueError, match="20 MiB"):
        mod._get("https://example.invalid/s", {"f": "json"})

    # Invalid block / lot / qualifier identifiers (empty, too long, control char)
    for kwargs in (
        {"block": "   ", "lot": "2"},
        {"block": "1", "lot": "x" * 81},
        {"block": "1", "lot": "2", "qualifier": "A\x07"},
    ):
        with pytest.raises(ValueError, match="Invalid"):
            fetch_njgin(
                municipality="0101", target_crs="EPSG:3857", fetch=lambda *_: b"{}", **kwargs
            )

    # Provider error payload and oversized cumulative responses
    with pytest.raises(ValueError, match="error or malformed"):
        fetch_njgin(
            municipality="0101",
            block="1",
            lot="2",
            target_crs="EPSG:3857",
            fetch=lambda *_: b'{"error":{"code":500}}',
        )
    with pytest.raises(ValueError, match="import limit"):
        fetch_njgin(
            municipality="0101",
            block="1",
            lot="2",
            target_crs="EPSG:3857",
            fetch=lambda *_: b" " * (mod.MAX_IMPORT_BYTES + 1),
        )

    # Invalid schema maxRecordCount (non-int and < 1)
    for bad_max in ("not-an-int", 0):
        bad_schema = {**SCHEMA, "maxRecordCount": bad_max}
        with pytest.raises(ValueError, match="invalid page size"):
            fetch_njgin(
                municipality="0101",
                block="1",
                lot="2",
                target_crs="EPSG:3857",
                fetch=lambda *_, s=bad_schema: json.dumps(s).encode(),
            )

    # objectIds: None yields empty result; invalid objectIds or exceededTransferLimit fails
    normal, _ = client()

    def null_ids(url, params):
        if params.get("returnIdsOnly") == "true":
            return json.dumps({"objectIds": None, "objectIdFieldName": "OBJECTID"}).encode()
        return normal(url, params)

    empty_res = fetch_njgin(
        municipality="0101", block="1", lot="2", target_crs="EPSG:3857", fetch=null_ids
    )
    assert empty_res["status"] == "empty"

    def bad_ids(url, params):
        if params.get("returnIdsOnly") == "true":
            return json.dumps({"objectIds": [7, 7], "objectIdFieldName": "OBJECTID"}).encode()
        return normal(url, params)

    with pytest.raises(ValueError, match="object-ID snapshot"):
        fetch_njgin(municipality="0101", block="1", lot="2", target_crs="EPSG:3857", fetch=bad_ids)

    # Geometry page with exceededTransferLimit or malformed feature schema
    def truncated_page(url, params):
        if params.get("f") == "geojson":
            return json.dumps(
                {"type": "FeatureCollection", "features": [], "exceededTransferLimit": True}
            ).encode()
        return normal(url, params)

    with pytest.raises(ValueError, match="Incomplete provider geometry page"):
        fetch_njgin(
            municipality="0101", block="1", lot="2", target_crs="EPSG:3857", fetch=truncated_page
        )

    def bad_feature_shape(url, params):
        if params.get("f") == "geojson":
            return json.dumps({"type": "FeatureCollection", "features": ["not-a-dict"]}).encode()
        return normal(url, params)

    with pytest.raises(ValueError, match="feature schema changed"):
        fetch_njgin(
            municipality="0101", block="1", lot="2", target_crs="EPSG:3857", fetch=bad_feature_shape
        )

    # Selected feature_id absent from candidates fails closed
    with pytest.raises(ValueError, match="not an exact query candidate"):
        fetch_njgin(
            municipality="0101",
            block="1",
            lot="2",
            target_crs="EPSG:3857",
            feature_id="999",
            fetch=normal,
        )
