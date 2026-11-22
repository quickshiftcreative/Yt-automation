import asyncio
import os
import random
import re
import subprocess
import time
import edge_tts
from config import VOICE_MAP, VOICE_STYLE

# 8 Distinct US Neural Voices (4 Male + 4 Female) tuned by content style
US_MALE_VOICES = [
    "en-US-AndrewNeural",       # Warm, authoritative documentary & tech lead
    "en-US-BrianNeural",        # Crisp, trustworthy news anchor
    "en-US-GuyNeural",          # High-energy, engaging viral & gaming host
    "en-US-ChristopherNeural",  # Deep, analytical deep-dive narrator
]

US_FEMALE_VOICES = [
    "en-US-AvaNeural",          # Expressive, modern US tech & culture anchor
    "en-US-EmmaNeural",         # Clear, intelligent documentary & market analyst
    "en-US-JennyNeural",        # Energetic, conversational viral & gaming host
    "en-US-AriaNeural",         # Sharp, broadcast news co-anchor
]

MODE_VOICE_PROFILES = {
    # Dual-anchor Male + Female rotation for Long News Bulletins
    "news_bulletin": {
        "dual_anchor": True,
        "male": ["en-US-BrianNeural", "en-US-AndrewNeural"],
        "female": ["en-US-AriaNeural", "en-US-AvaNeural"],
        "rate": "+6%",
    },
    # High-energy voices for Trending Games / Gamers / Viral Topics
    "trending_viral": {
        "dual_anchor": False,
        "male": ["en-US-GuyNeural", "en-US-AndrewNeural"],
        "female": ["en-US-JennyNeural", "en-US-AvaNeural"],
        "rate": "+8%",
    },
    # Authoritative documentary voices for 8-10 min Deep Dives & Versus
    "deep_dive_evergreen": {
        "dual_anchor": False,
        "male": ["en-US-AndrewNeural", "en-US-ChristopherNeural"],
        "female": ["en-US-EmmaNeural", "en-US-AvaNeural"],
        "rate": "+4%",
    },
}


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


def _sanitize_tts_text(text):
    """Cleans characters that occasionally trigger Edge-TTS empty audio responses."""
    text = re.sub(r"[\"'`“”‘’*_#~<>|\[\]{}]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


async def _synthesize_one(text, out_path, voice, rate="+5%"):
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await communicate.save(out_path)
    if not os.path.exists(out_path) or os.path.getsize(out_path) < 400:
        raise RuntimeError("Empty audio file returned by TTS")


def _create_fallback_silence(out_path, duration=3.0):
    """Emergency fallback so a 36-scene render never crashes on a single TTS glitch."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "anullsrc=r=24000:cl=mono",
        "-t", str(duration),
        "-q:a", "9",
        out_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)


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


def _select_voice_plan(total_scenes):
    """Builds a smart per-scene US voice lineup based on content mode, format & style."""
    mode = os.getenv("CONTENT_MODE", "news_bulletin").strip().lower()
    video_format = os.getenv("VIDEO_FORMAT", "horizontal").strip().lower()
    style = (VOICE_STYLE or "auto").strip().lower()

    profile = MODE_VOICE_PROFILES.get(mode, MODE_VOICE_PROFILES["news_bulletin"])
    rate = profile["rate"]
    is_long = video_format != "shorts" and total_scenes >= 12

    if style == "male_us":
        lead = random.choice(profile["male"])
        return [lead] * total_scenes, rate, f"US Male ({lead})"

    if style == "female_us":
        lead = random.choice(profile["female"])
        return [lead] * total_scenes, rate, f"US Female ({lead})"

    # Auto mode: adapts to video type (Dual-Anchor Male+Female for News Bulletin, curated host otherwise)
    if profile["dual_anchor"] and is_long:
        m_voice = random.choice(profile["male"])
        f_voice = random.choice(profile["female"])
        plan = []
        # Switch anchor every 4 scenes (matches bulletin segments naturally)
        for i in range(total_scenes):
            block = (i // 4) % 2
            plan.append(m_voice if block == 0 else f_voice)
        return plan, rate, f"Dual-Anchor Broadcast ({m_voice} + {f_voice})"

    # Single host auto-picked from matching Male/Female pool for this mode
    pool = profile["male"] + profile["female"]
    chosen = random.choice(pool)
    return [chosen] * total_scenes, rate, f"Auto Smart Pick ({chosen})"


def generate_scene_voices_and_srt(scenes, work_dir, srt_path):
    """Generates US neural voiceovers (8-voice pool + dual-anchor support) and synced SRT."""
    voice_plan, rate, plan_label = _select_voice_plan(len(scenes))
    backup_pool = US_MALE_VOICES + US_FEMALE_VOICES

    scene_audio_info = []
    srt_entries = []
    current_time = 0.0
    srt_index = 1

    print(f"[Voice] Mode Plan: {plan_label} | Rate: {rate}")
    for idx, scene in enumerate(scenes):
        raw_narration = scene["narration"]
        clean_narration = _sanitize_tts_text(raw_narration)
        mp3_path = os.path.join(work_dir, f"voice_{idx:02d}.mp3")
        primary_voice = voice_plan[idx]

        # Small pacing pause every 6 scenes to prevent Edge-TTS rate throttling
        if idx > 0 and idx % 6 == 0:
            time.sleep(1.5)
        elif idx > 0:
            time.sleep(0.35)

        synthesized = False
        last_err = None

        for attempt in range(6):
            # Switch to backup US voices if primary voice hits temporary Microsoft throttling
            if attempt < 3:
                active_voice = primary_voice
            else:
                active_voice = backup_pool[(idx + attempt) % len(backup_pool)]

            try:
                asyncio.run(_synthesize_one(clean_narration, mp3_path, active_voice, rate=rate))
                synthesized = True
                break
            except Exception as e:
                last_err = e
                wait_sec = min(8.0, 1.2 * (attempt + 1))
                print(f"[Voice] Retry {attempt + 1}/6 scene {idx + 1} ({active_voice}): {e}")
                time.sleep(wait_sec)

        if not synthesized:
            print(f"[Voice] Warning: Using silent placeholder for scene {idx + 1} after retries ({last_err})")
            _create_fallback_silence(mp3_path, duration=3.0)

        duration = get_audio_duration(mp3_path)
        scene_audio_info.append({
            "index": idx,
            "audio_path": mp3_path,
            "duration": duration,
            "visual_query": scene["visual_query"],
            "narration": raw_narration,
        })

        chunks = _split_caption_chunks(raw_narration, words_per_chunk=5)
        total_words = max(1, len(raw_narration.split()))
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
        print(f"[Voice] Scene {idx + 1}/{len(scenes)} [{primary_voice}] ({duration:.2f}s)")

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_entries))

    return scene_audio_info, current_time
