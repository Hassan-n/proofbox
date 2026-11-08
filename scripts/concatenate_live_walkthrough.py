import imageio_ffmpeg
import subprocess
import os

ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

def concatenate_walkthrough():
    out_dir = "brag-output"
    clips_dir = os.path.join(out_dir, "live_clips")
    
    clips = [
        "clip1_intro.mp4",
        "clip2_vultr.mp4",
        "clip_linklens.mp4",
        "clip_billlens.mp4",
        "clip_letterlens.mp4",
        "clip_casefile.mp4",
        "clip7_outro.mp4"
    ]
    
    concat_txt = os.path.join(out_dir, "live_concat.txt")
    with open(concat_txt, "w") as f:
        for c in clips:
            c_path = os.path.join("live_clips", c).replace("\\", "/")
            f.write(f"file '{c_path}'\n")
            
    print("live_concat.txt written. Merging 7 video clips with master audio...")
    
    raw_video = os.path.join(out_dir, "brag_live_raw.mp4")
    master_audio = os.path.join(out_dir, "master_audio.mp3")
    final_mp4 = os.path.join(out_dir, "brag.mp4")
    poster_jpg = os.path.join(out_dir, "brag.jpg")
    
    # 1. Concat video clips and add master audio
    cmd_merge = [
        ffmpeg, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_txt,
        "-i", master_audio,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        raw_video
    ]
    subprocess.run(cmd_merge, check=True)
    print("Merged live walkthrough video at:", raw_video)
    
    # 2. Extract best settled poster frame (from Bill Lens live discrepancy & prompt defense at 105s)
    print("Extracting live poster frame at 105s...")
    cmd_poster = [
        ffmpeg, "-y",
        "-ss", "105.0",
        "-i", raw_video,
        "-frames:v", "1",
        "-q:v", "2",
        poster_jpg
    ]
    subprocess.run(cmd_poster, check=True)
    print("Saved poster frame:", poster_jpg)
    
    # 3. Bake poster frame into frame 0 of brag.mp4
    print("Baking poster into frame 0 of final brag.mp4...")
    cmd_bake = [
        ffmpeg, "-y",
        "-i", raw_video,
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
    print("Final live master video ready at:", final_mp4)

if __name__ == "__main__":
    concatenate_walkthrough()

