import math
import os
import re
import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

LANCZOS = getattr(Image, "Resampling", Image).LANCZOS
FONT_CACHE_DIR = "/tmp/yt_thumb_fonts"

# 6 Trending High-CTR YouTube Fonts (including MrBeast-style chunky & YouTube Sans-like geometric bold)
TRENDING_FONTS = {
    "Anton": {
        "google_css": "Anton",
        "github_raw": "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf",
    },
    "Lilita One": {
        "google_css": "Lilita+One",
        "github_raw": "https://raw.githubusercontent.com/google/fonts/main/ofl/lilitaone/LilitaOne-Regular.ttf",
    },
    "Poppins Black": {
        "google_css": "Poppins:900",
        "github_raw": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Black.ttf",
    },
    "Bebas Neue": {
        "google_css": "Bebas+Neue",
        "github_raw": "https://raw.githubusercontent.com/google/fonts/main/ofl/bebasneue/BebasNeue-Regular.ttf",
    },
    "Oswald": {
        "google_css": "Oswald:700",
        "github_raw": "https://raw.githubusercontent.com/google/fonts/main/ofl/oswald/static/Oswald-Bold.ttf",
    },
    "Bangers": {
        "google_css": "Bangers",
        "github_raw": "https://raw.githubusercontent.com/google/fonts/main/ofl/bangers/Bangers-Regular.ttf",
    },
}

ACCENT_PALETTES = {
    "gold":  ((255, 230, 0),   (255, 175, 0)),    # Curiosity / Tech / Viral
    "green": ((0, 255, 136),   (0, 185, 95)),     # Money / Market Gains / High-RPM
    "red":   ((255, 42, 60),   (195, 18, 36)),    # Scandal / Crash / Warning
    "cyan":  ((0, 229, 255),   (0, 145, 255)),    # AI / Future / Gaming Hardware
}


def _download_google_font(font_name):
    os.makedirs(FONT_CACHE_DIR, exist_ok=True)
    safe_file = re.sub(r"[^a-zA-Z0-9]+", "_", font_name).strip("_") + ".ttf"
    dest = os.path.join(FONT_CACHE_DIR, safe_file)

    if os.path.exists(dest) and os.path.getsize(dest) > 10000:
        try:
            ImageFont.truetype(dest, 40)
            return dest
        except Exception:
            pass

    meta = TRENDING_FONTS.get(font_name)
    if not meta:
        return None

    # Method 1: Google Fonts CSS v1 returns direct .ttf URLs for non-browser User-Agents
    try:
        css_url = f"https://fonts.googleapis.com/css?family={meta['google_css']}"
        r = requests.get(css_url, headers={"User-Agent": "curl/7.81.0"}, timeout=12)
        if r.status_code == 200:
            m = re.search(r"url\((https://[^)]+\.ttf)\)", r.text)
            if m:
                fr = requests.get(m.group(1), timeout=15)
                if fr.status_code == 200 and len(fr.content) > 10000:
                    with open(dest, "wb") as f:
                        f.write(fr.content)
                    ImageFont.truetype(dest, 40)
                    return dest
    except Exception:
        pass

    # Method 2: Direct Google Fonts GitHub raw TTF fallback
    try:
        fr = requests.get(meta["github_raw"], timeout=15)
        if fr.status_code == 200 and len(fr.content) > 10000:
            with open(dest, "wb") as f:
                f.write(fr.content)
            ImageFont.truetype(dest, 40)
            return dest
    except Exception:
        pass

    return None


def _load_font(font_name, size):
    ttf_path = _download_google_font(font_name)
    if ttf_path:
        try:
            return ImageFont.truetype(ttf_path, size)
        except Exception:
            pass

    for sys_f in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        if os.path.exists(sys_f):
            try:
                return ImageFont.truetype(sys_f, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _polish_mrbeast_background(bg_image_path, width=1280, height=720, focus_right=False):
    """Polishes the real topic image with MrBeast-style vibrancy, crispness, spotlight & dramatic vignette."""
    if bg_image_path and os.path.exists(bg_image_path):
        try:
            img = Image.open(bg_image_path).convert("RGB")
        except Exception:
            img = Image.new("RGB", (width, height), (14, 18, 28))
    else:
        img = Image.new("RGB", (width, height), (14, 18, 28))

    # Smart aspect-ratio crop to 1280x720
    src_ratio = img.width / max(1, img.height)
    tgt_ratio = width / height
    if src_ratio > tgt_ratio:
        new_w = int(img.height * tgt_ratio)
        left = int((img.width - new_w) * (0.35 if focus_right else 0.5))
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        new_h = int(img.width / tgt_ratio)
        top = max(0, int((img.height - new_h) * 0.28))  # Keep faces/subjects in upper-center
        img = img.crop((0, top, img.width, top + new_h))

    img = img.resize((width, height), LANCZOS)

    # High-CTR color & clarity polish (vibrant, crisp, never muddy)
    img = ImageEnhance.Color(img).enhance(1.32)
    img = ImageEnhance.Contrast(img).enhance(1.22)
    img = ImageEnhance.Sharpness(img).enhance(1.45)
    img = ImageEnhance.Brightness(img).enhance(1.04)

    # Subtle radial center/subject spotlight + dramatic dark vignette on edges
    rgba = img.convert("RGBA")
    vignette = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    v_draw = ImageDraw.Draw(vignette)
    cx = int(width * (0.68 if focus_right else 0.50))
    cy = int(height * 0.42)
    max_r = int(math.hypot(width, height) * 0.62)

    for step in range(20):
        frac = step / 20.0
        r_out = int(max_r * (1.0 - frac * 0.58))
        alpha = int(125 * ((1.0 - frac) ** 1.8))
        if alpha > 0 and r_out > 40:
            v_draw.ellipse([cx - r_out, cy - r_out, cx + r_out, cy + r_out], outline=(4, 6, 12, alpha), width=36)

    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=32))
    rgba = Image.alpha_composite(rgba, vignette)
    return rgba


def _add_gradient_scrim(rgba, direction="bottom", strength=230):
    """Adds a silky dark gradient scrim so bold typography always pops with maximum mobile readability."""
    w, h = rgba.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    if direction == "bottom":
        start_y = int(h * 0.38)
        span = max(1, h - start_y)
        for y in range(start_y, h):
            p = (y - start_y) / span
            a = int(strength * (p ** 1.45))
            draw.line([(0, y), (w, y)], fill=(6, 8, 14, a))
    elif direction == "left":
        end_x = int(w * 0.68)
        for x in range(0, end_x):
            p = 1.0 - (x / max(1, end_x))
            a = int(strength * (p ** 1.25))
            draw.line([(x, 0), (x, h)], fill=(7, 9, 16, a))
    elif direction == "top":
        end_y = int(h * 0.52)
        for y in range(0, end_y):
            p = 1.0 - (y / max(1, end_y))
            a = int(strength * (p ** 1.45))
            draw.line([(0, y), (w, y)], fill=(6, 8, 14, a))

    return Image.alpha_composite(rgba, overlay)


def _add_rim_glow(rgba, accent_rgb, position="center_right"):
    """Adds a vibrant MrBeast-style subtle color rim glow behind the focal area."""
    w, h = rgba.size
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r, g, b = accent_rgb

    if position == "center_right":
        cx, cy = int(w * 0.74), int(h * 0.48)
    elif position == "bottom":
        cx, cy = int(w * 0.50), int(h * 0.82)
    else:
        cx, cy = int(w * 0.50), int(h * 0.45)

    gd.ellipse([cx - 320, cy - 260, cx + 320, cy + 260], fill=(r, g, b, 52))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=95))
    return Image.alpha_composite(rgba, glow)


def _punchy_words(headline, max_words=4):
    """Trims long headlines to ultra-readable 2-4 power words (zero clutter, topic-accurate)."""
    clean = re.sub(r"[#*|`~\"']", "", str(headline or "MAJOR SHIFT")).strip().upper()
    words = [w for w in clean.split() if w]
    if not words:
        return ["BIG", "SHIFT"]
    if len(words) <= max_words:
        return words
    # Prefer keeping numbers/tickers/strong nouns
    return words[:max_words]


def _pick_power_word_index(words):
    """Highlights the highest-impact word (number, $, %, or final punch word) in bright accent color."""
    for i, w in enumerate(words):
        if re.search(r"[\d$%?]", w):
            return i
    return len(words) - 1


def _split_into_lines(words, max_lines=2):
    if len(words) <= 2 or max_lines == 1:
        return [words]
    mid = max(1, len(words) // 2)
    return [words[:mid], words[mid:]]


def _draw_3d_stroked_line(draw, x, y, line_words, font, power_idx_offset, power_global_idx, accent_rgb, stroke_w=10):
    """Draws ultra-crisp MrBeast-style text with 3D offset drop shadow + thick black stroke + power-word highlight."""
    cur_x = x
    space_w = int(draw.textlength(" ", font=font))
    shadow_off = max(6, stroke_w - 2)

    for j, word in enumerate(line_words):
        is_power = (power_idx_offset + j == power_global_idx)
        fill_col = (*accent_rgb, 255) if is_power else (255, 255, 255, 255)

        # Hard 3D drop shadow
        draw.text(
            (cur_x + shadow_off, y + shadow_off),
            word,
            font=font,
            fill=(0, 0, 0, 235),
            stroke_width=stroke_w,
            stroke_fill=(0, 0, 0, 235),
        )
        # Main crisp stroked word
        draw.text(
            (cur_x, y),
            word,
            font=font,
            fill=fill_col,
            stroke_width=stroke_w,
            stroke_fill=(8, 10, 16, 255),
        )
        w_len = int(draw.textlength(word, font=font))
        cur_x += w_len + space_w


def _fit_font_for_lines(draw, lines, font_name, max_width, start_size=132, min_size=62):
    for sz in range(start_size, min_size - 1, -4):
        f = _load_font(font_name, sz)
        widest = max(draw.textlength(" ".join(ln), font=f) for ln in lines)
        if widest <= max_width:
            return f, sz
    return _load_font(font_name, min_size), min_size


def _draw_badge_pill(draw, x, y, text, accent_rgb, font_name):
    lbl = re.sub(r"[^A-Z0-9\s\-&•]", "", str(text or "BREAKING").upper()).strip()[:20] or "BREAKING"
    f = _load_font("Poppins Black", 28) if font_name != "Poppins Black" else _load_font(font_name, 28)
    bbox = draw.textbbox((0, 0), lbl, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 22, 12

    # Dark drop shadow behind pill
    draw.rounded_rectangle(
        [x + 5, y + 5, x + tw + pad_x * 2 + 5, y + th + pad_y * 2 + 5],
        radius=12,
        fill=(0, 0, 0, 190),
    )
    draw.rounded_rectangle(
        [x, y, x + tw + pad_x * 2, y + th + pad_y * 2],
        radius=12,
        fill=(*accent_rgb, 255),
        outline=(255, 255, 255, 220),
        width=3,
    )
    # Dark text on bright accents (gold/green/cyan), white text on red
    txt_col = (255, 255, 255, 255) if accent_rgb[0] > 200 and accent_rgb[1] < 90 else (10, 12, 16, 255)
    draw.text((x + pad_x, y + pad_y - 2), lbl, font=f, fill=txt_col)


def create_thumbnail(
    bg_image_path,
    headline,
    subtext="",
    output_path="output/thumbnail.jpg",
    bulletin_badge="TECH BULLETIN",
    font_name="Anton",
    layout="mrbeast_bottom_slam",
    accent="gold",
):
    """
    Generates a high-CTR, MrBeast-psychology 1280x720 thumbnail using the real video topic image.
    Supports 6 auto-downloaded trending fonts and 4 tested CTR layouts.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    width, height = 1280, 720
    accent_rgb, accent_dark = ACCENT_PALETTES.get(accent, ACCENT_PALETTES["gold"])

    words = _punchy_words(headline, max_words=4)
    power_idx = _pick_power_word_index(words)
    lines = _split_into_lines(words, max_lines=2)

    focus_right = (layout == "split_left_editorial")
    rgba = _polish_mrbeast_background(bg_image_path, width=width, height=height, focus_right=focus_right)

    if layout == "split_left_editorial":
        rgba = _add_rim_glow(rgba, accent_rgb, position="center_right")
        rgba = _add_gradient_scrim(rgba, direction="left", strength=245)
        draw = ImageDraw.Draw(rgba)

        # Bold vertical left accent bar
        draw.rectangle([0, 0, 16, height], fill=(*accent_rgb, 255))
        _draw_badge_pill(draw, 54, 52, bulletin_badge, accent_rgb, font_name)

        font, sz = _fit_font_for_lines(draw, lines, font_name, max_width=700, start_size=122, min_size=64)
        line_h = int(sz * 1.16)
        start_y = 175 if len(lines) == 2 else 245

        offset = 0
        for idx_l, ln in enumerate(lines):
            _draw_3d_stroked_line(
                draw, 54, start_y + idx_l * line_h, ln, font, offset, power_idx, accent_rgb, stroke_w=10
            )
            offset += len(ln)

        if subtext:
            sub_clean = str(subtext).strip().upper()[:30]
            f_sub = _load_font("Poppins Black", 34)
            draw.text(
                (56, height - 108),
                sub_clean,
                font=f_sub,
                fill=(235, 240, 248, 255),
                stroke_width=5,
                stroke_fill=(0, 0, 0, 230),
            )

    elif layout == "top_focus_frame":
        rgba = _add_rim_glow(rgba, accent_rgb, position="center")
        rgba = _add_gradient_scrim(rgba, direction="top", strength=230)
        draw = ImageDraw.Draw(rgba)

        # Crisp glowing focal corner brackets around lower subject area (draws eye to real visual)
        bx0, by0, bx1, by1 = 220, 320, 1060, 670
        blen = 52
        for (px, py, dx, dy) in [
            (bx0, by0, 1, 1), (bx1, by0, -1, 1), (bx0, by1, 1, -1), (bx1, by1, -1, -1)
        ]:
            draw.line([(px, py), (px + dx * blen, py)], fill=(*accent_rgb, 235), width=7)
            draw.line([(px, py), (px, py + dy * blen)], fill=(*accent_rgb, 235), width=7)

        font, sz = _fit_font_for_lines(draw, lines, font_name, max_width=1140, start_size=128, min_size=68)
        line_h = int(sz * 1.12)
        start_y = 36 if len(lines) == 2 else 74

        offset = 0
        for idx_l, ln in enumerate(lines):
            lw = int(draw.textlength(" ".join(ln), font=font))
            lx = (width - lw) // 2
            _draw_3d_stroked_line(
                draw, lx, start_y + idx_l * line_h, ln, font, offset, power_idx, accent_rgb, stroke_w=11
            )
            offset += len(ln)

        _draw_badge_pill(draw, 44, height - 92, bulletin_badge, accent_rgb, font_name)

    elif layout == "youtube_clean_pro":
        rgba = _add_rim_glow(rgba, accent_rgb, position="bottom")
        rgba = _add_gradient_scrim(rgba, direction="bottom", strength=235)
        draw = ImageDraw.Draw(rgba)

        # Subtle studio outer frame
        draw.rectangle([10, 10, width - 10, height - 10], outline=(*accent_rgb, 180), width=5)
        _draw_badge_pill(draw, 48, 44, bulletin_badge, accent_rgb, font_name)

        font, sz = _fit_font_for_lines(draw, lines, font_name, max_width=1140, start_size=126, min_size=66)
        line_h = int(sz * 1.14)
        total_h = line_h * len(lines)
        start_y = height - total_h - 68

        offset = 0
        for idx_l, ln in enumerate(lines):
            _draw_3d_stroked_line(
                draw, 54, start_y + idx_l * line_h, ln, font, offset, power_idx, accent_rgb, stroke_w=10
            )
            offset += len(ln)

    else:
        # Default: "mrbeast_bottom_slam" — Full-bleed high-contrast real visual + massive 3D centered text
        rgba = _add_rim_glow(rgba, accent_rgb, position="bottom")
        rgba = _add_gradient_scrim(rgba, direction="bottom", strength=240)
        draw = ImageDraw.Draw(rgba)

        _draw_badge_pill(draw, 44, 40, bulletin_badge, accent_rgb, font_name)

        font, sz = _fit_font_for_lines(draw, lines, font_name, max_width=1160, start_size=136, min_size=68)
        line_h = int(sz * 1.12)
        total_h = line_h * len(lines)
        start_y = height - total_h - 54

        offset = 0
        for idx_l, ln in enumerate(lines):
            lw = int(draw.textlength(" ".join(ln), font=font))
            lx = (width - lw) // 2
            _draw_3d_stroked_line(
                draw, lx, start_y + idx_l * line_h, ln, font, offset, power_idx, accent_rgb, stroke_w=12
            )
            offset += len(ln)

    final_rgb = rgba.convert("RGB")
    final_rgb.save(output_path, "JPEG", quality=93, optimize=True)
    print(
        f"[Thumbnail] Saved 1280x720 High-CTR Thumbnail -> {output_path} | "
        f"Font: {font_name} | Layout: {layout} | Accent: {accent}"
    )
    return output_path
