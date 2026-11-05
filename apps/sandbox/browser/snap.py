import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

url = sys.argv[1]
out_dir = Path(sys.argv[2])
quarantine_dir = Path(os.getenv("QUARANTINE_DIR", "/quarantine"))
proxy_url = os.getenv("HTTP_PROXY", "http://172.30.0.2:3128")
out_dir.mkdir(parents=True, exist_ok=True)
quarantine_dir.mkdir(parents=True, exist_ok=True)

trace = {
    "initial_url": url,
    "final_url": url,
    "redirect_chain": [],
    "requests": [],
    "blocked_requests": [],
    "forms_and_inputs": [],
    "downloads": [],
    "visible_text": "",
    "load_error": None,
}

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        proxy={"server": proxy_url, "bypass": ""},
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--proxy-bypass-list=<-loopback>",
        ],
    )
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 Chrome/128.0.0.0 Mobile Safari/537.36",
        viewport={"width": 390, "height": 844},
        accept_downloads=True,
        service_workers="block",
    )
    page = context.new_page()

    def on_request(request):
        trace["requests"].append(
            {"url": request.url, "method": request.method, "resource_type": request.resource_type}
        )

    def on_response(response):
        if response.status in (301, 302, 303, 307, 308):
            trace["redirect_chain"].append(
                {
                    "from": response.url,
                    "status": response.status,
                    "to": response.headers.get("location", ""),
                }
            )

    def observe_only(route):
        if route.request.method not in {"GET", "HEAD"}:
            trace["blocked_requests"].append(
                {"url": route.request.url, "method": route.request.method}
            )
            route.abort()
        else:
            route.continue_()

    def on_download(download):
        name = Path(download.suggested_filename).name or "download"
        quarantined_path = quarantine_dir / f"{uuid.uuid4().hex}_{name}"
        download.save_as(quarantined_path)
        digest = hashlib.sha256()
        with quarantined_path.open("rb") as downloaded_file:
            for chunk in iter(lambda: downloaded_file.read(8192), b""):
                digest.update(chunk)
        trace["downloads"].append(
            {
                "filename": name,
                "size_bytes": quarantined_path.stat().st_size,
                "sha256": digest.hexdigest(),
            }
        )

    page.route("**/*", observe_only)
    page.on("request", on_request)
    page.on("response", on_response)
    page.on("download", on_download)
    try:
        page.goto(url, wait_until="networkidle", timeout=10000)
        page.wait_for_timeout(1500)
    except Exception as error:
        trace["load_error"] = str(error)

    trace["final_url"] = page.url
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        page.wait_for_timeout(300)
        page.evaluate("window.scrollTo(0, 0)")
        trace["visible_text"] = page.evaluate(
            "() => document.body ? document.body.innerText.slice(0, 4000) : ''"
        )
        trace["forms_and_inputs"] = page.evaluate(
            """() => Array.from(document.querySelectorAll('input')).map(el => ({
                type: el.type || 'text', name: el.name || '', id: el.id || '',
                placeholder: el.placeholder || ''
            }))"""
        )
    except Exception:
        pass

    screenshot_path = out_dir / "shot.png"
    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception:
        pass
    browser.close()

if screenshot_path.exists():
    from PIL import Image

    with Image.open(screenshot_path) as screenshot:
        screenshot.save(out_dir / "shot.webp", "WEBP", quality=75)
    screenshot_path.unlink()

with (out_dir / "trace.json").open("w", encoding="utf-8") as trace_file:
    json.dump(trace, trace_file)