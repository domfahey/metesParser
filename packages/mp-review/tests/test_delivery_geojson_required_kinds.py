"""Only required selections GeoJSON would carry block a whole-format GeoJSON omission."""

from pathlib import Path

import pytest
from mp_models.delivery import DeliveryRequest
from mp_review.delivery import prepare_delivery

pytest.importorskip("pyproj")

_STORE = Path(__file__).with_name("test_delivery_store.py")


def _store():
    import importlib.util

    spec = importlib.util.spec_from_file_location("_delivery_store_kinds", _STORE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def unavailable(monkeypatch):
    import mp_review.webmap_projection as module

    def fail(scene, extent=None):
        raise module.WebMapUnavailable(
            "operation_unavailable", "No coordinate operation covers the placed display extent."
        )

    monkeypatch.setattr(module, "build_web_map_projection", fail)


def _request(request, *, required: dict[str, bool], formats=("svg", "pdf", "geojson")):
    data = request.model_dump(mode="json")
    for layer in data["layers"]:
        layer["required"] = required.get(layer["id"], False)
    data["formats"] = list(formats)
    return DeliveryRequest.model_validate(data)


def test_required_raster_does_not_count_toward_geojson_block():
    from mp_models.delivery import DeliveryItem, DeliveryLayer
    from mp_review.delivery import _required_geojson

    def item(kind, **kw):
        layer = DeliveryLayer(id=kind, kind=kind, visible=True, opacity=1.0, required=True)
        return DeliveryItem.model_construct(selection=layer, **kw)

    raster = item("raster", raster=object())
    vector = item("vector", vector=object())
    assert _required_geojson([raster]) == []
    assert _required_geojson([raster, vector]) == ["vector"]


def test_required_vector_still_blocks_geojson_omission(tmp_path, unavailable):
    bundle, revision, request = _store()._placed_case(tmp_path)
    request = _request(request, required={"context": True})
    with pytest.raises(ValueError, match="context: .*No coordinate operation"):
        prepare_delivery(bundle, revision, request)
