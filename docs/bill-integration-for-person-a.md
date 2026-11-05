# Bill Lens: how to plug it into the Proofbox app (for Person A)

Bill Lens is complete on `feat/day3-bill-lens`. It covers upload, sandboxed parsing, extraction, checks, the analyst, the dispute letter and the result page. None of your files were changed: everything lives in Bill-owned modules. To wire it in, you add **5 lines in the API, 2 in the worker and 1 in the worker Dockerfile**, plus one image build and one env var.

## 1. What is on the branch

| Path | What it does |
|------|--------------|
| `apps/api/lenses/bill/router.py` | `POST /api/bill/intake` and `GET /api/bill/receipts/{id}` |
| `apps/api/lenses/bill/job.py` | `process_bill_job(job)`, the queue entry point for `lens == "bill"` |
| `apps/api/lenses/bill/store.py` | `PostgresStore` built on your `db.pool` / `db.add_event` and the existing `jobs`, `job_events` and `receipts` tables (no schema change) |
| `apps/api/lenses/bill/worker_client.py` | Calls the worker's `/run-bill` and forwards container lifecycle events |
| `apps/api/lenses/bill/model_caller.py` | Uses your `gateway.client`, `MODELS_CFG` and `_log_call`, with thinking turned off (D-B12) |
| `apps/worker/bill_modes.py` | Worker `POST /run-bill`: the no-network gVisor sandbox for PDF parsing and analyst code |
| `sandbox/code/` | Image `proofbox-parse:latest` (pdfplumber + parse script) |
| `apps/web/bill/` | Bill page in plain HTML/CSS/JS: upload, live progress, results, receipts, letter |
| `scripts/bill_dev_server.py` | Local full-stack dev server (in memory, dev only) |

## 2. API: `apps/api/main.py` (5 lines)

```python
# with the other imports
from lenses.bill.router import router as bill_router
from lenses.bill.job import process_bill_job

# after app = FastAPI(...) and the CORS middleware
app.include_router(bill_router)

# first lines inside process_job(job)
    if job["lens"] == "bill":
        await process_bill_job(job)
        return
```

Your `claim_next_job` already marks the job `running`. After that, `process_bill_job` handles everything itself: it emits events, then sets `completed` with `result_json`, or `failed`. It runs in a thread, so the event loop is never blocked. It reuses your `/api/jobs/{id}` and `/api/jobs/{id}/events` (SSE) endpoints unchanged.

## 3. Worker (2 lines + 1 Dockerfile line)

`apps/worker/main.py`:

```python
from bill_modes import router as bill_router
app.include_router(bill_router)
```

`apps/worker/Dockerfile`, next to `COPY main.py .`:

```dockerfile
COPY bill_modes.py .
```

Bill uses its own `/run-bill` route because your `JobRequest` has no `inputs` field. The route uses the same bearer `WORKER_TOKEN`. Every sandbox it starts runs with `--runtime=runsc --network none --read-only --cap-drop=ALL --security-opt no-new-privileges --memory 512m --cpus 0.5 --pids-limit 64`, a tmpfs `/tmp`, and the input files mounted read-only at `/inputs`. The temporary directory is deleted afterwards.

## 4. Build the sandbox image (on the worker VM)

```bash
docker build -t proofbox-parse:latest sandbox/code
```

## 5. Environment

| Variable | Where | Required | Default / note |
|----------|-------|----------|----------------|
| `PROOFBOX_TARIFF_PATH` | API | **yes** | The API image only contains `apps/api`, so either mount `tariffs/tariff_v1.json` and point to it, or `COPY` it into the image |
| `WORKER_URL`, `WORKER_TOKEN` | API | already set | Same values Link Lens uses |
| `WORKER_TOKEN` | worker | already set | |
| `BILL_MODEL_WRITER` | API | recommended | `deepseek-v4.1-flash-1017`. `glm-5.3` needs `max_tokens` ≥ 4000 (D-B14) |
| `BILL_SANDBOX_RUNTIME` | worker | no | `runsc` (set to `runc` only if gVisor is missing; record it as a fallback) |
| `BILL_SANDBOX_IMAGE` | worker | no | `proofbox-parse:latest` |
| `BILL_SANDBOX_TIMEOUT_S` / `BILL_SANDBOX_PARALLEL` | worker | no | `20` / `2` |
| `BILL_WORK_DIR` | worker | no | `/tmp`. It must be a path the Docker daemon can bind-mount |
| `BILL_USE_SHARED_GATEWAY=1` | API | no | Use `gateway.call_model` as is, if you add thinking-off there yourself |
| `CORS_ORIGINS` | API | only if the web app is on another origin | |

## 6. Web

- The Bill page is `apps/web/bill/`. Its nav links back to your page with `../`, and your page can link to it with `bill/` (or `bill/?job={id}` for a bill job).
- The page calls the API at `location.origin`. If the API is on another host, open `/bill/?api=https://api.example.com` and set `CORS_ORIGINS`.
- Upload is JSON with base64 content (your API has no `python-multipart`): `{filename, pdf_base64, history?, session_id?}`. The limits are 5 MB, the file must start with `%PDF-`, and the optional history JSON is capped at 256 KB.

## 7. Smoke test after deploy

```bash
B64=$(base64 -w0 apps/web/bill/samples/A6_bill_errors.pdf)
HIST=$(cat apps/web/bill/samples/history.json)
curl -s -X POST "$API/api/bill/intake" -H 'content-type: application/json' \
  -d "{\"filename\":\"A6.pdf\",\"pdf_base64\":\"$B64\",\"history\":$HIST}"
# -> {"job_id":"job-…","status":"queued"}
curl -N "$API/api/jobs/<job_id>/events"
```

Expected events: `job_queued → bill_received → container_started → container_destroyed → bill_parsed → bill_extracted → checks_completed → analyst_completed → letter_drafted → job_completed`. The result has 3 findings (`arithmetic`, `estimated_readings`, `outage_consistency`): billed R875.15, should be R740.60, difference +R134.55. A7 adds `instruction_ignored`. A5 has no findings and no letter.

Or open `/bill/`, click **Check my bill** with A6 and the history file, and follow the steps.

## 8. Run it locally without Docker or Postgres

```powershell
python scripts/bill_dev_server.py --stub --port 8790   # canned model replies
python scripts/bill_dev_server.py --port 8790          # live models (needs VULTR_INFERENCE_KEY in .env)
# open http://127.0.0.1:8790/bill/
```

This is dev only. Parsing runs in a local process, not the sandbox, and every event says `DEV:`. A live A6 run took about 23 s, end to end.

## 9. Things to watch

- **`gateway.py` path bug:** `Path(__file__).resolve().parents[2]` raises `IndexError` when the file is `/app/gateway.py` in the container. Mount `config/models.yaml` and read the path from an env var, or use a guarded lookup.
- Bill model calls go through your gateway client and `_log_call`, so they appear in `model_calls` with `job_id`.
- The uploaded PDF is stored as a receipt of kind `pdf` (`blob_base64`). `/api/bill/receipts/{id}` never returns blobs and only serves receipts belonging to bill jobs.
