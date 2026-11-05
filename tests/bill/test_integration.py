"""Tests for the Person A integration modules: intake router, job runner, worker client,
model caller and the worker's /run-bill plug-in. No Docker, network or Postgres needed."""

import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lenses.bill import model_caller as mc
from lenses.bill.job import BillServices, completion_detail, run_bill_job
from lenses.bill.router import create_router
from lenses.bill.runners import LocalSubprocessRunner
from lenses.bill.store import MemoryStore
from lenses.bill.worker_client import SandboxError, WorkerClient, WorkerCodeRunner, WorkerParser

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sandbox" / "code"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "apps" / "worker"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bill_modes as bm  # noqa: E402
import generate_fixtures as gf  # noqa: E402
import parse_bill as pb  # noqa: E402
from test_pipeline import RoleGateway  # noqa: E402


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    out = tmp_path_factory.mktemp("fixtures")
    gf.generate(out, out / "stubs")
    return {
        "A5": (out / "A5_bill_clean.pdf").read_bytes(),
        "A6": (out / "A6_bill_errors.pdf").read_bytes(),
        "A7": (out / "A7_bill_injection.pdf").read_bytes(),
        "history": json.loads((out / "A8_history.json").read_text(encoding="utf-8")),
    }


def local_parser(job_id, emit):
    def parse(pdf):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bill.pdf"
            path.write_bytes(pdf)
            return pb.parse_pdf(path)

    return parse


def services(store, parser=local_parser, gateway=None):
    return BillServices(
        store=store,
        call_model=gateway or RoleGateway(),
        parser=parser,
        runner=lambda job_id, emit: LocalSubprocessRunner(timeout_s=10),
    )


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# ---------- router ----------


@pytest.fixture()
def api():
    store = MemoryStore()
    app = FastAPI()
    app.include_router(create_router(lambda: store))
    return TestClient(app), store


def test_intake_queues_job_and_stores_pdf_receipt(api, files):
    client, store = api
    response = client.post("/api/bill/intake", json={
        "filename": "../../My Bill?.pdf", "pdf_base64": "data:application/pdf;base64," + b64(files["A6"]),
        "history": files["history"],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued" and body["job_id"].startswith("job-")
    job = store.jobs[body["job_id"]]
    assert job["lens"] == "bill" and job["status"] == "queued"
    pdf, history, filename = store.load_upload(job)
    assert pdf == files["A6"] and history == files["history"]
    assert "/" not in filename and ".." not in filename
    assert [e["event_type"] for e in store.job_events(body["job_id"])] == ["job_queued"]


@pytest.mark.parametrize("payload, status", [
    ({"filename": "x.pdf", "pdf_base64": b64(b"hello world")}, 415),
    ({"filename": "x.pdf", "pdf_base64": "%%%not-base64%%%"}, 422),
    ({"filename": "x.pdf", "pdf_base64": ""}, 422),
    ({"filename": "x.pdf", "pdf_base64": b64(b"%PDF-" + b"0" * (5 * 1024 * 1024))}, 413),
    ({"filename": "x.pdf", "pdf_base64": b64(b"%PDF-1.4"), "history": {"previous_bills": "nope"}}, 422),
    ({"filename": "x.pdf", "pdf_base64": b64(b"%PDF-1.4"), "history": {"outage_log": [{}] * 401}}, 422),
])
def test_intake_rejects_bad_uploads(api, payload, status):
    client, store = api
    assert client.post("/api/bill/intake", json=payload).status_code == status
    assert store.jobs == {}


def test_receipt_endpoint_hides_pdf_blob(api, files):
    client, store = api
    job_id = client.post("/api/bill/intake", json={"filename": "a.pdf", "pdf_base64": b64(files["A5"])}).json()["job_id"]
    pdf_receipt = store.jobs[job_id]["input_ref"]
    receipt = client.get(f"/api/bill/receipts/{pdf_receipt}").json()["receipt"]
    assert receipt["kind"] == "pdf" and receipt["job_id"] == job_id
    assert b64(files["A5"]) not in json.dumps(receipt)
    assert client.get("/api/bill/receipts/rcpt-0000000000").status_code == 404
    assert client.get("/api/bill/receipts/not-an-id").status_code == 404


# ---------- job runner ----------


def test_run_bill_job_completes_with_findings_and_receipts(files):
    store = MemoryStore()
    job_id = store.create_job(None, "a6.pdf", files["A6"], files["history"])
    result = run_bill_job(store.claim_next(), services(store))
    assert store.jobs[job_id]["status"] == "completed"
    assert {f["check"] for f in result["findings"]} == {"arithmetic", "estimated_readings", "outage_consistency"}
    assert result["document"]["filename"] == "a6.pdf" and len(result["document"]["sha256"]) == 64
    for finding in result["findings"]:
        for receipt_id in finding["receipt_ids"]:
            assert receipt_id in result["receipts"] and store.get_receipt(receipt_id)["job_id"] == job_id
    events = [e["event_type"] for e in store.job_events(job_id)]
    assert events[:3] == ["job_queued", "bill_received", "bill_parsed"]
    assert events[-1] == "job_completed" and "letter_drafted" in events
    assert store.job_events(job_id)[-1]["detail"] == completion_detail(result)


def test_run_bill_job_flags_missing_history_and_injection(files):
    store = MemoryStore()
    job_id = store.create_job(None, "a7.pdf", files["A7"], None)
    run_bill_job(store.claim_next(), services(store))
    events = [e["event_type"] for e in store.job_events(job_id)]
    assert "history_missing" in events and "instruction_ignored" in events
    assert store.jobs[job_id]["status"] == "completed"


def test_run_bill_job_fails_cleanly_when_sandbox_fails(files):
    def broken(job_id, emit):
        def parse(pdf):
            raise SandboxError("worker unreachable")
        return parse

    store = MemoryStore()
    job_id = store.create_job(None, "a5.pdf", files["A5"], None)
    assert run_bill_job(store.claim_next(), services(store, parser=broken)) is None
    assert store.jobs[job_id]["status"] == "failed"
    last = store.job_events(job_id)[-1]
    assert last["event_type"] == "job_failed" and "worker unreachable" in last["detail"]
    assert store.claim_next() is None


# ---------- worker client ----------


def worker_transport(lines, seen=None, status=200):
    def handler(request):
        if seen is not None:
            seen.append({"auth": request.headers.get("authorization"), "body": json.loads(request.content)})
        return httpx.Response(status, content="".join(json.dumps(line) + "\n" for line in lines))

    return httpx.MockTransport(handler)


def test_worker_parser_returns_parsed_and_forwards_lifecycle_events():
    parsed = {"status": "ok", "text": "hello", "input": {"pages": 1}}
    seen, emitted = [], []
    client = WorkerClient("http://worker", "tok", transport=worker_transport([
        {"event": "container_started", "detail": "c1"},
        {"event": "bill_parsed", "detail": "ok", "data": {"parsed": parsed}},
        {"event": "container_destroyed", "detail": "c1"},
    ], seen))
    assert WorkerParser(client, "job-1", lambda t, d: emitted.append(t))(b"%PDF-1.4") == parsed
    assert emitted == ["container_started", "container_destroyed"]
    assert seen[0]["auth"] == "Bearer tok" and seen[0]["body"]["mode"] == "parse_bill"
    assert base64.b64decode(seen[0]["body"]["inputs"][0]["b64"]) == b"%PDF-1.4"


def test_worker_parser_raises_on_failure_and_refusal():
    failing = WorkerClient("http://w", "t", transport=worker_transport([{"event": "bill_parse_failed", "detail": "too many pages"}]))
    with pytest.raises(SandboxError, match="too many pages"):
        WorkerParser(failing, "job-1")(b"%PDF")
    refused = WorkerClient("http://w", "t", transport=worker_transport([], status=401))
    with pytest.raises(SandboxError, match="401"):
        WorkerParser(refused, "job-1")(b"%PDF")


def test_worker_code_runner_sends_inputs_and_maps_result():
    seen = []
    client = WorkerClient("http://w", "t", transport=worker_transport([
        {"event": "code_result", "detail": "", "data": {"exit_code": 0, "stdout": "{}", "stderr": "", "timed_out": False, "duration_ms": 42}},
    ], seen))
    result = WorkerCodeRunner(client, "job-1").run("print('hi')", {"bill.json": {"a": 1}})
    assert (result.exit_code, result.stdout, result.duration_ms) == (0, "{}", 42)
    names = {item["name"]: base64.b64decode(item["b64"]) for item in seen[0]["body"]["inputs"]}
    assert seen[0]["body"]["mode"] == "code" and json.loads(names["bill.json"]) == {"a": 1}
    assert b"/inputs" in names["main.py"]

    empty = WorkerClient("http://w", "t", transport=worker_transport([{"event": "worker_error", "detail": "boom"}]))
    result = WorkerCodeRunner(empty, "job-1").run("print(1)", {})
    assert result.exit_code == -1 and "boom" in result.stderr


# ---------- model caller ----------


class FakeCompletions:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])


def fake_client(replies):
    completions = FakeCompletions(replies)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def test_model_caller_turns_thinking_off_and_retries(monkeypatch):
    from pydantic import BaseModel

    class Reply(BaseModel):
        ok: bool

    monkeypatch.delenv("BILL_MODEL_WRITER", raising=False)
    client, completions = fake_client([RuntimeError("timeout"), "not json", '```json\n{"ok": true}\n```'])
    logged = []
    call = mc.make_caller(client, {"writer": "glm", "router": "small"}, {}, lambda *a: logged.append(a[-1]))
    assert call("writer", "job-1", "Prompt", "<b>data</b>", schema=Reply) == {"ok": True}
    assert len(completions.calls) == 3 and logged == ["retry_1_error", "retry_2_error", "ok"]
    first = completions.calls[0]
    assert first["model"] == "glm" and first["extra_body"] == mc.THINKING_OFF
    assert "<b>" not in first["messages"][1]["content"]
    assert "failed validation" in completions.calls[2]["messages"][1]["content"]


def test_model_caller_role_override_and_give_up(monkeypatch):
    monkeypatch.setenv("BILL_MODEL_WRITER", "deepseek-fast")
    client, completions = fake_client([RuntimeError("x")] * 3)
    call = mc.make_caller(client, {"writer": "glm", "router": "small"}, {}, lambda *a: None)
    assert call("writer", None, "p", "d")["error"] == "unreadable"
    assert {c["model"] for c in completions.calls} == {"deepseek-fast"}
    assert mc.model_for("unknown_role", {"router": "small"}) == "small"


# ---------- worker /run-bill plug-in ----------


def test_bill_modes_validate_request():
    pdf = bm.SandboxInput(name="bill.pdf", b64=b64(b"%PDF"))
    assert bm.validate_request(bm.BillRunRequest(job_id="j", mode="parse_bill", inputs=[pdf])) == {"bill.pdf": b"%PDF"}
    with pytest.raises(ValueError, match="Unknown"):
        bm.validate_request(bm.BillRunRequest(job_id="j", mode="shell", inputs=[pdf]))
    with pytest.raises(ValueError, match="main.py"):
        bm.validate_request(bm.BillRunRequest(job_id="j", mode="code", inputs=[pdf]))
    for bad in ("../etc/passwd", "a/b", ".hidden", ""):
        with pytest.raises(ValueError):
            bm.decode_inputs([bm.SandboxInput(name=bad, b64="")])
    with pytest.raises(ValueError, match="base64"):
        bm.decode_inputs([bm.SandboxInput(name="x", b64="@@@")])


def test_bill_modes_docker_command_is_locked_down(tmp_path):
    command = bm.docker_command("pb-1", "parse_bill", tmp_path)
    joined = " ".join(command)
    for flag in ("--network none", "--read-only", "--cap-drop=ALL", "no-new-privileges", "--memory=512m", "--pids-limit=64", "proofbox.owner=b"):
        assert flag in joined
    assert f"{tmp_path}:/inputs:ro" in command
    assert command[-3:] == ["python", "/app/parse_bill.py", "/inputs/bill.pdf"]
    assert bm.docker_command("pb-2", "code", tmp_path)[-3:] == ["python", "-I", "/inputs/main.py"]


def test_bill_modes_parse_result_lines():
    parsed = {"status": "ok", "input": {"pages": 2}, "events": [{"type": "instruction_ignored", "message": "NOTE TO AI"}]}
    lines = [json.loads(line) for line in bm.parse_result_lines("noise\n" + json.dumps(parsed), "", 0)]
    assert [line["event"] for line in lines] == ["instruction_ignored", "bill_parsed"]
    assert lines[-1]["data"]["parsed"] == parsed
    failed = json.loads(bm.parse_result_lines(json.dumps({"status": "error", "error": "encrypted"}), "", 1)[0])
    assert failed == {"event": "bill_parse_failed", "detail": "encrypted"}
    crashed = json.loads(bm.parse_result_lines("", "Traceback", 1)[0])
    assert crashed["event"] == "bill_parse_failed" and "Traceback" in crashed["detail"]


def test_bill_modes_endpoint_requires_token():
    app = FastAPI()
    app.include_router(bm.router)
    client = TestClient(app)
    body = {"job_id": "j", "mode": "parse_bill", "inputs": []}
    assert client.post("/run-bill", json=body).status_code == 401
    assert client.post("/run-bill", json=body, headers={"Authorization": "Bearer wrong"}).status_code == 401
    bad = client.post("/run-bill", json=body, headers={"Authorization": f"Bearer {bm.WORKER_TOKEN}"})
    assert bad.status_code == 422 and "Missing input bill.pdf" in bad.text
