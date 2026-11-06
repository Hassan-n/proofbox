"""Build deterministic PDF evidence packs and integrity-checked receipt archives."""

from __future__ import annotations

import hashlib
import io
import json
import re
import time
import zipfile
from datetime import date
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ID_NUMBER_PATTERN = re.compile(rb"\d{13}")
EVIDENCE_REF_PATTERN = re.compile(r"\[E(\d+)\]")
MAX_PACK_BYTES = 40 * 1024 * 1024


class PackBuildError(ValueError):
    """Raised when an evidence pack cannot be built without losing integrity."""


def _ascii(value: Any) -> str:
    return str(value if value is not None else "").encode("ascii", "replace").decode("ascii")


def _plain_receipt_bytes(receipt: dict[str, Any]) -> bytes:
    blob = receipt.get("blob_base64")
    if blob:
        import base64

        try:
            return base64.b64decode(blob, validate=True)
        except ValueError as error:
            raise PackBuildError(f"Receipt {receipt.get('id')} has invalid encoded data.") from error
    content = receipt.get("content_json") or {}
    if isinstance(content, str):
        return content.encode("utf-8")
    if isinstance(content, dict) and isinstance(content.get("content"), str):
        return content["content"].encode("utf-8")
    return json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _pack_receipt_bytes(receipt: dict[str, Any], source_sha256: str) -> bytes:
    if receipt.get("kind") != "letter_supporting_pdf":
        return _plain_receipt_bytes(receipt)
    content = receipt.get("content_json") or {}
    metadata = content if isinstance(content, dict) else {}
    filename = re.sub(r"(?<!\d)\d{13}(?!\d)", "[redacted]", str(metadata.get("filename", "supporting document.pdf")))
    text = (
        "Supporting PDF omitted from the evidence pack to protect personal information.\n"
        f"Filename: {filename[:120]}\n"
        f"Source SHA-256: {source_sha256}\n"
    )
    return text.encode("utf-8")


def _receipt_extension(kind: str) -> str:
    if kind == "screenshot":
        return ".webp"
    if kind in {"pdf", "letter_pdf"}:
        return ".pdf"
    return ".txt"


def _make_claims(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claims = []
    for item in evidence:
        ref = f"[E{item['seq']}]"
        facts = item.get("derived_facts") or {}
        findings = facts.get("findings") or []
        if item["kind"] == "bill" and findings:
            for finding in findings:
                details = []
                if finding.get("title"):
                    details.append(str(finding["title"]))
                if finding.get("billed") is not None:
                    details.append(f"Billed R {finding['billed']}")
                if finding.get("recomputed") is not None:
                    details.append(f"recomputed R {finding['recomputed']}")
                if finding.get("difference") is not None:
                    details.append(f"difference R {finding['difference']}")
                if finding.get("explanation"):
                    details.append(str(finding["explanation"]))
                text = "; ".join(details) or item["summary"]
                claims.append({"text": f"{text} {ref}", "evidence_seq": item["seq"]})
        else:
            claims.append({"text": f"{item['summary']} {ref}", "evidence_seq": item["seq"]})
    return claims


def _render_pdf(snapshot: dict[str, Any]) -> bytes:
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=f"Proofbox evidence pack {snapshot['case']['id']}",
        author="Proofbox",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CoverTitle", parent=styles["Title"], alignment=TA_CENTER, spaceAfter=12))
    styles.add(ParagraphStyle(name="Claim", parent=styles["BodyText"], leading=15, spaceAfter=9))
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8, leading=10))
    story = [
        Spacer(1, 35 * mm),
        Paragraph("PROOFBOX CASE FILE", styles["CoverTitle"]),
        Paragraph(f"Case: {escape(_ascii(snapshot['case']['id']))}", styles["Heading2"]),
        Paragraph(f"Pack version: {snapshot['version']}", styles["BodyText"]),
        Paragraph(f"Generated: {escape(snapshot['generated_at'])}", styles["BodyText"]),
        Spacer(1, 8 * mm),
        Paragraph("<b>NOT LEGAL ADVICE</b>", styles["Heading2"]),
        Paragraph(escape(_ascii(snapshot["rule_footer"])), styles["BodyText"]),
        PageBreak(),
        Paragraph("Numbered claims", styles["Heading1"]),
    ]
    valid_seqs = {item["seq"] for item in snapshot["evidence"]}
    for claim in snapshot["claims"]:
        refs = {int(number) for number in EVIDENCE_REF_PATTERN.findall(claim["text"])}
        if not refs or not refs.issubset(valid_seqs):
            raise PackBuildError("A claim does not resolve to evidence in this pack.")
        claim_markup = escape(_ascii(claim["text"]))
        claim_markup = EVIDENCE_REF_PATTERN.sub(
            lambda match: f'<link href="#E{match.group(1)}">{match.group(0)}</link>',
            claim_markup,
        )
        story.append(Paragraph(claim_markup, styles["Claim"]))

    story.extend([PageBreak(), Paragraph("Clocks", styles["Heading1"])])
    clock_rows = [["Clock", "Due date", "State"]]
    for clock in snapshot["clocks"]:
        clock_rows.append([
            _ascii(clock["name"]),
            _ascii(clock["due_at"]),
            _ascii(clock["state"]).replace("_", " ").title(),
        ])
    if len(clock_rows) == 1:
        clock_rows.append(["No clocks started", "-", "-"])
    clocks = Table(clock_rows, repeatRows=1, colWidths=[72 * mm, 42 * mm, 42 * mm])
    clocks.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#245c43")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd4ca")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([clocks, Spacer(1, 8 * mm), Paragraph("Evidence and receipt hashes", styles["Heading1"])])
    for item in snapshot["evidence"]:
        story.append(Paragraph(
            f'<a name="E{item["seq"]}"/>' + escape(_ascii(f"[E{item['seq']}] {item['kind'].title()}: {item['summary']}")),
            styles["BodyText"],
        ))
        for receipt in item["receipts"]:
            story.append(Paragraph(
                escape(_ascii(f"{receipt['id']} ({receipt['kind']}) SHA-256 {receipt['sha256']}")),
                styles["Small"],
            ))
        story.append(Spacer(1, 3 * mm))

    letters = [
        item for item in snapshot["evidence"]
        if (item.get("derived_facts") or {}).get("dispute_letter")
    ]
    for item in letters:
        letter = item["derived_facts"]["dispute_letter"]
        text = letter.get("text") if isinstance(letter, dict) else None
        if not text:
            continue
        story.extend([
            PageBreak(),
            Paragraph(f"Draft dispute letter [E{item['seq']}]", styles["Heading1"]),
        ])
        for line in text.splitlines():
            if line.strip():
                story.append(Paragraph(
                    escape(_ascii(f"{line} [E{item['seq']}]")),
                    styles["BodyText"],
                ))
            else:
                story.append(Spacer(1, 3 * mm))

    story.extend([PageBreak(), Paragraph("Receipt file appendix", styles["Heading1"])])
    for receipt in snapshot["manifest"]["files"]:
        story.append(Paragraph(
            escape(_ascii(f"{receipt['path']} — SHA-256 {receipt['sha256']}")),
            styles["Small"],
        ))

    def page_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#59665f"))
        canvas.drawCentredString(A4[0] / 2, 10 * mm, f"NOT LEGAL ADVICE · Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    return buffer.getvalue()


def _assert_no_identifiers(value: Any, path: str = "snapshot") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "blob_base64":
                continue
            _assert_no_identifiers(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_identifiers(item, f"{path}[{index}]")
    elif isinstance(value, str) and ID_NUMBER_PATTERN.search(value.encode("utf-8")):
        raise PackBuildError(f"{path} contains a 13-digit identifier; no pack was published.")


def build_pack(snapshot: dict[str, Any], pack_directory: str | Path) -> dict[str, Any]:
    started = time.monotonic()
    target = Path(pack_directory).resolve()
    target.mkdir(parents=True, exist_ok=True)
    if len(snapshot.get("evidence", [])) == 0:
        raise PackBuildError("Add at least one evidence item before generating a pack.")
    _assert_no_identifiers(snapshot)

    evidence_files = []
    receipt_records = []
    total_bytes = 0
    for item in snapshot["evidence"]:
        if not item.get("receipts"):
            raise PackBuildError(f"Evidence E{item['seq']} has no receipt attached.")
        for receipt in item.get("receipts", []):
            source_data = _plain_receipt_bytes(receipt)
            source_hash = hashlib.sha256(source_data).hexdigest()
            if not receipt.get("sha256") or not hmac_compare(source_hash, receipt["sha256"]):
                raise PackBuildError(f"Receipt {receipt['id']} failed its SHA-256 check.")
            data = _pack_receipt_bytes(receipt, source_hash)
            total_bytes += len(data)
            if total_bytes > MAX_PACK_BYTES:
                raise PackBuildError("Receipts exceed the 40 MB pack limit.")
            if ID_NUMBER_PATTERN.search(data):
                raise PackBuildError("A receipt contains a 13-digit identifier; no pack was published.")
            actual_hash = hashlib.sha256(data).hexdigest()
            directory = f"E{item['seq']}"
            filename = f"{receipt['id']}{_receipt_extension(receipt['kind'])}"
            relative_path = f"{directory}/{filename}"
            evidence_files.append((relative_path, data))
            receipt_records.append({
                "evidence_seq": item["seq"],
                "receipt_id": receipt["id"],
                "path": relative_path,
                "sha256": actual_hash,
                "source_sha256": source_hash,
                "bytes": len(data),
            })
            hash_path = f"{directory}/{receipt['id']}.sha256.txt"
            hash_data = (
                f"Pack file SHA-256: {actual_hash}  {filename}\n"
                f"Source receipt SHA-256: {source_hash}\n"
            ).encode("ascii")
            evidence_files.append((hash_path, hash_data))
            receipt_records.append({
                "evidence_seq": item["seq"],
                "receipt_id": receipt["id"],
                "path": hash_path,
                "sha256": hashlib.sha256(hash_data).hexdigest(),
                "bytes": len(hash_data),
            })

    claims = _make_claims(snapshot["evidence"])
    valid_seqs = {item["seq"] for item in snapshot["evidence"]}
    for claim in claims:
        refs = {int(number) for number in EVIDENCE_REF_PATTERN.findall(claim["text"])}
        if not refs or not refs.issubset(valid_seqs):
            raise PackBuildError("A claim does not resolve to evidence in this pack.")
    manifest = {
        "case_id": snapshot["case"]["id"],
        "version": snapshot["version"],
        "evidence_seq_max": max(valid_seqs),
        "files": receipt_records,
    }
    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
    all_files = [*evidence_files, ("manifest.json", manifest_bytes)]
    for path, data in all_files:
        if ID_NUMBER_PATTERN.search(path.encode("utf-8")) or ID_NUMBER_PATTERN.search(data):
            raise PackBuildError("Pack output contains a 13-digit identifier.")
        total_bytes += len(data)
        if total_bytes > MAX_PACK_BYTES:
            raise PackBuildError("Receipts exceed the 40 MB pack limit.")

    pdf_bytes = _render_pdf({**snapshot, "claims": claims, "manifest": manifest})
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in all_files:
            archive.writestr(path, data)
    zip_bytes = zip_buffer.getvalue()

    pdf_path = target / f"pack-v{snapshot['version']}.pdf"
    zip_path = target / f"pack-v{snapshot['version']}.zip"
    pdf_path.write_bytes(pdf_bytes)
    zip_path.write_bytes(zip_bytes)
    if time.monotonic() - started > 20:
        pdf_path.unlink(missing_ok=True)
        zip_path.unlink(missing_ok=True)
        raise PackBuildError("Pack generation exceeded the 20-second limit.")

    return {
        "pdf_path": str(pdf_path),
        "zip_path": str(zip_path),
        "claims": claims,
        "manifest": manifest,
        "bytes": {"pdf": len(pdf_bytes), "zip": len(zip_bytes)},
    }


def hmac_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)
