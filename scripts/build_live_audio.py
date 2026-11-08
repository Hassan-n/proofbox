import imageio_ffmpeg
import subprocess
import os

ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

def build_audio():
    # Delays in ms matching the 200s video sequence
    delays = [
        ("brag-output/voiceover/scene1.mp3", 500),       # 0.5s
        ("brag-output/voiceover/scene2.mp3", 30500),     # 30.5s
        ("brag-output/voiceover/scene3.mp3", 63500),     # 63.5s
        ("brag-output/voiceover/scene4.mp3", 94500),     # 94.5s
        ("brag-output/voiceover/scene5.mp3", 132500),    # 132.5s
        ("brag-output/voiceover/scene6.mp3", 154500),    # 154.5s
        ("brag-output/voiceover/scene7.mp3", 184500),    # 184.5s
    ]
    
    # 1. Combine voice tracks
    inputs = []
    filter_parts = []
    for i, (path, delay_ms) in enumerate(delays):
        inputs.extend(["-i", path])
        filter_parts.append(f"[{i}:a]adelay={delay_ms}|{delay_ms}[a{i}];")
        
    amix_inputs = "".join(f"[a{i}]" for i in range(len(delays)))
    filter_graph = "".join(filter_parts) + f"{amix_inputs}amix=inputs={len(delays)}:normalize=0[vo_mix]"
    
    vo_temp = "brag-output/voiceover/vo_live_combined.wav"
    cmd = [ffmpeg, "-y"] + inputs + ["-filter_complex", filter_graph, "-map", "[vo_mix]", vo_temp]
    print("Combining voiceover tracks...")
    subprocess.run(cmd, check=True)
    
    # 2. Mix with music and SFX
    music_path = "brag-output/assets/music/music.mp3"
    sfx_switch = "brag-output/assets/sfx/switch10.ogg"
    master_out = "brag-output/master_audio.mp3"
    
    # Total duration: 200s
    cmd_master = [
        ffmpeg, "-y",
        "-i", vo_temp,
        "-stream_loop", "-1", "-i", music_path,
        "-i", sfx_switch,
        "-filter_complex",
        "[1:a]volume=0.14,afade=t=out:st=196:d=4[bgm];"
        "[2:a]volume=0.35,adelay=500|500[sfx0];"
        "[2:a]volume=0.35,adelay=30000|30000[sfx1];"
        "[2:a]volume=0.35,adelay=63000|63000[sfx2];"
        "[2:a]volume=0.35,adelay=94000|94000[sfx3];"
        "[2:a]volume=0.35,adelay=132000|132000[sfx4];"
        "[2:a]volume=0.35,adelay=154000|154000[sfx5];"
        "[2:a]volume=0.35,adelay=184000|184000[sfx6];"
        "[0:a]volume=1.05[vo];"
        "[vo][bgm][sfx0][sfx1][sfx2][sfx3][sfx4][sfx5][sfx6]amix=inputs=9:normalize=0[aout]",
        "-map", "[aout]",
        "-t", "200",
        "-b:a", "192k",
        master_out
    ]
    print("Mixing master audio with 200s timeline...")
    subprocess.run(cmd_master, check=True)
    print("Live master audio created at:", master_out)

if __name__ == "__main__":
    build_audio()

