# Bill Lens integration (for Person A)

Bill Lens is merged and wired into the app on **`test_merge`**, which is your `link_lens` (`c90349d`) plus `feat/day3-bill-lens` (`d3b0f3b`). In code, nothing is left to wire. The only remaining steps are deploy steps: build one image and set a few env vars (sections 4 and 5).

## 0. Status (5 Nov, 21:10)

| Branch | Head | Contents |
|--------|------|----------|
| `origin/link_lens` (A) | `c90349d` | `5d929ff` hard-codes `MODELS_CFG` (roles only); `c90349d` adds the nginx `apps/web/Dockerfile` |
| `origin/feat/day3-bill-lens` (B) | `d3b0f3b` | Bill Lens, upload page, `/api/bill/*`, `process_bill_job`, worker `/run-bill`, dev server, tests |
| `test_merge` | merge + wiring commit | Both of the above, plus the wiring changes in section 2 |

- The merge had **no conflicts**. **201 tests pass**: 196 Bill tests plus 5 wiring tests in `tests/bill/test_wiring.py`.
- Your gateway change works with Bill. The Bill caller uses `gateway.client`, `MODELS_CFG["roles"]`, `MODELS_CFG.get("defaults", {})` and `_log_call` with the same signature, and turns thinking off itself.
- The earlier `parents[2]` `IndexError` in `gateway.py` is fixed by `5d929ff`.

## 1. Bill-owned files

| Path | What it does |
|------|--------------|
| `apps/api/lenses/bill/router.py` | `POST /api/bill/intake` and `GET /api/bill/receipts/{id}` |
| `apps/api/lenses/bill/job.py` | `process_bill_job(job)`, the queue entry point for `lens == "bill"` |
| `apps/api/lenses/bill/store.py` | `PostgresStore` on your `db.pool` / `db.add_event` and the existing `jobs`, `job_events` and `receipts` tables (no schema change) |
| `apps/api/lenses/bill/worker_client.py` | Calls the worker's `/run-bill` and forwards container lifecycle events |
| `apps/api/lenses/bill/model_caller.py` | Your gateway client with thinking turned off (D-B12) |
| `apps/api/tariffs/tariff_v1.json` | Copy of `tariffs/tariff_v1.json` inside the API build context, so the image ships it at `/app/tariffs/`. A test keeps the two files identical |
| `apps/worker/bill_modes.py` | Worker `POST /run-bill`: the no-network gVisor sandbox for PDF parsing and analyst code |
| `sandbox/code/` | Image `proofbox-parse:latest` (pdfplumber + parse script) |
| `apps/web/bill/` | Bill page (plain HTML/CSS/JS): upload, live progress, results, receipts, letter |
| `scripts/bill_dev_server.py` | Local full-stack dev server (in memory, dev only) |

## 2. Changes made to your files on `test_merge`

**`apps/api/main.py`**
- Imports `process_bill_job` and `bill_router`.
- Calls `app.include_router(bill_router)` after the CORS middleware.
- At the top of `process_job`: a job with `lens == "bill"` waits for one of `BILL_JOBS_PARALLEL` slots (default 2), then starts `process_bill_job` as a background task and returns. The queue loop goes straight back to claiming jobs, so a Bill job (~20 s with live models) never holds up Link jobs. The concurrency check (J5) needs this.
- On shutdown, the API waits up to 30 s for running Bill jobs before closing the DB pool.
- Link Lens code is unchanged.

**`apps/worker/main.py`**
- `from bill_modes import router as bill_router` and `app.include_router(bill_router)`.
- `/run`, `JobRequest` and `JOB_LOCK` are untouched. `/run-bill` has its own limit (`BILL_SANDBOX_PARALLEL`, default 2).

**`apps/worker/Dockerfile`**
- `COPY bill_modes.py .`

**`apps/web/Dockerfile`**
- `COPY bill /usr/share/nginx/html/bill`

**`apps/web/index.html`**
- A "Check a water bill →" link in the masthead goes to `bill/`, and carries `?api=` over when it is set.
- The Bill page's links back to `../` carry `?api=` the same way.

The Bill sandbox follows the same pattern as Link: it bind-mounts a temporary directory under `/tmp` and calls `docker run`. Every Bill sandbox runs with `--runtime=runsc --network none --read-only --cap-drop=ALL --security-opt no-new-privileges --memory 512m --cpus 0.5 --pids-limit 64`, a tmpfs `/tmp`, and the inputs mounted read-only at `/inputs`. The temporary directory is deleted afterwards.

## 3. API routes

| Route | Body / result |
|-------|---------------|
| `POST /api/bill/intake` | JSON `{filename, pdf_base64, history?, session_id?}` (base64, because the API has no `python-multipart`). PDF at most 5 MB, must start with `%PDF-`. History at most 256 KB. Returns `{job_id, status:"queued"}`. Errors: 413 too big, 415 not a PDF, 422 bad input |
| `GET /api/bill/receipts/{id}` | `{receipt:{id, job_id, kind, sha256, content, meta}}`. Only receipts of bill jobs; never returns the PDF blob |
| `GET /api/jobs/{id}`, `GET /api/jobs/{id}/events` | Your existing endpoints, used unchanged by the Bill page |

## 4. Build the sandbox image (on the worker VM)

```bash
docker build -t proofbox-parse:latest sandbox/code
```

## 5. Environment

| Variable | Where | Required | Default / note |
|----------|-------|----------|----------------|
| `WORKER_URL`, `WORKER_TOKEN` | API | already set | Same values Link Lens uses |
| `WORKER_TOKEN` | worker | already set | |
| `BILL_MODEL_WRITER` | API | recommended | `deepseek-v4.1-flash-1017`. `MODELS_CFG` maps `writer` to `glm-5.3`, which takes ~17 s per letter (D-B14). Any role can be overridden with `BILL_MODEL_<ROLE>` |
| `BILL_JOBS_PARALLEL` | API | no | `2` Bill jobs at a time |
| `PROOFBOX_TARIFF_PATH` | API | no | Defaults to `/app/tariffs/tariff_v1.json`, which is shipped in the image |
| `BILL_SANDBOX_RUNTIME` | worker | no | `runsc`. Use `runc` only if gVisor is missing, and record it as a fallback |
| `BILL_SANDBOX_IMAGE` | worker | no | `proofbox-parse:latest` |
| `BILL_SANDBOX_TIMEOUT_S` / `BILL_SANDBOX_PARALLEL` | worker | no | `20` / `2` |
| `BILL_WORK_DIR` | worker | no | `/tmp` (same as Link's `/tmp/job_*` directories) |
| `BILL_USE_SHARED_GATEWAY=1` | API | no | Use `gateway.call_model` as is, if you add thinking-off there yourself |
| `CORS_ORIGINS` | API | only if set | The default is `*`. If you restrict it, include the web origin |

## 6. Web

- nginx serves `/` (Link Lens) and `/bill/` (Bill Lens, including `samples/`).
- Both pages call the API at `?api=` if given, otherwise `location.origin`. When the web app and API are on different hosts, open `http://<web-host>/?api=http://<api-host>:8000`; the nav links keep `?api=` when you switch pages. A reverse proxy for `/api/` in nginx would remove the need for `?api=`.
- A finished Bill job can be opened with `/bill/?job=<id>`.

## 7. Smoke test after deploy

```bash
B64=$(base64 -w0 apps/web/bill/samples/A6_bill_errors.pdf)
HIST=$(cat apps/web/bill/samples/history.json)
curl -s -X POST "$API/api/bill/intake" -H 'content-type: application/json' \
  -d "{\"filename\":\"A6.pdf\",\"pdf_base64\":\"$B64\",\"history\":$HIST}"
# -> {"job_id":"job-…","status":"queued"}
curl -N "$API/api/jobs/<job_id>/events"
```

Expected events: `job_queued → bill_received → container_started → container_destroyed → bill_parsed → bill_extracted → checks_completed → analyst_completed → letter_drafted → job_completed`.
- **A6:** 3 findings (`arithmetic`, `estimated_readings`, `outage_consistency`): billed R875.15, should be R740.60, difference +R134.55.
- **A7:** the same findings plus `instruction_ignored`.
- **A5:** no findings and no letter.

Or open `http://<web-host>/bill/?api=http://<api-host>:8000`, drop A6 and the history file, and click **Check my bill**.

## 8. Run it locally without Docker or Postgres

```powershell
python scripts/bill_dev_server.py --stub --port 8790   # canned model replies
python scripts/bill_dev_server.py --port 8790          # live models (needs VULTR_INFERENCE_KEY in .env)
# open http://127.0.0.1:8790/bill/  (Link page: /index.html)
```

This is dev only. Parsing runs in a local process, not the sandbox, and every event says `DEV:`. A live A6 run took about 23 s, end to end.

## 9. Things to watch

- If you change `tariffs/tariff_v1.json`, copy it to `apps/api/tariffs/` as well. `test_api_image_has_the_same_tariff` fails until you do.
- If you put `defaults` (for example `system_prefix`, `temperature`) back into `MODELS_CFG`, Bill picks them up automatically.
- Bill model calls go through your gateway client and `_log_call`, so they appear in `model_calls` with `job_id` (J6).
- The uploaded PDF is stored as a receipt of kind `pdf` (`blob_base64`) and is never served back.
