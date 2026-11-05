"""Live analyst coder test (Step 3.5).

Asks the real analyst_coder model to write the recomputation program for A5 (no history)
and A6 + A8 (with history), runs it with the LOCAL dev runner (not a sandbox; the code is
statically allow-listed first), and checks it agrees with the tariff engine.

Usage:  python scripts/eval_analyst.py [--runs 1] [--model NAME] [--thinking]
Output: fixtures/out/eval/analyst_results.json and analyst_model_calls.jsonl (git-ignored).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from eval_extractor import OUT_DIR, REPO_ROOT, LiveCaller

sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

import generate_fixtures as gf  # noqa: E402
from lenses.bill.analyst import InMemoryReceipts, run_analyst  # noqa: E402
from lenses.bill.runners import LocalSubprocessRunner  # noqa: E402
from lenses.bill.tariff import load_tariff  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=1, help="Repeat each case this many times")
    parser.add_argument("--model")
    parser.add_argument("--thinking", action="store_true")
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    if not os.environ.get("VULTR_INFERENCE_KEY"):
        print("VULTR_INFERENCE_KEY is not set", file=sys.stderr)
        return 2

    tariff = load_tariff()
    dataset = gf.build_dataset(tariff)
    cases = [("A5", dataset["A5"], None), ("A6+A8", dataset["A6"], dataset["A8"])]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = OUT_DIR / "analyst_model_calls.jsonl"
    log_path.unlink(missing_ok=True)
    caller = LiveCaller(log_path, args.model, args.thinking)
    runner = LocalSubprocessRunner(timeout_s=20)

    results = []
    for run in range(args.runs):
        for name, bill, history in cases:
            receipts = InMemoryReceipts()
            started = time.monotonic()
            result = run_analyst(bill, history, caller, runner, tariff=tariff, save_receipt=receipts, job_id=f"eval-{name}-{run}")
            seconds = round(time.monotonic() - started, 1)
            code = receipts.items[result["receipt_ids"]["code"]]["content"] if result["receipt_ids"] else None
            results.append({"case": name, "run": run, "seconds": seconds, **result, "code": code})
            outcomes = ",".join(a["outcome"] for a in result["attempts"])
            print(f"{name:6} run {run}: {result['status']:9} attempts=[{outcomes}] {seconds}s")
            for a in result["attempts"]:
                if a.get("error"):
                    print(f"    error: {a['error'][:300]}")
            for key, item in (result["comparison"] or {}).items():
                if not item["agree"]:
                    print(f"    {key}: engine {item['engine']} vs analyst {item['analyst']}")

    (OUT_DIR / "analyst_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    agreed = sum(r["status"] == "agreed" for r in results)
    print(f"\n{agreed}/{len(results)} agreed with the tariff engine")
    return 0 if agreed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
