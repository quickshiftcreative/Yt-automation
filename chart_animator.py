import math
import os
import random
import re
import subprocess
from PIL import Image, ImageDraw, ImageFilter, ImageFont

LANCZOS = getattr(Image, "Resampling", Image).LANCZOS


def _load_bold_font(size):
    for fpath in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        if os.path.exists(fpath):
            try:
                return ImageFont.truetype(fpath, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _draw_centered(draw, cx, y, text, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text((cx - tw // 2, y), text, font=font, fill=fill)


def _open_ffmpeg_pipe(out_mp4, width, height, fps=24):
    os.makedirs(os.path.dirname(out_mp4) or ".", exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "-",
        "-an",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        out_mp4,
    ]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _close_ffmpeg_pipe(proc):
    if proc.stdin:
        try:
            proc.stdin.close()
        except Exception:
            pass
    _, err = proc.communicate()
    if proc.returncode != 0:
        msg = (err or b"").decode("utf-8", errors="ignore")[-600:]
        raise RuntimeError(f"Motion graphics FFmpeg pipe failed: {msg}")


def _draw_terminal_grid(width, height, accent_rgb):
    bg = Image.new("RGB", (width, height), (9, 12, 18))
    draw = ImageDraw.Draw(bg)
    step = 80 if width > height else 72
    for x in range(0, width, step):
        draw.line([(x, 0), (x, height)], fill=(18, 24, 34), width=1)
    for y in range(0, height, step):
        draw.line([(0, y), (width, y)], fill=(18, 24, 34), width=1)

    # Subtle ambient top glow
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r, g, b = accent_rgb
    gd.ellipse([width // 2 - 420, -180, width // 2 + 420, 380], fill=(r, g, b, 34))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=90))
    return Image.alpha_composite(bg.convert("RGBA"), glow).convert("RGB")


def render_animated_candlestick_clip(
    out_mp4,
    width=1920,
    height=1080,
    duration=4.0,
    symbol="SPY",
    bearish_bias=False,
    change_label="",
    subtitle="",
):
    """
    Renders a broadcast-grade animated Candlestick Chart synced to the exact spoken drop/rally
    (e.g., '-100 PTS' crashing red candles or '+14%' rallying green candles).
    """
    fps = 24
    n_frames = max(16, int(round(duration * fps)))
    is_vertical = height > width

    green = (34, 211, 138)
    red = (244, 63, 94)
    gold = (250, 204, 21)
    white = (246, 248, 252)
    muted = (150, 162, 182)
    accent = red if bearish_bias else green

    rng = random.Random(hash(f"{symbol}_{bearish_bias}_{change_label}") & 0xFFFFFFFF)
    n_candles = 18 if is_vertical else 26

    # Synthesize realistic OHLC candles that clearly match the spoken direction
    candles = []
    price = 100.0
    for i in range(n_candles):
        progress = i / max(1, n_candles - 1)
        if bearish_bias:
            # Mild consolidation then sharp dramatic drop
            drift = rng.uniform(-1.0, 1.4) if progress < 0.35 else rng.uniform(-5.5, -1.2)
            if i >= n_candles - 3:
                drift = rng.uniform(-6.8, -3.5)
        else:
            # Steady buildup then sharp bullish breakout
            drift = rng.uniform(-1.2, 1.2) if progress < 0.35 else rng.uniform(1.4, 5.4)
            if i >= n_candles - 3:
                drift = rng.uniform(3.5, 6.8)

        o = price
        c = max(20.0, o + drift)
        hi = max(o, c) + rng.uniform(0.8, 3.0)
        lo = min(o, c) - rng.uniform(0.8, 3.0)
        candles.append((o, hi, lo, c))
        price = c

    p_min = min(c[2] for c in candles) - 4.0
    p_max = max(c[1] for c in candles) + 4.0
    p_span = max(1.0, p_max - p_min)

    # Chart viewport (leaves room at top for header/badge and bottom for .ass captions)
    pad_l = 70 if is_vertical else 130
    pad_r = 70 if is_vertical else 130
    pad_t = int(height * 0.24) if is_vertical else int(height * 0.25)
    pad_b = int(height * 0.28) if is_vertical else int(height * 0.22)
    chart_w = width - pad_l - pad_r
    chart_h = height - pad_t - pad_b

    def py(val):
        return int(pad_t + chart_h * (1.0 - (val - p_min) / p_span))

    base_bg = _draw_terminal_grid(width, height, accent)
    f_sym = _load_bold_font(56 if is_vertical else 62)
    f_badge = _load_bold_font(42 if is_vertical else 46)
    f_sub = _load_bold_font(26 if is_vertical else 28)
    f_axis = _load_bold_font(20)

    clean_sym = (symbol or "MARKET").upper()[:12]
    if change_label:
        pill_txt = str(change_label).upper()[:18]
    else:
        pill_txt = "SELL-OFF ▼" if bearish_bias else "BREAKOUT ▲"
    sub_txt = (subtitle or ("LIVE BEARISH MOVE" if bearish_bias else "LIVE BULLISH RALLY")).upper()[:34]

    proc = _open_ffmpeg_pipe(out_mp4, width, height, fps=fps)
    try:
        for f_i in range(n_frames):
            t_norm = f_i / max(1, n_frames - 1)
            # Reveal candles smoothly across first 82% of duration, then hold final impact
            reveal_frac = min(1.0, t_norm / 0.82)
            visible_f = max(1.0, reveal_frac * n_candles)
            full_cnt = int(visible_f)
            part_frac = visible_f - full_cnt

            frame = base_bg.copy()
            draw = ImageDraw.Draw(frame)

            # Header bar
            draw.text((pad_l, int(height * 0.08)), clean_sym, font=f_sym, fill=white)
            draw.text((pad_l, int(height * 0.08) + (70 if is_vertical else 74)), sub_txt, font=f_sub, fill=muted)

            # Dynamic pulsing impact badge on top-right
            b_box = draw.textbbox((0, 0), pill_txt, font=f_badge)
            bw, bh = b_box[2] - b_box[0], b_box[3] - b_box[1]
            bx1 = width - pad_r
            bx0 = bx1 - bw - 44
            by0 = int(height * 0.08) + 4
            by1 = by0 + bh + 28
            draw.rounded_rectangle([bx0, by0, bx1, by1], radius=14, fill=accent)
            txt_col = (10, 12, 16) if not bearish_bias else white
            draw.text((bx0 + 22, by0 + 12), pill_txt, font=f_badge, fill=txt_col)

            # Subtle horizontal price guide lines
            for g_i in range(4):
                gy = pad_t + int(chart_h * g_i / 3.0)
                draw.line([(pad_l, gy), (width - pad_r, gy)], fill=(32, 42, 58), width=2)

            # Draw animated candles + glowing trendline
            step_x = chart_w / max(1, n_candles)
            body_w = max(12, int(step_x * 0.56))
            trend_pts = []

            limit_idx = min(n_candles, full_cnt + (1 if part_frac > 0.05 else 0))
            for i in range(limit_idx):
                o, hi, lo, c = candles[i]
                if i == full_cnt and i < n_candles:
                    # Smoothly grow current candle body & wicks
                    c = o + (c - o) * part_frac
                    hi = o + (hi - o) * part_frac
                    lo = o + (lo - o) * part_frac

                cx = int(pad_l + i * step_x + step_x * 0.5)
                y_o, y_c, y_hi, y_lo = py(o), py(c), py(hi), py(lo)
                col = green if c >= o else red

                # Wick
                draw.line([(cx, y_hi), (cx, y_lo)], fill=col, width=4)
                # Body
                top_y, bot_y = min(y_o, y_c), max(y_o, y_c)
                if bot_y - top_y < 6:
                    bot_y = top_y + 6
                draw.rounded_rectangle(
                    [cx - body_w // 2, top_y, cx + body_w // 2, bot_y],
                    radius=4,
                    fill=col,
                )
                trend_pts.append((cx, y_c))

            if len(trend_pts) >= 2:
                draw.line(trend_pts, fill=gold, width=4)
                lx, ly = trend_pts[-1]
                # Glowing live dot on latest candle
                draw.ellipse([lx - 10, ly - 10, lx + 10, ly + 10], fill=gold, outline=white, width=2)

            # Bottom chart frame border
            draw.line([(pad_l, pad_t + chart_h), (width - pad_r, pad_t + chart_h)], fill=(55, 68, 90), width=2)
            draw.text((pad_l, pad_t + chart_h + 14), "LIVE MARKET DATA SIMULATION", font=f_axis, fill=muted)

            proc.stdin.write(frame.tobytes())
    finally:
        _close_ffmpeg_pipe(proc)

    return out_mp4


def _parse_numeric_metric(metric_str):
    s = str(metric_str or "100%").strip()
    m = re.match(r"^([^\d\-+]*)([\-+]?\d+(?:\.\d+)?)(.*)$", s)
    if not m:
        return "", 0.0, s, False
    prefix, num_s, suffix = m.group(1), m.group(2), m.group(3)
    has_dec = "." in num_s
    return prefix, float(num_s), suffix, has_dec


def render_kpi_counter_clip(
    out_mp4,
    width=1920,
    height=1080,
    duration=3.2,
    value_text="$40B",
    label_text="KEY MARKET STAT",
    accent="gold",
):
    """Renders a Vox/MagnatesMedia-style animated rolling number slam with glowing progress bar."""
    fps = 24
    n_frames = max(14, int(round(duration * fps)))
    is_vertical = height > width

    palette = {
        "gold":  (250, 204, 21),
        "green": (34, 211, 138),
        "red":   (244, 63, 94),
        "cyan":  (0, 229, 255),
    }
    acc_rgb = palette.get(accent, palette["gold"])
    white = (248, 250, 252)
    muted = (176, 188, 208)

    prefix, target_num, suffix, has_dec = _parse_numeric_metric(value_text)
    base_bg = _draw_terminal_grid(width, height, acc_rgb)

    f_val = _load_bold_font(134 if is_vertical else 168)
    f_lbl = _load_bold_font(40 if is_vertical else 48)
    f_tag = _load_bold_font(24 if is_vertical else 26)

    clean_lbl = (label_text or "KEY NUMBER").upper()[:32]
    cx = width // 2
    card_w = int(width * 0.86) if is_vertical else int(width * 0.68)
    card_h = 460 if is_vertical else 430
    x0 = (width - card_w) // 2
    y0 = int(height * 0.24) if is_vertical else int(height * 0.20)
    x1, y1 = x0 + card_w, y0 + card_h

    proc = _open_ffmpeg_pipe(out_mp4, width, height, fps=fps)
    try:
        for f_i in range(n_frames):
            t_norm = f_i / max(1, n_frames - 1)
            # Fast ease-out cubic roll-up over first 48% of clip
            p = min(1.0, t_norm / 0.48)
            eased = 1.0 - ((1.0 - p) ** 3)

            if target_num != 0.0:
                cur_val = target_num * eased
                if has_dec:
                    val_disp = f"{prefix}{cur_val:.1f}{suffix}"
                else:
                    val_disp = f"{prefix}{int(round(cur_val)):,}{suffix}"
            else:
                val_disp = str(value_text).upper()[:14]

            frame = base_bg.copy()
            draw = ImageDraw.Draw(frame)

            # Frosted dark studio card
            draw.rounded_rectangle([x0, y0, x1, y1], radius=30, fill=(14, 18, 26), outline=acc_rgb, width=4)
            draw.rounded_rectangle([cx - 150, y0 + 28, cx + 150, y0 + 68], radius=12, fill=acc_rgb)
            pill_txt_col = (10, 12, 16) if accent != "red" else white
            _draw_centered(draw, cx, y0 + 36, "VERIFIED STAT", f_tag, pill_txt_col)

            # Animated bold number
            _draw_centered(draw, cx, y0 + 118, val_disp, f_val, acc_rgb)
            _draw_centered(draw, cx, y0 + (295 if is_vertical else 318), clean_lbl, f_lbl, white)

            # Animated accent progress meter bar at bottom of card
            bar_x0, bar_x1 = x0 + 60, x1 - 60
            bar_y = y1 - 44
            draw.rounded_rectangle([bar_x0, bar_y, bar_x1, bar_y + 14], radius=7, fill=(32, 40, 56))
            fill_x = bar_x0 + max(16, int((bar_x1 - bar_x0) * eased))
            draw.rounded_rectangle([bar_x0, bar_y, fill_x, bar_y + 14], radius=7, fill=acc_rgb)

            proc.stdin.write(frame.tobytes())
    finally:
        _close_ffmpeg_pipe(proc)

    return out_mp4


def render_entity_spotlight_clip(
    out_mp4,
    width=1920,
    height=1080,
    duration=3.5,
    entity_img_path=None,
    entity_title="SPOTLIGHT",
    sub_label="",
    accent="gold",
):
    """
    Showcases a real Wikimedia/News entity photo (person, logo, GPU, game) inside a sleek
    studio spotlight card with blurred backdrop, smooth zoom-in motion, and editorial name plate.
    """
    fps = 24
    n_frames = max(14, int(round(duration * fps)))
    is_vertical = height > width

    palette = {
        "gold":  (250, 204, 21),
        "green": (34, 211, 138),
        "red":   (244, 63, 94),
        "cyan":  (0, 229, 255),
    }
    acc_rgb = palette.get(accent, palette["gold"])
    white = (248, 250, 252)

    if entity_img_path and os.path.exists(entity_img_path):
        src = Image.open(entity_img_path).convert("RGB")
    else:
        src = Image.new("RGB", (800, 600), (20, 26, 38))

    # Build dark blurred ambient backdrop from the real photo itself
    bg = src.resize((width, height), LANCZOS).filter(ImageFilter.GaussianBlur(radius=34))
    dark_wash = Image.new("RGBA", (width, height), (8, 11, 18, 185))
    bg = Image.alpha_composite(bg.convert("RGBA"), dark_wash).convert("RGB")

    # Hero photo frame dimensions (kept cleanly above .ass captions)
    frame_w = int(width * 0.80) if is_vertical else int(width * 0.56)
    frame_h = int(height * 0.42) if is_vertical else int(height * 0.54)
    fx0 = (width - frame_w) // 2
    fy0 = int(height * 0.16) if is_vertical else int(height * 0.13)

    # Pre-crop source to match hero aspect ratio with 10% headroom for smooth zoom
    src_r = src.width / max(1, src.height)
    tgt_r = frame_w / max(1, frame_h)
    if src_r > tgt_r:
        nw = int(src.height * tgt_r)
        left = (src.width - nw) // 2
        hero_base = src.crop((left, 0, left + nw, src.height))
    else:
        nh = int(src.width / tgt_r)
        top = max(0, int((src.height - nh) * 0.25))  # Favor faces/top subject
        hero_base = src.crop((0, top, src.width, top + nh))

    hero_hi = hero_base.resize((int(frame_w * 1.12), int(frame_h * 1.12)), LANCZOS)
    mask = Image.new("L", (frame_w, frame_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, frame_w, frame_h], radius=24, fill=255)

    f_title = _load_bold_font(40 if is_vertical else 44)
    f_sub = _load_bold_font(24 if is_vertical else 26)
    clean_title = (entity_title or "IN FOCUS").upper()[:28]
    clean_sub = (sub_label or "KEY SUBJECT").upper()[:36]

    proc = _open_ffmpeg_pipe(out_mp4, width, height, fps=fps)
    try:
        for f_i in range(n_frames):
            t_norm = f_i / max(1, n_frames - 1)
            # Smooth Ken Burns zoom inside the spotlight frame
            z = 1.0 + 0.09 * t_norm
            crop_w = int(hero_hi.width / z)
            crop_h = int(hero_hi.height / z)
            cx0 = (hero_hi.width - crop_w) // 2
            cy0 = (hero_hi.height - crop_h) // 2
            hero_step = hero_hi.crop((cx0, cy0, cx0 + crop_w, cy0 + crop_h)).resize((frame_w, frame_h), LANCZOS)

            frame = bg.copy()
            draw = ImageDraw.Draw(frame)

            # Drop shadow & glowing border
            draw.rounded_rectangle([fx0 + 10, fy0 + 12, fx0 + frame_w + 10, fy0 + frame_h + 12], radius=26, fill=(0, 0, 0))
            frame.paste(hero_step, (fx0, fy0), mask)
            draw.rounded_rectangle([fx0, fy0, fx0 + frame_w, fy0 + frame_h], radius=24, outline=acc_rgb, width=4)

            # Editorial Name Plate right under the framed photo
            plate_y0 = fy0 + frame_h + 22
            plate_h = 104 if is_vertical else 96
            draw.rounded_rectangle(
                [fx0, plate_y0, fx0 + frame_w, plate_y0 + plate_h],
                radius=18,
                fill=(12, 16, 24),
                outline=(60, 72, 92),
                width=2,
            )
            draw.rounded_rectangle([fx0, plate_y0, fx0 + 12, plate_y0 + plate_h], radius=6, fill=acc_rgb)
            draw.text((fx0 + 30, plate_y0 + 14), clean_title, font=f_title, fill=white)
            draw.text((fx0 + 30, plate_y0 + 62), clean_sub, font=f_sub, fill=acc_rgb)

            proc.stdin.write(frame.tobytes())
    finally:
        _close_ffmpeg_pipe(proc)

    return out_mp4
