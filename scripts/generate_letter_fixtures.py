"""Generate synthetic Letter Lens A9/A10 PDFs; no real personal data is used.

Usage: python scripts/generate_letter_fixtures.py [--out apps/web/letter/samples]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "apps" / "web" / "letter" / "samples"
FIXTURE_DATE = date(2026, 11, 6)
NAME = "Jordan River"


def _months_before(value: date, months: int) -> date:
    month = value.month - months
    year = value.year
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def _synthetic_id() -> str:
    body = "850102500000"
    digits = [int(value) for value in body]
    checksum = sum(
        (digit * 2 - 9 if digit * 2 > 9 else digit * 2) if index % 2 == 0 else digit
        for index, digit in enumerate(reversed(digits))
    )
    return body + str((-checksum) % 10)


def _pdf(path: Path, pages: list[list[str]]) -> None:
    output = canvas.Canvas(str(path), pagesize=A4, pageCompression=0, invariant=1)
    _, height = A4
    for lines in pages:
        y = height - 60
        for line in lines:
            output.drawString(55, y, line)
            y -= 18
        output.showPage()
    output.save()


def generate(out_dir: Path = DEFAULT_OUT, check_date: date | None = None) -> dict:
    today = check_date or FIXTURE_DATE
    out_dir.mkdir(parents=True, exist_ok=True)
    deadline = today + timedelta(days=14)
    appointment = today + timedelta(days=21)
    files = {
        "A9_letter.pdf": [
            "KAROO BAY COMMUNITY ASSISTANCE OFFICE",
            f"Date: {today.isoformat()}",
            "Applicant: Jordan River",
            "Reference: KBC-2026-0418",
            "Your application is being reviewed. Please provide the documents listed below.",
            "Response deadline: " + deadline.isoformat(),
            "Appointment: " + appointment.isoformat() + " at 10:30",
            "Appointment place: Karoo Bay Civic Centre, Room 4",
            "Required: copy of identity document",
            "Required: proof of address dated within the last three months",
            "Required: bank statement covering the last three months",
            "Required: signed declaration",
            "Information: https://example.invalid/application",
            "Synthetic demo document. Not an official letter.",
        ],
        "A10_id_copy.pdf": [
            "SYNTHETIC DEMONSTRATION ID COPY",
            "Name: Jordan River",
            "ID number: " + _synthetic_id(),
            "This is fictional test data and is not a valid personal record.",
        ],
        "A10_old_proof_of_address.pdf": [
            "SYNTHETIC DEMONSTRATION MUNICIPAL ACCOUNT",
            "Name: Jordan River",
            f"Document date: {_months_before(today, 5).isoformat()}",
            "Address: 10 Example Road, Karoo Bay",
        ],
        "A10_bank_statement.pdf": [
            [
                "SYNTHETIC DEMONSTRATION BANK STATEMENT",
                "Name: Jordan River",
                f"Statement period: {_months_before(today, 3).isoformat()} to {today.isoformat()}",
                "Page 1 of 2",
                "Account activity page one.",
            ],
            [
                "SYNTHETIC DEMONSTRATION BANK STATEMENT",
                "Name: Jordan River",
                "Page 2 of 2",
                "Account activity page two.",
            ],
        ],
    }
    for name, content in files.items():
        pages = content if content and isinstance(content[0], list) else [content]
        _pdf(out_dir / name, pages)
    manifest = {
        "check_date": today.isoformat(),
        "synthetic_only": True,
        "files": {
            name: hashlib.sha256((out_dir / name).read_bytes()).hexdigest()
            for name in files
        },
        "expected": {
            "id_copy": "have",
            "proof_of_address": "needs_fixing",
            "bank_statement": "have",
            "signed_declaration": "missing",
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = generate(args.out)
    for name, digest in result["files"].items():
        print(f"{name}: sha256={digest[:12]}")


if __name__ == "__main__":
    main()
