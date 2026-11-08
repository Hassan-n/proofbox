import asyncio
import edge_tts
import os
import json

SCENES = {
    "scene1": "Every day, people receive suspicious payment links, municipal utility bills, and official government letters. In South Africa, navigating these inputs often means risking identity theft, disputing arbitrary municipal charges, or missing statutory deadlines. The problem isn't a shortage of AI chat summaries — it's a shortage of safe inspection and verifiable evidence. Proofbox solves this by inspecting safely, verifying claims with deterministic code, and preserving cryptographic receipts.",
    
    "scene2": "Proofbox is architected specifically around Vultr cloud infrastructure to separate application authority from untrusted execution. Our public control plane runs on a Vultr Cloud Compute VM hosting FastAPI and PostgreSQL. It interfaces directly with Vultr Serverless Inference at api.vultrinference.com. Untrusted jobs are dispatched across a private Vultr VPC to a dedicated Sandbox Host VM running Docker and gVisor. Model credentials never touch the worker sandbox, and execution containers run with zero network access.",
    
    "scene3": "First, Link Lens. When a user pastes a suspicious payment link, Proofbox never asks them to open it in their personal browser. Instead, an isolated browser instance launches behind a secure proxy on our Vultr worker. It renders the page, records DOM network traces, captures a high-resolution screenshot, and dispatches the visual evidence to Vultr Serverless Inference. The vision model identifies brand discrepancies and phishing vectors, giving the citizen an immediate, safe assessment.",
    
    "scene4": "Next, Bill Lens demonstrates our core containment philosophy. We upload a municipal electricity bill containing an adversarial prompt injection designed to trick the AI into approving the bill and dumping its environment. Proofbox treats all document text strictly as untrusted data. Vultr Serverless Inference extracts line items, while deterministic Python code audits the numbers in a no-network gVisor sandbox. The injection is neutralized. The math proves a one hundred thirty-four rand and fifty-five cent overcharge based on consecutive estimated readings and outage history, and drafts a formal municipal dispute letter.",
    
    "scene5": "Official correspondence comes with rigid deadlines. Letter Lens parses complex agency documents, running a layout-specific checklist to highlight missing attachments or outdated affidavits before submission. It extracts explicit dates and populates our statutory calendar engine, calculating exact response deadlines adjusted for South African public holidays.",
    
    "scene6": "All findings roll into a private Case File, where claims are bound to immutable SHA-256 evidence receipts. When the user exports their case as a signed evidence pack, our privacy containment gate activates. In this demo, the export is deliberately refused because a receipt matches a thirteen-digit South African identity number pattern. Proofbox protects citizen privacy at the perimeter — refusing to exfiltrate sensitive personal data while keeping the evidence safely accessible for review.",
    
    "scene7": "Proofbox proves that autonomous agents are ready for high-stakes civic tasks when bounded by secure cloud infrastructure. Models interpret. Code verifies. People confirm. Fight with receipts."
}

async def generate():
    voice = "en-ZA-LukeNeural"
    out_dir = "brag-output/voiceover"
    os.makedirs(out_dir, exist_ok=True)
    
    metadata = {}
    for key, text in SCENES.items():
        out_path = os.path.join(out_dir, f"{key}.mp3")
        print(f"Generating {key} with {voice}...")
        communicate = edge_tts.Communicate(text, voice, rate="-2%")
        await communicate.save(out_path)
        print(f"Saved {out_path}")

if __name__ == "__main__":
    asyncio.run(generate())

