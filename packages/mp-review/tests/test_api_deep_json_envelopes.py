"""Python API entry points keep their domain error contracts for deeply nested JSON.

Decision: ``InvalidInputJson`` deliberately does not subclass ValueError (that would change the
CLI codes of commands that map ValueError to their own domain code). Entry points that handled
RecursionError/ValueError before the shared boundary handle it explicitly.
"""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from mp_review.delivery import load_delivery, publish_delivery

pytest.importorskip("pyproj")

DEEP = "[" * 100000 + "]" * 100000
_TESTS = Path(__file__).parent


def _store_case(tmp_path):
    spec = importlib.util.spec_from_file_location("_store", _TESTS / "test_delivery_store.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._placed_case(tmp_path)


def test_diagnose_closure_file_returns_envelope_for_deep_json(tmp_path):
    from mp_review.diagnostics import diagnose_closure_file

    source = tmp_path / "request.json"
    source.write_text(DEEP)
    result = diagnose_closure_file(source, tmp_path / "out")
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "invalid_diagnostics_input"
    assert not (tmp_path / "out").exists()


def _published(tmp_path):
    bundle, revision, request = _store_case(tmp_path)
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "needs_review", result
    return bundle, revision, tmp_path / "deliveries" / request.id


def _replace(directory, name, content):
    (directory / name).write_text(content)
    manifest_path = directory / "delivery-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"][name] = hashlib.sha256((directory / name).read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))


@pytest.mark.parametrize("name", ["drawing.geojson", "request.json", "snapshot.json"])
def test_deep_package_artifact_is_invalid_delivery_naming_it(tmp_path, name):
    bundle, revision, directory = _published(tmp_path)
    _replace(directory, name, DEEP)
    with pytest.raises(ValueError, match=name.replace(".", r"\.")):
        load_delivery(bundle, revision, directory)


def test_deep_manifest_is_invalid_delivery(tmp_path):
    bundle, revision, directory = _published(tmp_path)
    (directory / "delivery-manifest.json").write_text(DEEP)
    with pytest.raises(ValueError, match=r"delivery-manifest\.json"):
        load_delivery(bundle, revision, directory)


def test_inspect_delivery_cli_reports_invalid_delivery_for_deep_geojson(tmp_path):
    bundle, revision, directory = _published(tmp_path)
    _replace(directory, "drawing.geojson", DEEP)
    bundle_file = tmp_path / "bundle.json"
    bundle_file.write_text(bundle.model_dump_json())
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "mp_review",
            "inspect-delivery",
            str(bundle_file),
            "--revision-dir",
            str(revision),
            "--package-dir",
            str(directory),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert done.returncode == 2, done.stdout + done.stderr[-500:]
    error = json.loads(done.stdout)["errors"][0]
    assert error["code"] == "invalid_delivery", error
    assert "drawing.geojson" in error["message"]
