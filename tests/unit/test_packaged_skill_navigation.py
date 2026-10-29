"""Comparison instructions must remain navigable after leaving the checkout."""

import json
import re
import zipfile
from pathlib import Path

import pytest
from mp_models.comparison import ComparisonRequest
from mp_models.diagnostics import ClosureDiagnosticRequest
from mp_models.source_handoff import DescriptionSelectionRecord, SourceAcquisitionRecord
from mp_review.source_handoff import validate_source_bundle
from mp_verify.comparison import compare_descriptions
from mp_verify.diagnostics import diagnose_closure

from scripts import build_claude_plugin as builder


@pytest.fixture
def extracted_plugin(tmp_path, monkeypatch):
    monkeypatch.setattr(builder.shutil, "which", lambda name: "/fake/uv")

    def fake_runtime(arguments, *, cwd):
        if arguments[1] == "build":
            directory = Path(arguments[arguments.index("--out-dir") + 1])
            package = arguments[arguments.index("--package") + 1]
            (directory / (package.replace("-", "_") + "-1.0.0-py3-none-any.whl")).write_bytes(
                b"synthetic packaging placeholder"
            )
        elif arguments[1] == "lock":
            (Path(arguments[arguments.index("--project") + 1]) / "uv.lock").write_text(
                "version = 1\n"
            )

    monkeypatch.setattr(builder, "run", fake_runtime)
    archive = builder.build(tmp_path / "comparison-navigation.zip")
    root = tmp_path / "outside-checkout" / "plugin"
    with zipfile.ZipFile(archive) as package:
        package.extractall(root)
    assert not (root / "packages").exists()
    return root


def test_comparison_doc_links_resolve_inside_extracted_archive(extracted_plugin):
    documents = [
        extracted_plugin / "skills/compare-descriptions/SKILL.md",
        extracted_plugin / "skills/compare-descriptions/README.md",
        extracted_plugin / "references/comparison-limits.md",
        extracted_plugin / "references/closure-diagnostics.md",
        extracted_plugin / "references/source-preparation.md",
    ]
    for document in documents:
        links = re.findall(r"\[[^\]]*\]\(([^)]+)\)", document.read_text())
        for link in links:
            if ":" in link or link.startswith("#"):
                continue
            target = (document.parent / link.split("#", 1)[0]).resolve()
            assert target.is_relative_to(extracted_plugin), (
                f"{document.relative_to(extracted_plugin)} escapes the packaged plugin: {link}"
            )
            assert target.is_file(), f"Packaged resource is missing: {link}"


def test_shipped_comparison_contract_and_example_validate_against_runtime(extracted_plugin):
    references = extracted_plugin / "skills/compare-descriptions/references"
    schema = json.loads((references / "comparison-request.schema.json").read_bytes())
    assert schema == ComparisonRequest.model_json_schema(mode="validation")
    request = ComparisonRequest.model_validate_json(
        (references / "comparison-example.json").read_bytes()
    )
    result = compare_descriptions(request)
    assert result.verified_export_eligible is False
    assert result.boundary_established is False


def test_shipped_source_schemas_and_examples_retain_valid_byte_identities(extracted_plugin):
    root = extracted_plugin / "references/source-handoff"
    for name, model in (
        ("source-acquisition", SourceAcquisitionRecord),
        ("description-selection", DescriptionSelectionRecord),
    ):
        schema = json.loads((root / (name + ".schema.json")).read_bytes())
        assert schema == model.model_json_schema(mode="validation")
        model.model_validate_json((root / (name + ".json")).read_bytes())
    result = validate_source_bundle(root)
    assert result["status"] == "needs_review"
    assert result["structure"]["status"] == "valid"
    assert result["identity"]["status"] == "matched"


def test_shipped_diagnosis_schema_and_example_are_executable(extracted_plugin):
    root = extracted_plugin / "references/closure-diagnostics"
    schema = json.loads((root / "request.schema.json").read_bytes())
    assert schema == ClosureDiagnosticRequest.model_json_schema(mode="validation")
    request = ClosureDiagnosticRequest.model_validate_json((root / "request.json").read_bytes())
    result = diagnose_closure(request)
    assert result.availability == "supported"
    assert result.verified_export_eligible is False
