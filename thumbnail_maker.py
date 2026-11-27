import base64
import io
import math
import os
import re
import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

LANCZOS = getattr(Image, "Resampling", Image).LANCZOS
BICUBIC = getattr(Image, "Resampling", Image).BICUBIC
FONT_CACHE_DIR = "/tmp/yt_thumb_fonts"

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
    "gold":  ((255, 230, 0),   (255, 160, 0)),
    "green": ((0, 255, 136),   (0, 180, 90)),
    "red":   ((255, 42, 60),   (190, 15, 35)),
    "cyan":  ((0, 229, 255),   (0, 140, 255)),
}


def _try_gemini_studio_bg(topic_prompt, gemini_api_key, width=1280, height=720):
    """Attempts to generate a clean, photorealistic, text-free MrBeast-style visual via Gemini Image API."""
    if not topic_prompt or not gemini_api_key:
        return None

    full_prompt = (
        f"{topic_prompt}. Photorealistic ultra-sharp 16:9 YouTube thumbnail photography, "
        f"vivid high-contrast MrBeast studio lighting, crisp central focal subject in the lower-middle, "
        f"clean uncluttered dark/atmospheric space at the top third. STRICTLY NO text, NO words, NO letters, NO watermarks."
    )
    for model in ("gemini-3.1-flash-image", "gemini-3.1-flash-lite-image", "gemini-2.5-flash-image"):
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_api_key}"
            payload = {
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": {"responseModalities": ["IMAGE"]},
            }
            r = requests.post(url, json=payload, timeout=35)
            if r.status_code != 200:
                continue
            parts = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
            for p in parts:
                idata = p.get("inlineData") or p.get("inline_data")
                if idata and idata.get("data"):
                    raw_bytes = base64.b64decode(idata["data"])
                    im = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
                    if im.width >= 512 and im.height >= 288:
                        print(f"[Thumbnail] Generated custom photorealistic backdrop via {model}!")
                        return im
        except Exception:
            continue
    return None


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

    try:
        r = requests.get(f"https://fonts.googleapis.com/css?family={meta['google_css']}", headers={"User-Agent": "curl/7.81.0"}, timeout=12)
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


def _polish_photo_background(pil_or_path, width=1280, height=720, focus_right=False):
    if isinstance(pil_or_path, Image.Image):
        img = pil_or_path.convert("RGB")
    elif pil_or_path and os.path.exists(pil_or_path):
        try:
            img = Image.open(pil_or_path).convert("RGB")
        except Exception:
            img = Image.new("RGB", (width, height), (14, 18, 28))
    else:
        img = Image.new("RGB", (width, height), (14, 18, 28))

    src_ratio = img.width / max(1, img.height)
    tgt_ratio = width / height
    if src_ratio > tgt_ratio:
        new_w = int(img.height * tgt_ratio)
        left = int((img.width - new_w) * (0.30 if focus_right else 0.50))
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        new_h = int(img.width / tgt_ratio)
        top = max(0, int((img.height - new_h) * 0.35))
        img = img.crop((0, top, img.width, top + new_h))

    img = img.resize((width, height), LANCZOS)
    # High-impact MrBeast vibrancy, clarity & studio contrast
    img = ImageEnhance.Color(img).enhance(1.36)
    img = ImageEnhance.Contrast(img).enhance(1.24)
    img = ImageEnhance.Sharpness(img).enhance(1.50)
    img = ImageEnhance.Brightness(img).enhance(1.05)

    rgba = img.convert("RGBA")
    # Soft dark edge vignette so focal subject pops
    vignette = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette)
    cx = int(width * (0.70 if focus_right else 0.50))
    cy = int(height * 0.56)
    max_r = int(math.hypot(width, height) * 0.60)
    for step in range(18):
        frac = step / 18.0
        r_out = int(max_r * (1.0 - frac * 0.52))
        alpha = int(115 * ((1.0 - frac) ** 1.8))
        if alpha > 0 and r_out > 40:
            vd.ellipse([cx - r_out, cy - r_out, cx + r_out, cy + r_out], outline=(4, 6, 12, alpha), width=36)
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=30))
    return Image.alpha_composite(rgba, vignette)


def _add_scrim(rgba, direction="top", strength=215):
    w, h = rgba.size
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(ov)
    if direction == "top":
        end_y = int(h * 0.48)
        for y in range(0, end_y):
            p = 1.0 - (y / max(1, end_y))
            draw.line([(0, y), (w, y)], fill=(5, 7, 13, int(strength * (p ** 1.35))))
    elif direction == "left":
        end_x = int(w * 0.62)
        for x in range(0, end_x):
            p = 1.0 - (x / max(1, end_x))
            draw.line([(x, 0), (x, h)], fill=(6, 8, 15, int(strength * (p ** 1.2))))
    return Image.alpha_composite(rgba, ov)


def _add_glow_spot(rgba, accent_rgb, cx, cy, rx=300, ry=240, alpha=60):
    w, h = rgba.size
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    r, g, b = accent_rgb
    ImageDraw.Draw(glow).ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(r, g, b, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=85))
    return Image.alpha_composite(rgba, glow)


def _draw_mrbeast_arrow(rgba, start_pt, end_pt, color_rgb=(255, 42, 60)):
    """Draws a chunky, bold YouTube-creator pointing arrow with black outline & glow."""
    layer = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x0, y0 = start_pt
    x1, y1 = end_pt
    ang = math.atan2(y1 - y0, x1 - x0)

    # Thick black outline shaft + bright inner shaft
    draw.line([(x0, y0), (x1, y1)], fill=(0, 0, 0, 235), width=26)
    draw.line([(x0, y0), (x1, y1)], fill=(*color_rgb, 255), width=14)

    # Chunky arrowhead triangle
    head_len = 48
    p1 = (x1 + int(math.cos(ang) * 10), y1 + int(math.sin(ang) * 10))
    p2 = (x1 - int(math.cos(ang - 0.55) * head_len), y1 - int(math.sin(ang - 0.55) * head_len))
    p3 = (x1 - int(math.cos(ang + 0.55) * head_len), y1 - int(math.sin(ang + 0.55) * head_len))

    # Outline triangle slightly expanded
    draw.polygon([p1, p2, p3], fill=(*color_rgb, 255), outline=(0, 0, 0, 245))
    draw.line([p1, p2, p3, p1], fill=(0, 0, 0, 245), width=6)
    return Image.alpha_composite(rgba, layer)


def _draw_focus_ring(rgba, cx, cy, radius=110, color_rgb=(255, 42, 60)):
    """Draws a subtle glowing focal target ring around the key subject (classic viral YouTube cue)."""
    glow = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        outline=(*color_rgb, 180),
        width=18,
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=14))
    rgba = Image.alpha_composite(rgba, glow)

    ring = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        outline=(*color_rgb, 245),
        width=9,
    )
    return Image.alpha_composite(rgba, ring)


def _punchy_words(headline, max_words=3):
    clean = re.sub(r"[#*|`~\"']", "", str(headline or "BIG SHIFT")).strip().upper()
    words = [w for w in clean.split() if w]
    if not words:
        return ["BIG", "SHIFT"]
    return words[:max_words]


def _pick_power_word_index(words):
    for i, w in enumerate(words):
        if re.search(r"[\d$%?]", w):
            return i
    return len(words) - 1


def _render_tilted_3d_headline(width, lines, font_name, accent_rgb, max_text_w=1120, tilt_deg=-2.5, start_sz=148, align="center"):
    """Renders massive, crisp 3D-extruded headline text onto a transparent RGBA layer with slight human tilt."""
    tmp = Image.new("RGBA", (width, 420), (0, 0, 0, 0))
    td = ImageDraw.Draw(tmp)

    font, sz = _load_font(font_name, 72), 72
    for try_sz in range(start_sz, 64, -4):
        f = _load_font(font_name, try_sz)
        widest = max(td.textlength(" ".join(ln), font=f) for ln in lines)
        if widest <= max_text_w:
            font, sz = f, try_sz
            break

    all_words = [w for ln in lines for w in ln]
    power_global = _pick_power_word_index(all_words)
    stroke_w = max(9, sz // 11)
    line_h = int(sz * 1.12)
    space_w = int(td.textlength(" ", font=font))

    layer_h = line_h * len(lines) + 80
    text_layer = Image.new("RGBA", (width, layer_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)

    offset = 0
    for idx_l, ln in enumerate(lines):
        full_w = int(draw.textlength(" ".join(ln), font=font))
        cur_x = (width - full_w) // 2 if align == "center" else 56
        cur_y = 24 + idx_l * line_h

        for j, word in enumerate(ln):
            is_power = (offset + j == power_global)
            fill_col = (*accent_rgb, 255) if is_power else (255, 255, 255, 255)

            # Deep multi-step 3D extrusion shadow
            for depth in (10, 7, 4):
                draw.text(
                    (cur_x + depth, cur_y + depth),
                    word,
                    font=font,
                    fill=(0, 0, 0, 210),
                    stroke_width=stroke_w,
                    stroke_fill=(0, 0, 0, 210),
                )
            draw.text(
                (cur_x, cur_y),
                word,
                font=font,
                fill=fill_col,
                stroke_width=stroke_w,
                stroke_fill=(8, 10, 16, 255),
            )
            cur_x += int(draw.textlength(word, font=font)) + space_w
        offset += len(ln)

    if abs(tilt_deg) > 0.1:
        text_layer = text_layer.rotate(tilt_deg, resample=BICUBIC, expand=True)
    return text_layer


def create_thumbnail(
    bg_image_path,
    headline,
    subtext="",
    output_path="output/thumbnail.jpg",
    bulletin_badge="DAILY BRIEF",
    font_name="Anton",
    layout="mrbeast_top_boom",
    accent="gold",
    topic_prompt="",
    gemini_api_key="",
):
    """
    100% Human/MrBeast-Style Thumbnail Engine:
    - ZERO bottom-bar text clutter (all headlines live cleanly in TOP or UPPER-LEFT).
    - Tries Gemini native photorealistic studio visual first, then polishes real topic photo.
    - Uses tilted 3D typography, dramatic lighting, pointing arrows & focal rings.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    width, height = 1280, 720
    accent_rgb, _ = ACCENT_PALETTES.get(accent, ACCENT_PALETTES["gold"])

    # Try custom photorealistic studio scene via Gemini Image API first (no text inside AI image)
    ai_bg = _try_gemini_studio_bg(topic_prompt, gemini_api_key, width=width, height=height)
    bg_source = ai_bg if ai_bg is not None else bg_image_path

    words = _punchy_words(headline, max_words=3)
    if layout == "upper_left_hero":
        lines = [[w] for w in words[:2]] if len(words) >= 2 else [words]
    else:
        lines = [words] if len(words) <= 3 else [words[:2], words[2:]]

    if layout == "upper_left_hero":
        rgba = _polish_photo_background(bg_source, width=width, height=height, focus_right=True)
        rgba = _add_glow_spot(rgba, accent_rgb, cx=int(width * 0.72), cy=int(height * 0.52), rx=340, ry=280, alpha=68)
        rgba = _add_scrim(rgba, direction="left", strength=230)

        # Massive stacked headline strictly in UPPER-LEFT (never bottom!)
        txt_img = _render_tilted_3d_headline(
            700, lines, font_name, accent_rgb, max_text_w=600, tilt_deg=-2.0, start_sz=146, align="left"
        )
        rgba.alpha_composite(txt_img, (18, 28))

        # Bold creator arrow pointing from upper-left text straight to the hero subject on the right
        arrow_col = (255, 42, 60) if accent != "red" else (255, 230, 0)
        rgba = _draw_mrbeast_arrow(rgba, (470, 315), (720, 415), color_rgb=arrow_col)

    elif layout == "split_vs_drama":
        rgba = _polish_photo_background(bg_source, width=width, height=height, focus_right=False)
        # Dramatic warm-vs-cool MrBeast split color tint on left vs right halves
        tint = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        td = ImageDraw.Draw(tint)
        td.rectangle([0, 0, width // 2, height], fill=(0, 140, 255, 44))
        td.rectangle([width // 2, 0, width, height], fill=(255, 45, 65, 48))
        td.line([(width // 2, 0), (width // 2, height)], fill=(255, 230, 0, 220), width=8)
        rgba = Image.alpha_composite(rgba, tint)
        rgba = _add_scrim(rgba, direction="top", strength=225)

        txt_img = _render_tilted_3d_headline(
            width, lines, font_name, accent_rgb, max_text_w=1140, tilt_deg=-1.8, start_sz=152, align="center"
        )
        tx = (width - txt_img.width) // 2
        rgba.alpha_composite(txt_img, (tx, 16))

    elif layout == "minimal_big_stat":
        rgba = _polish_photo_background(bg_source, width=width, height=height, focus_right=False)
        rgba = _add_glow_spot(rgba, accent_rgb, cx=width // 2, cy=int(height * 0.58), rx=380, ry=260, alpha=72)
        rgba = _add_scrim(rgba, direction="top", strength=210)

        txt_img = _render_tilted_3d_headline(
            width, lines, font_name, accent_rgb, max_text_w=1160, tilt_deg=0.0, start_sz=160, align="center"
        )
        tx = (width - txt_img.width) // 2
        rgba.alpha_composite(txt_img, (tx, 22))
        rgba = _draw_focus_ring(rgba, cx=width // 2, cy=int(height * 0.62), radius=128, color_rgb=accent_rgb)

    else:
        # Default: "mrbeast_top_boom" — Massive slightly-tilted TOP headline + glowing arrow + focus ring on subject
        rgba = _polish_photo_background(bg_source, width=width, height=height, focus_right=False)
        rgba = _add_glow_spot(rgba, accent_rgb, cx=width // 2, cy=int(height * 0.62), rx=360, ry=250, alpha=62)
        rgba = _add_scrim(rgba, direction="top", strength=225)

        txt_img = _render_tilted_3d_headline(
            width, lines, font_name, accent_rgb, max_text_w=1140, tilt_deg=-2.8, start_sz=154, align="center"
        )
        tx = (width - txt_img.width) // 2
        rgba.alpha_composite(txt_img, (tx, 14))

        arrow_col = (255, 42, 60) if accent != "red" else (255, 230, 0)
        rgba = _draw_mrbeast_arrow(rgba, (290, 290), (500, 445), color_rgb=arrow_col)
        rgba = _draw_focus_ring(rgba, cx=640, cy=485, radius=118, color_rgb=arrow_col)

    final_rgb = rgba.convert("RGB")
    final_rgb.save(output_path, "JPEG", quality=94, optimize=True)
    print(
        f"[Thumbnail] Saved 1280x720 MrBeast-Style Thumbnail -> {output_path} | "
        f"Font: {font_name} | Layout: {layout} | Accent: {accent}"
    )
    return output_path
