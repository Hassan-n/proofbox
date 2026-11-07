"""Record the deployed synthetic demo and build a narrated five-minute MP4.

Requires Playwright, Pillow, imageio-ffmpeg, Microsoft Edge, and a local Windows
speech voice. No responses are mocked and no deployed application is modified.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import textwrap
import time
import wave
from pathlib import Path
from urllib.parse import quote

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "Proofbox_Demo_5min.mp4"
CAPTIONS = ROOT / "docs" / "Proofbox_Demo_5min.srt"
FONT = Path(r"C:\Windows\Fonts\calibri.ttf")
BOLD = Path(r"C:\Windows\Fonts\calibrib.ttf")
SCENES = [
    ("intro", "PROOFBOX / INSPECT. VERIFY. PRESERVE.", 15),
    ("link", "01 / LINK LENS / LIVE BROWSER INSPECTION", 60),
    ("bill", "02 / BILL LENS / SYNTHETIC INJECTION FIXTURE", 70),
    ("letter", "03 / LETTER LENS / REQUIREMENTS AND CHECKLIST", 45),
    ("case", "04 / CASE FILE / EVIDENCE TO EXPORT", 70),
    ("architecture", "05 / VULTR / SEPARATED EXECUTION", 25),
    ("close", "PROOFBOX / EVIDENCE A PERSON CAN REVIEW", 15),
]


def title_html(closing: bool = False) -> str:
    title = "Less guesswork.<br>More evidence." if closing else "Open nothing unsafely.<br>Believe nothing unproven."
    subtitle = (
        "Inspect the input. Verify the claim. Preserve the proof."
        if closing else "Links. Bills. Letters. One private case file."
    )
    return f"""<!doctype html><html><head><style>
    body{{margin:0;background:#0c1823;color:#fff;font-family:Calibri,Arial}}
    main{{padding:110px 105px}} .tag{{color:#67e8c6;font-size:22px;letter-spacing:2px}}
    h1{{font-size:74px;line-height:1.15;margin:55px 0 40px}}
    p{{font-size:34px;color:#b1c6d0}} .foot{{margin-top:90px;font-size:24px;color:#67e8c6}}
    </style></head><body><main><div class="tag">PROOFBOX / VULTR AGENT RUSH</div>
    <h1>{title}</h1><p>{subtitle}</p>
    <div class="foot">Synthetic demonstration / Not legal advice</div></main></body></html>"""


def record(url: str, work: Path, selected: list[str] | None = None,
           api_url: str | None = None) -> dict:
    state: dict = (
        json.loads((work / "recording.json").read_text(encoding="utf-8"))
        if selected else {"scenes": {}, "jobs": {}, "pack_downloaded": False}
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(
            viewport={"width": 1600, "height": 900},
            record_video_dir=str(work / "raw"),
            record_video_size={"width": 1600, "height": 900},
            accept_downloads=True,
        )
        context.set_default_timeout(12000)
        for name, title, duration in SCENES:
            if selected and name not in selected:
                continue
            page = context.new_page()
            start = time.monotonic()
            info: dict = {"title": title, "duration": duration}

            def pause(seconds: float) -> None:
                page.wait_for_timeout(seconds * 1000)

            def focus(selector: str, seconds: float = 3) -> None:
                page.locator(selector).first.scroll_into_view_if_needed()
                pause(seconds)

            def navigate(path: str) -> None:
                target = url + path
                if api_url:
                    target += "?api=" + quote(api_url.rstrip("/"), safe="")
                page.goto(target, wait_until="networkidle")

            try:
                if name in {"intro", "close"}:
                    page.set_content(title_html(name == "close"))
                elif name == "link":
                    navigate("/")
                    pause(3)
                    page.get_by_role("textbox", name="Link or message to inspect").fill(url + "/")
                    pause(2)
                    page.get_by_role("button", name="Inspect link", exact=True).click()
                    page.locator("#verdict").wait_for(state="visible", timeout=45000)
                    info["result_at"] = time.monotonic() - start
                    info["verdict"] = page.locator("#verdict").inner_text().splitlines()[0].strip()
                    # This is the public demo site, not a hostile fixture.
                    focus("#verdict", 5)
                    focus("#verdict", 3)
                    state["jobs"]["link"] = page.locator("#verdict a[href*='#attach=']").get_attribute("href").split("#attach=")[1]
                    page.get_by_role("region", name="Sandbox Telemetry & Network Events").scroll_into_view_if_needed()
                    pause(5)
                elif name == "bill":
                    navigate("/bill/")
                    pause(3)
                    page.locator("#pdf-input").set_input_files(str(ROOT / "apps" / "web" / "bill" / "samples" / "A7_bill_injection.pdf"))
                    page.locator("details.bill-history summary").click()
                    page.locator("#history-input").set_input_files(str(ROOT / "apps" / "web" / "bill" / "samples" / "history.json"))
                    pause(3)
                    page.locator("#submit-btn").click()
                    focus("#stepper", 3)
                    page.locator("#result").wait_for(state="visible", timeout=45000)
                    info["result_at"] = time.monotonic() - start
                    info["summary"] = page.locator("#verdict-title").inner_text()
                    state["jobs"]["bill"] = page.locator("#job-id").inner_text().strip()
                    focus("#verdict", 7)
                    focus("#findings", 6)
                    receipt = page.get_by_role("button", name="Tariff recompute", exact=True).first
                    if receipt.count():
                        receipt.click()
                        pause(4)
                        page.keyboard.press("Escape")
                    focus("#letter-panel", 5)
                elif name == "letter":
                    navigate("/letter/")
                    pause(2)
                    fixtures = ROOT / "apps" / "web" / "letter" / "samples"
                    page.locator("#letter-file").set_input_files(str(fixtures / "A9_letter.pdf"))
                    page.locator("#supporting-files").set_input_files([
                        str(fixtures / filename) for filename in
                        ("A10_id_copy.pdf", "A10_old_proof_of_address.pdf", "A10_bank_statement.pdf")
                    ])
                    pause(2)
                    page.locator("#submit-button").click()
                    page.locator("#result-panel").wait_for(state="visible", timeout=35000)
                    info["result_at"] = time.monotonic() - start
                    info["checklist"] = page.locator("#checklist").inner_text()
                    state["jobs"]["letter"] = page.locator("#job-id").inner_text().strip()
                    focus("#letter-fields", 6)
                    focus("#checklist", 6)
                elif name == "case":
                    navigate("/case/")
                    page.locator("#case-title").fill("Proofbox Hackathon - Synthetic Demo")
                    pause(2)
                    page.locator("#create-form button[type=submit]").click()
                    page.wait_for_url(lambda target: "#" in target, timeout=20000)
                    # Creation changes only the URL fragment; reload to initialize the case view.
                    page.reload(wait_until="networkidle")
                    page.locator("#case-view").wait_for(state="visible", timeout=20000)
                    # Never write the possession-based case access URL into logs.
                    for lens in ("bill",):
                        if lens not in state["jobs"]:
                            raise RuntimeError(f"No completed {lens} job to attach")
                        page.locator("#job-id").fill(state["jobs"][lens])
                        page.locator("#attach-form button[type=submit]").click()
                        page.get_by_text("Evidence attached.", exact=True).wait_for(timeout=15000)
                        pause(2)
                    focus("#evidence", 4)
                    focus("#clocks", 4)
                    page.locator("#generate-pack").click()
                    page.locator("#pack-downloads").wait_for(state="visible", timeout=20000)
                    info["result_at"] = time.monotonic() - start
                    focus("#pack-preview", 4)
                    with page.expect_download(timeout=15000) as downloading:
                        page.locator("#download-pdf").click()
                    download = downloading.value
                    if download.failure():
                        raise RuntimeError(download.failure())
                    download.save_as(str(work / "synthetic-evidence-pack.pdf"))
                    with page.expect_download(timeout=15000) as downloading:
                        page.locator("#download-zip").click()
                    download = downloading.value
                    if download.failure():
                        raise RuntimeError(download.failure())
                    download.save_as(str(work / "synthetic-receipts.zip"))
                    state["pack_downloaded"] = True
                    focus("#pack-preview", 4)
                    page.locator("#job-id").fill(state["jobs"]["letter"])
                    page.locator("#attach-form button[type=submit]").click()
                    page.get_by_text("Evidence attached.", exact=True).wait_for(timeout=15000)
                    focus("#evidence", 3)
                    page.locator("#generate-pack").click()
                    page.locator("#pack-status").filter(
                        has_text="A receipt contains a 13-digit identifier"
                    ).wait_for(timeout=15000)
                    info["privacy_block_observed"] = True
                    focus("#pack-status", 3)
                elif name == "architecture":
                    navigate("/vultr.html")
                    pause(3)
                    focus(".diagram-container", 8)
                info["success"] = True
            except (PlaywrightTimeoutError, RuntimeError) as error:
                # Preserve the actual failure screen and report the failed scene.
                info["success"] = False
                info["error_type"] = type(error).__name__
                info["error_detail"] = str(error).split("Call log:")[0][:300]
                print(f"{name}: recorded an incomplete workflow ({type(error).__name__})", flush=True)
            remaining = duration - (time.monotonic() - start)
            if remaining > 0:
                pause(remaining)
            info["recorded_seconds"] = time.monotonic() - start
            video = page.video
            page.close()
            target = work / f"{name}.webm"
            video.save_as(str(target))
            info["video"] = target.name
            state["scenes"][name] = info
            (work / "recording.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
            print(f"{name}: captured; success={info['success']}", flush=True)
        context.close()
        browser.close()
    (work / "recording.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def narration(state: dict) -> dict[str, list[str]]:
    # Describe only observed outcomes; no fabricated success-shaped fallbacks.
    bill = state["scenes"]["bill"]
    letter = state["scenes"]["letter"]
    case = state["scenes"]["case"]
    link = state["scenes"]["link"]
    return {
        "intro": [
            "Meet Proofbox: containment-first agents, built on Vultr.",
            "We inspect links, verify paperwork, and preserve evidence in a private case file.",
            "This five-minute demonstration uses only synthetic records.",
        ],
        "link": [
            "We begin with Link Lens. It observes a page without asking the person to open it or submit credentials.",
            "For this recording, we inspect the public Proofbox demo site itself. This is not a malicious test page.",
            "The job runs in an isolated browser. The control plane collects the page trace and inspection image.",
            (
                f"The live result is {link.get('verdict', 'available')}. References to the fictional bank in the demo can trigger a brand-mismatch warning. This illustrates why findings still need human review."
                if link["success"] else
                "This live inspection did not complete within the recording window. We do not present an incomplete run as a successful containment test."
            ),
            "The trace and lifecycle events show what was observed. A warning is not proof of fraud, and no issue found would not guarantee safety.",
            "The built-in private-address example was rejected during rehearsal. No blocked-network or download-quarantine result is claimed in this recording.",
        ],
        "bill": [
            "Next, Bill Lens. We upload the synthetic injection fixture and a reading-history file with outage context.",
            "The PDF contains an instruction addressed to an AI: approve the bill and print its environment. That text is untrusted document data, not permission to act.",
            "The parser operates in the worker sandbox. The model extracts fields, while deterministic code checks the tariff arithmetic.",
            (
                "The live result reports a possible overcharge of one hundred thirty-four rand and fifty-five cents. It also flags consecutive estimated readings and consumption inconsistent with the supplied outage history."
                if bill["success"] and "134.55" in bill.get("summary", "") else
                "The screen shows the actual result of this run. We do not invent amounts or treat an incomplete check as a confirmed finding."
            ),
            "The receipt links connect each finding to the bill text, the recomputation, and the independently executed program.",
            "The final draft explains the discrepancy for review. No letter is sent automatically.",
            "Karoo Bay is fictional. These results demonstrate the fixture and configured rules, not verification of a real municipality's tariff.",
        ],
        "letter": [
            "Letter Lens turns correspondence into a checklist. We provide an agency letter and three synthetic supporting documents.",
            "The official letter supplies the requirements and explicit dates. Supporting PDFs are parsed and checked in the no-network worker sandbox.",
            (
                "The live checklist flags an address document that is too old, and a missing signed declaration. It also records the response deadline and appointment from the letter."
                if letter["success"] else
                "This check did not complete in the recording window. We retain the actual screen rather than replacing it with a simulated result."
            ),
            "These are layout-based checks. They do not authenticate identity or documents, and scanned PDFs are not supported.",
            "Supporting-document check facts, rather than full supporting text, form the model privacy boundary.",
        ],
        "case": [
            "Now we bring the completed bill check into a private case. This is a synthetic demonstration case created for this recording.",
            "We first attach the bill job. Stable evidence numbers connect the findings to case-owned receipts.",
            "A drafted municipal dispute does not start its response clock: the person must confirm when it was sent.",
            (
                "We generate an evidence-pack snapshot and download both the PDF and the receipt archive. These are actual downloads from the deployed application."
                if case["success"] and state["pack_downloaded"] else
                "The live export is refused: a receipt matches the thirteen-digit identifier gate. The synthetic bill contains a long numeric creation date in its PDF metadata. This is an export limitation, not proof that the bill holds a real identity number."
            ),
            "Numbered claims link back to evidence. Receipt hashes support content-integrity checks, but do not prove authenticity or legal correctness.",
            (
                "We then attach the letter result and try another export. The live privacy gate detects a thirteen-digit identifier and refuses to publish that combined pack. We show the refusal rather than hide the limitation."
                if case.get("privacy_block_observed") else
                "The case still keeps its evidence and receipts. Supporting identity PDFs are intended to be omitted from exports, and private case links must be shared with care."
            ),
            "This is the handoff: a record another person can inspect, rather than a disconnected chat answer.",
        ],
        "architecture": [
            "Vultr separates authority from execution. The control-plane VM owns the API, case engine, and model gateway.",
            "A private sandbox-host VM runs browser and code tasks with Docker and gVisor. The inference key stays outside the worker.",
            "Models interpret. Code verifies. People confirm consequential actions. This demo is not a certification of escape resistance.",
        ],
        "close": [
            "Proofbox connects useful agent work with bounded execution and reviewable evidence.",
            "Production checks and official domain rules still need verification.",
            "Open nothing unsafely. Believe nothing unproven.",
        ],
    }


def speech(sentence: str, target: Path, work: Path) -> None:
    source = work / "utterance.txt"
    source.write_text(sentence, encoding="utf-8")
    command = """
    Add-Type -AssemblyName System.Speech
    $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
    try {
      $s.SelectVoice('Microsoft Zira Desktop')
      $s.Rate = 1
      $s.SetOutputToWaveFile($env:PROOFBOX_WAV)
      $s.Speak([IO.File]::ReadAllText($env:PROOFBOX_TEXT))
    } finally { $s.Dispose() }
    """
    environment = dict(os.environ, PROOFBOX_WAV=str(target), PROOFBOX_TEXT=str(source))
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", command],
                   check=True, env=environment, capture_output=True)


def timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    return f"{milliseconds // 3600000:02}:{milliseconds // 60000 % 60:02}:{milliseconds // 1000 % 60:02},{milliseconds % 1000:03}"


def assemble(state: dict, work: Path) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    texts = narration(state)
    subtitle_entries = []
    full_pcm = bytearray()
    audio_format = None
    global_offset = 0
    manifest = []
    for name, title, duration in SCENES:
        overlay = Image.new("RGBA", (1920, 1080), (12, 24, 35, 255))
        overlay.paste((0, 0, 0, 0), (160, 60, 1760, 960))
        draw = ImageDraw.Draw(overlay)
        draw.text((160, 16), title, font=ImageFont.truetype(str(BOLD), 25), fill="#67e8c6")
        draw.text((1550, 19), "SYNTHETIC DEMO", font=ImageFont.truetype(str(FONT), 19), fill="#b1c6d0")
        overlay.save(work / f"{name}-overlay.png")
        chunks = []
        for index, sentence in enumerate(texts[name]):
            wav = work / f"{name}-{index}.wav"
            speech(sentence, wav, work)
            with wave.open(str(wav)) as source:
                fmt = (source.getnchannels(), source.getsampwidth(), source.getframerate())
                if audio_format is None:
                    audio_format = fmt
                if fmt != audio_format:
                    raise ValueError("Inconsistent speech audio format")
                frames = source.readframes(source.getnframes())
                chunks.append((sentence, frames, source.getnframes() / fmt[2]))
        speech_seconds = sum(c[2] for c in chunks)
        if speech_seconds > duration - .5:
            raise ValueError(f"{name}: narration is {speech_seconds:.1f}s for a {duration}s scene")
        gap = (duration - speech_seconds - .5) / len(chunks)
        channels, sample_width, rate = audio_format
        frame_bytes = channels * sample_width
        local_pcm = bytearray(b"\0" * round(.3 * rate) * frame_bytes)
        local_time = .3
        for sentence, frames, seconds in chunks:
            lines = textwrap.wrap(sentence, width=78)
            caption_time = local_time
            for i in range(0, len(lines), 2):
                part = "\n".join(lines[i:i + 2])
                part_seconds = seconds * len(part.split()) / len(sentence.split())
                subtitle_entries.append(
                    f"{len(subtitle_entries) + 1}\n{timestamp(global_offset + caption_time)} --> "
                    f"{timestamp(global_offset + caption_time + part_seconds)}\n{part}\n"
                )
                caption_time += part_seconds
            local_pcm.extend(frames)
            silence = round(gap * rate) * frame_bytes
            local_pcm.extend(b"\0" * silence)
            local_time += seconds + gap
        required = duration * rate * frame_bytes
        local_pcm = local_pcm[:required]
        local_pcm.extend(b"\0" * (required - len(local_pcm)))
        full_pcm.extend(local_pcm)
        manifest.append(f"file '{name}.mp4'")
        # Freeze only after the recorded scene ends; never fabricate UI state.
        result_at = state["scenes"][name].get("result_at", 0)
        if result_at > 30 and name in {"bill", "letter"}:
            draw.text((160, 967), "LIVE CAPTURE / PROCESSING WAIT SHORTENED",
                      font=ImageFont.truetype(str(FONT), 16), fill="#b1c6d0")
            overlay.save(work / f"{name}-overlay.png")
            preparation = (
                "[0:v]trim=end=16,setpts=PTS-STARTPTS[a];"
                f"[0:v]trim=start={result_at - 3:.3f},setpts=PTS-STARTPTS[b];"
                "[a][b]concat=n=2:v=1:a=0[edited];"
            )
            video_input = "[edited]"
        else:
            preparation = ""
            video_input = "[0:v]"
        graph = (
            preparation + f"{video_input}fps=30,tpad=stop_mode=clone:stop_duration={duration},"
            "scale=1600:900,pad=1920:1080:160:60:color=0x0c1823[base];"
            "[base][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
        )
        subprocess.run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(work / state["scenes"][name]["video"]), "-i", str(work / f"{name}-overlay.png"),
            "-filter_complex", graph, "-map", "[v]", "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-an", str(work / f"{name}.mp4"),
        ], check=True)
        global_offset += duration
        print(f"{name}: rendered; narration={speech_seconds:.1f}s", flush=True)
    if global_offset != 300:
        raise ValueError("Video timeline must be exactly 300 seconds")
    CAPTIONS.write_text("\n".join(subtitle_entries), encoding="utf-8")
    (work / "captions.srt").write_text("\n".join(subtitle_entries), encoding="utf-8")
    with wave.open(str(work / "narration.wav"), "wb") as target:
        target.setnchannels(audio_format[0])
        target.setsampwidth(audio_format[1])
        target.setframerate(audio_format[2])
        target.writeframes(full_pcm)
    (work / "concat.txt").write_text("\n".join(manifest), encoding="utf-8")
    subprocess.run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", "concat.txt",
        "-i", "narration.wav", "-i", "captions.srt",
        "-vf", "subtitles=captions.srt:force_style='FontName=Calibri,FontSize=9,Alignment=2,MarginV=6,Outline=1,Shadow=0'",
        "-map", "0:v", "-map", "1:a", "-map", "2:s",
        "-c:v", "libx264", "-preset", "fast", "-crf", "21",
        "-c:a", "aac", "-b:a", "160k", "-c:s", "mov_text",
        "-t", "300", "-movflags", "+faststart", str(OUTPUT),
    ], check=True, cwd=work)
    print(OUTPUT, flush=True)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--api-url")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--assemble-only", action="store_true")
    parser.add_argument("--record-only", action="store_true")
    parser.add_argument("--scenes", nargs="+", choices=[s[0] for s in SCENES])
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    state = (
        json.loads((args.work_dir / "recording.json").read_text(encoding="utf-8"))
        if args.assemble_only else record(args.url.rstrip("/"), args.work_dir, args.scenes, args.api_url)
    )
    if not args.record_only:
        assemble(state, args.work_dir)


if __name__ == "__main__":
    main()
