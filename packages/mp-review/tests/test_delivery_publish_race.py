"""A package appears only complete; a failing publish never affects a concurrent one."""

import threading
from pathlib import Path

from mp_models.dashboard import DashboardBundle
from mp_models.delivery import DeliveryRequest
from mp_models.revisions import revision_template
from mp_review.delivery import load_delivery, publish_delivery
from mp_review.revisions import publish_revision


def _setup(tmp_path):
    bundle = DashboardBundle.model_validate_json(
        (Path(__file__).parent / "fixtures/dashboard-absolute.json").read_text()
    )
    revision = revision_template(bundle, revision_id="published")
    assert publish_revision(bundle, revision, tmp_path / "revisions")["save_state"] == "published"
    request = DeliveryRequest(
        id="package",
        baseline=revision.baseline,
        revision_id="published",
        revision_generation=0,
        geometry="scenario",
        coordinate_mode="local",
        units="unknown_ft",
        layers=[
            {
                "id": "calc-one",
                "kind": "calculation",
                "visible": True,
                "opacity": 1.0,
                "required": True,
            }
        ],
        formats=["svg", "dxf"],
    )
    return bundle, tmp_path / "revisions" / "published", request


def test_failing_publish_cannot_discard_files_a_concurrent_manifest_references(
    tmp_path, monkeypatch
):
    import mp_review.delivery as api

    bundle, revision, request = _setup(tmp_path)
    store = tmp_path / "deliveries"
    original = api._write_once
    a_mid, b_at_manifest, a_done = threading.Event(), threading.Event(), threading.Event()
    results = {}

    def write_once(path, content):
        name = threading.current_thread().name
        if name == "A" and path.name == "metrics.json":
            # A has created pending/snapshot/request/revision-calls; let B run, then fail.
            a_mid.set()
            b_at_manifest.wait(timeout=1)
            raise OSError("A interrupted")
        if name == "B" and path.name == "delivery-manifest.json":
            b_at_manifest.set()
            a_done.wait(timeout=5)
        return original(path, content)

    monkeypatch.setattr(api, "_write_once", write_once)

    def run_a():
        try:
            results["A"] = publish_delivery(bundle, revision, request, store)
        finally:
            a_mid.set()
            a_done.set()

    def run_b():
        a_mid.wait(timeout=5)
        results["B"] = publish_delivery(bundle, revision, request, store)

    threads = [threading.Thread(target=run_a, name="A"), threading.Thread(target=run_b, name="B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert not any(thread.is_alive() for thread in threads)
    assert results["A"]["status"] == "error"
    directory = store / request.id
    assert results["B"]["status"] == "needs_review", results["B"]
    for artifact in results["B"]["artifacts"].values():
        assert Path(artifact).is_file(), artifact
    load_delivery(bundle, revision, directory)


def test_package_is_invisible_until_complete(tmp_path, monkeypatch):
    import mp_review.delivery as api

    bundle, revision, request = _setup(tmp_path)
    directory = tmp_path / "deliveries" / request.id
    original = api._write_once
    written = []

    def write_once(path, content):
        # Every file, the manifest last, goes to private staging, not the package.
        assert not directory.exists()
        assert path.parent != directory
        written.append(path.name)
        return original(path, content)

    monkeypatch.setattr(api, "_write_once", write_once)
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "needs_review", result
    assert written[-1] == "delivery-manifest.json"
    assert sorted(written[:-1]) == sorted(result["artifacts"])
    assert sorted(p.name for p in directory.iterdir()) == sorted(written)
    load_delivery(bundle, revision, directory)
