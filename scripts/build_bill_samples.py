"""Build Bill Lens result JSON for the web page (apps/web/bill/samples/).

Default stub mode is offline: canned extractor output, the stub analyst program run by the
dev-only LocalSubprocessRunner, and the template letter. `--live` sends every role to the
real models (needs VULTR_INFERENCE_KEY in .env).

Receipt contents are embedded in each result so the static page can show them without the API.

  python scripts/build_bill_samples.py            # stub
  python scripts/build_bill_samples.py --live     # live models, thinking off
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(REPO_ROOT / "sandbox" / "code"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import generate_fixtures as gf  # noqa: E402
import parse_bill as pb  # noqa: E402
from lenses.bill.analyst import InMemoryReceipts  # noqa: E402
from lenses.bill.extractor import StubExtractor  # noqa: E402
from lenses.bill.pipeline import run_bill_lens  # noqa: E402
from lenses.bill.runners import LocalSubprocessRunner  # noqa: E402

STUBS = REPO_ROOT / "fixtures" / "stubs"
SAMPLES_DIR = REPO_ROOT / "apps" / "web" / "bill" / "samples"
DOCS = {"A5": ("A5_bill_clean.pdf", False), "A6": ("A6_bill_errors.pdf", True), "A7": ("A7_bill_injection.pdf", True)}


class StubGateway:
    def __init__(self):
        self.extractor = StubExtractor(STUBS)
        self.code = (STUBS / "bill_analyst_coder.py").read_text(encoding="utf-8")

    def __call__(self, role, job_id, system_prompt, untrusted_data, schema=None, **_):
        if role == "extractor":
            return self.extractor(role, job_id, system_prompt, untrusted_data, schema=schema)
        if role == "analyst_coder":
            return {"code": self.code}
        return {"error": "unreadable", "detail": "stub mode has no writer; template letter used"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="call the real models instead of stubs")
    args = parser.parse_args()

    if args.live:
        from dotenv import load_dotenv
        from eval_extractor import OUT_DIR, LiveCaller

        load_dotenv(REPO_ROOT / ".env")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        gateway = LiveCaller(OUT_DIR / "samples_calls.jsonl")
    else:
        gateway = StubGateway()

    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        gf.generate(out, out / "stubs")
        history = json.loads((out / "A8_history.json").read_text(encoding="utf-8"))
        for name, (pdf, with_history) in DOCS.items():
            receipts = InMemoryReceipts()
            result = run_bill_lens(
                pb.parse_pdf(out / pdf),
                history=history if with_history else None,
                call_model=gateway,
                runner=LocalSubprocessRunner(timeout_s=20),
                save_receipt=receipts,
                job_id=f"sample-{name}",
                letter_date=date(2026, 11, 4),
            )
            for receipt_id, meta in result["receipts"].items():
                meta["content"] = receipts.items[receipt_id]["content"]
            result["sample"] = {"id": name, "document": pdf, "mode": "live" if args.live else "stub"}
            path = SAMPLES_DIR / f"{name}.json"
            path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            letter = result["dispute_letter"]
            print(
                f"{name}: {result['status']}, {len(result['findings'])} findings, analyst "
                f"{(result['analyst'] or {}).get('status')}, letter {letter['source'] if letter else 'none'} -> {path.relative_to(REPO_ROOT)}"
            )
            for note in (letter or {}).get("notes", []):
                print(f"   writer note: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
