import imageio_ffmpeg
import subprocess
import os

ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

def prepare_clips():
    out_dir = "brag-output/live_clips"
    stills = [
        ("clip1_intro.mp4", "brag-output/frames/scene1.png", 30.0),
        ("clip2_vultr.mp4", "brag-output/frames/scene2.png", 33.0),
        ("clip7_outro.mp4", "brag-output/frames/scene7.png", 16.0),
    ]
    
    for name, src, dur in stills:
        dest = os.path.join(out_dir, name)
        print(f"Creating {name} from {src} ({dur}s)...")
        cmd = [
            ffmpeg, "-y",
            "-loop", "1",
            "-t", str(dur),
            "-i", src,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            dest
        ]
        subprocess.run(cmd, check=True)
        print("Created:", dest)

if __name__ == "__main__":
    prepare_clips()

