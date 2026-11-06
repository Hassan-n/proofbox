import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pdfplumber
import pytest

from pack_builder import PackBuildError, build_pack


def _receipt(receipt_id, text):
    content = text.encode("utf-8")
    return {
        "id": receipt_id,
        "kind": "output",
        "sha256": hashlib.sha256(content).hexdigest(),
        "content_json": {"content": text, "meta": {"label": "Synthetic receipt"}},
        "blob_base64": None,
        "bytes": len(content),
    }


def _snapshot(version, evidence):
    return {
        "case": {"id": "case-demo", "title": "Synthetic case", "rule_set": "municipal_billing"},
        "version": version,
        "generated_at": "2026-11-06",
        "rule_footer": "Rules not yet verified. Not legal advice.",
        "clocks": [
            {"id": "clock-1", "name": "Response due", "due_at": "2026-11-20", "state": "upcoming"}
        ],
        "evidence": evidence,
    }


def test_pack_pdf_claims_resolve_and_manifest_matches_zip(tmp_path):
    evidence = [{
        "id": "evidence-1",
        "seq": 1,
        "kind": "link",
        "summary": "The link was checked in an isolated browser.",
        "derived_facts": {},
        "receipts": [_receipt("receipt-1", "Synthetic output, no personal data.")],
    }]
    result = build_pack(_snapshot(1, evidence), tmp_path / "case-demo")

    with pdfplumber.open(result["pdf_path"]) as pdf:
        pdf_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "[E1]" in pdf_text
    assert "NOT LEGAL ADVICE" in pdf_text
    assert "Upcoming" in pdf_text

    with zipfile.ZipFile(result["zip_path"]) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        for item in manifest["files"]:
            contents = archive.read(item["path"])
            assert hashlib.sha256(contents).hexdigest() == item["sha256"]
        assert any(item["path"] == "E1/receipt-1.txt" for item in manifest["files"])


def test_pack_regeneration_keeps_version_one_unchanged(tmp_path):
    output = tmp_path / "case-demo"
    first_evidence = [{
        "id": "evidence-1", "seq": 1, "kind": "link", "summary": "First evidence.",
        "derived_facts": {}, "receipts": [_receipt("receipt-1", "first receipt")],
    }]
    first = build_pack(_snapshot(1, first_evidence), output)
    original_pdf = Path(first["pdf_path"]).read_bytes()
    original_zip = Path(first["zip_path"]).read_bytes()

    second_evidence = [
        *first_evidence,
        {
            "id": "evidence-2", "seq": 2, "kind": "bill", "summary": "Second evidence.",
            "derived_facts": {}, "receipts": [_receipt("receipt-2", "second receipt")],
        },
    ]
    second = build_pack(_snapshot(2, second_evidence), output)
    assert Path(first["pdf_path"]).read_bytes() == original_pdf
    assert Path(first["zip_path"]).read_bytes() == original_zip
    assert "[E2]" in second["claims"][1]["text"]
    assert "[E2]" not in first["claims"][0]["text"]
    assert Path(second["pdf_path"]).name == "pack-v2.pdf"


@pytest.mark.parametrize("sensitive", [b"ID 8101011234567", "ID 8101011234567".encode()])
def test_pack_rejects_receipt_with_thirteen_digit_identifier(tmp_path, sensitive):
    evidence = [{
        "id": "evidence-1", "seq": 1, "kind": "letter", "summary": "Letter evidence.",
        "derived_facts": {}, "receipts": [{
            "id": "receipt-pii", "kind": "output", "sha256": hashlib.sha256(sensitive).hexdigest(),
            "blob_base64": __import__("base64").b64encode(sensitive).decode("ascii"),
            "content_json": None, "bytes": len(sensitive),
        }],
    }]
    with pytest.raises(PackBuildError, match="13-digit"):
        build_pack(_snapshot(1, evidence), tmp_path / "case-pii")


def test_pack_requires_evidence(tmp_path):
    with pytest.raises(PackBuildError, match="at least one evidence"):
        build_pack(_snapshot(1, []), tmp_path / "case-empty")


def test_pack_redacts_supporting_pdf_but_preserves_source_hash(tmp_path):
    import base64

    original = b"%PDF-1.4 synthetic ID 8101011234567"
    evidence = [{
        "id": "evidence-1",
        "seq": 1,
        "kind": "letter",
        "summary": "Letter checklist complete.",
        "derived_facts": {},
        "receipts": [{
            "id": "receipt-id",
            "kind": "letter_supporting_pdf",
            "sha256": hashlib.sha256(original).hexdigest(),
            "content_json": {"filename": "A10_id_copy.pdf", "bytes": len(original)},
            "blob_base64": base64.b64encode(original).decode("ascii"),
        }],
    }]
    result = build_pack(_snapshot(1, evidence), tmp_path / "case-letter")

    with zipfile.ZipFile(result["zip_path"]) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        record = next(item for item in manifest["files"] if item["path"].endswith(".txt") and not item["path"].endswith(".sha256.txt"))
        data = archive.read(record["path"])
        assert b"8101011234567" not in data
        assert hashlib.sha256(original).hexdigest().encode() in data
        assert record["source_sha256"] == hashlib.sha256(original).hexdigest()
