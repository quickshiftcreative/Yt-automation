import glob
import os
import random
import subprocess
from PIL import Image, ImageDraw, ImageFont
from config import CHANNEL_NAME
from chart_animator import (
    render_animated_candlestick_clip,
    render_entity_spotlight_clip,
    render_kpi_counter_clip,
)
from media_fetcher import (
    fetch_article_image,
    fetch_broll_clip,
    fetch_freesound_music,
    fetch_freesound_sfx,
    fetch_stock_image,
    fetch_wikimedia_entity_image,
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


def _probe_duration(media_path):
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                media_path,
            ],
            text=True,
        ).strip()
        return float(out)
    except Exception:
        return 0.0


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
    base_map = {"subtle": 0.068, "balanced": 0.088, "energetic": 0.108}
    vol = base_map.get(intensity, 0.085)
    if "volume_scale" in md:
        try:
            vol = (vol + float(md["volume_scale"])) / 2.0
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


def _create_progress_bar_png(out_png, width, bar_h=10):
    img = Image.new("RGBA", (width, bar_h), (250, 204, 21, 245))
    img.save(out_png, "PNG")
    return out_png


def _create_brand_watermark_png(out_png, width, height):
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    lbl = (CHANNEL_NAME or "QUICK SHIFT CREATIVE").upper()
    f = _find_font(20 if height > width else 22)
    bbox = draw.textbbox((0, 0), lbl, font=f)
    tw = bbox[2] - bbox[0]
    x = width - tw - 34
    y = 32 if height > width else 24
    draw.text((x + 2, y + 2), lbl, font=f, fill=(0, 0, 0, 85))
    draw.text((x, y), lbl, font=f, fill=(255, 255, 255, 95))
    canvas.save(out_png, "PNG")
    return out_png


def _create_editorial_tag_png(out_png, width, height, tag_text):
    """Sleek Premiere-Pro style top-left editorial context badge (zero clutter, human documentary feel)."""
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    lbl = str(tag_text or "").strip().upper()[:24]
    if not lbl:
        return None
    f = _find_font(22 if height > width else 24)
    bbox = draw.textbbox((0, 0), lbl, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x0 = 36 if height > width else 46
    y0 = 110 if height > width else 42
    pad_x, pad_y = 20, 12

    draw.rounded_rectangle(
        [x0, y0, x0 + tw + pad_x * 2 + 12, y0 + th + pad_y * 2],
        radius=12,
        fill=(10, 14, 22, 215),
        outline=(255, 255, 255, 45),
        width=2,
    )
    draw.rounded_rectangle(
        [x0, y0, x0 + 9, y0 + th + pad_y * 2],
        radius=4,
        fill=(250, 204, 21, 255),
    )
    draw.text((x0 + pad_x + 6, y0 + pad_y - 1), lbl, font=f, fill=(246, 248, 252, 255))
    canvas.save(out_png, "PNG")
    return out_png


def _create_countdown_card_png(out_png, width, height, prompt_text):
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    is_vertical = height > width
    cx = width // 2

    box_w = int(width * 0.86) if is_vertical else min(int(width * 0.60), 960)
    box_h = 250 if is_vertical else 220
    x0 = (width - box_w) // 2
    y0 = int(height * 0.15) if is_vertical else int(height * 0.14)
    x1, y1 = x0 + box_w, y0 + box_h

    gold = (250, 204, 21, 255)
    bg = (14, 17, 24, 238)
    white = (248, 250, 252, 255)

    draw.rounded_rectangle([x0, y0, x1, y1], radius=24, fill=bg, outline=gold, width=3)
    draw.rounded_rectangle([cx - 180, y0 + 22, cx + 180, y0 + 62], radius=12, fill=gold)
    _draw_centered_text(draw, cx, y0 + 29, "QUICK GUESS • 2 SECONDS", _find_font(22), (10, 12, 16, 255))

    txt = (prompt_text or "What do you think happens next?")[:46]
    _draw_centered_text(draw, cx, y0 + 96, txt, _find_font(34 if is_vertical else 38), white)
    _draw_centered_text(draw, cx, y1 - 54, "Drop your guess before the reveal...", _find_font(22), gold)
    canvas.save(out_png, "PNG")
    return out_png


def _create_debate_card_png(out_png, width, height, debate_card):
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    is_vertical = height > width
    cx = width // 2

    dc = debate_card or {}
    opt_a = str(dc.get("option_a", "REAL SHIFT")).upper()[:20]
    opt_b = str(dc.get("option_b", "PURE HYPE")).upper()[:20]
    q_lbl = str(dc.get("question", "COMMENT 1 OR 2 BELOW")).upper()[:30]

    box_w = int(width * 0.88) if is_vertical else min(int(width * 0.68), 1060)
    box_h = 285 if is_vertical else 245
    x0 = (width - box_w) // 2
    y0 = int(height * 0.14) if is_vertical else int(height * 0.13)
    x1, y1 = x0 + box_w, y0 + box_h

    bg = (12, 15, 22, 238)
    gold = (250, 204, 21, 255)
    green = (34, 211, 138, 255)
    red = (244, 63, 94, 255)
    white = (248, 250, 252, 255)

    draw.rounded_rectangle([x0, y0, x1, y1], radius=24, fill=bg, outline=(255, 255, 255, 55), width=2)
    _draw_centered_text(draw, cx, y0 + 20, "PICK YOUR SIDE", _find_font(24), gold)

    half_w = (box_w - 96) // 2
    py0 = y0 + 68
    py1 = y0 + (186 if is_vertical else 166)
    draw.rounded_rectangle([x0 + 24, py0, x0 + 24 + half_w, py1], radius=16, fill=(14, 34, 28, 240), outline=green, width=3)
    draw.rounded_rectangle([x1 - 24 - half_w, py0, x1 - 24, py1], radius=16, fill=(38, 16, 22, 240), outline=red, width=3)

    _draw_centered_text(draw, x0 + 24 + half_w // 2, py0 + 18, "1", _find_font(34), green)
    _draw_centered_text(draw, x0 + 24 + half_w // 2, py0 + 64, opt_a, _find_font(24 if is_vertical else 28), white)

    _draw_centered_text(draw, x1 - 24 - half_w // 2, py0 + 18, "2", _find_font(34), red)
    _draw_centered_text(draw, x1 - 24 - half_w // 2, py0 + 64, opt_b, _find_font(24 if is_vertical else 28), white)

    draw.ellipse([cx - 28, (py0 + py1) // 2 - 28, cx + 28, (py0 + py1) // 2 + 28], fill=gold)
    _draw_centered_text(draw, cx, (py0 + py1) // 2 - 14, "VS", _find_font(24), (10, 12, 16, 255))

    _draw_centered_text(draw, cx, y1 - 48, q_lbl, _find_font(24), gold)
    canvas.save(out_png, "PNG")
    return out_png


def _create_outro_card_png(out_png, width, height):
    """
    Properly centered, full-screen dark studio Outro overlay positioned cleanly in the
    upper-middle safe zone (zero collision with captions or YouTube end-screen cards).
    """
    canvas = Image.new("RGBA", (width, height), (6, 9, 16, 175))
    draw = ImageDraw.Draw(canvas)
    is_vertical = height > width
    cx = width // 2

    box_w = int(width * 0.88) if is_vertical else min(int(width * 0.66), 1180)
    box_h = 460 if is_vertical else 390
    x0 = (width - box_w) // 2
    y0 = int(height * 0.24) if is_vertical else int(height * 0.18)
    x1, y1 = x0 + box_w, y0 + box_h

    gold = (250, 204, 21, 255)
    yt_red = (235, 32, 48, 255)
    bg = (12, 16, 24, 245)
    white = (248, 250, 252, 255)
    muted = (190, 200, 218, 255)

    draw.rounded_rectangle([x0 + 8, y0 + 10, x1 + 8, y1 + 10], radius=30, fill=(0, 0, 0, 180))
    draw.rounded_rectangle([x0, y0, x1, y1], radius=30, fill=bg, outline=gold, width=4)
    draw.rounded_rectangle([x0, y0, x1, y0 + 12], radius=6, fill=gold)

    f_title = _find_font(54 if is_vertical else 60)
    f_chan = _find_font(30 if is_vertical else 32)
    f_pill = _find_font(26 if is_vertical else 28)
    f_foot = _find_font(24)

    _draw_centered_text(draw, cx, y0 + 46, "THANK YOU FOR WATCHING", f_title, white)
    _draw_centered_text(draw, cx, y0 + 126, (CHANNEL_NAME or "Quick Shift Creative").upper(), f_chan, gold)

    # Subtle divider line
    draw.line([(x0 + 80, y0 + 178), (x1 - 80, y0 + 178)], fill=(55, 68, 92, 200), width=2)

    # Three crisp CTA buttons: LIKE | SHARE | SUBSCRIBE (YouTube Red)
    pills = [
        ("LIKE", (26, 34, 50, 255), white, gold),
        ("SHARE", (26, 34, 50, 255), white, gold),
        ("SUBSCRIBE", yt_red, white, (255, 160, 170, 255)),
    ]
    pill_w = 240 if is_vertical else 270
    pill_h = 74
    gap = 26
    total_pw = len(pills) * pill_w + (len(pills) - 1) * gap
    px = cx - total_pw // 2
    py = y0 + (222 if is_vertical else 212)

    for lbl, p_fill, p_txt, p_out in pills:
        draw.rounded_rectangle([px, py, px + pill_w, py + pill_h], radius=18, fill=p_fill, outline=p_out, width=3)
        _draw_centered_text(draw, px + pill_w // 2, py + 21, lbl, f_pill, p_txt)
        px += pill_w + gap

    _draw_centered_text(draw, cx, y1 - 68, "Hit the bell so you never miss the next breakdown", f_foot, muted)
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
    x1, y1 = x0 + box_w, y0 + box_h

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


def _detect_ticker_symbol(text, query=""):
    low = f"{text} {query}".lower()
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
        (("nasdaq", "qqq"), "NASDAQ"),
        (("dow", "djia"), "DOW"),
        (("bitcoin", "btc"), "BTC"),
    ]
    for keys, sym in mapping:
        if any(k in low for k in keys):
            return sym
    q_up = str(query or "").strip().upper()
    if 2 <= len(q_up) <= 6 and q_up.isalpha():
        return q_up
    return "S&P 500"


def _render_media_beat(
    src_media,
    is_image,
    dur,
    out_mp4,
    width,
    height,
    overlay_png=None,
    fade_overlay=False,
    is_motion_graphic=False,
):
    os.makedirs(os.path.dirname(out_mp4), exist_ok=True)
    fps = 24
    n_frames = max(10, int(round(dur * fps)))

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
                "eq=contrast=1.06:brightness=-0.02:saturation=1.08",
                "vignette=PI/7",
            ]
        elif is_motion_graphic:
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
                "trim=start=0.30",
                "setpts=PTS-STARTPTS",
                f"scale={width}:{height}:force_original_aspect_ratio=increase",
                f"crop={width}:{height}",
                f"fps={fps}",
                "setsar=1",
                "eq=contrast=1.06:brightness=-0.02:saturation=1.08",
                "vignette=PI/7",
            ]
        filter_chain.append(f"[0:v]{','.join(vf_parts)}[base]")
        next_inp = 1
    else:
        filter_chain.append(f"color=c=0x0b0e14:s={width}x{height}:r={fps}:d={dur:.3f}[base]")
        next_inp = 0

    cur_label = "[base]"

    if overlay_png and os.path.exists(overlay_png):
        inp_args.extend(["-loop", "1", "-t", f"{dur:.3f}", "-i", overlay_png])
        if fade_overlay:
            filter_chain.append(f"[{next_inp}:v]format=rgba,fade=t=in:st=0:d=0.45:alpha=1[ovf]")
            filter_chain.append(f"{cur_label}[ovf]overlay=0:0:shortest=1[ov1]")
        else:
            filter_chain.append(f"{cur_label}[{next_inp}:v]overlay=0:0:shortest=1[ov1]")
        cur_label = "[ov1]"
        next_inp += 1

    final_map = cur_label.strip("[]")
    cmd = [
        "ffmpeg", "-y",
        *inp_args,
        "-filter_complex", ";".join(filter_chain),
        "-map", f"[{final_map}]",
        "-t", f"{dur:.3f}",
        "-r", str(fps),
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

    hits = sorted(set(hit_times_ms))[:32]
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
    music_drops=None,
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

    sfx_tick = fetch_freesound_sfx("clock ticking timer", os.path.join(work_dir, "fs_tick.mp3"))
    if not sfx_tick:
        sfx_tick = sfx_pop

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
        fade_out_d = 2.2 if not is_shorts else 1.8
        fade_out_st = max(0.5, total_dur - fade_out_d)

        drop_filters = ""
        for d0, d1 in (music_drops or [])[:4]:
            if d1 > d0:
                drop_filters += f",volume=0.05:enable='between(t,{d0:.2f},{d1:.2f})'"

        parts.append(f"{cur_v}asplit=2[v_for_mix][v_for_sc]")
        parts.append(
            f"[{idx}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=0:{total_dur:.2f},afade=t=in:st=0:d=0.6,afade=t=out:st={fade_out_st:.2f}:d={fade_out_d:.2f},"
            f"volume={music_vol:.3f}{drop_filters}[mbase]"
        )
        parts.append("[mbase][v_for_sc]sidechaincompress=threshold=0.025:ratio=6:attack=15:release=280[mduck]")
        parts.append("[v_for_mix][mduck]amix=inputs=2:duration=first:normalize=0[vmix]")
        cur_v = "[vmix]"
        idx += 1

    events = sfx_events or {}
    cur_v, idx = _append_sfx_layer(inputs, parts, cur_v, idx, sfx_whoosh, events.get("whoosh", []), 0.85, 0.14, "wh")
    cur_v, idx = _append_sfx_layer(inputs, parts, cur_v, idx, sfx_pop, events.get("pop", []), 0.55, 0.18, "pp")
    cur_v, idx = _append_sfx_layer(inputs, parts, cur_v, idx, sfx_impact, events.get("impact", []), 1.15, 0.22, "im")
    cur_v, idx = _append_sfx_layer(inputs, parts, cur_v, idx, sfx_tick, events.get("tick", []), 1.7, 0.22, "tk")

    final_afade_st = max(0.5, total_dur - 1.2)
    parts.append(f"{cur_v}alimiter=limit=0.95,afade=t=out:st={final_afade_st:.2f}:d=1.2[am_final]")

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


def _burn_subtitles_watermark_and_fade(video_mp4, subtitle_path, out_mp4, is_shorts, total_dur, work_dir):
    width, height = (1080, 1920) if is_shorts else (1920, 1080)
    fade_d = 1.4
    fade_st = max(0.2, float(total_dur) - fade_d)
    fade_chain = f"fade=t=in:st=0:d=0.25,fade=t=out:st={fade_st:.2f}:d={fade_d:.2f}"

    sub_filter = ""
    if subtitle_path and os.path.exists(subtitle_path) and os.path.getsize(subtitle_path) > 0:
        escaped = os.path.abspath(subtitle_path).replace("\\", "/").replace(":", "\\:")
        sub_filter = f"ass='{escaped}'" if subtitle_path.lower().endswith(".ass") else f"subtitles='{escaped}'"

    wm_png = os.path.join(work_dir, "brand_wm.png")
    _create_brand_watermark_png(wm_png, width, height)

    if is_shorts:
        bar_png = os.path.join(work_dir, "progress_bar.png")
        _create_progress_bar_png(bar_png, width, bar_h=10)
        base_chain = f"[0:v]{sub_filter}[vsub]" if sub_filter else "[0:v]null[vsub]"
        fc = (
            f"{base_chain};"
            f"[vsub][1:v]overlay=0:0:shortest=1[vwm];"
            f"[vwm][2:v]overlay=x='-w+(w*t/{max(1.0, total_dur):.2f})':y=0:shortest=1,{fade_chain}[vout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", video_mp4,
            "-loop", "1", "-i", wm_png,
            "-loop", "1", "-i", bar_png,
            "-filter_complex", fc,
            "-map", "[vout]", "-map", "0:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
            out_mp4,
        ]
    else:
        base_chain = f"[0:v]{sub_filter}[vsub]" if sub_filter else "[0:v]null[vsub]"
        fc = f"{base_chain};[vsub][1:v]overlay=0:0:shortest=1,{fade_chain}[vout]"
        cmd = [
            "ffmpeg", "-y",
            "-i", video_mp4,
            "-loop", "1", "-i", wm_png,
            "-filter_complex", fc,
            "-map", "[vout]", "-map", "0:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
            out_mp4,
        ]

    _run_ffmpeg(cmd)
    return out_mp4


def build_final_video(
    beat_audio_info,
    subtitle_path,
    work_dir,
    output_video_path,
    music_direction=None,
    chosen_topic="",
    debate_card=None,
):
    os.makedirs(os.path.dirname(output_video_path), exist_ok=True)
    is_shorts = os.getenv("VIDEO_FORMAT", "horizontal").strip().lower() == "shorts"
    mode = os.getenv("CONTENT_MODE", "news_bulletin").strip().lower()
    width, height = (1080, 1920) if is_shorts else (1920, 1080)
    orient = "portrait" if is_shorts else "landscape"

    used_urls = set()
    entity_cache = {}
    subclips = []
    voice_files = []
    sfx_events = {"whoosh": [], "pop": [], "impact": [], "tick": []}
    music_drops = []

    article_thumb = None
    if chosen_topic:
        art_dl = os.path.join(work_dir, "article_hero.jpg")
        article_thumb = fetch_article_image(chosen_topic, art_dl)

    outro_card_png = os.path.join(work_dir, "outro_card.png")
    _create_outro_card_png(outro_card_png, width, height)

    debate_card_png = os.path.join(work_dir, "debate_card.png")
    _create_debate_card_png(debate_card_png, width, height, debate_card)

    video_cursor = 0.0
    total_beats = len(beat_audio_info)
    print(f"[VideoBuilder] Assembling {total_beats} frame-locked voice-synced beats ({width}x{height})...")

    for pos, bt in enumerate(beat_audio_info):
        v_path = bt["audio_path"]
        start_t = float(bt.get("start_time", video_cursor))
        end_t = float(bt.get("end_time", start_t + float(bt["duration"])))
        # Drift-compensated exact beat duration so visuals stay locked to voice over 10+ minutes
        dur = max(0.6, round(end_t - video_cursor, 3))

        is_final_beat = bool(bt.get("is_final_beat", pos == total_beats - 1))
        itype = str(bt.get("interactive_type", "none")).strip().lower()
        vtype = str(bt.get("visual_type", "stock_video")).strip().lower()
        query = str(bt.get("visual_query", "technology")).strip() or "technology"
        alt_query = str(bt.get("alt_query", "")).strip()
        screen_tag = str(bt.get("screen_tag", "")).strip()
        narration = str(bt.get("narration", ""))
        m_val = str(bt.get("metric_value", "")).strip()
        m_lbl = str(bt.get("metric_label", "")).strip()
        highlight_text = str(bt.get("highlight_text", "") or m_lbl or narration)

        voice_files.append(v_path)
        beat_mp4 = os.path.join(work_dir, f"beat_vis_{pos:03d}.mp4")

        if itype == "music_drop":
            music_drops.append((start_t, min(start_t + 1.8, end_t)))
            sfx_events["impact"].append(int(start_t * 1000))
        if bt.get("countdown_start") is not None:
            sfx_events["tick"].append(int(float(bt["countdown_start"]) * 1000))
        if pos > 0 and (bt.get("is_scene_start") or is_final_beat):
            sfx_events["whoosh"].append(int(start_t * 1000))

        # Optional sleek top-left editorial badge on key B-roll shots
        tag_png = None
        if screen_tag and not is_final_beat and itype == "none" and vtype in ("stock_video", "editorial_photo"):
            tag_p = os.path.join(work_dir, f"etag_{pos:03d}.png")
            tag_png = _create_editorial_tag_png(tag_p, width, height, screen_tag)

        rendered_ok = False
        try:
            # ROUTE 1: Full-Screen Centered Cinematic Outro with Smooth Fade-In
            if is_final_beat:
                bg_img = fetch_stock_image("dark modern studio", os.path.join(work_dir, f"outro_bg_{pos:03d}.jpg"), orientation=orient, used_urls=used_urls)
                _render_media_beat(bg_img, True, dur, beat_mp4, width, height, overlay_png=outro_card_png, fade_overlay=True)
                sfx_events["pop"].append(int(start_t * 1000))
                rendered_ok = True

            # ROUTE 2: Interactive 1 vs 2 Debate Card
            elif itype == "debate":
                bg_img = fetch_stock_image(query, os.path.join(work_dir, f"deb_bg_{pos:03d}.jpg"), orientation=orient, used_urls=used_urls, alt_query=alt_query)
                _render_media_beat(bg_img, True, dur, beat_mp4, width, height, overlay_png=debate_card_png, fade_overlay=True)
                sfx_events["pop"].append(int(start_t * 1000))
                rendered_ok = True

            # ROUTE 3: Interactive 2-Second Countdown Quiz Card
            elif itype == "countdown":
                cd_png = os.path.join(work_dir, f"cd_{pos:03d}.png")
                _create_countdown_card_png(cd_png, width, height, highlight_text)
                bg_img = fetch_stock_image(query, os.path.join(work_dir, f"cd_bg_{pos:03d}.jpg"), orientation=orient, used_urls=used_urls, alt_query=alt_query)
                _render_media_beat(bg_img, True, dur, beat_mp4, width, height, overlay_png=cd_png, fade_overlay=True)
                sfx_events["pop"].append(int(start_t * 1000))
                rendered_ok = True

            # ROUTE 4: Live Animated Candlestick Chart (Only for real market/stock moves)
            elif vtype in ("chart_down", "chart_up"):
                is_bear = (vtype == "chart_down")
                sym = _detect_ticker_symbol(narration, query)
                raw_chart = os.path.join(work_dir, f"raw_chart_{pos:03d}.mp4")
                render_animated_candlestick_clip(
                    raw_chart,
                    width=width,
                    height=height,
                    duration=dur,
                    symbol=sym,
                    bearish_bias=is_bear,
                    change_label=m_val,
                    subtitle=m_lbl,
                )
                _render_media_beat(raw_chart, False, dur, beat_mp4, width, height, is_motion_graphic=True)
                sfx_events["impact"].append(int(start_t * 1000))
                rendered_ok = True

            # ROUTE 5: Animated Rolling KPI Stat Counter
            elif vtype == "kpi_slam":
                is_neg = m_val.startswith("-") or any(w in narration.lower() for w in ("lost", "drop", "crash", "fell", "loss"))
                acc = "red" if is_neg else ("green" if "$" in m_val else "gold")
                raw_kpi = os.path.join(work_dir, f"raw_kpi_{pos:03d}.mp4")
                render_kpi_counter_clip(
                    raw_kpi,
                    width=width,
                    height=height,
                    duration=dur,
                    value_text=m_val or "100%",
                    label_text=m_lbl or highlight_text[:30],
                    accent=acc,
                )
                _render_media_beat(raw_kpi, False, dur, beat_mp4, width, height, is_motion_graphic=True)
                sfx_events["impact"].append(int(start_t * 1000))
                rendered_ok = True

            # ROUTE 6: Real Entity Spotlight (Wikimedia / News Photo of Person, Company, Product, Game)
            elif vtype == "entity_photo":
                ent_key = query.lower()
                ent_img = entity_cache.get(ent_key)
                if not ent_img or not os.path.exists(ent_img):
                    ent_dl = os.path.join(work_dir, f"ent_{pos:03d}.jpg")
                    ent_img = fetch_wikimedia_entity_image(query, ent_dl)
                    if not ent_img:
                        ent_img = fetch_article_image(query, ent_dl)
                    if not ent_img:
                        ent_img = fetch_stock_image(query, ent_dl, orientation=orient, used_urls=used_urls, alt_query=alt_query)
                    entity_cache[ent_key] = ent_img

                raw_ent = os.path.join(work_dir, f"raw_ent_{pos:03d}.mp4")
                render_entity_spotlight_clip(
                    raw_ent,
                    width=width,
                    height=height,
                    duration=dur,
                    entity_img_path=ent_img,
                    entity_title=query,
                    sub_label=m_lbl or highlight_text[:32],
                    accent="cyan" if any(k in query.lower() for k in ("nvidia", "ai", "openai", "amd", "intel", "tsmc")) else "gold",
                )
                _render_media_beat(raw_ent, False, dur, beat_mp4, width, height, is_motion_graphic=True)
                sfx_events["pop"].append(int(start_t * 1000))
                rendered_ok = True

            # ROUTE 7: Newsroom Highlight Card (Beat 0 Hook or explicit news_card)
            elif vtype == "news_card" or pos == 0:
                card_png = os.path.join(work_dir, f"ncard_{pos:03d}.png")
                bg_img = fetch_stock_image(query, os.path.join(work_dir, f"nbg_{pos:03d}.jpg"), orientation=orient, used_urls=used_urls, alt_query=alt_query)
                badge = "BREAKING HOOK" if pos == 0 else "NEWSROOM BRIEF"
                _create_newsroom_highlight_card(
                    card_png,
                    width,
                    height,
                    badge,
                    m_lbl or highlight_text,
                    thumb_img_path=article_thumb or bg_img,
                    accent="gold",
                )
                _render_media_beat(bg_img, True, dur, beat_mp4, width, height, overlay_png=card_png, fade_overlay=(pos > 0))
                sfx_events["pop"].append(int(start_t * 1000))
                rendered_ok = True

            # ROUTE 8: Relevance-Scored Exact Topic Video Footage (e.g., chip fab, shipyard, gaming)
            elif vtype == "stock_video":
                broll_dl = os.path.join(work_dir, f"broll_{pos:03d}.mp4")
                clip = fetch_broll_clip(query, broll_dl, used_urls=used_urls, is_shorts=is_shorts, alt_query=alt_query)
                if clip:
                    _render_media_beat(clip, False, dur, beat_mp4, width, height, overlay_png=tag_png)
                else:
                    fb_img = fetch_stock_image(query, os.path.join(work_dir, f"fb_img_{pos:03d}.jpg"), orientation=orient, used_urls=used_urls, alt_query=alt_query)
                    _render_media_beat(fb_img, True, dur, beat_mp4, width, height, overlay_png=tag_png)
                rendered_ok = True

            # ROUTE 9: Editorial HD Photo with Smooth Ken Burns Motion
            else:
                ed_img = fetch_stock_image(query, os.path.join(work_dir, f"ed_{pos:03d}.jpg"), orientation=orient, used_urls=used_urls, alt_query=alt_query)
                _render_media_beat(ed_img, True, dur, beat_mp4, width, height, overlay_png=tag_png)
                rendered_ok = True

        except Exception as beat_err:
            print(f"[VideoBuilder] Beat {pos + 1} ({vtype}) warning: {beat_err} -> safe fallback")
            rendered_ok = False

        if not rendered_ok or not os.path.exists(beat_mp4) or os.path.getsize(beat_mp4) < 1024:
            safe_img = fetch_stock_image("dark modern studio", os.path.join(work_dir, f"safe_{pos:03d}.jpg"), orientation=orient)
            _render_media_beat(safe_img, True, dur, beat_mp4, width, height)

        actual_d = _probe_duration(beat_mp4)
        video_cursor += actual_d if actual_d > 0.2 else dur
        subclips.append(beat_mp4)

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

    total_dur = _probe_duration(voice_merged) or sum(float(x["duration"]) for x in beat_audio_info)
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
        music_drops=music_drops,
    )

    combined_mp4 = os.path.join(work_dir, "video_with_audio.mp4")
    _run_ffmpeg([
        "ffmpeg", "-y", "-i", raw_video, "-i", master_wav,
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
        combined_mp4,
    ])

    _burn_subtitles_watermark_and_fade(combined_mp4, subtitle_path, output_video_path, is_shorts, total_dur, work_dir)
    return output_video_path
