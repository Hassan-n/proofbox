import os
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

WORKER_URL = os.getenv("WORKER_URL", "http://10.99.0.3:8080")
WORKER_TOKEN = os.getenv("WORKER_TOKEN", "dev-secret-token")

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.post("/api/test-job")
async def test_job(mode: str = "normal"):
    async def event_stream():
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream(
                "POST",
                f"{WORKER_URL}/run",
                json={"job_id": "test-1", "mode": mode},
                headers={"Authorization": f"Bearer {WORKER_TOKEN}"},
            ) as resp:
                async for line in resp.aiter_lines():
                    if line:
                        yield f"{line}\n"
    return StreamingResponse(event_stream(), media_type="application/x-ndjson")