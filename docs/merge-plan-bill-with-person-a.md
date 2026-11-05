# Merge plan: Bill Lens (Person B) with Link Lens (Person A)

Status at the start of this plan:

- `origin/feat/day3-bill-lens` @ `564b9c5`: Bill Lens features 1–3 and 5–8 are done. All 176 tests pass offline. Live evals have run against Vultr.
- `origin/link_lens` @ `4767ed8`: Person A's API, queue, gateway, worker and Link Lens. Not merged to `main` yet.
- `main` @ `3c4cb50` is the merge base of both branches.
- A test merge of both branches is **clean**. `git merge-tree` reports no conflicts, because neither branch touches the other's files.

## Current status on `test_merge` (5 Nov, 21:10)

`test_merge` = `link_lens` @ `c90349d` + `feat/day3-bill-lens` @ `d3b0f3b`, plus the wiring commit. The merge had no conflicts, and **201 tests pass**. This branch replaces M1–M5 as the integration branch: test here, then merge to `main`. Setup and env for A: **[bill-integration-for-person-a.md](bill-integration-for-person-a.md)**.

| Item | Status | Where / note |
|------|--------|--------------|
| A1 thinking off | ✅ Bill side | `lenses/bill/model_caller.py` turns it off; the gateway is unchanged |
| A2 writer model | ⏳ deploy | Set `BILL_MODEL_WRITER=deepseek-v4.1-flash-1017` |
| A3 config path | ✅ | Fixed by A in `5d929ff` |
| A4 stub mode | ➖ optional | `scripts/bill_dev_server.py --stub` covers local smoke tests |
| A5 receipts | ✅ | `GET /api/bill/receipts/{id}` (`router.py`, `store.py`) |
| A6 bill intake | ✅ | `POST /api/bill/intake`, JSON base64 (no `python-multipart`) |
| A7 dispatch | ✅ | `main.py`: `lens == "bill"` → background `process_bill_job`, at most 2 at a time |
| A8 worker modes | ✅ | `apps/worker/bill_modes.py` `/run-bill`, included in `worker/main.py` and its Dockerfile |
| A9 parse image | ⏳ deploy | `docker build -t proofbox-parse:latest sandbox/code` on the worker VM |
| A10 tariff | ✅ | `apps/api/tariffs/tariff_v1.json` ships in the API image (test keeps it in sync) |
| A11 web | ✅ | `apps/web/Dockerfile` copies `bill/`; masthead link on the Link page |
| B1–B6 | ✅ | `job.py`, `worker_client.py` (`WorkerCodeRunner`), `store.py` (`ReceiptSaver`), `apps/web/bill/`, D-B15, `test_integration.py` + `test_wiring.py` |
| B7 20-document run | ➖ optional | 5 documents run live |
| J1 contracts | ⏳ | Write `docs/contracts.md` from section 2 (now matches the code) |
| J2–J8 | ⏳ deploy | Need the deployed stack: Docker sandbox test, Gate 2/4 runs, concurrency, `model_calls`, decisions, tag |

The original plan follows. Where it conflicts with the table above or the integration doc, the table and the integration doc win.

At the start of this plan the two halves were not wired together: Bill Lens was a library that nothing in the API, worker or intake called. The status table above shows that this is now done on `test_merge`.

Owner key: **A** = Person A, **B** = Person B, **A+B** = together.

---

## 1. Merge order

| # | Step | Owner | Done when |
|---|------|-------|-----------|
| M1 | Squash-merge `link_lens` into `main` | A | `main` contains `apps/api/{main,db,gateway}.py` and `apps/worker/main.py` |
| M2 | Merge `main` into `feat/day3-bill-lens` and re-run `pytest` | B | 176 tests are still green |
| M3 | Open a PR for `feat/day3-bill-lens` and have A review it (this also covers the pending reviews of Features 1 and 2) | B → A | PR approved |
| M4 | Squash-merge the Bill library PR into `main` | A or B | Bill code is on `main`. It is not wired in yet, so there is no runtime risk |
| M5 | Integration work (sections 3–5) on a new branch `feat/bill-integration`, in small PRs | A + B | Gate 4 passes |

Merging the library before it is wired in (M4) is safe. Nothing imports it yet, so Link Lens keeps working.

---

## 2. Gate 0 contracts we still need to agree (`docs/contracts.md`)

The original contracts (C1–C9) were never written down. These are the ones Bill integration depends on. Agree them in a 15-minute call, write them into `docs/contracts.md`, and merge.

| ID | Contract | As built (was: proposal from B) | Decide |
|----|----------|-----------------|--------|
| K1 | Bill intake | `POST /api/bill/intake` with JSON `{filename, pdf_base64, history?, session_id?}` (maximum 5 MB, `%PDF-` magic check, history ≤ 256 KB). Store the PDF in `receipts` (`kind=pdf`, `blob_base64`). `input_ref` = receipt id. This needs no extra volume | A |
| K2 | Result envelope | Keep B's current `result_json` (`lens:"bill"`, `status`, `summary`, `findings[]`, `receipts{}`, `dispute_letter`, `document`). A's job page just links to `/bill/?job={id}` for `lens == "bill"` | A+B |
| K3 | Lens dispatch | `process_job` branches on `job["lens"]`: `"link"` keeps the current code; `"bill"` runs `lenses.bill.job.process_bill_job(job)` as a background task (at most `BILL_JOBS_PARALLEL`). A full C3 registry is optional | A |
| K4 | Worker sandbox for Bill | Separate `POST /run-bill` (same bearer token) with `mode` `parse_bill` or `code` and `inputs: [{name, b64}]`. The worker writes the inputs to a temporary directory, mounts it read-only at `/inputs`, uses `--network none`, a read-only root filesystem, 20 s, 512 MB and 0.5 CPU, then deletes it. It streams NDJSON `{event, detail, data?}`. `/run` and `JOB_LOCK` are unchanged | A |
| K5 | Receipts | `save_receipt(job_id, kind, content:str, meta:dict) -> id`, written to `receipts.content_json = {content, meta}` with `sha256` of the content. `GET /api/bill/receipts/{id}` returns `{receipt:{id, job_id, kind, sha256, content, meta}}` | B (done) |
| K6 | Events | Bill emits using A's `add_event(job_id, type, detail)`. Types: `bill_received`, `bill_parsed`, `history_missing`, `bill_extracted`, `checks_completed`, `analyst_completed` / `analyst_skipped`, `letter_drafted`, the shared `instruction_ignored`, and the worker's `container_*` and `*_kill` | A+B |
| K7 | Gateway | Bill uses `gateway.client`, `MODELS_CFG` and `_log_call` with thinking off; `BILL_USE_SHARED_GATEWAY=1` switches to `call_model(role, job_id, system_prompt, untrusted_data, schema, image_base64_webp, max_tokens)` | A |

---

## 3. Person A tasks

| # | Task | File | Gate | Blocker | Done when |
|---|------|------|------|---------|-----------|
| A1 | **Turn thinking off in the gateway.** Send `extra_body={"chat_template_kwargs":{"enable_thinking": False}}` to qwen and deepseek models (D-B12). Without it the Bill extractor and analyst return empty content | `apps/api/gateway.py` | G3 | none | A live `extractor` call returns JSON in under 10 s |
| A2 | **Writer role decision.** `glm-5.3` ignores the thinking switch and needs `max_tokens ≥ 4000` (~17 s). The other option is to point `writer` at `deepseek-v4.1-flash-1017` (1.2 s). See D-B14 | `config/models.yaml`, gateway roles | G4 | none | A letter is written live with `source: writer` |
| A3 | **Check that `CONFIG_PATH` works in the container.** The gateway uses `Path(__file__).resolve().parents[2]`. In the image the file is `/app/gateway.py`, which has only two parents, so this probably raises `IndexError` at import. Guard it or use a `PROOFBOX_MODELS_PATH` environment variable | `apps/api/gateway.py` | G0 | none | The API container starts and the roles load from YAML |
| A4 | Optional stub mode: `MODEL_GATEWAY_MODE=stub` returns canned JSON from `fixtures/stubs/` | `apps/api/gateway.py` | G0 | none | Smoke tests run without a key |
| A5 | **Receipts in the DB.** `save_receipt()` helper plus `GET /api/receipts/{id}` (K5) | `apps/api/db.py`, `main.py` | G2 | K5 agreed | The receipt dialog on the Bill page loads real content |
| A6 | **Bill intake** (K1). Add `python-multipart` to requirements. Enforce the size and type limits. Store the PDF and create a job with `lens="bill"` | `apps/api/main.py`, `requirements.txt` | G2 | K1 agreed | `curl -F file=@A6.pdf` returns a `job_id` |
| A7 | **Lens dispatch** in `process_job` (K3). Wrap it in try/except so a failed Bill job is marked `failed` and the queue keeps running | `apps/api/main.py` | G2 | B1 merged | Link and Bill jobs both complete |
| A8 | **Worker modes `parse_bill` and `code`** with `inputs` (K4). Change the global `JOB_LOCK` to allow at least 2 concurrent jobs, or a separate lock per mode, so the concurrency test can pass | `apps/worker/main.py` | G2 | K4 agreed | `parse_bill` on A7.pdf streams `instruction_ignored` and returns parsed JSON |
| A9 | **Build the `proofbox-parse` image** from `sandbox/code/Dockerfile` on the server, and add it to the worker allow-list | server or Coolify | G2 | A8 | `docker images` shows `proofbox-parse` |
| A10 | **Tariff file in the API image.** Either copy `tariffs/` into the build context or set `PROOFBOX_TARIFF_PATH=/app/tariffs/tariff_v1.json`. The prompts already ship inside `lenses/bill/prompts/` | `apps/api/Dockerfile` / Coolify env | G2 | none | `python -c "from lenses.bill.tariff import load_tariff; load_tariff()"` runs inside the container |
| A11 | **Serve the Bill page.** Serve `apps/web/bill/` at `/bill/` and add a "Check a bill" link or upload entry on the main page | web / static config | G4 | none | `/bill/?job=<id>` renders |

## 4. Person B tasks

| # | Task | File | Gate | Blocker | Done when |
|---|------|------|------|---------|-----------|
| B1 | **Job glue.** `process_bill_job(job)` does the following: load the PDF → worker `parse_bill` → `run_bill_lens(call_model=gateway.call_model, runner=WorkerCodeRunner, save_receipt=db adapter, emit=add_event)` → write `result_json` → add `job_completed` | `apps/api/lenses/bill/job.py` | G2 | K1, K4, K5 | Unit test with a fake worker, gateway and DB passes |
| B2 | **`WorkerCodeRunner`.** Implements `CodeRunner.run(code, inputs)`: POSTs `mode=code` to the worker and maps the final result line to `RunResult` | `apps/api/lenses/bill/runners.py` | G2 | K4 | Unit test with a mocked HTTP stream passes |
| B3 | **`save_receipt` adapter.** Replaces `InMemoryReceipts` in production and keeps the in-memory version for tests | `apps/api/lenses/bill/job.py` | G2 | A5 | Receipt ids in `result_json` resolve through `/api/receipts/{id}` |
| B4 | **Upload form on the Bill page.** File input, optional history file, POST to `/api/intake/bill`, then poll or stream events and render the result | `apps/web/bill/{index.html,bill.js}` | G4 | A6 | Uploading A6.pdf in the browser shows 3 findings |
| B5 | **History source decision.** Choose between an optional upload alongside the bill or skipping the history checks with `skipped_checks` (already supported). Record it as D-B15 | `decisions-b.md` | G2 | none | Decision recorded |
| B6 | Contract tests for B1–B3 using fakes (no network, no Docker) | `tests/bill/test_job.py` | G2 | B1–B3 | `pytest` is green |
| B7 | Optional 20-document extractor run once A1 is live | `scripts/eval_extractor.py` | G3 | A1 | 20/20 parsed and the result recorded |

## 5. Joint tasks (on the deployed `main`)

| # | Task | Gate | Done when |
|---|------|------|-----------|
| J1 | Agree K1–K7 and merge `docs/contracts.md` | G0 | Merged |
| J2 | Docker test of the parse image: A7.pdf gives `instruction_ignored`, and no network is reachable | G2 | Logged in `decisions-b.md` |
| J3 | **Gate 2 smoke test:** one real Bill job through the UI (stub models are fine) | G2 | Job `completed`, with events visible |
| J4 | **Gate 4 live run:** A5 shows no discrepancies; A6 shows 3 findings with receipts; A7 shows the same findings plus `instruction_ignored`; the letter contains no threats | G4 | All four checks pass on the deployed site |
| J5 | **Concurrency test:** run A2 five times while A7 runs. Every event lands on the right job | Exit | Both lenses complete |
| J6 | `SELECT role, count(*) FROM model_calls GROUP BY role` shows `extractor`, `analyst_coder` and `writer` | Exit | Rows present |
| J7 | Finish `decisions-b.md`, including the fallbacks used (template letter, skipped checks, writer model) | Exit | Written |
| J8 | Merge, tag `day2-3-done`, and confirm Coolify deployed the tag | Exit | Tag deployed |

## 6. Critical path

```
J1 contracts ─┬─ A1/A3 gateway fixes ───────────────────────────┐
              ├─ A5 receipts ── B3 ─┐                           │
              ├─ A6 intake ─────────┼─ B1 job glue ─ A7 dispatch ┼─ J3 Gate 2 ─ B4 upload UI ─ J4 Gate 4 ─ J5/J6 ─ J8 tag
              └─ A8 worker modes ─ A9 image ─ B2 runner ─┘       │
A10 tariff, A11 static page ─────────────────────────────────────┘
```

The longest chain is the worker modes (A8 → A9 → B2), so A should start there. B can write B1–B3 against the contracts with fakes straight away, without waiting.

## 7. What already works and needs no change

- All of the Bill logic: tariff, checks, extractor, analyst, writer, pipeline, prompts and result page.
- The code uses Python 3.12 syntax and depends only on the standard library, pydantic, FastAPI, httpx and psycopg, all already in A's API image.
- Bill passes its own `max_tokens` (4000 for the writer) straight to the gateway client.
- The `instruction_ignored` detection runs inside the trusted parse script, as C4 requires.
