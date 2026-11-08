import imageio_ffmpeg
import subprocess
import os

ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

def build_audio():
    # Audio segments and their start delays in ms
    delays = [
        ("brag-output/voiceover/scene1.mp3", 1000),      # 1.0s
        ("brag-output/voiceover/scene2.mp3", 31500),     # 31.5s
        ("brag-output/voiceover/scene3.mp3", 65000),     # 65.0s
        ("brag-output/voiceover/scene4.mp3", 96500),     # 96.5s
        ("brag-output/voiceover/scene5.mp3", 134500),    # 134.5s
        ("brag-output/voiceover/scene6.mp3", 156500),    # 156.5s
        ("brag-output/voiceover/scene7.mp3", 187000),    # 187.0s
    ]
    
    # 1. First concatenate voice track with adelay
    inputs = []
    filter_parts = []
    for i, (path, delay_ms) in enumerate(delays):
        inputs.extend(["-i", path])
        filter_parts.append(f"[{i}:a]adelay={delay_ms}|{delay_ms}[a{i}];")
    
    amix_inputs = "".join(f"[a{i}]" for i in range(len(delays)))
    filter_graph = "".join(filter_parts) + f"{amix_inputs}amix=inputs={len(delays)}:normalize=0[vo_mix]"
    
    vo_temp = "brag-output/voiceover/vo_combined.wav"
    cmd = [ffmpeg, "-y"] + inputs + ["-filter_complex", filter_graph, "-map", "[vo_mix]", vo_temp]
    print("Combining voiceover tracks...")
    subprocess.run(cmd, check=True)
    print("Voiceover combined successfully!")
    
    # 2. Mix with music and SFX
    music_path = "brag-output/assets/music/music.mp3"
    sfx_switch = "brag-output/assets/sfx/switch10.ogg"
    master_out = "brag-output/master_audio.mp3"
    
    # We want music ducked (volume 0.14) and looped for 204 seconds, fading out at 200-204s
    # SFX at transition points
    cmd_master = [
        ffmpeg, "-y",
        "-i", vo_temp,
        "-stream_loop", "-1", "-i", music_path,
        "-i", sfx_switch,
        "-filter_complex",
        "[1:a]volume=0.14,afade=t=out:st=200:d=4[bgm];"
        "[2:a]volume=0.35,adelay=1000|1000[sfx0];"
        "[2:a]volume=0.35,adelay=31000|31000[sfx1];"
        "[2:a]volume=0.35,adelay=64500|64500[sfx2];"
        "[2:a]volume=0.35,adelay=96000|96000[sfx3];"
        "[2:a]volume=0.35,adelay=134000|134000[sfx4];"
        "[2:a]volume=0.35,adelay=156000|156000[sfx5];"
        "[2:a]volume=0.35,adelay=186500|186500[sfx6];"
        "[0:a]volume=1.05[vo];"
        "[vo][bgm][sfx0][sfx1][sfx2][sfx3][sfx4][sfx5][sfx6]amix=inputs=9:normalize=0[aout]",
        "-map", "[aout]",
        "-t", "204",
        "-b:a", "192k",
        master_out
    ]
    print("Mixing master audio...")
    subprocess.run(cmd_master, check=True)
    print("Master audio created at:", master_out)

if __name__ == "__main__":
    build_audio()

