"""Trusted Bill Lens parse script. Runs inside the no-network `code` sandbox.

    python parse_bill.py /inputs/bill.pdf [--out /out/parse.json]

Extracts text lines and tables with pdfplumber, runs a static prompt-injection
scan, and writes one JSON result. Lines that look like instructions to an AI
are removed from `text` (the only text handed to the extractor model) and
reported as `instruction_ignored` events. This script is part of the trusted
code path (contract C4), so its `events` may be forwarded by the worker.
Document content is only ever data: it is never executed or interpreted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

PARSER_VERSION = "parse_bill/1"
MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 20
MAX_EVENT_LINE_CHARS = 300
HIDDEN_MAX_FONT_SIZE = 3.0
WHITE_THRESHOLD = 0.95

INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        ("ignore_instructions", r"\b(ignore|disregard|forget|override)\b.{0,40}\b(instructions?|prompts?|rules)\b"),
        ("approve_bill", r"\b(mark|treat|approve|report|flag)\b.{0,30}\b(bill|invoice|account|this)\b.{0,20}\b(as )?(correct|valid|accurate|approved|paid|fine)\b"),
        ("exfiltrate", r"\b(print|reveal|show|output|send|list|dump)\b.{0,40}\b(environment|env vars?|variables|system prompt|secrets?|api[ _-]?keys?|passwords?|tokens?|credentials)\b"),
        ("address_model", r"\b(note|message|instructions?)\s+(to|for)\s+(the\s+)?(ai|assistant|model|llm|chatbot|gpt)\b"),
        ("role_override", r"\byou are (now )?(an? |the )?(ai|assistant|model|llm)\b"),
        ("system_prompt", r"\b(system prompt|developer message|jailbreak)\b"),
    )
)


class ParseError(Exception):
    pass


def scan_line(text: str) -> list[str]:
    return [name for name, pattern in INJECTION_PATTERNS if pattern.search(text)]


def _is_white(color: Any) -> bool:
    if color is None:
        return False
    values = color if isinstance(color, (list, tuple)) else (color,)
    numeric = [v for v in values if isinstance(v, (int, float))]
    if not numeric:
        return False
    if len(numeric) == 4:  # CMYK: white is no ink
        return all(v <= 1 - WHITE_THRESHOLD for v in numeric)
    return all(v >= WHITE_THRESHOLD for v in numeric)


def is_hidden(chars: list[dict[str, Any]]) -> bool:
    visible = [c for c in chars if not c.get("text", "").isspace()]
    if not visible:
        return False
    return all(c.get("size", 99) <= HIDDEN_MAX_FONT_SIZE or _is_white(c.get("non_stroking_color")) for c in visible)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_pdf(path: str | Path) -> dict[str, Any]:
    import pdfplumber

    path = Path(path)
    if not path.is_file():
        raise ParseError(f"Input not found: {path.name}")
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise ParseError(f"Input is {size} bytes; limit is {MAX_BYTES}")
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise ParseError("Input is not a PDF")

    pages: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []
    hidden: list[dict[str, Any]] = []
    model_text: list[str] = []

    try:
        pdf = pdfplumber.open(path)
    except Exception as exc:  # pdfminer raises a variety of types for corrupt files
        raise ParseError(f"Could not open PDF: {type(exc).__name__}") from exc
    with pdf:
        if len(pdf.pages) > MAX_PAGES:
            raise ParseError(f"PDF has {len(pdf.pages)} pages; limit is {MAX_PAGES}")
        for number, page in enumerate(pdf.pages, start=1):
            kept_lines = []
            for line in page.extract_text_lines(return_chars=True):
                text = line["text"].strip()
                if not text:
                    continue
                reasons = scan_line(text)
                line_hidden = is_hidden(line.get("chars", []))
                if reasons:
                    ignored.append({"page": number, "line": text, "reasons": reasons, "hidden": line_hidden})
                elif line_hidden:
                    hidden.append({"page": number, "line": text})
                else:
                    kept_lines.append(text)
            pages.append({"page": number, "lines": kept_lines, "tables": page.extract_tables()})
            model_text.append(f"--- page {number} ---\n" + "\n".join(kept_lines))

    return {
        "parser": PARSER_VERSION,
        "input": {"name": path.name, "sha256": _sha256(path), "bytes": size, "pages": len(pages)},
        "text": "\n".join(model_text),
        "pages": pages,
        "ignored_lines": ignored,
        "hidden_lines": hidden,
        "events": [_instruction_ignored_event(item) for item in ignored],
    }


def _instruction_ignored_event(item: dict[str, Any]) -> dict[str, Any]:
    line = item["line"]
    if len(line) > MAX_EVENT_LINE_CHARS:
        line = line[:MAX_EVENT_LINE_CHARS] + "..."
    where = "hidden text" if item["hidden"] else "text"
    return {
        "type": "instruction_ignored",
        "severity": "warning",
        "message": f'Ignored an instruction in the document ({where}, page {item["page"]}): "{line}"',
        "data": {"page": item["page"], "line": line, "reasons": item["reasons"], "hidden": item["hidden"]},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse a bill PDF inside the code sandbox")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--out", type=Path, help="also write the result JSON here")
    args = parser.parse_args(argv)

    try:
        result: dict[str, Any] = {"status": "ok", **parse_pdf(args.pdf)}
        code = 0
    except ParseError as exc:
        result = {"status": "error", "parser": PARSER_VERSION, "error": str(exc), "events": []}
        code = 2

    payload = json.dumps(result, ensure_ascii=False)
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
    sys.stdout.write(payload + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
