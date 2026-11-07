"""Add background/problem context to the existing demo, retaining a five-minute runtime.

The original 15-second title is replaced by a 45-second narrated opening.
The remaining live footage and its narration are played about 12% faster;
no results or caveats are removed. Work files stay in the supplied directory.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import textwrap
import wave
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

from build_demo_video import CAPTIONS, OUTPUT, speech, timestamp

MARKER = "Proofbox background and problem opening v1"
FONT_DIR = Path(r"C:\Windows\Fonts")
OPENING = [
    {
        "duration": 18,
        "tag": "BACKGROUND",
        "title": "Everyday decisions.\nUntrusted inputs.",
        "body": "Payment links. Utility bills. Official letters.\nMoney, documents, and deadlines are at stake.",
        "footer": "People need clarity without taking unnecessary risks.",
        "narration": (
            "Every day, people receive payment links, utility bills, and official letters. "
            "These inputs can ask for money, identity documents, or a response by a deadline. "
            "Understanding them should not require taking unnecessary risks."
        ),
    },
    {
        "duration": 22,
        "tag": "PROBLEM STATEMENT",
        "title": "An AI answer\nis not evidence.",
        "body": "Unsafe inspection. Unverified conclusions.\nScattered documents, findings, and deadlines.",
        "footer": "What can I trust, and what should I do next?",
        "narration": (
            "The problem is not a shortage of AI answers. It is a shortage of safe inspection "
            "and verifiable evidence. A link can be deceptive. A bill can contain incorrect "
            "charges. Letter requirements and deadlines can be missed. And a confident "
            "summary does not prove what was checked."
        ),
    },
    {
        "duration": 5,
        "tag": "THE PROOFBOX APPROACH",
        "title": "Inspect. Verify. Preserve.",
        "body": "Bounded execution.\nEvidence a person can review.",
        "footer": "Now, see the live synthetic demonstration.",
        "narration": "Proofbox inspects safely, verifies claims, and preserves evidence.",
    },
]


def font(size: int, bold: bool = False):
    return ImageFont.truetype(str(FONT_DIR / ("calibrib.ttf" if bold else "calibri.ttf")), size)


def card(item: dict, output: Path) -> None:
    image = Image.new("RGB", (1920, 1080), "#0c1823")
    draw = ImageDraw.Draw(image)
    draw.text((125, 57), "PROOFBOX / VULTR AGENT RUSH", font=font(24, True), fill="#67e8c6")
    draw.text((125, 191), item["tag"], font=font(28, True), fill="#67e8c6")
    draw.multiline_text((120, 278), item["title"], font=font(91, True), fill="white", spacing=15)
    draw.multiline_text((125, 553), item["body"], font=font(39), fill="#b1c6d0", spacing=16)
    draw.rounded_rectangle((125, 757, 1795, 860), radius=14, fill="#162a37")
    draw.text((158, 786), item["footer"], font=font(34, True), fill="#67e8c6")
    draw.text((125, 916), "SYNTHETIC DEMONSTRATION / NOT LEGAL ADVICE", font=font(20), fill="#b1c6d0")
    image.save(output)


def parse_time(value: str) -> float:
    hours, minutes, seconds = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def cue(number: int, start: float, end: float, text: str) -> str:
    return f"{number}\n{timestamp(start)} --> {timestamp(end)}\n{text}\n"


def build(work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    metadata = subprocess.run([ffmpeg, "-hide_banner", "-i", str(OUTPUT)],
                              capture_output=True, text=True).stderr
    if MARKER in metadata:
        raise ValueError("This video already has the background/problem opening.")
    if "Duration: 00:05:00.00" not in metadata:
        raise ValueError("Expected the existing five-minute demo.")
    original = work / "original.mp4"
    shutil.copy2(OUTPUT, original)
    shutil.copy2(CAPTIONS, work / "original.srt")
    entries: list[str] = []
    offset = 0
    for index, item in enumerate(OPENING):
        card(item, work / f"context-{index}.png")
        speech(item["narration"], work / f"context-{index}.wav", work)
        with wave.open(str(work / f"context-{index}.wav")) as audio:
            seconds = audio.getnframes() / audio.getframerate()
        if seconds > item["duration"] - .1:
            raise ValueError(f"Context {index} narration exceeds the scene: {seconds:.2f}s")
        lines = textwrap.wrap(item["narration"], width=78)
        local_entries = []
        start = .1
        for i in range(0, len(lines), 2):
            text = "\n".join(lines[i:i + 2])
            span = seconds * len(text.split()) / len(item["narration"].split())
            local_entries.append(cue(len(local_entries) + 1, start, start + span, text))
            entries.append(cue(len(entries) + 1, offset + start, offset + start + span, text))
            start += span
        (work / f"context-{index}.srt").write_text("\n".join(local_entries), encoding="utf-8")
        subprocess.run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-loop", "1",
            "-i", f"context-{index}.png", "-i", f"context-{index}.wav",
            "-vf", f"subtitles=context-{index}.srt:force_style='FontName=Calibri,FontSize=9,Alignment=2,MarginV=6,Outline=1,Shadow=0',format=yuv420p",
            "-af", "apad", "-t", str(item["duration"]), "-r", "30",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-ar", "22050", "-ac", "1", f"context-{index}.mp4",
        ], check=True, cwd=work)
        offset += item["duration"]
        print(f"{item['tag']}: {item['duration']}s, narrated {seconds:.1f}s", flush=True)
    assert offset == 45
    speed = 285 / 255
    old_captions = (work / "original.srt").read_text(encoding="utf-8")
    for block in old_captions.strip().split("\n\n"):
        lines = block.splitlines()
        match = re.fullmatch(r"(.+) --> (.+)", lines[1])
        if not match:
            raise ValueError("Invalid existing caption timestamp")
        start, end = (parse_time(value) for value in match.groups())
        if end <= 15:
            continue
        if start < 15:
            raise ValueError("A caption crosses the original title boundary")
        entries.append(cue(len(entries) + 1, 45 + (start - 15) / speed,
                           45 + (end - 15) / speed, "\n".join(lines[2:])))
    subprocess.run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", "15",
        "-i", "original.mp4", "-map", "0:v:0", "-map", "0:a:0",
        "-vf", f"setpts=(PTS-STARTPTS)/{speed},fps=30",
        "-af", f"atempo={speed},apad", "-t", "255",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-ar", "22050", "-ac", "1", "live-demo.mp4",
    ], check=True, cwd=work)
    (work / "revised.srt").write_text("\n".join(entries), encoding="utf-8")
    (work / "concat.txt").write_text(
        "file 'context-0.mp4'\nfile 'context-1.mp4'\nfile 'context-2.mp4'\nfile 'live-demo.mp4'\n",
        encoding="utf-8",
    )
    finish(work)


def finish(work: Path) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    revised = work / "revised.mp4"
    subprocess.run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", "concat.txt", "-i", "revised.srt",
        "-map", "0:v:0", "-map", "0:a:0", "-map", "1:0",
        "-vf", "setpts=PTS-STARTPTS,fps=30", "-af", "asetpts=PTS-STARTPTS,apad",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-c:s", "mov_text",
        "-t", "300", "-metadata", f"comment={MARKER}",
        "-movflags", "+faststart", str(revised),
    ], check=True, cwd=work)
    # Verify the replacement before changing either user-facing deliverable.
    meta = subprocess.run([ffmpeg, "-hide_banner", "-i", str(revised)],
                          capture_output=True, text=True).stderr
    if "Duration: 00:05:00.00" not in meta or "1920x1080" not in meta:
        raise ValueError("Revised video has incorrect runtime or dimensions")
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(revised),
                    "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], check=True)
    shutil.copy2(revised, OUTPUT)
    shutil.copy2(work / "revised.srt", CAPTIONS)
    (work / "edit-summary.json").write_text(json.dumps({
        "opening_seconds": 45, "live_footage_speed": 285 / 255, "runtime_seconds": 300,
        "removed_original_seconds": 15, "live_results_removed": False,
    }, indent=2))
    print(f"Verified and updated: {OUTPUT}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--finish-only", action="store_true")
    args = parser.parse_args()
    if args.finish_only:
        finish(args.work_dir)
    else:
        build(args.work_dir)
