"""Wiring of Bill Lens into Person A's API, worker and web images (merge-plan A7-A11)."""

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def api_main(monkeypatch):
    """Person A's API module with the DB, Link Lens and psycopg replaced by stubs."""
    db = types.ModuleType("db")
    db.add_event = lambda *a: None
    db.claim_next_job = lambda: None
    db.init_db = lambda: None
    db.pool = None
    link = types.ModuleType("link_lens")
    link.evaluate_link = lambda *a: {}
    link.validate_inspection_url = lambda value: value
    psycopg = types.ModuleType("psycopg")
    psycopg_types = types.ModuleType("psycopg.types")
    psycopg_json = types.ModuleType("psycopg.types.json")
    psycopg_json.Jsonb = lambda value: value
    for name, module in {
        "db": db, "link_lens": link, "psycopg": psycopg,
        "psycopg.types": psycopg_types, "psycopg.types.json": psycopg_json,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    return _load("proofbox_api_main", ROOT / "apps" / "api" / "main.py")


def test_api_mounts_bill_routes(api_main):
    paths = set(api_main.app.openapi()["paths"])
    assert {"/api/bill/intake", "/api/bill/receipts/{receipt_id}", "/api/intake", "/api/jobs/{job_id}"} <= paths


def test_bill_jobs_run_beside_the_queue_with_a_limit(api_main, monkeypatch):
    started, release = [], asyncio.Event()

    async def fake_bill(job):
        started.append(job["id"])
        await release.wait()

    monkeypatch.setattr(api_main, "process_bill_job", fake_bill)
    api_main.BILL_SLOTS = asyncio.Semaphore(2)

    async def scenario():
        # process_job returns at once for bill jobs, so the queue loop can claim the next job.
        await asyncio.wait_for(api_main.process_job({"id": "job-1", "lens": "bill"}), 1)
        await asyncio.wait_for(api_main.process_job({"id": "job-2", "lens": "bill"}), 1)
        third = asyncio.create_task(api_main.process_job({"id": "job-3", "lens": "bill"}))
        await asyncio.sleep(0.05)
        assert started == ["job-1", "job-2"] and not third.done()
        release.set()
        await asyncio.wait_for(third, 1)
        await asyncio.wait_for(asyncio.gather(*list(api_main._bill_tasks)), 1)
        await asyncio.sleep(0)
        assert started == ["job-1", "job-2", "job-3"] and not api_main._bill_tasks

    asyncio.run(scenario())


def test_worker_mounts_run_bill(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "apps" / "worker"))
    worker = _load("proofbox_worker_main", ROOT / "apps" / "worker" / "main.py")
    paths = set(worker.app.openapi()["paths"])
    assert {"/run", "/run-bill"} <= paths
    assert TestClient(worker.app).post("/run-bill", json={}).status_code in {401, 422}


def test_dockerfiles_ship_bill_files():
    worker = (ROOT / "apps" / "worker" / "Dockerfile").read_text()
    web = (ROOT / "apps" / "web" / "Dockerfile").read_text()
    assert "COPY bill_modes.py ." in worker
    assert "COPY bill /usr/share/nginx/html/bill" in web


def test_api_image_has_the_same_tariff():
    shipped = ROOT / "apps" / "api" / "tariffs" / "tariff_v1.json"
    assert json.loads(shipped.read_text()) == json.loads((ROOT / "tariffs" / "tariff_v1.json").read_text())
