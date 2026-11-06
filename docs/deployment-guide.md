# Proofbox deployment guide (Link Lens + Bill Lens, `test_merge`)

How to deploy the merged app from branch `test_merge`, step by step. The steps follow the setup in the Day 2 plan, with two hosts:

| Host | What runs there | How |
|------|-----------------|-----|
| **App host** (Coolify) | `apps/api` (FastAPI, port 8000), `apps/web` (nginx, port 80), Postgres | Docker images built by Coolify from the repo |
| **`sandbox-host`** (private IP `10.99.0.3`) | `apps/worker` (FastAPI, port 8080) as **systemd service `proofbox-worker`** from `/opt/proofbox/worker/`, plus Docker + gVisor (`runsc`), the `pb_internal`/`pb_egress` networks, `pb-proxy`, and the sandbox images | Files copied by hand, `systemctl restart` |

> **Important:** the worker is **not** redeployed by pushing to git or by redeploying in Coolify. You have to copy the new worker files to `sandbox-host` and restart the service (step 3). If you skip this, every Bill upload fails with `Worker refused the parse_bill request (HTTP 404)`.

Order matters: **sandbox-host first (steps 2–4), then the API and web (steps 5–7)**. A new API calling an old worker gives exactly that 404.

---

## Step 0. Before you start

- [ ] You can SSH to `sandbox-host` and open the Coolify dashboard.
- [ ] You know the values of `WORKER_TOKEN`, `VULTR_INFERENCE_KEY` and `DATABASE_URL` (in Coolify's env settings for the API).
- [ ] Local tests pass on the commit you are deploying:

```powershell
cd C:\work\2026\AI_Learning\sandbox-spike
git checkout test_merge; git pull
.\.venv\Scripts\python.exe -m pytest -q          # expect 201 passed
git log --oneline -1                              # note the commit hash you deploy
```

- [ ] Everything is pushed: `git status` is clean and `git log origin/test_merge -1` shows the same hash.

---

## Step 1. Get the code onto `sandbox-host`

```bash
ssh root@<sandbox-host>
cd /opt/proofbox
# If there is a git checkout here already:
git -C /opt/proofbox/repo fetch && git -C /opt/proofbox/repo checkout test_merge && git -C /opt/proofbox/repo pull
# Otherwise clone it once:
git clone -b test_merge <repo-url> /opt/proofbox/repo
git -C /opt/proofbox/repo log --oneline -1     # must match the hash from step 0
```

(If the server has no git access, `scp` the folders `apps/worker/` and `sandbox/code/` from your machine instead.)

---

## Step 2. Build the Bill parse sandbox image (`sandbox-host`)

The worker starts this image for every bill, with `--network none`, a read-only root filesystem, 512 MB, 0.5 CPU and a 20 s limit.

```bash
cd /opt/proofbox/repo/sandbox/code
docker build -t proofbox-parse:latest .
docker image ls proofbox-parse           # should show "latest", created just now
```

Check that it runs under gVisor and can parse a PDF without network:

```bash
mkdir -p /tmp/bill-check
cp /opt/proofbox/repo/apps/web/bill/samples/A6_bill_errors.pdf /tmp/bill-check/bill.pdf
ls -l /tmp/bill-check            # must list bill.pdf (~2 KB); if not, stop here
docker run --rm --runtime=runsc --network none --read-only --tmpfs /tmp:size=64m \
  -v /tmp/bill-check:/inputs:ro proofbox-parse:latest python /app/parse_bill.py /inputs/bill.pdf | head -c 60; echo
rm -rf /tmp/bill-check
```

Expected: the output starts with `{"status": "ok", "parser": "parse_bill/1"`.

- `"error": "Input not found: bill.pdf"` means the file wasn't copied. Docker then mounts an empty directory, so check the `ls` output.

- If you see `unknown or invalid runtime name: runsc`, gVisor is not registered. Link Lens needs it too, so fix that (`runsc install && systemctl restart docker`) rather than switching runtime.
- `BILL_SANDBOX_RUNTIME=runc` works as a temporary fallback. If you use it, note it in the decisions log.

---

## Step 3. Update the worker (`sandbox-host`)

### 3a. Find out how the service runs

```bash
systemctl cat proofbox-worker
```

Note:
- `WorkingDirectory=`: `/opt/proofbox/worker`.
- `ExecStart=`: `/opt/proofbox/worker/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080`.
- `Environment=`: `WORKER_TOKEN=dev-secret-token`. This is the code default; the API must use the same value. Change it in both places after the demo.

### 3b. Back up, then copy the new files

```bash
cd /opt/proofbox/worker
cp main.py main.py.bak.$(date +%H%M)
cp /opt/proofbox/repo/apps/worker/main.py       ./main.py
cp /opt/proofbox/repo/apps/worker/bill_modes.py ./bill_modes.py
```

`main.py` from `test_merge` is A's worker plus two lines (`from bill_modes import router as bill_router` and `app.include_router(bill_router)`). `/run`, `JobRequest` and `JOB_LOCK` are unchanged.

> If A changed `main.py` directly on the server since the last commit, `diff main.py.bak.* /opt/proofbox/repo/apps/worker/main.py` first, and keep A's version plus the two Bill lines.

### 3c. Dependencies

`bill_modes.py` needs only `fastapi` and `pydantic`, which the worker already has. Nothing to install. To check (the service runs from `/opt/proofbox/worker/venv`):

```bash
/opt/proofbox/worker/venv/bin/python -c "import fastapi, pydantic; print(fastapi.__version__, pydantic.__version__)"
```

### 3d. Optional worker env

Add these only if you want something other than the defaults, using the service's `Environment=` lines or its `EnvironmentFile`:

| Variable | Default | Meaning |
|----------|---------|---------|
| `BILL_SANDBOX_IMAGE` | `proofbox-parse:latest` | Image from step 2 |
| `BILL_SANDBOX_RUNTIME` | `runsc` | gVisor. Use `runc` only as a recorded fallback |
| `BILL_SANDBOX_TIMEOUT_S` | `20` | Wall-clock kill |
| `BILL_SANDBOX_PARALLEL` | `2` | Concurrent Bill containers |
| `BILL_WORK_DIR` | `/tmp` | Temporary input directories (deleted after each run) |

`WORKER_TOKEN` is shared with `/run`; do not change it.

### 3e. Restart and verify

```bash
systemctl daemon-reload            # only if you edited the unit/env file
systemctl restart proofbox-worker
systemctl status proofbox-worker --no-pager | head -n 15
journalctl -u proofbox-worker -n 30 --no-pager      # no ImportError / traceback
```

```bash
# 1. The route exists
curl -s http://127.0.0.1:8080/openapi.json | grep -o '"/run-bill"'     # prints "/run-bill"
curl -s http://127.0.0.1:8080/openapi.json | grep -o '"/run"'          # Link route still there

# 2. Auth works (expect 401 with a wrong token, not 404)
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8080/run-bill \
  -H 'Authorization: Bearer wrong' -H 'content-type: application/json' -d '{"job_id":"x","mode":"parse_bill","inputs":[]}'

# 3. Full sandbox run with the real token
B64=$(base64 -w0 /opt/proofbox/repo/apps/web/bill/samples/A6_bill_errors.pdf)
curl -s -N -X POST http://127.0.0.1:8080/run-bill \
  -H "Authorization: Bearer $WORKER_TOKEN" -H 'content-type: application/json' \
  -d "{\"job_id\":\"deploy-check\",\"mode\":\"parse_bill\",\"inputs\":[{\"name\":\"bill.pdf\",\"b64\":\"$B64\"}]}" | cut -c1-160
```

Expected NDJSON lines: `container_started` …, parse event(s), `container_destroyed`. **Not** `bill_parse_failed` or `worker_error`.

---

## Step 4. Check the API can reach the worker

Run this from the app host, or from inside the API container in Coolify (Terminal tab):

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://10.99.0.3:8080/openapi.json     # 200
curl -s http://10.99.0.3:8080/openapi.json | grep -o '"/run-bill"'               # "/run-bill"
```

If this returns 404 for `/run-bill` while step 3e passed, `WORKER_URL` points to a different (old) worker. Check `WORKER_URL` in the API env.

---

## Step 5. API (Coolify)

### 5a. Point the API app at `test_merge`

In Coolify → API application → **Source**: branch `test_merge`, base directory `apps/api`, Dockerfile `apps/api/Dockerfile`.

The image copies all of `apps/api`, so it includes `lenses/bill/` (code and prompts) and `tariffs/tariff_v1.json`. No requirement changes: Bill uses the libraries the API already pins.

### 5b. Environment variables

| Variable | Required | Value |
|----------|----------|-------|
| `DATABASE_URL` | already set | unchanged |
| `VULTR_INFERENCE_KEY` | already set | unchanged; Bill uses the same key through A's gateway |
| `WORKER_URL` | already set | `http://10.99.0.3:8080` (the worker from step 3) |
| `WORKER_TOKEN` | already set | same value as on the worker |
| `BILL_MODEL_WRITER` | **add** | `deepseek-v4.1-flash-1017`. A's `MODELS_CFG` maps `writer` to `glm-5.3`, which takes about 17 s per letter (D-B14) |
| `BILL_JOBS_PARALLEL` | optional | `2`: Bill jobs that run beside the Link queue |
| `PROOFBOX_TARIFF_PATH` | optional | Default finds `/app/tariffs/tariff_v1.json` in the image |
| `CORS_ORIGINS` | optional | Default `*`. If you restrict it, include the web origin |
| `BILL_USE_SHARED_GATEWAY` | leave unset | `1` uses A's `call_model` directly, but only once it sends `enable_thinking=False` |

### 5c. Deploy and verify

Click **Redeploy**. In the deployment logs, the build must finish and the container log must show `Application startup complete.`

```bash
API=https://<api-domain>        # or http://<app-host>:8000
curl -s $API/openapi.json | grep -o '"/api/bill/[^"]*"' | sort -u
# "/api/bill/intake"
# "/api/bill/receipts/{receipt_id}"
```

The database needs no migration: `init_db()` already creates `jobs`, `job_events`, `receipts` and `model_calls` at startup, and Bill uses these tables.

---

## Step 6. Web (Coolify)

In Coolify → web application → **Source**: branch `test_merge`, base directory `apps/web`, Dockerfile `apps/web/Dockerfile`. Redeploy.

```bash
WEB=https://<web-domain>
curl -s -o /dev/null -w "%{http_code}\n" $WEB/                               # 200  (Link Lens)
curl -s -o /dev/null -w "%{http_code}\n" $WEB/bill/                          # 200  (Bill Lens)
curl -s -o /dev/null -w "%{http_code}\n" $WEB/bill/samples/A6_bill_errors.pdf   # 200
```

The pages call the API at `?api=` if given, otherwise at their own origin. When web and API are on different domains, use:

```
https://<web-domain>/?api=https://<api-domain>
```

The "Check a water bill →" / back links keep `?api=`.

---

## Step 7. End-to-end smoke test (Bill)

### 7a. From the browser

1. Open `https://<web-domain>/bill/?api=https://<api-domain>`.
2. Upload `A6_bill_errors.pdf` and `history.json` (both are in `apps/web/bill/samples/`, or click the sample buttons), then click **Check my bill**.
3. Expected within about 25 s:
   - The timeline goes `bill_received → container_started → container_destroyed → bill_parsed → bill_extracted → checks_completed → analyst_completed → letter_drafted → job_completed`.
   - **3 findings:** `arithmetic`, `estimated_readings`, `outage_consistency`.
   - Billed **R875.15**, should be **R740.60**, difference **+R134.55**.
   - A dispute letter is shown, and the receipt links open.
4. **A7** (`A7_bill_injection.pdf`): the same findings, plus an `instruction_ignored` event.
5. **A5** (`A5_bill_clean.pdf`): no findings and no letter.

### 7b. From the command line

```bash
B64=$(base64 -w0 apps/web/bill/samples/A6_bill_errors.pdf)
HIST=$(cat apps/web/bill/samples/history.json)
curl -s -X POST "$API/api/bill/intake" -H 'content-type: application/json' \
  -d "{\"filename\":\"A6.pdf\",\"pdf_base64\":\"$B64\",\"history\":$HIST}"
# {"job_id":"job-…","status":"queued"}
curl -N "$API/api/jobs/<job_id>/events"        # stream until job_completed
curl -s "$API/api/jobs/<job_id>" | head -c 600  # status "completed", result_json.findings has 3 items
```

### 7c. Link Lens still works (regression)

Run the Day 2 exit checks on the Link page: A1 is `dangerous`, A2 shows `download_quarantined` + `network_blocked`, A3 is `no_issue_found`, and `/demo-fixtures-9x7k/submissions-count` returns `{"count": 0}`.

---

## Step 8. Joint checks (J5–J6)

**J5, concurrency:** start one Link job and two Bill jobs at the same time. All three should finish. A Link job must not wait about 20 s behind a Bill job.

```bash
for f in A6_bill_errors A7_bill_injection; do
  B64=$(base64 -w0 apps/web/bill/samples/$f.pdf)
  curl -s -X POST "$API/api/bill/intake" -H 'content-type: application/json' \
    -d "{\"filename\":\"$f.pdf\",\"pdf_base64\":\"$B64\"}" & done; wait
# meanwhile submit a Link URL in the UI, then watch it finish
```

On `sandbox-host`, `docker ps --filter label=proofbox.owner=b` should never show more than 2 containers, and none should be left over afterwards.

**J6, model calls are logged:**

```sql
SELECT role, model, latency_ms, prompt_tokens, completion_tokens, outcome FROM model_calls
WHERE job_id = '<bill job_id>' ORDER BY created_at;
-- extractor, analyst, writer (writer = deepseek-v4.1-flash-1017)
```

---

## Step 9. Finish

- [ ] Note the deployed commit hash in `docs/person-b-checklist.md` and the decisions log, and record any fallback (for example `runc`).
- [ ] Tag the release: `git tag -a day3-deploy -m "Link + Bill on test_merge" && git push origin day3-deploy`.
- [ ] Merge `test_merge` → `main` when both of you agree.
- [ ] Delete the `main.py.bak.*` files on `sandbox-host` once everything is stable.

---

## Rollback

| Part | How |
|------|-----|
| Worker | `cp /opt/proofbox/worker/main.py.bak.<HHMM> /opt/proofbox/worker/main.py && systemctl restart proofbox-worker`. `bill_modes.py` can stay; it is unused without the include |
| API / web | Coolify → Deployments → redeploy the previous successful deployment, or switch the branch back to `link_lens` |
| Bill only | Leave everything deployed and just don't link to `/bill/`. Link jobs never touch Bill code (`lens == "link"` path unchanged) |

---

## Troubleshooting

| Symptom (API log / UI) | Cause | Fix |
|------------------------|-------|-----|
| `Worker refused the parse_bill request (HTTP 404): {"detail":"Not Found"}` | The worker is still the old code without `/run-bill` | Step 3 (copy `main.py` + `bill_modes.py`, restart); verify with step 4 |
| `… (HTTP 401)` | `WORKER_TOKEN` differs between API and worker | Make both the same, then redeploy the API or restart the worker |
| `… (HTTP 422)` | API/worker version mismatch in the request body | Deploy both from the same `test_merge` commit |
| `SandboxError` / connection refused / timeout | `WORKER_URL` wrong, the worker is down, or the private network is down | `systemctl status proofbox-worker`; from the API container, `curl $WORKER_URL/openapi.json` |
| Event `bill_parse_failed` with `Unable to find image` / `No such image` | Step 2 not done | `docker build -t proofbox-parse:latest sandbox/code` |
| `bill_parse_failed` with `unknown or invalid runtime name: runsc` | gVisor not registered on this Docker daemon | `runsc install && systemctl restart docker`, or set `BILL_SANDBOX_RUNTIME=runc` temporarily and record it |
| `timeout_kill` / `memory_kill` | The PDF is too big or complex for 20 s / 512 MB | Expected for hostile files; for real bills, try `BILL_SANDBOX_TIMEOUT_S=30` |
| `bill_extracted` never arrives, or the model errors are 401 | `VULTR_INFERENCE_KEY` missing or wrong in the API env | Set it in Coolify and redeploy |
| Extractor/analyst return empty content | Thinking is on (`BILL_USE_SHARED_GATEWAY=1` with the old gateway) | Unset `BILL_USE_SHARED_GATEWAY` |
| Letter step takes about 17 s | `BILL_MODEL_WRITER` not set (falls back to `glm-5.3`) | Set `BILL_MODEL_WRITER=deepseek-v4.1-flash-1017` |
| `FileNotFoundError` mentioning `tariff_v1.json` | `PROOFBOX_TARIFF_PATH` points to a missing file | Unset it (the image ships `/app/tariffs/tariff_v1.json`) |
| Browser: CORS error | `CORS_ORIGINS` doesn't include the web origin | Add it, or use `*` |
| Bill page loads but uploads go to the wrong host | The web app and API are on different domains, without `?api=` | Open `/bill/?api=https://<api-domain>` |
| `/bill/` returns 404 on the web domain | The web image was built from `link_lens` (no `COPY bill`) | Set the web app's branch to `test_merge` and redeploy |
