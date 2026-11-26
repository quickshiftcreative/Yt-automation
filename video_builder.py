import glob
import os
import random
import subprocess
from PIL import Image, ImageDraw, ImageFont
from config import CHANNEL_NAME
from chart_animator import render_animated_candlestick_clip
from media_fetcher import (
    fetch_article_image,
    fetch_broll_clip,
    fetch_freesound_music,
    fetch_freesound_sfx,
    fetch_giphy_sticker,
    fetch_stock_image,
)


def _repo_root():
    return os.path.dirname(os.path.abspath(__file__))


def _run_ffmpeg(cmd):
    try:
        subprocess.run(cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        err_msg = (e.stderr or b"").decode("utf-8", errors="ignore")[-900:]
        print(f"[FFmpeg Error] {err_msg}")
        raise


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
            candidates.extend(
                sorted(glob.glob(os.path.join(folder, "*.wav")) + glob.glob(os.path.join(folder, "*.mp3")))
            )
    return list(dict.fromkeys(candidates))


def _pick_sfx_by_keywords(all_files, keywords, rng):
    if not all_files:
        return None
    matched = [f for f in all_files if any(k in os.path.basename(f).lower() for k in keywords)]
    if matched:
        return rng.choice(matched)
    return rng.choice(all_files)


def _pick_local_music_fallback(music_direction, mode, is_shorts, rng):
    root = _repo_root()
    files = []
    for m_dir in (os.path.join(root, "assets", "music"), os.path.join(root, "assets", "music_beds")):
        if os.path.isdir(m_dir):
            for ext in ("*.mp3", "*.wav", "*.m4a"):
                files.extend(sorted(glob.glob(os.path.join(m_dir, ext))))
    files = list(dict.fromkeys(files))
    if not files:
        return None

    md = music_direction or {}
    wanted_file = str(md.get("track_file", "")).strip().lower()
    mood = str(md.get("mood", "news")).strip().lower()

    if wanted_file and wanted_file != "auto":
        for f in files:
            if os.path.basename(f).lower() == wanted_file:
                return f

    mood_keywords = {
        "tense": ["tense", "dark", "scandal", "suspense", "drama", "risk"],
        "news": ["news", "bulletin", "market", "breaking", "pulse"],
        "energetic": ["energetic", "viral", "gaming", "phonk", "shorts", "hype"],
        "deep_dive": ["deep", "lofi", "ambient", "tech", "ai", "doc"],
        "business": ["business", "corporate", "finance", "luxury", "money"],
        "calm": ["calm", "chill", "lofi", "soft", "ambient"],
    }
    for kw in mood_keywords.get(mood, []):
        for f in files:
            if kw in os.path.basename(f).lower():
                return f
    return rng.choice(files)


def _compute_safe_music_volume(music_direction, is_shorts):
    md = music_direction or {}
    intensity = str(md.get("intensity", "balanced")).strip().lower()
    base_map = {
        "subtle": 0.068,
        "balanced": 0.088,
        "energetic": 0.108,
    }
    vol = base_map.get(intensity, 0.085)

    if "volume_scale" in md:
        try:
            ai_vol = float(md["volume_scale"])
            vol = (vol + ai_vol) / 2.0
        except Exception:
            pass

    if is_shorts:
        vol += 0.012
    return round(max(0.058, min(0.120, vol)), 3)


def _find_font(size):
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


def _draw_centered_text(draw, center_x, y, text, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text((center_x - tw // 2, y), text, fill=fill, font=font)


def _create_outro_card_png(out_png, width, height):
    """Creates a clean dark-gold glassmorphism Outro Card positioned cleanly above captions."""
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    is_vertical = height > width

    box_w = int(width * 0.86) if is_vertical else min(int(width * 0.62), 1080)
    box_h = 370 if is_vertical else 310
    x0 = (width - box_w) // 2
    y0 = int(height * 0.22) if is_vertical else int(height * 0.17)
    x1 = x0 + box_w
    y1 = y0 + box_h
    cx = width // 2

    gold = (250, 204, 21, 255)
    bg = (12, 15, 22, 236)
    white = (248, 250, 252, 255)
    muted = (198, 206, 220, 255)

    draw.rounded_rectangle([x0, y0, x1, y1], radius=28, fill=bg, outline=gold, width=3)
    draw.rounded_rectangle([x0, y0, x1, y0 + 10], radius=6, fill=gold)

    f_title = _find_font(48 if is_vertical else 52)
    f_sub = _find_font(28 if is_vertical else 30)
    f_pill = _find_font(24 if is_vertical else 26)

    _draw_centered_text(draw, cx, y0 + 38, "THANK YOU FOR WATCHING", f_title, white)
    _draw_centered_text(draw, cx, y0 + 112, (CHANNEL_NAME or "Quick Shift Creative").upper(), f_sub, gold)

    # Three clean CTA pills: LIKE | SHARE | SUBSCRIBE
    pills = ["LIKE", "SHARE", "SUBSCRIBE"]
    pill_w = 215 if is_vertical else 240
    pill_h = 62
    gap = 24
    total_pw = len(pills) * pill_w + (len(pills) - 1) * gap
    px = cx - total_pw // 2
    py = y0 + (190 if is_vertical else 178)

    for idx_p, lbl in enumerate(pills):
        is_sub = (idx_p == 2)
        p_fill = gold if is_sub else (28, 34, 48, 245)
        p_txt = (10, 12, 16, 255) if is_sub else white
        p_out = gold if not is_sub else (255, 235, 130, 255)
        draw.rounded_rectangle([px, py, px + pill_w, py + pill_h], radius=16, fill=p_fill, outline=p_out, width=2)
        _draw_centered_text(draw, px + pill_w // 2, py + 16, lbl, f_pill, p_txt)
        px += pill_w + gap

    _draw_centered_text(draw, cx, y1 - 56, "See you in the next update", _find_font(22), muted)

    canvas.save(out_png, "PNG")
    return out_png


def _create_newsroom_highlight_card(out_png, width, height, badge_text, headline_text, thumb_img_path=None, accent="gold"):
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    palette = {
        "gold":  ((250, 204, 21, 255), (14, 17, 23, 236)),
        "green": ((34, 211, 138, 255), (11, 20, 18, 236)),
        "red":   ((244, 63, 94, 255),  (22, 11, 15, 238)),
    }
    acc_col, bg_col = palette.get(accent, palette["gold"])
    is_vertical = height > width

    box_w = int(width * 0.88) if is_vertical else min(int(width * 0.72), 1120)
    box_h = 330 if is_vertical else 255
    x0 = (width - box_w) // 2
    y0 = int(height * 0.13) if is_vertical else int(height * 0.12)
    x1 = x0 + box_w
    y1 = y0 + box_h

    draw.rounded_rectangle([x0, y0, x1, y1], radius=24, fill=bg_col, outline=(255, 255, 255, 45), width=2)
    draw.rounded_rectangle([x0, y0, x1, y0 + 10], radius=6, fill=acc_col)

    txt_left = x0 + 34
    if thumb_img_path and os.path.exists(thumb_img_path) and not is_vertical:
        try:
            with Image.open(thumb_img_path) as im:
                im = im.convert("RGB")
                tw, th = 280, box_h - 54
                im_ratio = im.width / max(1, im.height)
                tgt_ratio = tw / th
                if im_ratio > tgt_ratio:
                    new_w = int(im.height * tgt_ratio)
                    left = (im.width - new_w) // 2
                    im = im.crop((left, 0, left + new_w, im.height))
                else:
                    new_h = int(im.width / tgt_ratio)
                    top = (im.height - new_h) // 2
                    im = im.crop((0, top, im.width, top + new_h))
                im = im.resize((tw, th), Image.Resampling.LANCZOS)
                mask = Image.new("L", (tw, th), 0)
                ImageDraw.Draw(mask).rounded_rectangle([0, 0, tw, th], radius=16, fill=255)
                canvas.paste(im, (x0 + 26, y0 + 30), mask)
                txt_left = x0 + tw + 52
        except Exception:
            pass

    f_badge = _find_font(22)
    f_head = _find_font(40 if not is_vertical else 38)

    pill_lbl = (badge_text or "NEWSROOM BRIEF").upper()[:24]
    draw.rounded_rectangle([txt_left, y0 + 28, txt_left + 260, y0 + 64], radius=10, fill=acc_col)
    draw.text((txt_left + 14, y0 + 34), pill_lbl, fill=(10, 12, 16, 255), font=f_badge)

    words = (headline_text or "Market Update").split()
    max_chars = 26 if not is_vertical else 24
    lines, cur = [], []
    for w in words:
        if len(" ".join(cur + [w])) <= max_chars:
            cur.append(w)
        else:
            if cur:
                lines.append(" ".join(cur))
            cur = [w]
        if len(lines) >= 2:
            break
    if cur and len(lines) < 2:
        lines.append(" ".join(cur))

    y_txt = y0 + 88
    for idx_l, ln in enumerate(lines[:2]):
        if idx_l == 1 or len(lines) == 1:
            bbox = draw.textbbox((txt_left, y_txt), ln, font=f_head)
            pad_x, pad_y = 10, 6
            draw.rounded_rectangle(
                [bbox[0] - pad_x, bbox[1] - pad_y, bbox[2] + pad_x, bbox[3] + pad_y],
                radius=8,
                fill=(250, 204, 21, 240),
            )
            draw.text((txt_left, y_txt), ln, fill=(10, 12, 16, 255), font=f_head)
        else:
            draw.text((txt_left, y_txt), ln, fill=(246, 248, 252, 255), font=f_head)
        y_txt += 58

    canvas.save(out_png, "PNG")
    return out_png


def _detect_ticker_symbol(text):
    low = (text or "").lower()
    mapping = [
        (("nvidia", "nvda", "jensen huang", "blackwell", "cuda"), "NVDA"),
        (("intel", "intc"), "INTC"),
        (("alphabet", "google", "googl"), "GOOGL"),
        (("apple", "iphone", "aapl"), "AAPL"),
        (("amazon", "aws", "amzn"), "AMZN"),
        (("microsoft", "msft"), "MSFT"),
        (("tesla", "tsla"), "TSLA"),
        (("amd", "ryzen"), "AMD"),
        (("meta", "zuckerberg"), "META"),
    ]
    for keys, sym in mapping:
        if any(k in low for k in keys):
            return sym
    return "SPY"


def _render_subclip(
    src_media,
    is_image,
    dur,
    out_mp4,
    width,
    height,
    is_shorts,
    rng,
    overlay_png=None,
    gif_path=None,
    is_chart=False,
):
    os.makedirs(os.path.dirname(out_mp4), exist_ok=True)
    fps = 24
    n_frames = max(12, int(round(dur * fps)))

    inp_args = []
    filter_chain = []

    if src_media and os.path.exists(src_media):
        if is_image:
            scale_w = int(width * 1.12)
            scale_h = int(height * 1.12)
            scale_w += scale_w % 2
            scale_h += scale_h % 2
            zoom_end = 1.09
            inp_args.extend(["-loop", "1", "-t", f"{dur:.3f}", "-i", src_media])
            vf_parts = [
                f"scale={scale_w}:{scale_h}:force_original_aspect_ratio=increase",
                f"crop={scale_w}:{scale_h}",
                f"zoompan=z='min({zoom_end}, 1.0+({zoom_end}-1.0)*on/{max(1,n_frames)})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n_frames}:s={width}x{height}:fps={fps}",
                "setsar=1",
                "eq=contrast=1.07:brightness=-0.03:saturation=1.06",
                "vignette=PI/7",
            ]
        else:
            if is_chart:
                inp_args.extend(["-i", src_media])
                vf_parts = [
                    f"scale={width}:{height}:force_original_aspect_ratio=increase",
                    f"crop={width}:{height}",
                    f"fps={fps}",
                    "setsar=1",
                ]
            else:
                inp_args.extend(["-stream_loop", "-1", "-i", src_media])
                vf_parts = [
                    "trim=start=0.4",
                    "setpts=PTS-STARTPTS",
                    f"scale={width}:{height}:force_original_aspect_ratio=increase",
                    f"crop={width}:{height}",
                    f"fps={fps}",
                    "setsar=1",
                    "eq=contrast=1.07:brightness=-0.03:saturation=1.06",
                    "vignette=PI/7",
                ]
        filter_chain.append(f"[0:v]{','.join(vf_parts)}[base]")
        next_inp = 1
    else:
        filter_chain.append(f"color=c=0x0b0e14:s={width}x{height}:r={fps}:d={dur:.2f}[base]")
        next_inp = 0

    cur_label = "[base]"

    if overlay_png and os.path.exists(overlay_png):
        inp_args.extend(["-i", overlay_png])
        filter_chain.append(f"{cur_label}[{next_inp}:v]overlay=0:0:shortest=1[ov1]")
        cur_label = "[ov1]"
        next_inp += 1

    if gif_path and os.path.exists(gif_path):
        inp_args.extend(["-ignore_loop", "0", "-i", gif_path])
        gw = 220 if not is_shorts else 200
        gx = width - gw - 36
        gy = 36 if not is_shorts else 120
        filter_chain.append(f"[{next_inp}:v]scale={gw}:-1:flags=lanczos,format=rgba[gf]")
        filter_chain.append(f"{cur_label}[gf]overlay={gx}:{gy}:shortest=1[ov2]")
        cur_label = "[ov2]"
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
    _run_ffmpeg(cmd)
    return out_mp4


def _append_sfx_layer(inputs, parts, cur_v, idx, sfx_path, hit_times_ms, max_dur, vol, tag_prefix):
    if not sfx_path or not os.path.exists(sfx_path) or not hit_times_ms:
        return cur_v, idx

    hits = sorted(set(hit_times_ms))[:28]
    inputs.extend(["-i", sfx_path])
    s_idx = idx
    idx += 1

    if len(hits) == 1:
        parts.append(
            f"[{s_idx}:a]atrim=0:{max_dur:.2f},aresample=44100,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"volume={vol:.3f},adelay={hits[0]}|{hits[0]}[{tag_prefix}_trk]"
        )
    else:
        split_outs = "".join(f"[{tag_prefix}s{k}]" for k in range(len(hits)))
        parts.append(
            f"[{s_idx}:a]atrim=0:{max_dur:.2f},aresample=44100,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"volume={vol:.3f},asplit={len(hits)}{split_outs}"
        )
        d_labels = []
        for k, d_ms in enumerate(hits):
            parts.append(f"[{tag_prefix}s{k}]adelay={d_ms}|{d_ms}[{tag_prefix}d{k}]")
            d_labels.append(f"[{tag_prefix}d{k}]")
        parts.append(
            f"{''.join(d_labels)}amix=inputs={len(d_labels)}:duration=longest:normalize=0[{tag_prefix}_trk]"
        )

    out_tag = f"mix_{tag_prefix}"
    parts.append(f"{cur_v}[{tag_prefix}_trk]amix=inputs=2:duration=first:normalize=0[{out_tag}]")
    return f"[{out_tag}]", idx


def _master_voice_and_music(
    voice_concat_mp3,
    total_dur,
    mode,
    is_shorts,
    work_dir,
    out_audio_wav,
    music_direction=None,
    sfx_events=None,
):
    rng = random.Random(404)

    v_filt = (
        "highpass=f=80,lowpass=f=15000,"
        "equalizer=f=160:width_type=o:width=1.4:g=2.2,"
        "equalizer=f=3000:width_type=o:width=1.2:g=2.0,"
        "acompressor=threshold=-18dB:ratio=2.8:attack=12:release=140:makeup=1.8,"
        "loudnorm=I=-15:TP=-1.5:LRA=9"
    )
    v_master = os.path.join(work_dir, "voice_mastered.wav")
    _run_ffmpeg(["ffmpeg", "-y", "-i", voice_concat_mp3, "-af", v_filt, "-ar", "44100", "-ac", "2", v_master])

    md = music_direction or {}
    music_file = fetch_freesound_music(
        md.get("music_query", "ambient technology electronic loop"),
        os.path.join(work_dir, "fs_bgm.mp3"),
    )
    if not music_file:
        music_file = _pick_local_music_fallback(md, mode, is_shorts, rng)

    music_vol = _compute_safe_music_volume(md, is_shorts)
    if music_file:
        print(
            f"[MusicAI] Active BGM: {os.path.basename(music_file)} | Mood: {md.get('mood', 'auto')} | "
            f"Intensity: {md.get('intensity', 'balanced')} | SafeVol: {music_vol}"
        )

    sfx_pool = _all_sfx_files()
    sfx_whoosh = fetch_freesound_sfx("soft whoosh transition", os.path.join(work_dir, "fs_whoosh.mp3"))
    if not sfx_whoosh:
        sfx_whoosh = _pick_sfx_by_keywords(sfx_pool, ["whoosh", "swipe", "glitch"], rng)

    sfx_pop = fetch_freesound_sfx("subtle ui pop click", os.path.join(work_dir, "fs_pop.mp3"))
    if not sfx_pop:
        sfx_pop = _pick_sfx_by_keywords(sfx_pool, ["pop", "click", "chime", "alert"], rng)

    sfx_impact = fetch_freesound_sfx("low cinematic thud boom", os.path.join(work_dir, "fs_impact.mp3"))
    if not sfx_impact:
        sfx_impact = _pick_sfx_by_keywords(sfx_pool, ["boom", "impact", "market", "riser"], rng)

    inputs = ["-i", v_master]
    idx = 1
    parts = ["[0:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[vnorm]"]
    cur_v = "[vnorm]"

    if music_file and os.path.exists(music_file):
        m_norm = os.path.join(work_dir, "music_norm.wav")
        _run_ffmpeg([
            "ffmpeg", "-y", "-stream_loop", "-1", "-i", music_file,
            "-t", f"{total_dur + 1.0:.2f}",
            "-af", "highpass=f=45,lowpass=f=12000,loudnorm=I=-24:TP=-2:LRA=11",
            "-ar", "44100", "-ac", "2",
            m_norm,
        ])
        inputs.extend(["-i", m_norm])
        fade_out_d = 2.0 if not is_shorts else 1.6
        fade_out_st = max(0.5, total_dur - fade_out_d)
        parts.append(f"{cur_v}asplit=2[v_for_mix][v_for_sc]")
        parts.append(
            f"[{idx}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=0:{total_dur:.2f},afade=t=in:st=0:d=0.8,afade=t=out:st={fade_out_st:.2f}:d={fade_out_d:.2f},"
            f"volume={music_vol:.3f}[mbase]"
        )
        parts.append("[mbase][v_for_sc]sidechaincompress=threshold=0.025:ratio=6:attack=15:release=280[mduck]")
        parts.append("[v_for_mix][mduck]amix=inputs=2:duration=first:normalize=0[vmix]")
        cur_v = "[vmix]"
        idx += 1

    events = sfx_events or {}
    cur_v, idx = _append_sfx_layer(inputs, parts, cur_v, idx, sfx_whoosh, events.get("whoosh", []), 0.9, 0.14, "wh")
    cur_v, idx = _append_sfx_layer(inputs, parts, cur_v, idx, sfx_pop, events.get("pop", []), 0.6, 0.18, "pp")
    cur_v, idx = _append_sfx_layer(inputs, parts, cur_v, idx, sfx_impact, events.get("impact", []), 1.2, 0.20, "im")

    # Gentle final audio fade-out over the last 1.0s so audio never ends abruptly
    final_afade_st = max(0.5, total_dur - 1.0)
    parts.append(f"{cur_v}alimiter=limit=0.95,afade=t=out:st={final_afade_st:.2f}:d=1.0[am_final]")

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", ";".join(parts),
        "-map", "[am_final]",
        "-t", f"{total_dur:.3f}",
        out_audio_wav,
    ]
    _run_ffmpeg(cmd)
    return out_audio_wav


def _burn_subtitles_and_fade(video_mp4, subtitle_path, out_mp4, is_shorts, total_dur):
    """Burns pop captions and applies a smooth 1.2s fade-to-black at the end of every video."""
    fade_d = 1.2
    fade_st = max(0.2, float(total_dur) - fade_d)
    fade_filter = f"fade=t=out:st={fade_st:.2f}:d={fade_d:.2f}"

    if not subtitle_path or not os.path.exists(subtitle_path) or os.path.getsize(subtitle_path) == 0:
        vf_chain = fade_filter
    else:
        escaped = os.path.abspath(subtitle_path).replace("\\", "/").replace(":", "\\:")
        if subtitle_path.lower().endswith(".ass"):
            vf_chain = f"ass='{escaped}',{fade_filter}"
        else:
            font_size = 18 if is_shorts else 20
            margin_v = 150 if is_shorts else 58
            style = (
                f"FontName=DejaVu Sans,FontSize={font_size},Bold=1,"
                f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00080A0E,BackColour=&H88000000,"
                f"BorderStyle=3,Outline=2,Shadow=1,MarginV={margin_v}"
            )
            vf_chain = f"subtitles='{escaped}':force_style='{style}',{fade_filter}"

    cmd = [
        "ffmpeg", "-y",
        "-i", video_mp4,
        "-vf", vf_chain,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        out_mp4,
    ]
    _run_ffmpeg(cmd)
    return out_mp4


def _gif_query_for_scene(narration, mode, bearish_flag, is_market):
    low = narration.lower()
    if bearish_flag:
        return "stock market crash"
    if is_market:
        return "stonks chart up"
    if any(w in low for w in ("ai", "artificial intelligence", "robot", "model", "gpu")):
        return "artificial intelligence"
    if any(w in low for w in ("game", "gaming", "gta", "playstation", "xbox", "steam")):
        return "gaming controller"
    if mode == "trending_viral":
        return "mind blown reaction"
    return "breaking news"


def build_final_video(
    scene_audio_info,
    subtitle_path,
    work_dir,
    output_video_path,
    music_direction=None,
    chosen_topic="",
):
    os.makedirs(os.path.dirname(output_video_path), exist_ok=True)
    is_shorts = os.getenv("VIDEO_FORMAT", "horizontal").strip().lower() == "shorts"
    mode = os.getenv("CONTENT_MODE", "news_bulletin").strip().lower()
    width, height = (1080, 1920) if is_shorts else (1920, 1080)
    orient = "portrait" if is_shorts else "landscape"

    rng = random.Random(2026)
    used_urls = set()
    subclips = []
    voice_files = []
    sfx_events = {"whoosh": [], "pop": [], "impact": []}

    article_thumb = None
    if chosen_topic:
        art_dl = os.path.join(work_dir, "article_hero.jpg")
        article_thumb = fetch_article_image(chosen_topic, art_dl)

    outro_card_png = os.path.join(work_dir, "outro_card.png")
    _create_outro_card_png(outro_card_png, width, height)

    total_scenes = len(scene_audio_info)
    timeline_t = 0.0

    for pos, sc in enumerate(scene_audio_info):
        idx = sc["index"]
        is_last_scene = (pos == total_scenes - 1)
        v_path = sc["audio_path"]
        dur = max(1.5, float(sc["duration"]))
        query = sc.get("visual_query", "technology")
        narration = sc.get("narration", "")
        highlight_text = sc.get("highlight_text", "") or narration
        voice_files.append(v_path)

        if idx == 0:
            n_cuts = max(2, min(5, int(round(dur / 1.8))))
        elif is_last_scene:
            # Keep the outro steady (1-2 clean shots so the Outro Card stays readable)
            n_cuts = 1 if dur <= 7.5 else 2
        else:
            cut_target = 3.6 if is_shorts else 4.3
            n_cuts = max(1, min(4, int(round(dur / cut_target))))
        cut_dur = dur / n_cuts

        if idx > 0 and (idx % 2 == 1 or is_shorts or is_last_scene):
            sfx_events["whoosh"].append(int(timeline_t * 1000))

        combined_text = narration + " " + query
        is_market_scene = any(
            k in combined_text.lower()
            for k in ("stock", "market", "candle", "nasdaq", "s&p", "rally", "crash", "drop", "nvda", "nvidia", "price", "earnings", "portfolio", "margin")
        )
        bearish_flag = any(
            w in combined_text.lower()
            for w in ("drop", "crash", "fall", "bear", "plunge", "down", "loss", "scandal", "pullback", "risk")
        )

        for c_i in range(n_cuts):
            sub_mp4 = os.path.join(work_dir, f"sub_{idx:03d}_{c_i:02d}.mp4")
            is_final_subclip = (is_last_scene and c_i == n_cuts - 1)
            src_media = None
            is_img = False
            is_chart = False

            if is_market_scene and c_i == 0 and not is_last_scene and (idx % 3 == 0):
                chart_mp4 = os.path.join(work_dir, f"chart_{idx:03d}.mp4")
                try:
                    render_animated_candlestick_clip(
                        chart_mp4,
                        width=width,
                        height=height,
                        duration=cut_dur,
                        symbol=_detect_ticker_symbol(combined_text),
                        bearish_bias=bearish_flag,
                    )
                    src_media = chart_mp4
                    is_img = False
                    is_chart = True
                    sfx_events["impact"].append(int(timeline_t * 1000))
                except Exception:
                    src_media = None

            if not src_media:
                if c_i % 2 == 1 or is_final_subclip:
                    photo_dl = os.path.join(work_dir, f"photo_{idx:03d}_{c_i:02d}.jpg")
                    src_media = fetch_stock_image(query, photo_dl, orientation=orient, used_urls=used_urls)
                    is_img = True
                else:
                    q_variant = query if c_i == 0 else f"{query} modern"
                    broll_dl = os.path.join(work_dir, f"raw_{idx:03d}_{c_i:02d}.mp4")
                    src_media = fetch_broll_clip(q_variant, broll_dl, used_urls=used_urls, is_shorts=is_shorts)
                    is_img = False
                    if not src_media:
                        photo_dl = os.path.join(work_dir, f"photo_fb_{idx:03d}_{c_i:02d}.jpg")
                        src_media = fetch_stock_image(query, photo_dl, orientation=orient, used_urls=used_urls)
                        is_img = True

            overlay_png = None
            if is_final_subclip:
                overlay_png = outro_card_png
                sfx_events["pop"].append(int(timeline_t * 1000))
            elif (idx == 0 and c_i == 0) or (c_i == 1 and dur >= 5.5 and not is_last_scene and (idx % 3 == 0)):
                card_p = os.path.join(work_dir, f"card_{idx:03d}_{c_i:02d}.png")
                acc = "red" if bearish_flag else ("green" if is_market_scene else "gold")
                badge = "BREAKING HOOK" if idx == 0 else ("MARKET DATA" if is_market_scene else "NEWSROOM BRIEF")
                card_thumb = article_thumb if (idx == 0 and article_thumb) else (src_media if is_img else article_thumb)
                _create_newsroom_highlight_card(
                    card_p,
                    width,
                    height,
                    badge,
                    highlight_text,
                    thumb_img_path=card_thumb,
                    accent=acc,
                )
                overlay_png = card_p
                sfx_events["pop"].append(int(timeline_t * 1000))

            gif_pick = None
            if not overlay_png and not is_last_scene and c_i == 0 and idx > 0 and (idx % 5 == 2):
                g_q = _gif_query_for_scene(narration, mode, bearish_flag, is_market_scene)
                gif_dl = os.path.join(work_dir, f"giphy_{idx:03d}.gif")
                gif_pick = fetch_giphy_sticker(g_q, gif_dl)

            _render_subclip(
                src_media,
                is_img,
                cut_dur,
                sub_mp4,
                width,
                height,
                is_shorts,
                rng,
                overlay_png=overlay_png,
                gif_path=gif_pick,
                is_chart=is_chart,
            )
            subclips.append(sub_mp4)
            timeline_t += cut_dur

    concat_list_txt = os.path.join(work_dir, "visual_concat.txt")
    with open(concat_list_txt, "w", encoding="utf-8") as f:
        for sp in subclips:
            abs_sp = os.path.abspath(sp).replace(os.sep, "/")
            f.write(f"file '{abs_sp}'\n")

    raw_video = os.path.join(work_dir, "visual_merged.mp4")
    _run_ffmpeg([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list_txt,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
        raw_video,
    ])

    voice_list_txt = os.path.join(work_dir, "voice_concat.txt")
    with open(voice_list_txt, "w", encoding="utf-8") as f:
        for vp in voice_files:
            abs_vp = os.path.abspath(vp).replace(os.sep, "/")
            f.write(f"file '{abs_vp}'\n")

    voice_merged = os.path.join(work_dir, "voice_merged.mp3")
    _run_ffmpeg(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", voice_list_txt, "-c:a", "libmp3lame", "-q:a", "3", voice_merged])

    total_dur = sum(float(x["duration"]) for x in scene_audio_info)
    master_wav = os.path.join(work_dir, "audio_master.wav")
    _master_voice_and_music(
        voice_merged,
        total_dur,
        mode,
        is_shorts,
        work_dir,
        master_wav,
        music_direction=music_direction,
        sfx_events=sfx_events,
    )

    combined_mp4 = os.path.join(work_dir, "video_with_audio.mp4")
    _run_ffmpeg([
        "ffmpeg", "-y", "-i", raw_video, "-i", master_wav,
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
        combined_mp4,
    ])

    _burn_subtitles_and_fade(combined_mp4, subtitle_path, output_video_path, is_shorts, total_dur)
    return output_video_path
