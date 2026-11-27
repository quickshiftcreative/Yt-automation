import asyncio
import inspect
import os
import random
import re
import subprocess
import edge_tts

TONE_PROSODY = {
    "hook":       ("+6%", "+2Hz"),
    "urgent":     ("+7%", "+1Hz"),
    "excited":    ("+6%", "+3Hz"),
    "serious":    ("-3%", "-2Hz"),
    "analytical": ("+1%", "+0Hz"),
    "calm":       ("-4%", "-1Hz"),
}

MALE_VOICES = ["en-US-AndrewNeural", "en-US-BrianNeural"]
FEMALE_VOICES = ["en-US-AvaNeural", "en-US-EmmaNeural"]

SPOKEN_REPLACEMENTS = [
    (r"\$(\d+(?:\.\d+)?)\s*[Tt]\b", r"$\1 trillion"),
    (r"\$(\d+(?:\.\d+)?)\s*[Bb]\b", r"$\1 billion"),
    (r"\$(\d+(?:\.\d+)?)\s*[Mm]\b", r"$\1 million"),
    (r"\b(\d+(?:\.\d+)?)\s*[xX]\b", r"\1 times"),
    (r"\b(\d+(?:,\d+)*(?:\.\d+)?)\s*pts?\b", r"\1 points"),
    (r"\bNVDA\b", "Nvidia"),
    (r"\bAAPL\b", "Apple"),
    (r"\bMSFT\b", "Microsoft"),
    (r"\bTSLA\b", "Tesla"),
    (r"\bGOOGL\b", "Google"),
    (r"\bAMZN\b", "Amazon"),
    (r"\bINTC\b", "Intel"),
    (r"\bTSMC\b", "T S M C"),
    (r"\bYoY\b", "year-over-year"),
    (r"\bQoQ\b", "quarter-over-quarter"),
    (r"\bQ1\b", "first quarter"),
    (r"\bQ2\b", "second quarter"),
    (r"\bQ3\b", "third quarter"),
    (r"\bQ4\b", "fourth quarter"),
]


def _normalize_for_natural_speech(text):
    out = str(text or "")
    for pat, repl in SPOKEN_REPLACEMENTS:
        out = re.sub(pat, repl, out, flags=re.IGNORECASE if "pts" in pat else 0)
    return re.sub(r"\s+", " ", out).strip()


def _pick_host_pair():
    style = os.getenv("VOICE_STYLE", "auto").strip().lower()
    if style == "male_us":
        return random.choice(MALE_VOICES), random.choice(FEMALE_VOICES)
    if style == "female_us":
        return random.choice(FEMALE_VOICES), random.choice(MALE_VOICES)
    if random.random() < 0.55:
        return random.choice(MALE_VOICES), random.choice(FEMALE_VOICES)
    return random.choice(FEMALE_VOICES), random.choice(MALE_VOICES)


def _probe_duration(media_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        media_path,
    ]
    out = subprocess.check_output(cmd, text=True).strip()
    return max(0.4, float(out))


def _format_ass_time(seconds):
    seconds = max(0.0, float(seconds))
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{hrs}:{mins:02d}:{secs:02d}.{cs:02d}"


def _escape_ass(text):
    return (text or "").replace("\\", "").replace("{", "").replace("}", "").replace("\n", " ").strip()


def _supports_boundary_param():
    try:
        return "boundary" in inspect.signature(edge_tts.Communicate.__init__).parameters
    except Exception:
        return False


async def _synthesize_single_beat(text, voice, rate, pitch, out_raw_mp3):
    kwargs = {"voice": voice, "rate": rate, "pitch": pitch}
    if _supports_boundary_param():
        kwargs["boundary"] = "WordBoundary"

    comm = edge_tts.Communicate(text, **kwargs)
    words = []
    audio_bytes = bytearray()

    async for chunk in comm.stream():
        ctype = chunk.get("type")
        if ctype == "audio":
            audio_bytes.extend(chunk.get("data", b""))
        elif ctype == "WordBoundary":
            w_text = _escape_ass(chunk.get("text", ""))
            if w_text:
                start_s = float(chunk.get("offset", 0)) / 10_000_000.0
                dur_s = max(0.08, float(chunk.get("duration", 1200000)) / 10_000_000.0)
                words.append({"text": w_text, "start": start_s, "end": start_s + dur_s})

    with open(out_raw_mp3, "wb") as f:
        f.write(audio_bytes)
    return words


async def _synthesize_all_beats_concurrent(beat_jobs):
    sem = asyncio.Semaphore(4)

    async def _worker(job):
        async with sem:
            try:
                return await _synthesize_single_beat(
                    job["spoken_text"], job["voice"], job["rate"], job["pitch"], job["raw_mp3"]
                )
            except Exception as e:
                print(f"[Voice] Retry fallback on beat {job['beat_idx'] + 1}: {e}")
                return await _synthesize_single_beat(
                    job["spoken_text"], "en-US-AndrewNeural", "+1%", "+0Hz", job["raw_mp3"]
                )

    return await asyncio.gather(*[_worker(j) for j in beat_jobs])


def _build_word_chunks(words, max_words=3, max_chars=22):
    chunks = []
    cur = []
    for w in words:
        cand = cur + [w]
        joined = " ".join(x["text"] for x in cand)
        if cur and (len(cand) > max_words or len(joined) > max_chars):
            chunks.append(cur)
            cur = [w]
        else:
            cur = cand
    if cur:
        chunks.append(cur)
    return chunks


def _write_pop_captions_ass(all_word_events, ass_path, is_shorts):
    play_x, play_y = (1080, 1920) if is_shorts else (1920, 1080)
    font_size = 74 if is_shorts else 58
    margin_v = 340 if is_shorts else 76
    outline_w = 6 if is_shorts else 5

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_x}
PlayResY: {play_y}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: PopCap,DejaVu Sans,{font_size},&H00FFFFFF,&H0000D7FF,&H00080A0E,&H90000000,-1,0,0,0,100,100,0,0,1,{outline_w},2,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    max_w = 3 if is_shorts else 4
    max_c = 18 if is_shorts else 28

    for beat_words in all_word_events:
        chunks = _build_word_chunks(beat_words, max_words=max_w, max_chars=max_c)
        for ch in chunks:
            for active_i, w_act in enumerate(ch):
                t0 = w_act["start"]
                if active_i + 1 < len(ch):
                    t1 = max(t0 + 0.06, ch[active_i + 1]["start"])
                else:
                    t1 = max(t0 + 0.12, w_act["end"] + 0.05)

                rendered_tokens = []
                for j, w_tok in enumerate(ch):
                    tok_upper = w_tok["text"].upper() if is_shorts else w_tok["text"]
                    if j == active_i:
                        rendered_tokens.append(
                            f"{{\\c&H00D7FF&\\fscx108\\fscy108}}{tok_upper}{{\\c&HFFFFFF&\\fscx100\\fscy100}}"
                        )
                    else:
                        rendered_tokens.append(tok_upper)

                line_txt = " ".join(rendered_tokens)
                lines.append(
                    f"Dialogue: 0,{_format_ass_time(t0)},{_format_ass_time(t1)},PopCap,,0,0,0,,{line_txt}\n"
                )

    with open(ass_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def generate_scene_voices_and_srt(scenes, work_dir, subtitle_path):
    os.makedirs(work_dir, exist_ok=True)
    is_shorts = os.getenv("VIDEO_FORMAT", "horizontal").strip().lower() == "shorts"
    main_voice, cohost_voice = _pick_host_pair()

    beat_pad_in_scene = 0.10 if is_shorts else 0.14
    scene_breath_pad = 0.20 if is_shorts else 0.26
    outro_tail_pad = 2.00 if is_shorts else 2.60

    beat_jobs = []
    beat_idx = 0
    for s_idx, sc in enumerate(scenes):
        is_last_scene = (s_idx == len(scenes) - 1)
        tone = "calm" if is_last_scene else sc.get("tone", "hook" if s_idx == 0 else "analytical").strip().lower()
        speaker = str(sc.get("speaker", "main")).strip().lower()
        itype = str(sc.get("interactive_type", "none")).strip().lower()
        highlight_text = sc.get("highlight_text", "")

        raw_beats = sc.get("beats") or []
        if not raw_beats:
            nar = sc.get("narration", "").strip()
            if not nar:
                continue
            raw_beats = [{
                "text": nar,
                "visual_type": "stock_video",
                "query": sc.get("visual_query", "technology"),
                "alt_query": "",
                "screen_tag": "",
                "metric_value": "",
                "metric_label": "",
            }]

        for b_pos, b in enumerate(raw_beats):
            raw_txt = str(b.get("text", "")).strip()
            if not raw_txt:
                continue
            is_last_in_scene = (b_pos == len(raw_beats) - 1)
            active_voice = cohost_voice if (not is_shorts and speaker == "cohost" and not is_last_scene) else main_voice

            base_rate, base_pitch = TONE_PROSODY.get(tone, ("+1%", "+0Hz"))
            if is_shorts and not is_last_scene and tone not in ("hook", "urgent", "excited"):
                base_rate = "+4%"

            beat_jobs.append({
                "beat_idx": beat_idx,
                "scene_index": s_idx,
                "is_scene_start": (b_pos == 0),
                "is_last_in_scene": is_last_in_scene,
                "is_last_scene": is_last_scene,
                "raw_text": raw_txt,
                "spoken_text": _normalize_for_natural_speech(raw_txt),
                "voice": active_voice,
                "rate": base_rate,
                "pitch": base_pitch,
                "tone": tone,
                "speaker": speaker,
                "scene_interactive": itype,
                "highlight_text": highlight_text,
                "visual_type": b.get("visual_type", "stock_video"),
                "visual_query": b.get("query", sc.get("visual_query", "technology")),
                "alt_query": b.get("alt_query", ""),
                "screen_tag": b.get("screen_tag", ""),
                "metric_value": b.get("metric_value", ""),
                "metric_label": b.get("metric_label", ""),
                "raw_mp3": os.path.join(work_dir, f"raw_beat_{beat_idx:03d}.mp3"),
                "clean_mp3": os.path.join(work_dir, f"beat_{beat_idx:03d}.mp3"),
            })
            beat_idx += 1

    if not beat_jobs:
        raise RuntimeError("No valid spoken beats found in script blueprint.")

    print(f"[Voice] Main: {main_voice} | Co-Host: {cohost_voice} | Synthesizing {len(beat_jobs)} synced beats...")
    all_raw_words = asyncio.run(_synthesize_all_beats_concurrent(beat_jobs))

    beat_audio_info = []
    all_word_events = []
    timeline_cursor = 0.0
    total_beats = len(beat_jobs)

    for k, (job, words) in enumerate(zip(beat_jobs, all_raw_words)):
        is_final_beat = (k == total_beats - 1)
        is_countdown_pause = (job["scene_interactive"] == "countdown" and job["is_last_in_scene"])

        if is_final_beat:
            pad_sec = outro_tail_pad
        elif is_countdown_pause:
            pad_sec = 1.80
        elif job["is_last_in_scene"]:
            pad_sec = scene_breath_pad
        else:
            pad_sec = beat_pad_in_scene

        subprocess.run(
            [
                "ffmpeg", "-y", "-i", job["raw_mp3"],
                "-af", f"apad=pad_dur={pad_sec:.2f}",
                "-ar", "44100", "-ac", "2",
                "-c:a", "libmp3lame", "-q:a", "3",
                job["clean_mp3"],
            ],
            capture_output=True,
            check=True,
        )

        dur = _probe_duration(job["clean_mp3"])

        if not words:
            raw_tokens = job["spoken_text"].split()
            speak_dur = max(0.4, dur - pad_sec)
            step = speak_dur / max(1, len(raw_tokens))
            words = [
                {"text": _escape_ass(tok), "start": m * step, "end": (m + 1) * step}
                for m, tok in enumerate(raw_tokens)
                if _escape_ass(tok)
            ]

        shifted_words = [
            {"text": w["text"], "start": timeline_cursor + w["start"], "end": timeline_cursor + w["end"]}
            for w in words
        ]
        all_word_events.append(shifted_words)

        beat_audio_info.append({
            "index": k,
            "scene_index": job["scene_index"],
            "is_scene_start": job["is_scene_start"],
            "is_last_in_scene": job["is_last_in_scene"],
            "is_final_beat": is_final_beat,
            "audio_path": job["clean_mp3"],
            "duration": dur,
            "start_time": timeline_cursor,
            "end_time": timeline_cursor + dur,
            "countdown_start": (timeline_cursor + max(0.3, dur - pad_sec)) if is_countdown_pause else None,
            "narration": job["raw_text"],
            "visual_type": job["visual_type"],
            "visual_query": job["visual_query"],
            "alt_query": job["alt_query"],
            "screen_tag": job["screen_tag"],
            "metric_value": job["metric_value"],
            "metric_label": job["metric_label"],
            "tone": job["tone"],
            "speaker": job["speaker"],
            "interactive_type": job["scene_interactive"] if job["is_last_in_scene"] else ("music_drop" if job["scene_interactive"] == "music_drop" and job["is_scene_start"] else "none"),
            "highlight_text": job["highlight_text"],
        })
        timeline_cursor += dur

    print(f"[Voice] Synthesized {total_beats} synced beats | Total duration: {timeline_cursor:.2f}s")
    ass_out = subtitle_path if subtitle_path.lower().endswith(".ass") else subtitle_path.rsplit(".", 1)[0] + ".ass"
    _write_pop_captions_ass(all_word_events, ass_out, is_shorts)
    return beat_audio_info, timeline_cursor
