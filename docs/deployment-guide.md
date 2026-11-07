# Proofbox deployment guide: Day 4

Deploy Link Lens, Bill Lens, Letter Lens and the case file from **`letter-lens`**.
This guide carries forward the Day 3 guide from `test_merge`, updated for the
Day 4 code. It is an operational guide, not confirmation that deployment has
been performed or tested on your servers.

## What changed since Day 3

| Component | Day 4 change |
|---|---|
| API | Letter intake and jobs, case files, clocks, replies and pack generation. New `reportlab` and `tzdata` dependencies. |
| Web | New `/letter/` and `/case/` pages. Built-in Nginx reverse proxy (`nginx.conf`) with dynamic `API_URL` configuration (`40-configure-api-url.sh`) and 25 MB upload limit. |
| Worker | `/run-bill` gains `parse_document` for Letter Lens; `code` is also used for its document checks. |
| Sandbox image | `proofbox-parse:latest` must be rebuilt to include `parse_document.py`. |
| Database | API startup creates and migrates case-related tables. **Back up and review the migration before starting the new API.** |
| Storage | Case pack PDFs and ZIPs need durable, writable storage at `CASE_STORAGE_DIR`. |

**Deployment order:** prepare and back up → rebuild the sandbox image → update
the worker → deploy API → deploy web → verify all lenses and the case workflow.
The API and web are assumed to run in Coolify; the worker previously shown in
your logs runs as systemd service `proofbox-worker` on `sandbox-host`. Verify
the actual setup before replacing anything.

The worker last observed used `/opt/proofbox/worker` and port `8080`, and the
API default worker address is `http://10.99.0.3:8080`. These are environment
details, not guarantees. Never expose the worker or Docker socket publicly.
Use a private network, firewall restrictions and a unique `WORKER_TOKEN`;
the known development token is not suitable for deployment.

## 0. Prepare and record the release

1. Agree with Person A on a maintenance window, deployment target, backup and
   rollback owner. Finish or pause in-flight jobs before restarting services.
2. On your Windows development machine:

   ```powershell
   cd C:\work\2026\AI_Learning\sandbox-spike
   git status -sb
   git branch --show-current
   git log -1 --oneline
   .\.venv\Scripts\python.exe -m pytest -q
   ```

   The branch should be `letter-lens`. Record the commit hash, check the
   tests pass, and commit and push the intended release when both of you
   approve. If there are uncommitted changes, do not assume the deployed
   server will receive them. Verify the remote branch is at the same commit.
   The number of tests can change; do not rely on the old Day 3 count.
3. Confirm Coolify and the worker server can access the same commit. Back up
   the currently deployed worker files and record the previous API and web
   deployment/image identifiers. Do not copy over server-only changes without
   reviewing them.
4. **Back up Postgres and verify that the backup can be restored.** Take a
   consistent backup of any existing case-pack storage too. Schedule the
   deployment so the backups represent the same maintenance point.
5. Review `apps/api/db.py`, particularly `_migrate_case_tables`, against a
   copy of the existing database. Startup runs `CREATE TABLE`, `ALTER TABLE`,
   backfills and indexes; it can drop a legacy `cases.access_token` column
   after hashing it. The database user needs appropriate DDL permissions.
   Test the migration on a restored copy first. It is **not** safe to assume
   rolling the API image back will undo these changes.
6. Prepare private, persistent, writable API storage, for example mount a
   Coolify persistent volume at `/data/proofbox-cases` and set
   `CASE_STORAGE_DIR=/data/proofbox-cases`. Confirm permissions for the API
   container user. Protect and back up this data. The default is temporary
   storage and can disappear when the container is replaced. If running
   multiple API instances, all must see the same storage at the same path.
7. Keep keys, database URLs, worker tokens, case links and document content
   out of chat, Git, screenshots and shared logs. Use the existing secret
   management in Coolify and systemd.

## 1. Get the release onto the worker host

Connect using your existing SSH procedure. On `sandbox-host`, if the checkout
already exists:

```bash
git -C /opt/proofbox/repo status -sb
git -C /opt/proofbox/repo fetch origin
git -C /opt/proofbox/repo switch letter-lens
git -C /opt/proofbox/repo pull --ff-only origin letter-lens
git -C /opt/proofbox/repo log -1 --oneline
```

Stop if the checkout has local changes, the switch fails, or the hash is not
the release hash from step 0. If there is no checkout, have Person A provide
the approved repository URL and clone `letter-lens` into a suitable empty
directory; adapt paths in the remaining commands.

## 2. Rebuild and verify the sandbox image

The existing Day 3 image is insufficient even if `parse_bill.py` works: it
must also contain `/app/parse_document.py`.

```bash
cd /opt/proofbox/repo
docker build -t proofbox-parse:latest sandbox/code
docker image inspect proofbox-parse:latest --format '{{.Id}}'
docker run --rm --runtime=runsc --network none --read-only \
  proofbox-parse:latest python -c "import pdfplumber; from pathlib import Path; assert Path('/app/parse_bill.py').is_file() and Path('/app/parse_document.py').is_file(); print('Both parsers present')"
```

Expect `Both parsers present`. `runsc` must be registered with Docker. If it
is missing, stop and resolve the gVisor setup with Person A; do not silently
weaken the runtime. Rebuilding the image does not update the worker service.

Test a synthetic Letter Lens PDF inside the sandbox:

```bash
mkdir -p /tmp/proofbox-letter-check
cp /opt/proofbox/repo/apps/web/letter/samples/A9_letter.pdf /tmp/proofbox-letter-check/document.pdf
ls -l /tmp/proofbox-letter-check/document.pdf
```

Stop if the copy or listing fails. Then run:

```bash
set -o pipefail
docker run --rm --runtime=runsc --network none --read-only --tmpfs /tmp:size=64m \
  -v /tmp/proofbox-letter-check:/inputs:ro proofbox-parse:latest \
  python /app/parse_document.py /inputs/document.pdf |
  python3 -c 'import json,sys; d=json.load(sys.stdin); print("status:", d.get("status"), "pages:", d.get("pages")); sys.exit(0 if d.get("status") == "ok" else 1)'
```

Expect `status: ok` and a positive page count. The check prints no document
text. Remove only the test file and its now-empty directory after success:

```bash
rm /tmp/proofbox-letter-check/document.pdf
rmdir /tmp/proofbox-letter-check
```

## 3. Update and verify the worker

### 3.1 Inspect before changing

```bash
systemctl cat proofbox-worker
systemctl status proofbox-worker --no-pager
```

Confirm the working directory, Python environment, token configuration and
port. The previously observed service used
`/opt/proofbox/worker/venv/bin/uvicorn`, but confirm it still does.
Compare the currently deployed files **before** copying; `diff` returns 1
when files differ:

```bash
diff -u /opt/proofbox/worker/main.py /opt/proofbox/repo/apps/worker/main.py
diff -u /opt/proofbox/worker/bill_modes.py /opt/proofbox/repo/apps/worker/bill_modes.py
```

If a deployed file is missing, or there are server-only modifications, stop
and reconcile them with Person A. In particular, keep the Link Lens `/run`
route and the Bill router include. Do not overwrite an unknown live version.

### 3.2 Back up, install and restart

After confirming the differences are intended, choose a new backup directory
that does not already exist. For example:

```bash
BACKUP="/opt/proofbox/worker-backup-$(date +%Y%m%d-%H%M%S)"
mkdir "$BACKUP"
cp -p /opt/proofbox/worker/main.py /opt/proofbox/worker/bill_modes.py "$BACKUP/"
echo "Worker backup: $BACKUP"
cp /opt/proofbox/repo/apps/worker/main.py /opt/proofbox/worker/main.py
cp /opt/proofbox/repo/apps/worker/bill_modes.py /opt/proofbox/worker/bill_modes.py
/opt/proofbox/worker/venv/bin/python -c "import fastapi, pydantic; print(fastapi.__version__, pydantic.__version__)"
systemctl restart proofbox-worker
systemctl is-active proofbox-worker
journalctl -u proofbox-worker -n 30 --no-pager
```

Record the backup path. If your paths differ, adapt the commands. Stop on any
copy, import or restart failure. Verify logs without sharing credentials or
document contents. The image defaults to `proofbox-parse:latest`, the runtime
to `runsc`, and the worker's Bill/Letter sandbox concurrency to 2; overrides
are `BILL_SANDBOX_IMAGE`, `BILL_SANDBOX_RUNTIME`, `BILL_SANDBOX_PARALLEL`,
`BILL_SANDBOX_TIMEOUT_S` and `BILL_WORK_DIR`.

### 3.3 Verify the route and the new mode

```bash
curl -fsS http://127.0.0.1:8080/openapi.json |
  python3 -c 'import json,sys; p=json.load(sys.stdin)["paths"]; print("/run:", "/run" in p, "/run-bill:", "/run-bill" in p); sys.exit(0 if "/run" in p and "/run-bill" in p else 1)'
```

Both should be `True`. Route presence alone is insufficient: an old worker
may have `/run-bill` but not `parse_document`. Test the actual mode with a
synthetic file and the token configured in the worker service:

```bash
read -rs -p "Worker token: " WORKER_TOKEN; echo
B64=$(base64 -w0 /opt/proofbox/repo/apps/web/letter/samples/A9_letter.pdf)
set -o pipefail
curl -fsS -N -X POST http://127.0.0.1:8080/run-bill \
  -H "Authorization: Bearer $WORKER_TOKEN" -H 'Content-Type: application/json' \
  -d "{\"job_id\":\"deploy-check\",\"mode\":\"parse_document\",\"inputs\":[{\"name\":\"document.pdf\",\"b64\":\"$B64\"}]}" |
  python3 -c 'import json,sys; events=[json.loads(line).get("event") for line in sys.stdin if line.strip()]; print("Events:", ", ".join(str(e) for e in events)); sys.exit(0 if "document_parsed" in events and "container_destroyed" in events and not set(events).intersection({"document_parse_failed","worker_error","timeout_kill","memory_kill"}) else 1)'
unset WORKER_TOKEN B64
```

Expect `document_parsed` and `container_destroyed`; no error event. This
prints event names only, not parsed text. A 401 means the token is wrong; a
422 with unknown mode often means the old worker is still running. A
`document_parse_failed` can also mean the rebuilt image was not used.

## 4. Deploy the API

1. In Coolify, configure the existing API application to build from the
   approved `letter-lens` commit. Verify the build context resolves to
   `apps/api` and its Dockerfile. Coolify's Dockerfile path convention
   depends on its source/build settings; check the build log rather than
   assuming a particular UI path format.
2. Keep the existing working `DATABASE_URL`, `VULTR_INFERENCE_KEY`,
   `WORKER_URL` and `WORKER_TOKEN`. The worker token must match the one in
   systemd. The API image installs the updated requirements during its build.
3. Configure and verify:

   | Variable | Setting |
   |---|---|
   | `CASE_STORAGE_DIR` | Persistent writable mounted directory, e.g. `/data/proofbox-cases`. |
   | `CORS_ORIGINS` | If restricted, include the exact HTTPS web origin; `GET`, `POST`, `DELETE` and `Authorization` must be allowed through your proxy. |
   | `LETTER_JOBS_PARALLEL` | Optional; defaults to `2`. |
   | `BILL_JOBS_PARALLEL` | Optional; defaults to `2`. Bill and Letter share the worker sandbox limit. |
   | `BILL_MODEL_WRITER` | Optional existing Bill override; it does not select Letter's extractor model. |
   | `BILL_USE_SHARED_GATEWAY` | Leave as previously tested unless Person A has verified its behavior with the current gateway. |
   | `PROOFBOX_TARIFF_PATH` | Optional; the API image includes the default tariff. |

4. After the database backup and migration rehearsal, redeploy. Inspect build
   and startup logs for migration, dependency, storage or database errors.
   A failed migration is not a successful deployment.
5. From a trusted location, using your real API URL:

   ```bash
   API='https://your-api-domain'
   curl -fsS "$API/healthz"
   curl -fsS "$API/openapi.json" |
     python3 -c 'import json,sys; p=json.load(sys.stdin)["paths"]; required=["/api/letter/intake","/api/bill/intake","/api/cases"]; missing=[x for x in required if x not in p]; print("Missing routes:", missing); sys.exit(bool(missing))'
   ```

   Expect `{"status":"ok"}` and `Missing routes: []`. From the API network,
   verify `WORKER_URL` reaches the intended worker; `openapi.json` alone
   does not verify its new mode. Use the step 3 test for that.

## 5. Deploy the web app

In Coolify, build the existing web application from the same approved
`letter-lens` commit and `apps/web` context. Its Dockerfile copies `bill/`,
`letter/` and `case/` into nginx, along with `nginx.conf` and
`40-configure-api-url.sh`.

### 5.1 Configure API reverse proxy in Coolify

The web container provides an Nginx reverse proxy routing `/api/*` requests
directly to the FastAPI backend. Configure the `API_URL` environment variable
on the web application in Coolify:

```env
API_URL=http://<api-container-name>:8000
```

- **Coolify internal networking:** Both web and API containers share the
  `coolify` Docker network. The internal container name corresponds to the
  resource ID / UUID shown in the API app's URL or General tab (for example,
  if the API domain is `http://zzarudpebhfzoohnpppp0snw.64.177.59.98.sslip.io`,
  the internal container host is `zzarudpebhfzoohnpppp0snw`, so set
  `API_URL=http://zzarudpebhfzoohnpppp0snw:8000`).
- **Do not use the public IP or external sslip.io domain for `API_URL`:**
  Cloud VPS instances (such as Vultr) drop loopback traffic from inside Docker
  containers attempting to reach their own public IP (`64.177.59.98`) due to
  hairpin NAT restrictions. In addition, port 80 is bound to Traefik rather
  than FastAPI (which listens on port 8000). Always use the internal container
  name and port 8000.
- **Query parameter fallback:** If testing directly in a browser or across
  external origins, you can still append `?api=http://your-api-domain` to the
  URL (e.g. `http://4kcvz2ocaby56a8gdp4cdvvk.64.177.59.98.sslip.io/?api=http://zzarudpebhfzoohnpppp0snw.64.177.59.98.sslip.io`).
  The frontend preserves the `?api=` parameter across navigation links.

### 5.2 Verify web and reverse proxy routes

```bash
WEB='https://your-web-domain'
for path in / /bill/ /letter/ /case/ /letter/samples/A9_letter.pdf; do
  printf '%s: ' "$path"
  curl -sS -o /dev/null -w '%{http_code}\n' "$WEB$path"
done
```

Each should return 200. Next verify that `/api/` reverse proxies properly to
FastAPI through the web host:

```bash
curl -fsS "$WEB/api/cases" -X POST -H 'Content-Type: application/json' \
  -d '{"title":"Deployment Verification","rule_set":"municipal_billing"}' |
  python3 -c 'import json,sys; d=json.load(sys.stdin); print("Case created:", d.get("case",{}).get("id")); sys.exit(0 if "case" in d else 1)'
```

Expect a created case response (`201` with `case-…` ID). If this returns 404,
Nginx is serving static files instead of proxying; if it returns 504 / 110
timeout, verify the internal `API_URL` setting.

## 6. Letter Lens end-to-end smoke test

Use the **synthetic** fixtures shipped with the web page, not real identity
documents for deployment testing:

1. Open `/letter/` with `?api=` if needed. Download and choose `A9_letter.pdf`
   as the official letter. Add `A10_id_copy.pdf`,
   `A10_old_proof_of_address.pdf` and `A10_bank_statement.pdf` as supporting
   PDFs. Click **Check letter**.
2. Confirm the job completes, shows extracted letter fields and a document
   checklist. The synthetic fixture manifest expects ID copy `have`, old proof
   of address `needs_fixing`, bank statement `have`, and signed declaration
   `missing` as of its `2026-11-06` check date. Checks involving document age
   depend on the date and model extraction can vary; inspect any mismatch.
3. Record the synthetic job ID. If it fails, inspect the job status and
   event details and private API/worker logs without posting document text.
   Letter events include `letter_received`, `letter_checks_completed` and,
   when dates are found, `letter_clock_found`. Document parser events are
   handled by the worker client and are not necessarily in the job timeline.
4. Verify the limits: one text-based letter PDF plus up to four supporting
   PDFs, each at most 5 MB and 10 MB combined. Image-only/scanned PDFs are
   not supported; document checks are layout-based and do not authenticate
   documents. Verify extracted dates against the original.

## 7. Case file and Day 4 exit check

1. Open `/case/` and create a private test case. Save its access link securely:
   its fragment contains the case token. Do not paste the link in logs or
   chat. Cases expire after seven days; the API runs expiry cleanup hourly.
2. From the case, select **Check a letter**, run the synthetic A9/A10 check,
   and choose **Add result to this case**. Alternatively use **Add a completed
   check** with its job ID. Confirm the Letter evidence and any explicitly
   extracted response or appointment dates appear in the timeline and
   clocks after attachment.
3. Run the existing Link A2 and Bill A7 checks and attach their completed job
   IDs to the same case. Verify all three evidence items appear and receipts
   can be opened.
4. Use **Log a reply** and review the proposal. Confirm nothing changes before
   confirmation; then confirm it and check the clock effect.
5. Generate a pack. Check the preview, open a numbered claim's receipt, and
   download both PDF and ZIP. Supporting PDFs are represented by hash-bearing
   placeholders in the ZIP, not the original identity documents.
6. Restart/redeploy the API in a planned window and confirm the same test
   case's pack can still be downloaded. This verifies the actual persistent
   mount, not just its configuration.
7. Check the rules/clock warning: municipal and grant-review rules and
   holidays remain unverified. Do not present them as verified legal advice.
   Delete the synthetic test case when finished.

Also repeat the existing Bill A6 and Link A1/A2/A3 checks before declaring
the release ready. Running two Bill/Letter jobs and a Link job concurrently is
a useful additional test; observe completion and worker sandbox limits.

## 8. Troubleshooting and rollback

| Symptom | Check |
|---|---|
| `/letter/` or `/case/` returns 404 | Verify the web build used `letter-lens` and copied both directories. |
| `/api/letter/intake` returns 404 | Verify the API deployment commit and OpenAPI paths. |
| `/run-bill` returns 404 | Wrong or old worker, or wrong `WORKER_URL`; verify both routes and the destination from the API network. |
| `/run-bill` returns 401 | Compare API and worker token configuration securely. |
| `parse_document` returns 422 | Worker likely still runs old `bill_modes.py`; restart the correct service and rerun step 3.3. |
| `document_parse_failed` or missing `/app/parse_document.py` | Rebuild the image on the worker's Docker daemon; verify the image tag and runtime. |
| No readable text | Use a text-based PDF; scanned/image-only files are unsupported. |
| API fails on startup | Inspect private logs for dependency, database connection, DDL permission or migration errors. Do not assume partial migrations were reverted. |
| Pack download fails after redeploy | Check `CASE_STORAGE_DIR`, mount persistence, permissions and identical paths across replicas. |
| Browser CORS or wrong API host | Check `?api=`, `CORS_ORIGINS`, HTTPS and proxy configuration. |
| `open() /usr/share/nginx/html/api/... failed (404)` | Web container lacks Nginx reverse proxy configuration. Ensure latest `apps/web/Dockerfile`, `nginx.conf`, and `40-configure-api-url.sh` are built. |
| `upstream timed out (110)` connecting to `http://<ip>:80` | `API_URL` was set to the host's public IP/domain instead of internal Docker network. Set `API_URL=http://<api-container-name>:8000`. |
| `413 Request Entity Too Large` on PDF uploads | Ensure `client_max_body_size 25M;` is active in `apps/web/nginx.conf`. |

For rollback, coordinate with Person A and stop new work first. Restore the
recorded previous API and web deployments and the backed-up worker files
and image as a compatible set, then verify both Link and Bill. If the Day 4
schema migration has run, **do not assume the old API is schema-compatible**:
use the tested database and storage recovery procedure, accounting for data
created since the backup. Do not restore a production database without
explicit approval and a recovery plan.

Record the release commit, image identifiers, backup location, test outcomes
and any remaining issues. Tag or merge the release only after both owners
approve; this guide does not perform those actions.
