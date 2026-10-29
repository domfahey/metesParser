"""Exact-byte source evidence validation, independent of OCR and geometry."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "source_handoff"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_json(path: Path, value: dict) -> None:
    path.write_bytes(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))


@pytest.fixture
def bundle(tmp_path):
    shutil.copytree(FIXTURES, tmp_path, dirs_exist_ok=True)
    return tmp_path


def load(bundle: Path, name="source-acquisition.json") -> dict:
    return json.loads((bundle / name).read_bytes())


def alter(bundle: Path, name: str, action) -> None:
    data = load(bundle, name)
    action(data)
    save_json(bundle / name, data)
    # Keep an otherwise valid selection linked to the modified acquisition bytes.
    if name == "source-acquisition.json":
        selection = load(bundle, "description-selection.json")
        selection["acquisition_sha256"] = digest((bundle / name).read_bytes())
        save_json(bundle / "description-selection.json", selection)


def validate(bundle: Path, **kwargs) -> dict:
    from mp_review.source_handoff import validate_source_bundle

    return validate_source_bundle(bundle, **kwargs)


def findings(result, code):
    return [item for item in result["findings"] if item["code"] == code]


def test_exact_multibyte_bom_crlf_noncontiguous_selection_is_valid(bundle):
    before = {p.name: p.read_bytes() for p in bundle.iterdir()}
    result = validate(bundle)
    assert result["status"] == "needs_review"
    assert result["structure"]["status"] == "valid"
    assert result["identity"]["status"] == "matched"
    assert result["source_uncertainties"]["status"] == "none_declared"
    assert result["acquisition"]["id"] == "acq-1"
    assert result["selection"]["id"] == "selection-1"
    assert result["findings"] == []
    assert "accuracy" in " ".join(result["limitations"]).lower()
    assert {p.name: p.read_bytes() for p in bundle.iterdir()} == before


@pytest.mark.parametrize(
    "target,code",
    [
        ("original.bin", "hash_mismatch"),
        ("source-text.txt", "hash_mismatch"),
        ("description-a.txt", "hash_mismatch"),
    ],
)
def test_changed_bytes_identify_affected_file(bundle, target, code):
    (bundle / target).write_bytes((bundle / target).read_bytes() + b" ")
    result = validate(bundle)
    assert result["status"] == "needs_review"
    assert result["identity"]["status"] == "mismatched"
    assert any(item["path"] == target for item in findings(result, code))


def test_selected_content_cannot_be_replaced_by_self_consistent_hash(bundle):
    replacement = b"fabricated description"
    (bundle / "description-a.txt").write_bytes(replacement)
    alter(
        bundle,
        "description-selection.json",
        lambda d: d["candidates"][0]["selected_text"].update(sha256=digest(replacement)),
    )
    result = validate(bundle)
    assert findings(result, "selected_bytes_mismatch")[0]["id"] == "candidate-a"
    assert result["structure"]["status"] == "invalid"


def test_missing_original_is_unavailable_not_a_match_or_schema_error(bundle):
    (bundle / "original.bin").unlink()
    result = validate(bundle)
    assert result["status"] == "needs_review"
    assert result["structure"]["status"] == "valid"
    assert result["identity"]["status"] == "unverifiable"
    assert findings(result, "missing_file")[0]["id"] == "source-1"


def test_attachment_identifiers_are_opaque_and_never_fetched(bundle, monkeypatch):
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("no network"))
    alter(
        bundle,
        "source-acquisition.json",
        lambda d: d["sources"][0].update(
            path=None, attachment_id="https://example.invalid/../../secret"
        ),
    )
    result = validate(bundle)
    assert result["status"] == "needs_review"
    assert result["structure"]["status"] == "valid"
    assert result["identity"]["status"] == "unverifiable"
    assert findings(result, "attachment_unavailable")[0]["id"] == "source-1"


@pytest.mark.parametrize(
    "field", ["source", "transcript", "selected", "acquisition", "selection_transcript"]
)
def test_null_hash_is_unverifiable_never_matched(bundle, field):
    if field in {"source", "transcript"}:
        alter(
            bundle,
            "source-acquisition.json",
            lambda d: (d["sources"][0] if field == "source" else d["transcript"]).update(
                sha256=None
            ),
        )
    elif field == "selected":
        alter(
            bundle,
            "description-selection.json",
            lambda d: d["candidates"][0]["selected_text"].update(sha256=None),
        )
    else:
        key = "acquisition_sha256" if field == "acquisition" else "transcript_sha256"
        alter(bundle, "description-selection.json", lambda d: d.update({key: None}))
    result = validate(bundle)
    assert result["status"] == "needs_review"
    assert result["identity"]["status"] == "unverifiable"
    assert findings(result, "hash_unavailable")


def test_acquisition_record_hash_binds_selection_to_raw_record_bytes(bundle):
    path = bundle / "source-acquisition.json"
    path.write_bytes(path.read_bytes() + b"\n")
    result = validate(bundle)
    assert findings(result, "acquisition_hash_mismatch")[0]["id"] == "selection-1"


def test_selection_transcript_hash_must_match_acquisition_and_actual_bytes(bundle):
    alter(bundle, "description-selection.json", lambda d: d.update(transcript_sha256="0" * 64))
    result = validate(bundle)
    assert findings(result, "transcript_identity_mismatch")[0]["id"] == "selection-1"
    assert result["identity"]["status"] == "mismatched"


@pytest.mark.parametrize("name", ["source-text.txt", "description-a.txt"])
def test_invalid_utf8_is_rejected_without_replacement_or_normalization(bundle, name):
    (bundle / name).write_bytes(b"\xffinvalid")
    result = validate(bundle)
    assert findings(result, "invalid_utf8")[0]["path"] == name
    assert result["structure"]["status"] == "invalid"


def test_lf_normalization_changes_identity_and_selected_bytes(bundle):
    path = bundle / "description-a.txt"
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
    result = validate(bundle)
    assert findings(result, "hash_mismatch")
    assert findings(result, "selected_bytes_mismatch")


@pytest.mark.parametrize(
    "start,end,code",
    [
        (10000, 10001, "span_out_of_bounds"),
        (3, 8, "span_character_boundary"),
        (0, 8, "span_character_boundary"),
    ],
)
def test_bad_byte_spans_are_not_silently_adjusted(bundle, start, end, code):
    # Byte 3 is valid after BOM; byte 8 is within the multibyte degree sign.
    def update(d):
        candidate = d["candidates"][0]
        span = dict(candidate["spans"][0], start_byte=start, end_byte=end)
        candidate.update(spans=[span], separators=[])

    alter(bundle, "description-selection.json", update)
    result = validate(bundle)
    assert findings(result, code)[0]["id"] == "candidate-a"


def test_bom_can_be_selected_as_exact_bytes(bundle):
    transcript = (bundle / "source-text.txt").read_bytes()
    (bundle / "description-a.txt").write_bytes(transcript[:3])
    alter(
        bundle,
        "description-selection.json",
        lambda d: d["candidates"][0].update(
            selected_text={"path": "description-a.txt", "sha256": digest(transcript[:3])},
            spans=[
                {
                    "page_id": "page-1",
                    "start_byte": 0,
                    "end_byte": 3,
                    "start_line": 1,
                    "end_line": 1,
                }
            ],
            separators=[],
            opening_words="\ufeff",
            closing_words="\ufeff",
        ),
    )
    assert validate(bundle)["structure"]["status"] == "valid"


@pytest.mark.parametrize(
    "change,code",
    [
        (lambda c: c.update(separators=[]), "schema_invalid"),
        (lambda c: c.update(separators=[" "]), "selected_bytes_mismatch"),
        (lambda c: c.update(spans=list(reversed(c["spans"]))), "schema_invalid"),
        (lambda c: c["spans"][0].update(start_line=2), "schema_invalid"),
        (lambda c: c["spans"][0].update(end_line=2), "span_line_mismatch"),
        (lambda c: c["spans"][0].update(page_id="absent-page"), "dangling_page_id"),
        (lambda c: c.update(opening_words="made up"), "opening_words_mismatch"),
        (lambda c: c.update(closing_words="made up"), "closing_words_mismatch"),
    ],
)
def test_selection_structure_and_verbatim_wording_are_checked(bundle, change, code):
    alter(bundle, "description-selection.json", lambda d: change(d["candidates"][0]))
    result = validate(bundle)
    assert findings(result, code)


@pytest.mark.parametrize(
    "change,code",
    [
        (lambda d: d["page_map"][1].update(end_line=1000), "page_lines_out_of_bounds"),
        (lambda d: d["page_map"][1].update(start_line=1), "schema_invalid"),
        (lambda d: d["page_map"][0].update(source_id="missing"), "schema_invalid"),
        (lambda d: d.update(read_pages=["missing"]), "schema_invalid"),
        (lambda d: d["sources"][0].update(page_count=1), "schema_invalid"),
        (lambda d: d["page_map"].append(dict(d["page_map"][0])), "schema_invalid"),
        (lambda d: d["sources"].append(dict(d["sources"][0])), "schema_invalid"),
    ],
)
def test_page_inventory_ids_and_line_bounds_are_validated(bundle, change, code):
    alter(bundle, "source-acquisition.json", change)
    assert findings(validate(bundle), code)


def test_span_must_lie_inside_declared_page_not_just_transcript(bundle):
    alter(
        bundle,
        "description-selection.json",
        lambda d: d["candidates"][0]["spans"][0].update(page_id="page-2"),
    )
    result = validate(bundle)
    assert findings(result, "span_page_mismatch")[0]["id"] == "candidate-a"


def test_declared_unreadable_page_preserves_valid_structure_and_uncertainty(bundle):
    def update(d):
        d["read_pages"] = ["page-1"]
        d["unreadable_pages"] = ["page-2"]
        d["uncertainties"] = [
            {
                "id": "u-digit",
                "page_ids": ["page-2"],
                "description": "Obscured distance digit",
                "affected_field": "distance",
            }
        ]

    alter(bundle, "source-acquisition.json", update)
    alter(
        bundle,
        "description-selection.json",
        lambda d: d["candidates"][0].update(carried_uncertainty_ids=["u-digit"]),
    )
    result = validate(bundle)
    assert result["status"] == "needs_review"
    assert result["structure"]["status"] == "valid"
    assert result["source_uncertainties"]["status"] == "declared"
    assert result["source_uncertainties"]["unreadable_pages"] == ["page-2"]
    assert result["source_uncertainties"]["items"][0]["id"] == "u-digit"


@pytest.mark.parametrize("page_ids", [[], ["page-1"], ["page-2"]])
def test_relevant_page_and_document_uncertainties_must_be_carried(bundle, page_ids):
    alter(
        bundle,
        "source-acquisition.json",
        lambda d: d.update(
            uncertainties=[
                {"id": "u-missing", "page_ids": page_ids, "description": "Unknown source fact"}
            ]
        ),
    )
    result = validate(bundle)
    item = findings(result, "uncertainty_dropped")[0]
    assert item["id"] == "candidate-a"
    assert item["uncertainty_id"] == "u-missing"


def test_uncertainty_from_unselected_page_need_not_be_carried(bundle):
    alter(
        bundle,
        "source-acquisition.json",
        lambda d: d.update(
            uncertainties=[
                {"id": "u-other", "page_ids": ["page-2"], "description": "Historical page fact"}
            ]
        ),
    )
    transcript = (bundle / "source-text.txt").read_bytes()
    candidate = load(bundle, "description-selection.json")["candidates"][0]
    span = candidate["spans"][0]
    selected = transcript[span["start_byte"] : span["end_byte"]]
    (bundle / "description-a.txt").write_bytes(selected)
    alter(
        bundle,
        "description-selection.json",
        lambda d: d["candidates"][0].update(
            spans=[span],
            separators=[],
            selected_text={"path": "description-a.txt", "sha256": digest(selected)},
            closing_words="  \r\n",
        ),
    )
    assert not findings(validate(bundle), "uncertainty_dropped")


def test_dangling_carried_uncertainty_is_invalid(bundle):
    alter(
        bundle,
        "description-selection.json",
        lambda d: d["candidates"][0].update(carried_uncertainty_ids=["u-absent"]),
    )
    assert findings(validate(bundle), "dangling_uncertainty_id")[0]["id"] == "candidate-a"


def test_historical_and_operative_candidates_remain_distinct(bundle):
    def update(d):
        historical = dict(
            d["candidates"][0],
            id="candidate-historical",
            role="historical",
            label="Historic wording",
        )
        d["candidates"].append(historical)

    alter(bundle, "description-selection.json", update)
    result = validate(bundle)
    assert result["selection"]["candidate_ids"] == ["candidate-a", "candidate-historical"]
    assert result["structure"]["status"] == "valid"


def test_duplicate_candidates_are_schema_errors(bundle):
    alter(
        bundle,
        "description-selection.json",
        lambda d: d["candidates"].append(dict(d["candidates"][0])),
    )
    assert validate(bundle)["status"] == "error"


def test_acquisition_id_cannot_be_replaced_with_equal_looking_filename(bundle):
    alter(bundle, "description-selection.json", lambda d: d.update(acquisition_id="wrong-source"))
    assert findings(validate(bundle), "acquisition_id_mismatch")[0]["id"] == "selection-1"


@pytest.mark.parametrize(
    "name,container,key",
    [
        ("source-acquisition.json", "source", "path"),
        ("source-acquisition.json", "transcript", "path"),
        ("description-selection.json", "selected_text", "path"),
    ],
)
@pytest.mark.parametrize(
    "unsafe",
    [
        "../outside",
        "/etc/passwd",
        "nested/../../outside",
        "C:\\secret",
        "https://example.invalid/file",
        "folder\\file",
    ],
)
def test_unsafe_record_paths_are_schema_errors(bundle, name, container, key, unsafe):
    def update(d):
        item = (
            d["sources"][0]
            if container == "source"
            else d["transcript"]
            if container == "transcript"
            else d["candidates"][0]["selected_text"]
        )
        item[key] = unsafe

    alter(bundle, name, update)
    result = validate(bundle)
    assert result["status"] == "error"
    assert findings(result, "schema_invalid")


@pytest.mark.parametrize("inside", [True, False])
def test_symlink_components_are_rejected_even_when_target_is_inside_root(
    bundle, tmp_path_factory, inside
):
    target = bundle / "real" if inside else tmp_path_factory.mktemp("external")
    target.mkdir(exist_ok=True)
    (target / "original.bin").write_bytes((bundle / "original.bin").read_bytes())
    (bundle / "linked").symlink_to(target, target_is_directory=True)
    alter(
        bundle,
        "source-acquisition.json",
        lambda d: d["sources"][0].update(path="linked/original.bin"),
    )
    result = validate(bundle)
    assert findings(result, "unsafe_path")[0]["path"] == "linked/original.bin"
    assert result["structure"]["status"] == "invalid"


def test_record_symlink_is_rejected(bundle):
    (bundle / "linked-acquisition.json").symlink_to(bundle / "source-acquisition.json")
    result = validate(bundle, acquisition=Path("linked-acquisition.json"))
    assert result["status"] == "error"
    assert findings(result, "unsafe_path")


def test_bundle_root_is_explicit_not_cwd(bundle, monkeypatch, tmp_path_factory):
    monkeypatch.chdir(tmp_path_factory.mktemp("wrong-cwd"))
    assert validate(bundle)["identity"]["status"] == "matched"


def test_root_itself_may_be_a_symlink_but_no_component_below_it(bundle, tmp_path_factory):
    link = tmp_path_factory.mktemp("root-link") / "bundle"
    link.symlink_to(bundle, target_is_directory=True)
    assert validate(link)["structure"]["status"] == "valid"


@pytest.mark.parametrize("root_kind", ["file", "absent"])
def test_invalid_bundle_root_returns_error(bundle, root_kind):
    result = validate(bundle / ("source-text.txt" if root_kind == "file" else "absent"))
    assert result["status"] == "error"
    assert findings(result, "invalid_bundle_root")


def test_acquisition_alone_is_validated_without_fabricating_selection(bundle):
    (bundle / "description-selection.json").unlink()
    result = validate(bundle)
    assert result["status"] == "needs_review"
    assert result["acquisition"]["status"] == "valid"
    assert result["selection"]["status"] == "missing"
    assert result["structure"]["status"] == "valid"


def test_standalone_selection_checks_selected_file_and_missing_prerequisite(bundle):
    (bundle / "source-acquisition.json").unlink()
    (bundle / "description-a.txt").write_bytes(b"changed")
    result = validate(bundle)
    assert result["status"] == "needs_review"
    assert findings(result, "missing_acquisition")
    assert any(x["path"] == "description-a.txt" for x in findings(result, "hash_mismatch"))
    assert result["identity"]["status"] == "mismatched"


def test_missing_explicit_record_is_invocation_error(bundle):
    result = validate(bundle, acquisition=Path("absent.json"))
    assert result["status"] == "error"
    assert findings(result, "missing_record")


@pytest.mark.parametrize("name", ["source-acquisition.json", "description-selection.json"])
def test_legacy_records_are_unverifiable_not_silently_migrated(bundle, name):
    original = {"schema_version": "1.0", "unknown_legacy_key": "retained"}
    save_json(bundle / name, original)
    before = (bundle / name).read_bytes()
    result = validate(bundle)
    assert result["status"] == "needs_review"
    assert result["structure"]["status"] == "legacy"
    assert result["identity"]["status"] != "matched"
    assert findings(result, "legacy_schema")[0]["path"] == name
    assert (bundle / name).read_bytes() == before


@pytest.mark.parametrize(
    "content,code",
    [
        (b'{"schema_version":"9.0"}', "unknown_schema_version"),
        (b'{"schema_version":"1.1"}', "schema_invalid"),
        (b'{"schema_version":"1.1","schema_version":"1.0"}', "invalid_json"),
        (b"[]", "invalid_json"),
        (b"{", "invalid_json"),
        (b"\xff", "invalid_utf8"),
    ],
)
def test_invalid_records_return_machine_readable_errors(bundle, content, code):
    (bundle / "source-acquisition.json").write_bytes(content)
    result = validate(bundle)
    assert result["status"] == "error"
    assert findings(result, code)[0]["path"] == "source-acquisition.json"


def test_no_records_is_an_invocation_error(tmp_path):
    result = validate(tmp_path)
    assert result["status"] == "error"
    assert findings(result, "no_source_records")


def test_known_page_inventory_gaps_remain_unknown_not_complete(bundle):
    alter(bundle, "source-acquisition.json", lambda d: d["sources"][0].update(page_count=4))
    result = validate(bundle)
    assert result["structure"]["status"] == "valid"
    assert result["source_uncertainties"]["status"] == "declared"
    assert findings(result, "undeclared_pages")[0]["page_numbers"] == [3, 4]
    assert findings(result, "undeclared_pages")[0]["id"] == "source-1"


def test_unknown_page_count_stays_unknown(bundle):
    alter(bundle, "source-acquisition.json", lambda d: d["sources"][0].update(page_count=None))
    result = validate(bundle)
    assert result["source_uncertainties"]["unknown_page_count_source_ids"] == ["source-1"]
    assert result["source_uncertainties"]["status"] == "declared"


def test_missing_exhibit_uncertainty_is_carried_without_fabricating_a_span(bundle):
    def update(d):
        d["sources"][0]["page_count"] = 3
        d["missing_pages"] = [{"id": "missing-exhibit", "source_id": "source-1", "page": 3}]
        d["uncertainties"] = [
            {
                "id": "u-exhibit",
                "page_ids": ["missing-exhibit"],
                "description": "Referenced exhibit was not supplied",
            }
        ]

    alter(bundle, "source-acquisition.json", update)
    result = validate(bundle)
    assert result["source_uncertainties"]["missing_pages"][0]["id"] == "missing-exhibit"
    assert findings(result, "uncertainty_dropped")[0]["uncertainty_id"] == "u-exhibit"


def test_invalid_invocation_cannot_claim_matching_identity(tmp_path):
    result = validate(tmp_path)
    assert result["identity"]["status"] == "unverifiable"


def test_new_output_paths_are_not_created_and_optional_stage_is_not_requested(bundle):
    before = set(bundle.rglob("*"))
    result = validate(
        bundle,
        acquisition=Path("source-acquisition.json"),
        selection=Path("description-selection.json"),
    )
    assert result["status"] == "needs_review"
    assert set(bundle.rglob("*")) == before
    assert not (bundle / "output").exists()


def test_absolute_record_override_inside_bundle_is_supported(bundle):
    result = validate(bundle, acquisition=bundle / "source-acquisition.json")
    assert result["identity"]["status"] == "matched"


def test_outside_record_override_is_not_read(bundle, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "acquisition.json"
    outside.write_bytes((bundle / "source-acquisition.json").read_bytes())
    result = validate(bundle, acquisition=outside)
    assert result["status"] == "error"
    assert findings(result, "unsafe_path")[0]["path"] == str(outside)


def test_in_bundle_absolute_override_through_symlinked_root_is_accepted(bundle, tmp_path_factory):
    link = tmp_path_factory.mktemp("symlinked-root") / "bundle"
    link.symlink_to(bundle, target_is_directory=True)
    result = validate(
        link,
        acquisition=link / "source-acquisition.json",
        selection=link / "description-selection.json",
    )
    assert result["status"] == "needs_review"
    assert findings(result, "unsafe_path") == []
    assert result["identity"]["status"] == "matched"


def test_outside_absolute_override_through_symlinked_root_is_rejected(bundle, tmp_path_factory):
    link = tmp_path_factory.mktemp("symlinked-root") / "bundle"
    link.symlink_to(bundle, target_is_directory=True)
    outside = tmp_path_factory.mktemp("outside-link") / "acquisition.json"
    outside.write_bytes((bundle / "source-acquisition.json").read_bytes())
    result = validate(link, acquisition=outside)
    assert result["status"] == "error"
    assert findings(result, "unsafe_path")[0]["path"] == str(outside)


@pytest.mark.parametrize(
    "content,code", [(b"{not json", "invalid_json"), (b"\xff", "invalid_utf8")]
)
def test_unreadable_acquisition_record_is_reported_invalid_with_identity(bundle, content, code):
    (bundle / "source-acquisition.json").write_bytes(content)
    result = validate(bundle)
    assert result["status"] == "error"
    assert result["acquisition"]["status"] == "invalid"
    assert result["acquisition"]["path"] == "source-acquisition.json"
    assert result["acquisition"]["sha256"] == digest(content)
    assert findings(result, code)[0]["path"] == "source-acquisition.json"


def test_non_utf8_transcript_still_reports_selection_transcript_identity(bundle):
    raw = b"\xff\xfe transcript bytes that are not UTF-8\n"
    (bundle / "source-text.txt").write_bytes(raw)
    alter(
        bundle,
        "source-acquisition.json",
        lambda d: d["transcript"].update(sha256=digest(raw)),
    )
    alter(
        bundle,
        "description-selection.json",
        lambda d: d.update(transcript_sha256=digest(raw)),
    )
    result = validate(bundle)
    assert result["status"] == "needs_review"
    assert findings(result, "invalid_utf8")[0]["path"] == "source-text.txt"
    check = next(
        c
        for c in result["identity"]["checks"]
        if c["id"] == "selection-1" and c["path"] == "source-text.txt"
    )
    assert check["actual_sha256"] == digest(raw)
    assert check["status"] == "matched"


@pytest.mark.parametrize("via_symlinked_root", [False, True])
def test_absolute_override_through_symlinked_directory_below_root_is_rejected(
    bundle, tmp_path_factory, via_symlinked_root
):
    real = bundle / "real"
    real.mkdir()
    (real / "acquisition.json").write_bytes((bundle / "source-acquisition.json").read_bytes())
    (bundle / "sub").symlink_to(real, target_is_directory=True)
    root = bundle
    if via_symlinked_root:
        root = tmp_path_factory.mktemp("symlinked-root") / "bundle"
        root.symlink_to(bundle, target_is_directory=True)
    result = validate(root, acquisition=root / "sub" / "acquisition.json")
    assert result["status"] == "error"
    assert findings(result, "unsafe_path")


def test_absolute_override_that_is_a_file_symlink_below_root_is_rejected(bundle):
    (bundle / "linked-acquisition.json").symlink_to(bundle / "source-acquisition.json")
    result = validate(bundle, acquisition=bundle / "linked-acquisition.json")
    assert result["status"] == "error"
    assert findings(result, "unsafe_path")
