# Person B decisions

## D-B1 Tariff engine rounding (Step 3.1)

- **Decision:** All money and consumption values use `Decimal`. Each charge line (tier and fixed) is rounded to cents with `ROUND_HALF_UP`. The subtotal is the sum of rounded lines. VAT is calculated on the subtotal and rounded once. Total = subtotal + VAT.
- **Rationale:** Municipal bills print rounded line items, so recomputing at line level makes billed and recomputed rows directly comparable. One documented rule keeps the R0.05 arithmetic threshold meaningful.
- **Alternatives considered:** Rounding only the final total (hides per-line errors); VAT per line (does not match how the example bill applies VAT).

## D-B2 VAT scope

- **Decision:** VAT at 15% applies to the whole subtotal, including water service and refuse fixed charges.
- **Rationale:** The guide lists one VAT rate for the tariff without exemptions. Revisit if the fixture bill layout shows VAT on a subset of lines.

## D-B3 Numeric inputs

- **Decision:** The engine accepts `Decimal`, `int` or numeric strings and rejects `float`, `bool`, NaN, infinity and negative consumption.
- **Rationale:** Floats introduce binary rounding errors in money. Extracted JSON should be parsed with `parse_float=Decimal`.

## D-B4 Tariff file location

- **Decision:** `load_tariff()` uses `PROOFBOX_TARIFF_PATH` if set, otherwise searches parent directories for `tariffs/tariff_v1.json`.
- **Rationale:** The API Docker build context is `apps/api`, so the container must either copy the tariff file or set the environment variable. Tracked as an integration item with Person A.

## D-B5 Fixture design (Step 3.2)

- **Decision:** A5 is a separate clean account; A6, A7 and A8 share account `1004 7781 02` for September 2026. Both bills use 18 kl so the only arithmetic difference in A6 is the planted wrong tier rate (6-15 kl at R38 instead of R25).
- **Decision:** The outage error is planted as an estimate: two consecutive estimated readings at the 18 kl average while A8 logs 9 of 30 days without supply. Expected wording: billed use equals the normal average although 9 of 30 days had no supply (implied 12.6 kl). No entitlement claim.
- **Decision:** The A7 injection is white 1 pt text that pdfplumber still extracts, so the parse step sees it and must emit `instruction_ignored`.
- **Decision:** PDF creation date is fixed so reruns are byte-identical and manifest hashes stay stable.

## D-B6 Draft extractor output shape

- **Decision:** `fixtures/stubs/bill_extractor_*.json` define the draft bill schema: account and period details, `meter_readings[{date, reading_kl, type}]`, `consumption_kl`, `tariff_lines[{description, quantity_kl, rate_per_kl, amount}]`, `fixed_charges[{description, amount}]`, `subtotal`, `vat_rate`, `vat`, `total_due`. Numbers are strings so they load into `Decimal`.
- **Follow-up:** Formalise as a JSON schema in Step 3.4; regenerate stubs if the shape changes.

## D-B7 Dev dependencies

- **Decision:** `fpdf2` (write) and `pdfplumber` (verify) live in `scripts/requirements-fixtures.txt`, not `apps/api/requirements.txt` (owned by Person A). `pdfplumber` will also go into the `sandbox/code` image in Step 3.3.

## D-B8 Parser in code container (Step 3.3)

- **Decision:** Lines matching injection patterns are removed from the model text and reported as trusted `instruction_ignored` events. Hidden lines (white or tiny text) without an injection phrase are dropped silently into `hidden_lines`. Result: A7 model text equals A6.
- **Decision:** The script writes `/out/parse.json` (same pattern as Person A's browser `trace.json`) and also prints JSON to stdout. The Dockerfile uses `CMD`, not `ENTRYPOINT`, so the analyst coder can reuse the image.
- **Fallback used:** Docker is not installed on the dev machine, so the image is unbuilt; the script is tested in plain Python.

## D-B9 Feature 4 skipped

- **Decision:** Link Lens static checks are not built by Person B. Person A's `run_static_checks` in `link_lens.py` already covers them.

## D-B10 Extractor (Step 3.4)

- **Decision:** The model caller is injected (`call_model` matching Person A's gateway signature); the extractor never imports the gateway, so it works with stubs and tests.
- **Decision:** Grounding: every text value must appear in the document text, every number must be a number in the document, and a reading's type must be on the same line as its date. Failures become `"unreadable"`. Grounding never "fixes" genuine bill errors.
- **Decision:** The prompt lives in `apps/api/lenses/bill/prompts/` because the API Docker build context is `apps/api`.

## D-B11 Deterministic checks (Step 3.5)

- **Decision:** Thresholds: arithmetic R0.05; meter tolerance 0.05 kl; at least 2 consecutive estimates; true-up when an actual reading follows an estimate and use exceeds 1.5x normal; outage flagged when there are 3 or more no-supply days and billed use exceeds implied use by more than 10%.
- **Decision:** Normal use is the average of previous bills from history with the same account number (at least 2). Implied use = normal x supplied days / period days.
- **Decision:** Findings are numbered `F1..Fn`; `receipt_ids` stays empty until `save_receipt()` exists. Explanations state facts and figures only, tested against a list of legal words.

## D-B12 Extractor model must run with thinking off (live test, 5 Nov)

- **Finding:** `qwen3.8-27b` ignores the `/no_think` prefix for the extractor prompt. It spends all 1500 `max_tokens` on hidden reasoning (`finish_reason=length`, empty content), so every call fails validation 3 times and the bill becomes `unreadable`. With 4000 tokens it does finish (~3050 tokens), but slowly.
- **Decision:** Send `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` (`reasoning_effort: "none"` also works). Result: ~636 tokens, ~2.5 s per bill, valid JSON on the first attempt.
- **Action for Person A:** add this to `gateway.call_model` (at least for the extractor role). `scripts/eval_extractor.py` mirrors the gateway with this change; `--thinking` reproduces the failure.
- **Result:** 5-document live test PASS: 193/194 fields correct, 0 wrong, 1 account number rejected by grounding (model typo caught, became `unreadable`), deterministic checks agree on all 5.
- **Update (analyst live test):** `deepseek-v4.1-flash-1017` has the same problem: with thinking on it returns empty content for the analyst prompt. The gateway fix is needed for every JSON role, not just the extractor.

## D-B13 Analyst coder (Step 3.5)

- **Decision:** The model sees the extracted bill, the tariff and the history, and returns `{"code": ...}`. Inputs are JSON files under `INPUT_DIR` (a constant the runner prepends; `/inputs` in the container), so no data is pasted into code.
- **Decision:** Before anything runs, an AST allow-list rejects other imports, `eval`/`exec`/`getattr`-style builtins, dunder names and `INPUT_DIR` reassignment. This is defence in depth only; the no-network sandbox is the security boundary. The prompt includes the exact file-reading helper; without it the model used `os` on every first attempt.
- **Decision:** Agreement uses `checks.reference_figures` (engine total, VAT, subtotal, normal use, period/outage/supplied days, implied use). Tolerances: money ±R0.01, kl ±0.05, days exact. Only figures the engine can compute are compared, and the analyst must supply all of them.
- **Decision:** Retry budget: 1 attempt + 2 error-feedback retries (the gateway's own 3 JSON attempts are separate). No code, rejected code, crash, timeout, non-JSON output or disagreement all end in `skipped_checks: analyst_coder`; the deterministic findings still stand.
- **Decision:** Receipts are saved only when the figures agree: `code` (executed program with `INPUT_DIR = '/inputs'` header) and `output` (stdout). Both are linked to the arithmetic and outage findings.
- **Decision:** `CodeRunner` is an injected interface. `LocalSubprocessRunner` is development-only (timeout, temp dir, empty env, `python -I`); it is not a sandbox and must not run on a server.

## D-B14 Dispute letter, pipeline and result page (Step 3.6)

- **Decision:** The writer model only words the letter. It sees only the findings, the municipality and the billing period, and returns JSON (`subject, greeting, opening, findings[{id, paragraph}], request, closing`). Code adds the account details, numbering, receipt references and sign-off, so they are always correct. Unreadable fields become a fill-in placeholder.
- **Decision:** Code validates the wording: finding ids must match in order; banned phrases (legal conclusions, threats, ultimatums, injection echoes); every number must appear in the findings; each paragraph must state its billed and recomputed figures; the request must ask for a review and a written response. One retry with the problems as feedback, then a fixed template letter (`source: template`). No findings means no letter.
- **Decision:** `run_bill_lens` saves an `extract` receipt (document text plus extracted values) and a `recompute` receipt (engine calculation plus check results) and attaches both to every finding, so every finding has a receipt even when the analyst is skipped. Analyst `code`/`output` receipts are added to the arithmetic and outage findings.
- **Decision:** The result page is plain HTML/CSS/JS under `apps/web/bill/` with Person A's design tokens. All result data is written with `textContent`. It reads `?job=` from the API, or sample JSON built by `scripts/build_bill_samples.py`, which embeds receipt contents so the page works without the API.
- **Finding (live):** `glm-5.3` always reasons before answering on Vultr: `enable_thinking: false`, `thinking: {type: disabled}` and `reasoning_effort: none` are all ignored for the letter prompt (1500 reasoning tokens, empty content). With `max_tokens` 4000 it used about 3.2k tokens and 17 s, and the letter passed validation. `deepseek-v4.1-flash-1017` (the configured writer fallback) wrote a valid letter in about 1.2 s with 300 tokens. The writer uses `max_tokens=4000`.
- **Action for Person A:** the gateway must honour the caller's `max_tokens` for the writer, or switch `roles.writer` to `deepseek-v4.1-flash-1017` for demo speed.

## D-B15 Upload and integration without touching Person A's files (Step 4)

- **Decision:** Bill intake is `POST /api/bill/intake` with a JSON body (`filename`, `pdf_base64`, optional `history`, `session_id`), not multipart, because Person A's API has no `python-multipart`. Limits: PDF at most 5 MB and must start with `%PDF-`; history at most 256 KB, with lists of at most 400 rows. The filename is sanitised. The PDF is stored as a `pdf` receipt (`blob_base64`), and `jobs.input_ref` points to it. Blobs are never served back.
- **Decision:** The worker gets a separate `POST /run-bill` router (`apps/worker/bill_modes.py`, modes `parse_bill` and `code`, `inputs:[{name,b64}]`), because Person A's `JobRequest` would drop an `inputs` field. Same bearer token. Sandbox: gVisor, no network, read-only root, all capabilities dropped, 512 MB, 0.5 CPU, 64 pids, inputs read-only at `/inputs`, 20 s timeout.
- **Decision:** All integration code lives in Bill-owned files. Person A plugs it in with `include_router` twice and a 3-line `lens == "bill"` dispatch in `process_job` (see `docs/bill-integration-for-person-a.md`). The API only forwards container lifecycle events from the worker. `job.py` emits its own Bill events, and the completion or failure event is written together with the job status update, so SSE never sees a final event before the result.
- **Decision:** The model caller reuses the gateway client, the role config and `_log_call`, but turns thinking off (D-B12). `BILL_USE_SHARED_GATEWAY=1` switches to `gateway.call_model` unchanged.
- **Dev only:** `scripts/bill_dev_server.py` runs the whole flow in memory with a local subprocess parser (not a sandbox; events are marked `DEV:`). Live A6 run: about 23 s, 3 findings, analyst agreed, writer letter.
