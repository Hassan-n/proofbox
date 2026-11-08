import imageio_ffmpeg
import subprocess
import os

ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

def render():
    out_dir = "brag-output"
    video_out = os.path.join(out_dir, "brag_raw.mp4")
    final_mp4 = os.path.join(out_dir, "brag.mp4")
    poster_jpg = os.path.join(out_dir, "brag.jpg")
    audio_path = os.path.join(out_dir, "master_audio.mp3")
    
    # 1. Create concat file
    concat_txt = os.path.join(out_dir, "concat.txt")
    # Exact scene durations matching master_audio
    scenes = [
        ("frames/scene1.png", 31.0),
        ("frames/scene2.png", 33.5),
        ("frames/scene3.png", 31.5),
        ("frames/scene4.png", 38.0),
        ("frames/scene5.png", 22.0),
        ("frames/scene6.png", 30.5),
        ("frames/scene7.png", 17.5),
    ]
    
    with open(concat_txt, "w") as f:
        for fname, dur in scenes:
            f.write(f"file '{fname}'\n")
            f.write(f"duration {dur}\n")
        # Final image repeat for last frame
        f.write(f"file '{scenes[-1][0]}'\n")
        
    print("Concat file written. Rendering video with audio...")
    
    # 2. Render video with x264, yuv420p for universal compatibility
    cmd = [
        ffmpeg, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_txt,
        "-i", audio_path,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        video_out
    ]
    subprocess.run(cmd, check=True)
    print("Raw video rendered successfully at:", video_out)
    
    # 3. Save poster frame (Scene 4 shows the containment shield & prompt injection neutralization)
    poster_src = os.path.join(out_dir, "frames", "scene4.png")
    # Convert PNG to high-quality JPG poster
    cmd_poster = [
        ffmpeg, "-y",
        "-i", poster_src,
        "-q:v", "2",
        poster_jpg
    ]
    subprocess.run(cmd_poster, check=True)
    print("Poster frame saved to:", poster_jpg)
    
    # 4. Bake poster as frame 0 of final brag.mp4
    # Overlay poster.jpg only on frame 0 (n==0)
    print("Baking poster into frame 0 of final MP4...")
    cmd_bake = [
        ffmpeg, "-y",
        "-i", video_out,
        "-i", poster_jpg,
        "-filter_complex", "[0:v][1:v]overlay=0:0:enable='eq(n,0)'[v]",
        "-map", "[v]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        final_mp4
    ]
    subprocess.run(cmd_bake, check=True)
    print("Master hackathon video completed at:", final_mp4)

if __name__ == "__main__":
    render()

