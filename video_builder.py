import glob
import os
import random
import subprocess
from PIL import Image, ImageDraw, ImageFont
from config import VIDEO_FORMAT
from chart_animator import render_animated_candlestick_clip
from media_fetcher import fetch_broll_clip


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _asset_path(*parts):
    p = os.path.join(_repo_root(), "assets", *parts)
    return p if os.path.exists(p) else None


def _all_sfx_files():
    root = _repo_root()
    candidates = []
    for folder in (
        os.path.join(root, "assets", "sfx"),
        os.path.join(root, "sfx"),
        os.path.join(root, "assets", "sfx_transitions"),
        os.path.join(root, "assets", "sfx_impacts"),
        os.path.join(root, "assets", "sfx_ui_alerts"),
        os.path.join(root, "assets", "sfx_market_news"),
    ):
        if os.path.isdir(folder):
            candidates.extend(sorted(glob.glob(os.path.join(folder, "*.wav")) + glob.glob(os.path.join(folder, "*.mp3"))))
    return list(dict.fromkeys(candidates))


def _pick_sfx_by_keywords(all_files, keywords, rng):
    if not all_files:
        return None
    matched = [f for f in all_files if any(k in os.path.basename(f).lower() for k in keywords)]
    if matched:
        return rng.choice(matched)
    return rng.choice(all_files)


def _pick_music_bed(mode, is_shorts, rng):
    root = _repo_root()
    files = []
    for m_dir in (os.path.join(root, "assets", "music_beds"), os.path.join(root, "assets", "music")):
        if os.path.isdir(m_dir):
            files.extend(sorted(glob.glob(os.path.join(m_dir, "*.wav")) + glob.glob(os.path.join(m_dir, "*.mp3"))))
    if not files:
        return None

    if is_shorts:
        for f in files:
            if "phonk" in os.path.basename(f).lower() or "shorts" in os.path.basename(f).lower():
                return f

    pref_map = {
        "news_bulletin": ["06_market_wallstreet_news", "10_breaking_news_urgency", "08_business_luxury_rpm"],
        "trending_viral": ["04_gaming_cyber_hype", "12_viral_debate_groove", "01_hook_tension_pulse"],
        "deep_dive_evergreen": ["02_tech_dark_ambient", "03_ai_neural_pulse", "08_business_luxury_rpm", "09_lofi_tech_explainer"],
    }
    for key in pref_map.get(mode, []):
        for f in files:
            if key in os.path.basename(f).lower():
                return f
    return rng.choice(files)


def _find_font(size, style="bold"):
    f_dir = os.path.join(_repo_root(), "assets", "fonts")
    name_map = {
        "impact": ["Impact_Condensed_Black.ttf", "Impact_Display_Black.ttf"],
        "mono": ["Ticker_Mono_Bold.ttf", "Ticker_Mono_Regular.ttf"],
        "bold": ["Modern_Lato_Black.ttf", "Modern_Lato_Bold.ttf"],
    }
    for fn in name_map.get(style, ["Modern_Lato_Black.ttf"]):
        p = os.path.join(f_dir, fn)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    for sys_f in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]:
        if os.path.exists(sys_f):
            try:
                return ImageFont.truetype(sys_f, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _create_motion_card_png(out_png, width, height, title_text, body_text, card_type="stat", accent="gold"):
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    palette = {
        "gold": ((224, 182, 58, 255), (12, 14, 18, 232), (246, 244, 238, 255)),
        "green": ((36, 224, 132, 255), (10, 18, 16, 232), (235, 255, 245, 255)),
        "red": ((245, 56, 72, 255), (20, 10, 12, 234), (255, 238, 240, 255)),
    }
    acc_col, bg_col, txt_col = palette.get(accent, palette["gold"])

    box_w = min(int(width * 0.84), 980)
    box_h = 230 if card_type != "news" else 270
    x0 = (width - box_w) // 2
    y0 = int(height * 0.14) if height > width else int(height * 0.16)
    x1 = x0 + box_w
    y1 = y0 + box_h

    draw.rounded_rectangle([x0, y0, x1, y1], radius=22, fill=bg_col, outline=acc_col, width=3)
    draw.rounded_rectangle([x0, y0, x0 + 14, y1], radius=7, fill=acc_col)

    f_hdr = _find_font(24, "mono")
    f_bdy = _find_font(38, "bold")

    hdr_lbl = "MARKET & STAT CALLOUT" if card_type == "stat" else "VERIFIED REPORT"
    draw.text((x0 + 34, y0 + 22), hdr_lbl, fill=acc_col, font=f_hdr)

    words = (body_text or title_text or "").split()
    lines = []
    cur = []
    for w in words:
        test = " ".join(cur + [w])
        if len(test) <= 34:
            cur.append(w)
        else:
            if cur:
                lines.append(" ".join(cur))
            cur = [w]
        if len(lines) >= 2:
            break
    if cur and len(lines) < 2:
        lines.append(" ".join(cur))

    y_txt = y0 + 72
    for ln in lines[:2]:
        draw.text((x0 + 34, y_txt), ln, fill=txt_col, font=f_bdy)
        y_txt += 52

    canvas.save(out_png, "PNG")
    return out_png


def _render_subclip(src_mp4, dur, out_mp4, width, height, is_shorts, rng, overlay_png=None, gif_path=None):
    os.makedirs(os.path.dirname(out_mp4), exist_ok=True)
    fps = 24
    n_frames = max(12, int(round(dur * fps)))

    scale_w = int(width * 1.12)
    scale_h = int(height * 1.12)
    scale_w += scale_w % 2
    scale_h += scale_h % 2

    zoom_start = 1.0
    zoom_end = 1.07 if rng.random() > 0.35 else 1.03

    if src_mp4 and os.path.exists(src_mp4):
        vf_parts = [
            f"scale={scale_w}:{scale_h}:force_original_aspect_ratio=increase",
            f"crop={scale_w}:{scale_h}",
            f"zoompan=z='min({zoom_end}, {zoom_start}+({zoom_end}-{zoom_start})*on/{max(1,n_frames)})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n_frames}:s={width}x{height}:fps={fps}",
            "eq=contrast=1.06:brightness=-0.02:saturation=1.08",
        ]
        inp_args = ["-stream_loop", "-1", "-i", src_mp4]
    else:
        vf_parts = ["color=c=0x0b0e14:s={width}x{height}:r={fps}:d={dur:.2f}".format(width=width, height=height, fps=fps, dur=dur), "eq=contrast=1.05"]
        inp_args = []

    filter_chain = []
    cur_label = "[base]"
    if inp_args:
        filter_chain.append(f"[0:v]{','.join(vf_parts)}[base]")
    else:
        filter_chain.append(f"{vf_parts[0]}[base]")

    next_inp = 1
    if overlay_png and os.path.exists(overlay_png):
        inp_args.extend(["-i", overlay_png])
        filter_chain.append(f"{cur_label}[{next_inp}:v]overlay=0:0:shortest=1[ov1]")
        cur_label = "[ov1]"
        next_inp += 1

    if gif_path and os.path.exists(gif_path):
        inp_args.extend(["-ignore_loop", "0", "-i", gif_path])
        gw = 240 if not is_shorts else 220
        gx = width - gw - 36
        gy = 36 if not is_shorts else 130
        filter_chain.append(f"[{next_inp}:v]scale={gw}:-1[gf]")
        filter_chain.append(f"{cur_label}[gf]overlay={gx}:{gy}:shortest=1[ov2]")
        cur_label = "[ov2]"
        next_inp += 1

    vig_name = "vignette_9x16.png" if is_shorts else "vignette_16x9.png"
    vig_p = _asset_path("overlays", vig_name)
    if vig_p:
        inp_args.extend(["-i", vig_p])
        filter_chain.append(f"[{next_inp}:v]scale={width}:{height}[vg]")
        filter_chain.append(f"{cur_label}[vg]overlay=0:0:shortest=1[vout]")
        cur_label = "[vout]"
        next_inp += 1

    final_map = cur_label.strip("[]")
    cmd = [
        "ffmpeg", "-y",
        *inp_args,
        "-filter_complex", ";".join(filter_chain),
        "-map", f"[{final_map}]",
        "-t", f"{dur:.3f}",
        "-an",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        out_mp4,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return out_mp4


def _master_voice_and_music(voice_concat_mp3, total_dur, mode, is_shorts, work_dir, out_audio_wav):
    rng = random.Random(404)
    v_filt = (
        "highpass=f=85,lowpass=f=14500,"
        "equalizer=f=180:width_type=o:width=1.5:g=2.5,"
        "acompressor=threshold=-18dB:ratio=3:attack=10:release=120:makeup=2.0,"
        "loudnorm=I=-15:TP=-1.5:LRA=11"
    )
    v_master = os.path.join(work_dir, "voice_mastered.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", voice_concat_mp3, "-af", v_filt, "-ar", "44100", "-ac", "2", v_master],
        capture_output=True,
        check=True,
    )

    music_file = _pick_music_bed(mode, is_shorts, rng)
    sfx_pool = _all_sfx_files()
    sfx_whoosh = _pick_sfx_by_keywords(sfx_pool, ["whoosh", "swipe", "glitch"], rng)
    sfx_market = _pick_sfx_by_keywords(sfx_pool, ["market_drop", "market_rally", "boom", "riser"], rng)

    inputs = ["-i", v_master]
    idx = 1
    parts = []
    cur_v = "[0:a]"

    if music_file:
        inputs.extend(["-stream_loop", "-1", "-i", music_file])
        parts.append(f"[{idx}:a]atrim=0:{total_dur:.2f},volume=0.075[mbase]")
        parts.append(f"{cur_v}[mbase]sidechaincompress=threshold=0.04:ratio=4:attack=20:release=250:level_sc=0.8[vmix]")
        cur_v = "[vmix]"
        idx += 1

    if sfx_whoosh and total_dur > 6.0:
        inputs.extend(["-i", sfx_whoosh])
        w_idx = idx
        idx += 1
        parts.append(f"[{w_idx}:a]volume=0.22[w_raw]")
        w_labels = []
        t_cur = 3.5
        k = 0
        while t_cur < total_dur - 1.5 and k < 75:
            d_ms = int(t_cur * 1000)
            parts.append(f"[w_raw]adelay={d_ms}|{d_ms}[wd{k}]")
            w_labels.append(f"[wd{k}]")
            t_cur += 8.0
            k += 1
        if w_labels:
            parts.append(f"{cur_v}{''.join(w_labels)}amix=inputs={1 + len(w_labels)}:normalize=0[am_w]")
            cur_v = "[am_w]"

    if sfx_market and total_dur > 10.0:
        inputs.extend(["-i", sfx_market])
        m_sfx_idx = idx
        idx += 1
        d_ms = int(min(total_dur * 0.45, 180.0) * 1000)
        parts.append(f"[{m_sfx_idx}:a]volume=0.32,adelay={d_ms}|{d_ms}[msfx]")
        parts.append(f"{cur_v}[msfx]amix=inputs=2:normalize=0[am_final]")
        cur_v = "[am_final]"

    if not parts:
        subprocess.run(["ffmpeg", "-y", "-i", v_master, "-c:a", "copy", out_audio_wav], capture_output=True, check=True)
        return out_audio_wav

    final_tag = cur_v.strip("[]")
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", ";".join(parts),
        "-map", f"[{final_tag}]",
        "-t", f"{total_dur:.3f}",
        out_audio_wav,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return out_audio_wav


def _burn_subtitles(video_mp4, srt_path, out_mp4, is_shorts):
    if not srt_path or not os.path.exists(srt_path) or os.path.getsize(srt_path) == 0:
        subprocess.run(["ffmpeg", "-y", "-i", video_mp4, "-c", "copy", out_mp4], capture_output=True, check=True)
        return out_mp4

    font_size = 18 if is_shorts else 20
    margin_v = 150 if is_shorts else 58
    style = (
        f"FontName=DejaVu Sans,FontSize={font_size},Bold=1,"
        f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00080A0E,BackColour=&H88000000,"
        f"BorderStyle=3,Outline=2,Shadow=1,MarginV={margin_v}"
    )
    escaped_srt = srt_path.replace("\\", "/").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-y",
        "-i", video_mp4,
        "-vf", f"subtitles='{escaped_srt}':force_style='{style}'",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        out_mp4,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return out_mp4


def build_final_video(scene_audio_info, srt_path, work_dir, output_video_path):
    os.makedirs(os.path.dirname(output_video_path), exist_ok=True)
    is_shorts = VIDEO_FORMAT == "shorts"
    mode = os.getenv("CONTENT_MODE", "news_bulletin").strip().lower()
    width, height = (1080, 1920) if is_shorts else (1920, 1080)

    rng = random.Random(2026)
    used_urls = set()
    subclips = []
    voice_files = []

    badge_list = [
        _asset_path("gifs_badges", "live_breaking_badge.gif"),
        _asset_path("gifs_badges", "live_market_badge.gif"),
        _asset_path("gifs_badges", "trending_fire_badge.gif"),
    ]
    badge_list = [b for b in badge_list if b]

    for sc in scene_audio_info:
        idx = sc["index"]
        v_path = sc["audio_path"]
        dur = max(1.5, float(sc["duration"]))
        query = sc.get("visual_query", "technology")
        narration = sc.get("narration", "")
        voice_files.append(v_path)

        cut_target = 4.5 if not is_shorts else 4.0
        n_cuts = max(1, min(4, int(round(dur / cut_target))))
        cut_dur = dur / n_cuts

        is_market_scene = any(k in (narration + " " + query).lower() for k in ("stock", "market", "candle", "nasdaq", "s&p", "rally", "crash", "drop", "nvda", "price", "earnings"))
        bearish_flag = any(w in (narration + " " + query).lower() for w in ("drop", "crash", "fall", "bear", "plunge", "down", "loss"))

        for c_i in range(n_cuts):
            sub_mp4 = os.path.join(work_dir, f"sub_{idx:03d}_{c_i:02d}.mp4")
            src_clip = None

            if is_market_scene and c_i == 0:
                chart_mp4 = os.path.join(work_dir, f"chart_{idx:03d}.mp4")
                try:
                    render_animated_candlestick_clip(
                        chart_mp4,
                        width=width,
                        height=height,
                        duration=cut_dur,
                        symbol="NVDA" if "nvda" in narration.lower() else "SPY",
                        bearish_bias=bearish_flag,
                    )
                    src_clip = chart_mp4
                except Exception:
                    src_clip = None

            if not src_clip:
                q_variant = query if c_i == 0 else f"{query} modern"
                broll_dl = os.path.join(work_dir, f"raw_{idx:03d}_{c_i:02d}.mp4")
                src_clip = fetch_broll_clip(q_variant, broll_dl, used_urls=used_urls, is_shorts=is_shorts)

            overlay_png = None
            if c_i == 1 and dur >= 6.0 and (idx % 3 == 0):
                card_p = os.path.join(work_dir, f"card_{idx:03d}.png")
                acc = "red" if bearish_flag else ("green" if is_market_scene else "gold")
                _create_motion_card_png(card_p, width, height, query, narration, card_type="stat" if is_market_scene else "news", accent=acc)
                overlay_png = card_p

            gif_pick = badge_list[(idx + c_i) % len(badge_list)] if (badge_list and c_i == 0 and idx % 4 == 0) else None
            _render_subclip(src_clip, cut_dur, sub_mp4, width, height, is_shorts, rng, overlay_png=overlay_png, gif_path=gif_pick)
            subclips.append(sub_mp4)

    concat_list_txt = os.path.join(work_dir, "visual_concat.txt")
    with open(concat_list_txt, "w", encoding="utf-8") as f:
        for sp in subclips:
            f.write(f"file '{sp.replace(os.sep, '/')}'\n")

    raw_video = os.path.join(work_dir, "visual_merged.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_txt, "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", raw_video],
        capture_output=True,
        check=True,
    )

    voice_list_txt = os.path.join(work_dir, "voice_concat.txt")
    with open(voice_list_txt, "w", encoding="utf-8") as f:
        for vp in voice_files:
            f.write(f"file '{vp.replace(os.sep, '/')}'\n")

    voice_merged = os.path.join(work_dir, "voice_merged.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", voice_list_txt, "-c:a", "libmp3lame", "-q:a", "3", voice_merged],
        capture_output=True,
        check=True,
    )

    total_dur = sum(float(x["duration"]) for x in scene_audio_info)
    master_wav = os.path.join(work_dir, "audio_master.wav")
    _master_voice_and_music(voice_merged, total_dur, mode, is_shorts, work_dir, master_wav)

    combined_mp4 = os.path.join(work_dir, "video_with_audio.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-i", raw_video, "-i", master_wav, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", combined_mp4],
        capture_output=True,
        check=True,
    )

    _burn_subtitles(combined_mp4, srt_path, output_video_path, is_shorts)
    return output_video_path
