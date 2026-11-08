# Proofbox

Proofbox helps people in South Africa check suspicious links, municipal bills and official letters, then turn what they find into a documented case with deadlines and an evidence pack. It uses AI models for extraction and plain-language advice. Calculations and document checks run in a sandbox.

> **Status:** Day 4 build (branch `letter-lens`). Municipal response and escalation rules and the grant-review checklist are **unverified**. Deployed end-to-end testing is outstanding. Proofbox does not authenticate documents and does not give legal advice.

## Features

| Lens / module | What it does |
|---|---|
| **Link Lens** | Takes a suspicious URL and loads it in an isolated browser sandbox behind a proxy. It screenshots the page and uses a vision model to judge it. |
| **Bill Lens** | Takes a municipal bill PDF, extracts the line items as strict JSON, and checks them against the tariff (`tariffs/tariff_v1.json`). Model-written analysis code runs in a no-network sandbox. It then writes a plain-language explanation and a dispute letter. |
| **Letter Lens** | Takes an official letter PDF, such as a grant-review letter. It extracts text and runs a layout-specific checklist in the sandbox. It pulls out explicit response and appointment dates. |
| **Case file** | Groups evidence, receipts and replies under one case. The case link carries a random token in the URL fragment. The database stores only its SHA-256 hash. |
| **Clocks** | Business-day and calendar deadline engine with South African public holidays for 2026–2027. Dispute clocks start only when you confirm the sent date. |
| **Reply lens** | Proposes evidence, clocks and actions from a reply you paste in. Nothing is written until you confirm. |
| **Evidence pack** | Builds a versioned PDF and ZIP with ReportLab. It rejects hash mismatches and detected 13-digit identifiers. |

## Architecture

```
Browser ──► web (Nginx, static) ──/api──► api (FastAPI) ──► Postgres
                                            │   └──► Vultr Serverless Inference (LLMs)
                                            ▼
                                  worker (private, token-auth)
                                            │
                      ┌─────────────────────┴───────────────┐
                      ▼                                     ▼
          sandbox/code (gVisor, no network)      sandbox/browser + proxy
          parse_bill.py, parse_document.py       snap.py (Link Lens)
```

## Vultr integration: services, infrastructure and deployment

Vultr powers both model inference and the documented two-host deployment architecture. The control plane holds application authority and model credentials; a separate sandbox host executes untrusted browser, document and generated-code tasks. This separation keeps model access out of the execution sandbox.

| Vultr service / infrastructure | Role in Proofbox | Implementation and deployment boundary |
|---|---|---|
| **Vultr Serverless Inference** | Extracts structured bill and letter fields, generates analysis code and explanations, and evaluates Link Lens screenshots. | The FastAPI [model gateway](apps/api/gateway.py) uses the OpenAI-compatible endpoint `https://api.vultrinference.com/v1` with `VULTR_INFERENCE_KEY`. Model calls originate from the control plane, not the worker. |
| **Vultr Cloud Compute: control-plane VM** | Hosts the public application and trusted backend. | Nginx serves the static UI and proxies `/api` to FastAPI. The documented deployment uses Coolify for the web/API containers, PostgreSQL for jobs, events and cases, and persistent storage for evidence packs. |
| **Vultr Cloud Compute: sandbox-host VM** | Provides a separate execution host for untrusted work. | The `proofbox-worker` service launches per-job Docker containers with gVisor (`runsc`). Code/document jobs have no network; browser jobs use a controlled proxy. |
| **Vultr VPC** | Connects the control plane to the sandbox host privately. | Both VMs belong in the same region and VPC. `WORKER_URL` must point to the worker's private address; requests require a deployment-specific `WORKER_TOKEN`. |
| **Vultr Firewall, complemented by host firewall rules** | Restricts access to the public application and private execution service. | Expose the web entry point, restrict administrative access, and permit worker traffic only from the control plane over the private network. Never publish the worker or Docker socket. |

**Deployment evidence and scope:** Serverless Inference is wired in the application code. The two-VM/VPC/firewall arrangement above describes the documented deployment design, not an independently verified inventory of the live Vultr account. The [deployment guide](docs/deployment-guide.md) records the worker previously observed as a systemd service; complete deployed end-to-end verification remains outstanding. PostgreSQL and pack storage are application-hosted components in this design, not claims of using Vultr Managed Databases or Object Storage. No dedicated GPU deployment or Kubernetes service is claimed.

### Backend execution and trust boundaries

1. **Intake and orchestration:** The browser submits a URL or PDF to FastAPI. The API creates a job, persists its status/events in PostgreSQL, and streams progress to the UI through server-sent events.
2. **Model interpretation:** The control-plane gateway sends task-specific requests to Vultr Serverless Inference. Document/page content is marked as untrusted data; structured responses are schema-validated and model prompts pass through the privacy gate.
3. **Bounded execution:** The API delegates execution to the authenticated private worker. The worker launches gVisor containers with read-only root filesystems, dropped capabilities and resource/time limits. Browser inspection uses a proxy; document parsing and generated-code execution use no-network containers.
4. **Evidence and human review:** Results, traces and receipts return to the API. Case evidence is stored in PostgreSQL and pack files require durable `CASE_STORAGE_DIR` storage. Users review drafts, confirm reply proposals and confirm sent dates before dispute clocks start.

Vultr is therefore not just a hosting destination: its inference service supplies the agent's interpretation, while separate compute hosts and private networking provide the infrastructure for separating trusted orchestration from untrusted execution. Docker, gVisor and the application checks enforce the execution boundaries on those hosts; VM separation alone is not proof of containment.

## Agent use case: real tasks, not just chat

Proofbox is an evidence-first assistant for people navigating suspicious links, municipal billing disputes and official correspondence in South Africa. It runs tools and produces reviewable artifacts rather than stopping at a conversational answer.

| User task | What the agent executes | Reviewable result |
|---|---|---|
| Inspect a suspicious payment link without opening it personally | Runs an isolated browser, collects a screenshot and page trace, and asks the Vultr vision model to assess the observed page. | A finding with inspection artifacts; a warning is not proof of fraud and a clean result is not a safety guarantee. |
| Check a municipal bill and prepare a dispute | Parses the PDF in the worker, extracts structured line items with inference, recomputes tariff arithmetic and executes model-written analysis code in a no-network sandbox. | Evidence-linked discrepancies, a plain-language explanation and a draft dispute letter. Nothing is sent automatically. |
| Understand an official letter and prepare supporting documents | Parses the letter/supporting PDFs, executes a layout-specific checklist, and extracts explicit response and appointment dates. | Missing/expired-document findings and dates for review, not document authentication. |
| Assemble a case for follow-up | Attaches receipts to numbered evidence, proposes reply-derived actions, starts clocks after confirmation and attempts a versioned PDF/ZIP export. | A case timeline and, when integrity/privacy checks pass, a downloadable evidence pack. Export failures are surfaced rather than treated as success. |

The recorded examples use synthetic inputs and a fictional municipality. They demonstrate executable workflows, not validation of a real municipality's tariffs or official agency rules.

## Hackathon demo video and presentation

- **[Recorded Video Walkthrough (MP4, 1080p, 03:20)](docs/brag.mp4)** — Full walkthrough demonstrating live working features (Link Lens, Bill Lens, Letter Lens, Case File) with natural voiceover narration, ducked background track, and containment events.
- **[Hackathon Slide Presentation (PDF)](docs/Proofbox_Hackathon_Presentation.pdf)** — Presentation slide deck covering the civic problem, two-host Vultr architecture, Serverless Inference, and containment boundaries.

### Observed containment moments in `docs/brag.mp4`:
- **Challenge 1 Containment (01:34–02:12, Prompt-Injection Neutralization):** Bill Lens processes a synthetic municipal bill PDF containing an adversarial prompt injection instructing the AI to approve the bill and dump environment variables. Proofbox treats all document text strictly as untrusted data. The worker executes deterministic tariff arithmetic against `tariffs/tariff_v1.json` inside a zero-network gVisor sandbox, completely neutralizing the injection, confirming a **R134.55 overcharge**, and drafting a formal municipal dispute letter.
- **Challenge 2 & Privacy Containment (02:34–03:04, 13-Digit PII Export Gate Refusal):** Link Lens runs browser automation safely behind an isolated proxy. When the citizen attempts to export an evidence pack from Case File, the ReportLab engine validates receipts against privacy rules: a 13-digit national ID pattern in the synthetic bill metadata triggers `🛑 EXPORT REFUSED: 13-digit identifier gate triggered`. Sensitive citizen PII is blocked at the perimeter while evidence remains safely preserved in the local database.

*(Note: The archive recording [docs/Proofbox_Demo_5min.mp4](docs/Proofbox_Demo_5min.mp4) remains available for historical reference).*

## Repository layout

```
apps/
  api/        FastAPI service: intake, jobs (SSE), cases, clocks, packs, privacy gate
    lenses/   Letter Lens (router, job, checks)
    rules/    calendar.yaml, municipal_billing.yaml, grant_review.yaml
    tariffs/  tariff_v1.json
  web/        Static front end (index, bill/, letter/, case/, styleguide, vultr) + Nginx config
  worker/     Runs sandboxed jobs (/run-bill, bill modes)
  sandbox/    browser/ and proxy/ images for Link Lens
  testpages/  Test pages for Link Lens
sandbox/code/ Parsing image (proofbox-parse): parse_bill.py, parse_document.py
config/       models.yaml: model role mapping and fallbacks
fixtures/     Synthetic sample bills, stubs, reply text
scripts/      Fixture generation, evals, model checks, screenshots, dev server
tests/bill/   pytest suite
docs/         Deployment guide, design system, decisions, audits, screenshots
```

## Tech stack

- **Backend:** Python 3.12, FastAPI, Uvicorn, psycopg 3 (Postgres), Pydantic, ReportLab, tldextract
- **Models:** Vultr Serverless Inference via the OpenAI-compatible client. Roles are configured in [config/models.yaml](config/models.yaml).
- **Front end:** Plain HTML, CSS and JS with design tokens. Nginx serves it and reverse-proxies the API.
- **Isolation:** Docker with gVisor (`runsc`), `--network none`, and read-only file systems.

### Model roles

| Role | Model |
|---|---|
| router | `deepseek-v4.1-flash-1017` |
| extractor | `qwen3.8-27b` |
| analyst_coder | `deepseek-v4.1-flash-1017` |
| writer | `glm-5.3` |
| vision_verifier | `mimo-v2.6-pro` |
| translator (stretch) | `qwen3.8-flash-next` |

Fallbacks are defined for each role. Defaults are `max_tokens: 1500` and `temperature: 0.0`.

## Getting started (local)

### Prerequisites

Python 3.12, a Postgres database, Docker (with gVisor for the full sandbox), and a Vultr Inference API key.

### Setup

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r apps/api/requirements.txt
```

Create a `.env` in the repo root. **Never commit it.**

```env
VULTR_INFERENCE_KEY=your-key
```

Check that the models respond:

```powershell
python scripts/check_models.py
```

Run the API:

```powershell
cd apps/api
uvicorn main:app --reload
```

Serve the front end by opening `apps/web/index.html` through a static server and pointing it at the API. For Bill Lens work only, use `python scripts/bill_dev_server.py`.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `VULTR_INFERENCE_KEY` | `missing-key` | Model API key |
| `WORKER_URL` | `http://10.99.0.3:8080` | Private worker address |
| `WORKER_TOKEN` | `dev-secret-token` | Shared secret with the worker. **Change it for any deployment.** |
| `CASE_STORAGE_DIR` | system temp dir | Durable, writable storage for pack PDFs and ZIPs |
| `CORS_ORIGINS` | `*` | Allowed origins. Restrict this in production. |
| `BILL_JOBS_PARALLEL` | `2` | Concurrent Bill Lens jobs |
| `LETTER_JOBS_PARALLEL` | `2` | Concurrent Letter Lens jobs |

The database connection is configured in [apps/api/db.py](apps/api/db.py). The web container reads `API_URL` (see `apps/web/40-configure-api-url.sh`).

## API overview

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/healthz` | Health check |
| POST | `/api/sessions` | Create a session |
| POST | `/api/intake` | Submit a link or bill |
| GET | `/api/jobs/{id}`, `/api/jobs/{id}/events` | Job status and SSE progress |
| POST | `/api/letter/intake` | Submit a letter (Letter Lens). The route prefix is set in `main.py`. |
| POST | `/api/cases` | Create a case |
| GET / DELETE | `/api/cases/{id}` | Read or delete a case. Deleting removes its receipt copies. |
| POST | `/api/cases/{id}/evidence` | Add evidence |
| POST | `/api/cases/{id}/replies` | Propose changes from a reply |
| POST | `/api/cases/{id}/replies/{rid}/confirm` or `/discard` | Apply or discard a proposal |
| POST | `/api/cases/{id}/clocks/dispute-sent` | Start dispute clocks from a confirmed sent date |
| POST | `/api/cases/{id}/packs` | Build an evidence pack |
| GET | `/api/packs/{id}`, `/pdf`, `/zip` | Pack metadata and downloads |
| GET | `/api/receipts/{id}` | Fetch a receipt |

Case endpoints use a bearer token in the `Authorization` header.

## Testing

```powershell
python -m pytest -q
```

Generate synthetic fixtures:

```powershell
pip install -r scripts/requirements-fixtures.txt
python scripts/generate_fixtures.py
python scripts/generate_letter_fixtures.py
```

Evals: `scripts/eval_extractor.py` and `scripts/eval_analyst.py`.

## Deployment

The API and web run as Docker images (for example, on Coolify). The worker runs as a service (`proofbox-worker`) on a separate sandbox host reachable only over a private network. The sandbox image must be rebuilt as `proofbox-parse:latest` so that it includes `parse_document.py`. See [docs/deployment-guide.md](docs/deployment-guide.md) for the order of steps, backups, migration review and verification.

> **Important:** API startup creates and migrates case tables. Back up Postgres and case storage first, because rolling the image back will not undo the migration. Never expose the worker or the Docker socket publicly.

## Privacy and security

- Model prompts pass through a privacy gate ([apps/api/privacy.py](apps/api/privacy.py)).
- Evidence packs reject 13-digit identifiers. Supporting PDFs are replaced by hash-bearing placeholders in ZIPs.
- Case tokens are stored only as SHA-256 hashes.
- Untrusted documents and generated code run in a no-network sandbox.
- Use only synthetic data in fixtures. The A10 ID number is fictitious.

## Known limitations

- Scanned or image-only PDFs are not supported, because text extraction only works on text PDFs.
- The Letter Lens checklist is layout-specific.
- Municipal rules (`last_verified: null`) and public holidays must be checked against official sources.
- No deployed end-to-end testing yet.

## License

Proofbox is licensed under the [MIT License](LICENSE).

Copyright (c) 2026 Proofbox authors.

## Documentation

- [docs/decisions.md](docs/decisions.md): implementation decisions
- [docs/deployment-guide.md](docs/deployment-guide.md): deployment
- [docs/design-system.md](docs/design-system.md): design system
- [docs/frontend-audit.md](docs/frontend-audit.md): front-end audit
- [docs/screens/](docs/screens/): screenshots
