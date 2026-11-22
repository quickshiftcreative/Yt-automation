import asyncio
import os
import subprocess
import edge_tts
from config import VOICE_MAP, VOICE_STYLE


def get_audio_duration(audio_path):
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


async def _synthesize_one(text, out_path, voice):
    communicate = edge_tts.Communicate(text=text, voice=voice, rate="+5%")
    await communicate.save(out_path)


def _format_srt_time(seconds):
    ms = int(round((seconds - int(seconds)) * 1000))
    total_sec = int(seconds)
    if ms >= 1000:
        ms = 0
        total_sec += 1
    hrs = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"


def _split_caption_chunks(text, words_per_chunk=5):
    words = text.split()
    if not words:
        return []
    return [" ".join(words[i : i + words_per_chunk]) for i in range(0, len(words), words_per_chunk)]


def generate_scene_voices_and_srt(scenes, work_dir, srt_path):
    """Generates crisp US English neural voiceover per scene and builds synced SRT subtitles."""
    voice = VOICE_MAP.get(VOICE_STYLE, "en-US-AndrewNeural")
    scene_audio_info = []
    srt_entries = []
    current_time = 0.0
    srt_index = 1

    print(f"[Voice] Using US Neural Voice: {voice}")
    for idx, scene in enumerate(scenes):
        narration = scene["narration"]
        mp3_path = os.path.join(work_dir, f"voice_{idx:02d}.mp3")

        last_err = None
        for attempt in range(3):
            try:
                asyncio.run(_synthesize_one(narration, mp3_path, voice))
                break
            except Exception as e:
                last_err = e
                print(f"[Voice] Retry {attempt + 1} for scene {idx}: {e}")
        else:
            raise RuntimeError(f"Edge-TTS failed on scene {idx}: {last_err}")

        duration = get_audio_duration(mp3_path)
        scene_audio_info.append({
            "index": idx,
            "audio_path": mp3_path,
            "duration": duration,
            "visual_query": scene["visual_query"],
            "narration": narration,
        })

        chunks = _split_caption_chunks(narration, words_per_chunk=5)
        total_words = max(1, len(narration.split()))
        chunk_start = current_time
        for chunk in chunks:
            chunk_words = len(chunk.split())
            chunk_dur = duration * (chunk_words / total_words)
            chunk_end = min(current_time + duration, chunk_start + chunk_dur)
            srt_entries.append(
                f"{srt_index}\n"
                f"{_format_srt_time(chunk_start)} --> {_format_srt_time(chunk_end)}\n"
                f"{chunk}\n"
            )
            srt_index += 1
            chunk_start = chunk_end

        current_time += duration
        print(f"[Voice] Scene {idx + 1}/{len(scenes)} generated ({duration:.2f}s)")

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_entries))

    return scene_audio_info, current_time
