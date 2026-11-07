import subprocess
import time
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pathlib import Path

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
if not os.path.exists(CHROME_PATH):
    CHROME_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

ROOT_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT_DIR / "apps" / "web"
OUT_DIR = ROOT_DIR / "docs" / "screens"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PORT = 8922

class QuietHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)
    def log_message(self, format, *args):
        pass

def run_server():
    server = HTTPServer(("127.0.0.1", PORT), QuietHandler)
    server.serve_forever()

server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()
time.sleep(1)

SCREENS = [
    ("intake-link", "/index.html"),
    ("bill-lens", "/bill/index.html"),
    ("letter-lens", "/letter/index.html"),
    ("case-timeline", "/case/index.html"),
    ("vultr-judges", "/vultr.html"),
    ("styleguide", "/styleguide.html"),
]

VIEWPORTS = [
    (360, 740, "360px"),
    (768, 1024, "768px"),
    (1280, 800, "1280px"),
]

print(f"Taking screenshots using {CHROME_PATH}...")
for screen_name, path in SCREENS:
    for width, height, label in VIEWPORTS:
        out_file = OUT_DIR / f"{screen_name}-{label}.png"
        url = f"http://127.0.0.1:{PORT}{path}"
        cmd = [
            CHROME_PATH,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--window-size={width},{height}",
            f"--screenshot={out_file}",
            url
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        if out_file.exists():
            print(f"Captured: {out_file.name} ({out_file.stat().st_size} bytes)")
        else:
            print(f"Failed to capture: {out_file.name}")

print("All screenshots captured!")

