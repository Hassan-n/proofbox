import imageio_ffmpeg
import subprocess
import os

ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

def extract_clips():
    clips = [
        ("clip_linklens.mp4", "00:00:47.0", 31.0),
        ("clip_billlens.mp4", "00:01:42.0", 38.0),
        ("clip_letterlens.mp4", "00:02:44.0", 22.0),
        ("clip_casefile.mp4", "00:03:32.0", 30.0),
    ]
    
    src = "docs/Proofbox_Demo_5min.mp4"
    out_dir = "brag-output/live_clips"
    
    for name, start, dur in clips:
        out_path = os.path.join(out_dir, name)
        print(f"Extracting {name} from {start} for {dur}s...")
        cmd = [
            ffmpeg, "-y",
            "-ss", start,
            "-t", str(dur),
            "-i", src,
            "-an",  # Strip original audio so we can mix our custom natural voiceover & music
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            out_path
        ]
        subprocess.run(cmd, check=True)
        print(f"Saved: {out_path}")

if __name__ == "__main__":
    extract_clips()

