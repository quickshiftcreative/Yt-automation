import os
import textwrap
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from config import CHANNEL_NAME

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/impact.ttf",
]


def _load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def create_thumbnail(bg_image_path, headline, subtext, output_path, bulletin_badge="TECH BULLETIN"):
    """Generates a high-CTR 1280x720 dark matte black & metallic gold US News Bulletin thumbnail."""
    W, H = 1280, 720

    if bg_image_path and os.path.exists(bg_image_path):
        bg = Image.open(bg_image_path).convert("RGB")
        bg_ratio = bg.width / bg.height
        target_ratio = W / H
        if bg_ratio > target_ratio:
            new_h = H
            new_w = int(H * bg_ratio)
        else:
            new_w = W
            new_h = int(W / bg_ratio)
        bg = bg.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = (new_w - W) // 2
        top = (new_h - H) // 2
        bg = bg.crop((left, top, left + W, top + H))
        bg = ImageEnhance.Contrast(bg).enhance(1.22)
        bg = ImageEnhance.Brightness(bg).enhance(0.55)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=1.5))
    else:
        bg = Image.new("RGB", (W, H), (14, 14, 18))

    # Dark vignette overlay for maximum text readability on US mobile feeds
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    for x in range(W):
        alpha = int(220 - (x / W) * 115)
        odraw.line([(x, 0), (x, H)], fill=(10, 10, 14, max(75, min(230, alpha))))
    img = Image.alpha_composite(bg.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(img)

    # Metallic Gold luxury frame bars + crimson breaking news accent
    gold = (245, 197, 66, 255)
    gold_soft = (212, 175, 55, 255)
    crimson = (220, 38, 38, 255)

    draw.rectangle([0, 0, W, 12], fill=gold)
    draw.rectangle([0, H - 12, W, H], fill=gold)
    draw.rectangle([64, 170, 80, 565], fill=gold)

    # Top-left Brand Pill Badge ("QUICK SHIFT CREATIVE")
    badge_font = _load_font(28)
    badge_text = CHANNEL_NAME.upper()
    bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
    bw = bbox[2] - bbox[0]
    bh = bbox[3] - bbox[1]
    pad_x, pad_y = 22, 12
    bx, by = 64, 54
    draw.rounded_rectangle(
        [bx, by, bx + bw + pad_x * 2, by + bh + pad_y * 2],
        radius=10,
        fill=(18, 18, 24, 240),
        outline=gold_soft,
        width=3,
    )
    draw.text((bx + pad_x, by + pad_y - 2), badge_text, font=badge_font, fill=gold)

    # Top-right Breaking Bulletin Pill (e.g., "LIVE • AI BULLETIN")
    live_text = f"LIVE  |  {(bulletin_badge or 'TECH BULLETIN').upper()[:18]}"
    lbox = draw.textbbox((0, 0), live_text, font=badge_font)
    lw = lbox[2] - lbox[0]
    lh = lbox[3] - lbox[1]
    lx = W - 64 - (lw + pad_x * 2)
    ly = 54
    draw.rounded_rectangle(
        [lx, ly, lx + lw + pad_x * 2, ly + lh + pad_y * 2],
        radius=10,
        fill=crimson,
    )
    draw.text((lx + pad_x, ly + pad_y - 2), live_text, font=badge_font, fill=(255, 255, 255, 255))

    # Main Viral Headline (2-3 huge lines)
    headline_clean = (headline or "AI JUST SHIFTED").upper().strip()
    lines = textwrap.wrap(headline_clean, width=13)[:3]
    headline_font = _load_font(104 if len(lines) <= 2 else 86)

    y_cursor = 178
    for idx, line in enumerate(lines):
        fill_color = gold if idx == len(lines) - 1 and len(lines) > 1 else (255, 255, 255, 255)
        draw.text(
            (108, y_cursor),
            line,
            font=headline_font,
            fill=fill_color,
            stroke_width=6,
            stroke_fill=(0, 0, 0, 255),
        )
        line_box = draw.textbbox((0, 0), line, font=headline_font)
        y_cursor += (line_box[3] - line_box[1]) + 22

    # Supporting Subtext Pill
    if subtext:
        sub_clean = subtext.upper().strip()[:30]
        sub_font = _load_font(40)
        sbox = draw.textbbox((0, 0), sub_clean, font=sub_font)
        sw = sbox[2] - sbox[0]
        sh = sbox[3] - sbox[1]
        sy = min(H - 120, y_cursor + 24)
        draw.rounded_rectangle(
            [108, sy, 108 + sw + 36, sy + sh + 24],
            radius=8,
            fill=gold,
        )
        draw.text((126, sy + 9), sub_clean, font=sub_font, fill=(14, 14, 18, 255))

    final_rgb = img.convert("RGB")
    final_rgb.save(output_path, "JPEG", quality=92, optimize=True)
    print(f"[Thumbnail] Saved 1280x720 US Bulletin thumbnail -> {output_path}")
    return output_path
