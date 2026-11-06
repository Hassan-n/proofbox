"""Extract text from one supported text-based PDF layout in the isolated code container."""

from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

import pdfplumber

MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 100_000
MAX_PAGES = 50


def parse_document(path: Path) -> dict:
    data = path.read_bytes()
    if not data.startswith(b"%PDF-"):
        raise ValueError("The uploaded file is not a PDF.")
    if len(data) > MAX_PDF_BYTES:
        raise ValueError("The uploaded PDF exceeds the 5 MB limit.")
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        if len(pdf.pages) > MAX_PAGES:
            raise ValueError(f"The PDF exceeds the {MAX_PAGES}-page limit.")
        pages = [page.extract_text() or "" for page in pdf.pages]
    if not pages or not any(page.strip() for page in pages):
        raise ValueError("No readable text was found in the PDF.")
    if sum(map(len, pages)) > MAX_TEXT_CHARS:
        raise ValueError("Extracted text exceeds the document size limit.")
    return {
        "status": "ok",
        "page_texts": pages,
        "text": "\n".join(pages),
        "pages": len(pages),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"status": "error", "error": "A PDF input path is required."}))
        return 2
    try:
        result = parse_document(Path(sys.argv[1]))
    except ValueError as error:
        print(json.dumps({"status": "error", "error": str(error)[:200]}))
        return 1
    except Exception:
        print(json.dumps({"status": "error", "error": "The PDF could not be parsed."}))
        return 1
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
