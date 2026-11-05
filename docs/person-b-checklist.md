# Person B checklist: Day 3 Bill Lens

Branch: `feat/day3-bill-lens`
Source plan: `Proofbox Parallel Build Plan for Wed 4 Nov (Day 2 + Day 3).md`

Legend: `[x]` done, `[ ]` open, `BLOCKED` waiting on Person A or a shared contract.

## Phase 0 and integration blockers

- [ ] Gate 0 contracts (`docs/contracts.md`) agreed and merged to `main`.
- [ ] Gate 0 scaffolding merged: lens registry, Bill router, `emit_event()`, `save_receipt()`, renderer slots.
- [ ] Shared dependencies pre-installed in `apps/api/requirements.txt` (`pdfplumber`, `jsonschema`, etc.).
- [ ] Model gateway supports `MODEL_GATEWAY_MODE=stub|live` and canned stubs from `fixtures/stubs/`.
  - Note: `origin/link_lens` currently has a synchronous `call_model(role, schema=...)` using Pydantic schemas and no stub mode. Agree the Bill Lens call shape before Step 3.4.
- [ ] Worker `/run` supports the no-network `code` profile with read-only `inputs`.
- [ ] API container includes `tariffs/tariff_v1.json`, or sets `PROOFBOX_TARIFF_PATH` (the current API Docker build context is `apps/api` only).

## Feature 1: Tariff engine (Step 3.1)

- [x] `tariffs/tariff_v1.json`: 0-6 kl R15, 6-15 kl R25, 15+ kl R38, water service R120, refuse R95, VAT 15%.
- [x] `apps/api/lenses/bill/tariff.py`: Decimal-only engine, tier split, fixed charges, VAT, total.
- [x] Documented rounding policy (see `docs/decisions/decisions-b.md`).
- [x] At least 20 unit tests in `tests/bill/test_tariff.py` (31 passing), including 6 and 15 kl boundaries, zero use and rounding.
- [ ] Reviewed by Person A.

## Feature 2: Fixture generator A5-A8 (Step 3.2)

- [x] `scripts/generate_fixtures.py` with fixed seed (`20261104`); output is byte-identical on rerun, written to git-ignored `fixtures/out/`.
- [x] A5 clean bill (18 kl, R740.60), totals match the tariff engine.
- [x] A6 with three planted errors: 6-15 kl tier billed at R38 instead of R25 (R875.15 vs R740.60, +R134.55), two consecutive estimated readings, 18 kl billed despite a nine-day outage (implied 12.6 kl).
- [x] A7 = A6 plus hidden injection line (white, 1 pt text).
- [x] A8 three previous bills JSON plus nine-day outage log (2026-09-08 to 2026-09-16).
- [x] Footer "Synthetic demo document" on every PDF page; A8 JSON marked `synthetic`.
- [x] `fixtures/stubs/bill_extractor_A5.json` and `bill_extractor_A6.json` (regenerated from the same data; `--check` flags stale stubs).
- [x] `fixtures/out/manifest.json`: sha256 per file and expected findings for exit checks.
- [x] 15 generator tests in `tests/bill/test_fixtures.py` (46 Bill tests passing in total).
- [ ] Reviewed by Person A.
- [ ] **Gate 1:** Features 1 and 2 merged; switch stub to live once gateway is ready.

Setup on a new machine: `pip install -r scripts/requirements-fixtures.txt`, then `python scripts/generate_fixtures.py`.

## Feature 3: Parse in code container (Step 3.3)

- [x] `sandbox/code/Dockerfile`: Python 3.12 slim, non-root (uid 10001), pdfplumber only. Run limits (no network, read-only inputs, 20 s, 512 MB, 0.5 CPU) are applied by the worker `code` profile.
- [x] `sandbox/code/parse_bill.py`: pdfplumber text lines per page, 10 MB / 20 page / `%PDF-` limits, writes `/out/parse.json` and prints JSON to stdout.
- [x] Static injection scan emits trusted `instruction_ignored` (C1 shape) with the ignored line and continues; injected and hidden lines are removed from model text (A7 text == A6 text).
- [x] 32 parser tests in `tests/bill/test_parse_bill.py`, run in plain Python against A5-A7.
- [ ] Tested with plain `docker run`, then via own worker on port 8081. **Not done: Docker not installed on this machine (user decision).**
- [ ] BLOCKED: worker `code` profile and file inputs (Person A).
- [ ] **Gate 2:** merged; smoke one real Bill job through the UI.

## Feature 4: Link Lens static checks (Step 2.5)

- [x] SKIPPED by user decision: Person A's `link_lens.py` on `origin/link_lens` already has `run_static_checks`.

## Feature 5: Extractor and validation (Step 3.4)

- [x] `apps/api/lenses/bill/prompts/bill_extractor.md`: delimited document text, bill schema only, untrusted-data rules.
- [x] `apps/api/lenses/bill/extractor.py`: Pydantic `BillExtraction` (`extra="forbid"`), sanity rules, grounding against document text; uncertain fields become `"unreadable"`.
- [x] Retry with validation error is delegated to the gateway (3 attempts), then `status: unreadable`.
- [x] `StubExtractor` serves `fixtures/stubs/` by account number for stub mode.
- [x] 32 extractor tests in `tests/bill/test_extractor.py`.
- [x] Live extraction test `scripts/eval_extractor.py` (5 documents by default, up to 20 with `--limit 20`): **PASS** on 5 (193/194 fields correct, 1 unreadable, 0 wrong; checks agree on all 5; A7 injection flagged; ~2.6 s per bill). Needs thinking switched off (D-B12).
- [ ] Ask Person A to add `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` to `gateway.call_model` (or raise `max_tokens` for the extractor role). Without it every extractor call returns empty JSON.
- [ ] Full 20-document run (`--limit 20`), optional.
- [ ] **Gate 3:** Feature 5 merged.

## Feature 6: Deterministic checks (Step 3.5, part 1)

- [x] `apps/api/lenses/bill/checks.py`: `run_checks(bill, history, tariff)` returns `{findings, skipped_checks, checks_run, recomputation}`.
- [x] Arithmetic vs tariff engine (flag difference > R0.05), with per-line billed vs tariff rate.
- [x] Estimated readings (two or more consecutive, or true-up > 1.5x normal use).
- [x] Meter sanity (non-decreasing readings, consumption = last two readings).
- [x] Outage consistency (facts and implied figure only, no legal entitlement claims; history must match account number).
- [x] Duplicate or unknown lines.
- [x] Findings match C2 shape: `{id, check, billed, recomputed, difference, explanation, receipt_ids[]}` plus `unit` and `data`.
- [x] Unreadable inputs skip the check with a reason in `skipped_checks`.
- [x] 14 tests in `tests/bill/test_checks.py`: A5 no findings, A6 matches manifest exactly (124 Bill tests passing in total).
- [ ] `receipt_ids` filled once `save_receipt()` exists (Person A).
## Feature 7: Analyst coder (Step 3.5, part 2)

- [x] `apps/api/lenses/bill/prompts/analyst_coder.md` + `analyst.py`: model writes short Python from extracted JSON + tariff + history; only tool is running it.
- [x] Static allow-list before running (`check_code`: imports json/decimal/datetime/math/statistics/fractions only; no eval/exec/getattr/dunders; no `INPUT_DIR` reassignment; max 8000 chars).
- [x] Up to two error-feedback retries (exit code, stderr, rejection reason; host paths scrubbed).
- [x] Results must agree with the tariff engine (`checks.reference_figures`; money ±R0.01, kl ±0.05, days exact).
- [x] Failure / disagreement path: deterministic checks only plus `skipped_checks` entry `analyst_coder`.
- [x] Executed code and output saved as `code` and `output` receipts; `attach_receipts` links them to arithmetic and outage findings.
- [x] 34 tests in `tests/bill/test_analyst.py` (158 Bill tests passing in total).
- [x] Live test `scripts/eval_analyst.py`: **6/6 agreed on the first attempt** with thinking off (~3-6 s); with thinking on 0/2 (empty JSON, fell back to skipped as designed).
- [ ] BLOCKED: real sandbox runner. `runners.LocalSubprocessRunner` is dev only (not a sandbox); needs the worker no-network `code` profile with read-only `/inputs` (Person A). The `CodeRunner.run(code, inputs) -> RunResult` interface is ready for it.
- [ ] BLOCKED: real `save_receipt()` (Gate 0); `InMemoryReceipts` stands in.
- [ ] Gateway thinking-off fix also needed for the `analyst_coder` role (D-B12).

## Feature 8: Report, letter and Bill result page (Step 3.6)

- [x] Result page in plain HTML/CSS/JS (no TSX): `apps/web/bill/index.html`, `bill.css`, `bill.js`. Uses Person A's design tokens. Shows billed, recomputed and difference plus receipt buttons per row, a containment notice, skipped checks, the letter (copy and download .txt), the extracted fields and a "not legal advice" note. Untrusted data is written with `textContent` only.
- [x] Page loads `?job=<id>` (`/api/jobs/{id}` → `result_json`, SSE while running), `?sample=A5|A6|A7`, or a result JSON file. Receipts open in a dialog: embedded content, otherwise `/api/receipts/{id}`.
- [x] `prompts/bill_writer.md` + `writer.py`: letter from structured findings only. Code adds the account details, numbering and receipt refs.
- [x] Letter contains account details, period, numbered findings with receipt refs, review request, written response request.
- [x] No threats, no legal conclusions: banned-phrase list, no numbers outside the findings, one retry with feedback, then a template letter.
- [x] `pipeline.py`: `run_bill_lens` runs extract → checks → analyst → letter. Extract and recompute receipts are attached to every finding.
- [x] `scripts/build_bill_samples.py` builds `apps/web/bill/samples/A5|A6|A7.json` (stub by default, `--live` for real models).
- [x] Live run passed: extractor, analyst agreed, `glm-5.3` letters passed validation on A6 and A7 (D-B14).
- [x] Page checked in the browser (A5, A7, receipt dialog, letter).
- [ ] Upload from the page: blocked on Gate 0 (`/api/intake` accepts only `lens == "link"`, worker has no bill job).
- [ ] **Person A:** writer `max_tokens` must be ≥ 4000 for `glm-5.3`, or switch the writer role to `deepseek-v4.1-flash-1017` (D-B14).
- [ ] **Gate 4:** all features merged.

## Exit checks (joint, section 10)

- [x] A6: all three errors found, each with a receipt (`test_pipeline.py`, live samples).
- [x] A5: no discrepancies.
- [x] A7: same findings as A6 plus `instruction_ignored`.
- [x] Dispute letter has no threats and no legal conclusions.
- [ ] Concurrency: A2 five times while A7 runs; events land on the correct jobs.
- [ ] `model_calls` shows Bill Lens calls through Vultr Serverless Inference.
- [ ] `docs/decisions/decisions-b.md` complete, including fallbacks used.
