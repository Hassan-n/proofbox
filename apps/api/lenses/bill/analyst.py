"""Analyst coder (guide Step 3.5, Pattern A).

The model writes a short Python program from the extracted bill plus a fixed task. Its only
tool is running that program in the sandbox. Errors are fed back up to MAX_RETRIES times.
The program's figures must agree with the tariff engine (`checks.reference_figures`); if it
cannot produce working, agreeing code, the report shows deterministic checks only and the
analyst is listed in `skipped_checks`. Executed code and output are saved as receipts.
"""

from __future__ import annotations

import ast
import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict

from .checks import reference_figures
from .runners import CodeRunner, RunResult
from .tariff import Tariff, load_tariff

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "analyst_coder.md"
TARIFF_PATH_NAME = "tariff.json"
MAX_RETRIES = 2
MAX_CODE_CHARS = 8000
MAX_ERROR_CHARS = 2000
MAX_TOKENS = 2500

ALLOWED_IMPORTS = {"json", "decimal", "datetime", "math", "statistics", "fractions"}
BANNED_NAMES = {
    "eval", "exec", "compile", "__import__", "breakpoint", "input", "globals", "locals",
    "vars", "getattr", "setattr", "delattr", "memoryview", "help", "exit", "quit",
}
MONEY_KEYS = ("subtotal", "vat", "total")
KL_KEYS = ("normal_kl", "implied_kl")
DAY_KEYS = ("period_days", "outage_days", "supplied_days")
MONEY_TOLERANCE = Decimal("0.01")
KL_TOLERANCE = Decimal("0.05")

# Which recomputed figures back which deterministic finding.
FINDING_FIGURES = {
    "arithmetic": MONEY_KEYS,
    "outage_consistency": ("normal_kl", "implied_kl", "period_days", "outage_days"),
}

ModelCaller = Callable[..., Any]
ReceiptSaver = Callable[..., str]


class AnalystCode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str


class InMemoryReceipts:
    """Stand-in for Person A's save_receipt() until Gate 0 lands."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def __call__(self, job_id: str | None, kind: str, content: str, meta: dict[str, Any] | None = None) -> str:
        receipt_id = f"rcpt-{len(self.items) + 1}"
        self.items[receipt_id] = {
            "job_id": job_id,
            "kind": kind,
            "content": content,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "meta": meta or {},
        }
        return receipt_id


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def check_code(code: str) -> list[str]:
    """Static allow-list before anything runs. Defence in depth; the sandbox is the real boundary."""
    if len(code) > MAX_CODE_CHARS:
        return [f"Program is longer than {MAX_CODE_CHARS} characters"]
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"SyntaxError: {exc.msg} (line {exc.lineno})"]
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""] if node.level == 0 else ["relative import"]
        else:
            modules = []
        for module in modules:
            if module.split(".")[0] not in ALLOWED_IMPORTS:
                problems.append(f"Import of '{module}' is not allowed")
        if isinstance(node, ast.Name) and (node.id in BANNED_NAMES or node.id.startswith("__")):
            problems.append(f"Use of '{node.id}' is not allowed")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            problems.append(f"Dunder attribute '{node.attr}' is not allowed")
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "INPUT_DIR" for t in node.targets):
            problems.append("INPUT_DIR must not be redefined")
    return sorted(set(problems))


def run_analyst(
    bill: dict[str, Any],
    history: dict[str, Any] | None,
    call_model: ModelCaller,
    runner: CodeRunner,
    *,
    tariff: Tariff | None = None,
    save_receipt: ReceiptSaver | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Returns `{status: agreed|disagreed|failed, figures, comparison, attempts, receipt_ids, skipped_checks, notes}`."""
    tariff = tariff or load_tariff()
    tariff_data = _tariff_json(tariff)
    reference = reference_figures(bill, history, tariff)
    inputs: dict[str, Any] = {"bill.json": bill, TARIFF_PATH_NAME: tariff_data}
    if history:
        inputs["history.json"] = history

    payload: dict[str, Any] = {
        "bill": bill,
        "tariff": tariff_data,
        "history": history,
    }
    attempts: list[dict[str, Any]] = []
    for attempt in range(MAX_RETRIES + 1):
        raw = call_model(
            "analyst_coder", job_id, load_prompt(), json.dumps(payload, ensure_ascii=False), schema=AnalystCode, max_tokens=MAX_TOKENS
        )
        if not isinstance(raw, dict) or raw.get("error") or not isinstance(raw.get("code"), str):
            detail = raw.get("detail", "") if isinstance(raw, dict) else "unexpected gateway response"
            attempts.append({"attempt": attempt + 1, "outcome": "no_code", "error": str(detail)[:MAX_ERROR_CHARS]})
            return _failed(attempts, "The analyst model did not return a program")

        code = raw["code"]
        problems = check_code(code)
        if problems:
            error = "Program rejected before running: " + "; ".join(problems)
            attempts.append({"attempt": attempt + 1, "outcome": "rejected", "error": error})
            payload["previous_attempt"] = {"code": code, "error": error}
            continue

        result = runner.run(code, inputs)
        figures, error = _parse_output(result)
        attempt_log = {"attempt": attempt + 1, "exit_code": result.exit_code, "duration_ms": result.duration_ms}
        if error:
            attempts.append({**attempt_log, "outcome": "error", "error": error})
            payload["previous_attempt"] = {"code": code, "error": error}
            continue

        attempts.append({**attempt_log, "outcome": "ran"})
        comparison = compare(reference, figures)
        if not all(item["agree"] for item in comparison.values()):
            bad = [key for key, item in comparison.items() if not item["agree"]]
            return {
                **_failed(attempts, f"Analyst figures disagreed with the tariff engine on: {', '.join(bad)}"),
                "status": "disagreed",
                "figures": figures,
                "comparison": comparison,
            }

        saver = save_receipt or InMemoryReceipts()
        meta = {"attempts": len(attempts), "duration_ms": result.duration_ms}
        receipt_ids = {
            "code": saver(job_id, "code", result.executed_code, {**meta, "language": "python"}),
            "output": saver(job_id, "output", result.stdout, {**meta, "comparison": comparison}),
        }
        return {
            "status": "agreed",
            "figures": figures,
            "comparison": comparison,
            "attempts": attempts,
            "receipt_ids": receipt_ids,
            "skipped_checks": [],
            "notes": [],
        }

    return _failed(attempts, f"The analyst program still failed after {MAX_RETRIES} retries: {attempts[-1]['error'][:300]}")


def compare(reference: dict[str, Any], figures: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Compare only figures the engine could compute; the analyst must supply each of them."""
    comparison: dict[str, dict[str, Any]] = {}
    for key, expected in reference.items():
        if expected is None:
            continue
        got = figures.get(key)
        comparison[key] = {"engine": str(expected), "analyst": None if got is None else str(got), "agree": _agrees(key, expected, got)}
    return comparison


def attach_receipts(checks_result: dict[str, Any], analyst_result: dict[str, Any]) -> dict[str, Any]:
    """Link analyst receipts to the findings whose figures it reproduced; record a skip otherwise."""
    if analyst_result["status"] != "agreed":
        checks_result["skipped_checks"].extend(analyst_result["skipped_checks"])
        return checks_result
    receipts = list(analyst_result["receipt_ids"].values())
    for finding in checks_result["findings"]:
        keys = FINDING_FIGURES.get(finding["check"], ())
        if keys and all(key in analyst_result["comparison"] for key in keys):
            finding["receipt_ids"] = [*finding["receipt_ids"], *(r for r in receipts if r not in finding["receipt_ids"])]
    return checks_result


def _agrees(key: str, expected: Any, got: Any) -> bool:
    if got is None:
        return False
    if key in DAY_KEYS:
        return isinstance(got, int) and not isinstance(got, bool) and got == expected
    try:
        got_dec = Decimal(str(got))
    except InvalidOperation:
        return False
    if not got_dec.is_finite():
        return False
    tolerance = MONEY_TOLERANCE if key in MONEY_KEYS else KL_TOLERANCE
    return abs(got_dec - Decimal(str(expected))) <= tolerance


def _parse_output(result: RunResult) -> tuple[dict[str, Any], str | None]:
    if result.timed_out:
        return {}, "The program timed out"
    if result.exit_code != 0:
        return {}, f"Exit code {result.exit_code}. stderr:\n{result.stderr[-MAX_ERROR_CHARS:]}"
    try:
        data = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        return {}, f"stdout is not one JSON object ({exc.msg}). stdout started with: {result.stdout[:200]!r}"
    if not isinstance(data, dict):
        return {}, "stdout must be one JSON object"
    return data, None


def _failed(attempts: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "figures": None,
        "comparison": None,
        "attempts": attempts,
        "receipt_ids": {},
        "skipped_checks": [
            {"check": "analyst_coder", "reason": f"Extra recomputation checks were skipped. {reason}"[:500]}
        ],
        "notes": [reason[:500]],
    }


def _tariff_json(tariff: Tariff) -> dict[str, Any]:
    return {
        "tariff_id": tariff.tariff_id,
        "version": tariff.version,
        "currency": tariff.currency,
        "water_tiers": [
            {"from_kl": str(t.from_kl), "to_kl": None if t.to_kl is None else str(t.to_kl), "rate_per_kl": str(t.rate_per_kl)}
            for t in tariff.water_tiers
        ],
        "fixed_charges": [{"code": c.code, "description": c.description, "amount": str(c.amount)} for c in tariff.fixed_charges],
        "vat_rate": str(tariff.vat_rate),
        "rounding": {"mode": tariff.rounding_mode, "quantum": str(tariff.rounding_quantum)},
    }
