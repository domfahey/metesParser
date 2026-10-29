"""Shared web-map binding checks require no geographic or rendering libraries."""

import hashlib
import json
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_models.webmap import WebMapArtifact, WebMapOptions
from mp_verify.dashboard import calculate_dashboard
from mp_verify.webmap import validate_web_map_artifact


def inputs():
    root = Path(__file__).resolve().parents[3]
    data = json.loads(
        (root / "packages/mp-review/tests/fixtures/dashboard-absolute.json").read_text()
    )
    data["schema_version"] = "1.1"
    data["scenes"] = [
        {"id": "scene", "name": "Synthetic", "kind": "projected", "crs": "EPSG:3857", "units": "m"}
    ]
    prepared = calculate_dashboard(DashboardBundle.model_validate(data))
    options = WebMapOptions()
    artifact = WebMapArtifact(
        scene_id="scene",
        input_hashes=tuple(
            (key, value)
            for key, value in prepared.manifest.model_dump().items()
            if key.endswith("_hash") and value is not None
        ),
        options=options,
        options_sha256=hashlib.sha256(
            json.dumps(
                options.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
        availability="unavailable",
    )
    return prepared, artifact


def test_direct_validator_returns_revalidated_artifact():
    prepared, artifact = inputs()
    validated = validate_web_map_artifact(prepared, artifact)
    assert validated == artifact
    assert validated is not artifact


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("input_hashes", (), "input hashes"),
        ("options_sha256", "0" * 64, "options hash"),
        ("scene_id", "absent", "scene"),
    ],
)
def test_direct_validator_rejects_forged_bindings(field, value, message):
    prepared, artifact = inputs()
    with pytest.raises(ValueError, match=message):
        validate_web_map_artifact(prepared, artifact.model_copy(update={field: value}))


def test_direct_validator_recalculates_prepared_results():
    prepared, artifact = inputs()
    forged = prepared.model_copy(update={"calculations": ()})
    with pytest.raises(ValueError, match="deterministic inputs"):
        validate_web_map_artifact(forged, artifact)


def test_direct_validator_revalidates_prepared_model():
    prepared, artifact = inputs()
    forged = prepared.model_copy(
        update={"manifest": prepared.manifest.model_copy(update={"cache_reused": "invalid"})}
    )
    with pytest.warns(UserWarning, match="serializer warnings"), pytest.raises(ValueError):
        validate_web_map_artifact(forged, artifact)


def test_shared_context_preserves_dashboard_manifest_hashes():
    from mp_verify.webmap import normalize_web_map_context

    prepared, artifact = inputs()
    context = normalize_web_map_context(prepared)
    assert context.input_hashes == artifact.input_hashes
    assert context.geometries == prepared.plots.geometries


def test_standalone_validator_uses_no_dashboard_or_projection(monkeypatch):
    from mp_models.webmap import StandaloneWebMapInput
    from mp_verify import webmap

    def forbidden(*args, **kwargs):
        raise AssertionError("standalone validation must not use a dashboard")

    monkeypatch.setattr(webmap, "validate_prepared_dashboard", forbidden)
    prepared = StandaloneWebMapInput(
        title="Local overlay input",
        scenes=({"id": "local", "name": "Local", "kind": "local", "units": "unknown_ft"},),
    )
    context = webmap.normalize_web_map_context(prepared)
    options = WebMapOptions()
    artifact = WebMapArtifact(
        scene_id="local",
        options=options,
        options_sha256=webmap._digest(options.model_dump(mode="json")),
        input_hashes=context.input_hashes,
        availability="unavailable",
    )
    assert validate_web_map_artifact(prepared, artifact) == artifact
