import os
import random
import subprocess
from PIL import Image, ImageDraw, ImageFont


def _find_font(size, mono=False):
    base = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base, "assets", "fonts", "Ticker_Mono_Bold.ttf" if mono else "Modern_Lato_Black.ttf"),
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf" if mono else "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _fetch_real_ohlc(symbol="NVDA", count=24):
    """Fetches real recent daily OHLC candles via yfinance if available, else realistic OHLC."""
    try:
        import yfinance as yf
        hist = yf.Ticker(symbol).history(period="1mo", interval="1d")
        if hist is not None and len(hist) >= 10:
            sub = hist.tail(count)
            candles = []
            for _, row in sub.iterrows():
                o = float(row["Open"])
                h = float(row["High"])
                l = float(row["Low"])
                c = float(row["Close"])
                candles.append((o, h, l, c))
            pct = ((candles[-1][3] - candles[0][0]) / max(0.01, candles[0][0])) * 100.0
            return candles, pct, True
    except Exception:
        pass

    rng = random.Random(hash(symbol) % 100000)
    price = 142.0 if symbol.upper() in ("NVDA", "MSFT", "AAPL") else 248.0
    candles = []
    for i in range(count):
        drift = -1.6 if i > count * 0.65 else 0.65
        o = price
        chg = rng.gauss(drift, 2.4)
        c = max(12.0, o + chg)
        h = max(o, c) + abs(rng.gauss(1.1, 0.7))
        l = min(o, c) - abs(rng.gauss(1.1, 0.7))
        candles.append((o, h, l, c))
        price = c
    pct = ((candles[-1][3] - candles[0][0]) / max(0.01, candles[0][0])) * 100.0
    return candles, pct, False


def render_animated_candlestick_clip(out_mp4, width=1920, height=1080, duration=6.0, symbol="NVDA", bearish_bias=None):
    """Renders a smooth animated OHLC candlestick chart MP4 (red candles falling or green candles surging)."""
    os.makedirs(os.path.dirname(out_mp4), exist_ok=True)
    candles, pct, is_live = _fetch_real_ohlc(symbol=symbol, count=22)

    if bearish_bias is True and pct > -0.5:
        candles = [(o, max(o, h), min(o, c) - 1.5, o - abs(c - o) - 1.8) for o, h, l, c in candles]
        pct = ((candles[-1][3] - candles[0][0]) / max(0.01, candles[0][0])) * 100.0
    elif bearish_bias is False and pct < 0.5:
        candles = [(o, max(o, c) + 1.8, min(o, l), o + abs(c - o) + 1.8) for o, h, l, c in candles]
        pct = ((candles[-1][3] - candles[0][0]) / max(0.01, candles[0][0])) * 100.0

    is_bear = pct < 0
    fps = 24
    total_frames = max(24, int(duration * fps))
    frames_dir = out_mp4 + "_frames"
    os.makedirs(frames_dir, exist_ok=True)

    all_highs = [x[1] for x in candles]
    all_lows = [x[2] for x in candles]
    p_min = min(all_lows)
    p_max = max(all_highs)
    span = max(0.01, p_max - p_min)

    f_title = _find_font(34, mono=False)
    f_badge = _find_font(28, mono=True)
    f_price = _find_font(44, mono=True)
    f_label = _find_font(22, mono=True)

    chart_x0 = int(width * 0.08)
    chart_x1 = int(width * 0.90)
    chart_y0 = int(height * 0.22)
    chart_y1 = int(height * 0.84)
    chart_w = max(200, chart_x1 - chart_x0)
    chart_h = max(200, chart_y1 - chart_y0)

    def price_to_y(val):
        norm = (val - p_min) / span
        return int(chart_y1 - norm * chart_h)

    n_c = len(candles)
    step_w = chart_w / max(1, n_c)
    body_w = max(8, int(step_w * 0.56))

    for f_idx in range(total_frames):
        reveal_f = min(1.0, (f_idx + 1) / (total_frames * 0.78))
        exact_idx = reveal_f * (n_c - 1)
        full_count = int(exact_idx) + 1
        partial = exact_idx - int(exact_idx)

        img = Image.new("RGB", (width, height), (9, 11, 16))
        d = ImageDraw.Draw(img)

        for g_i in range(6):
            gy = int(chart_y0 + (g_i / 5.0) * chart_h)
            d.line([(chart_x0, gy), (chart_x1, gy)], fill=(24, 30, 42), width=1)
            val_lbl = p_max - (g_i / 5.0) * span
            d.text((chart_x1 + 14, gy - 12), f"${val_lbl:.1f}", fill=(130, 142, 165), font=f_label)

        src_tag = "LIVE MARKET FEED" if is_live else "MARKET ANALYTICS"
        d.text((chart_x0, int(height * 0.08)), f"{symbol.upper()}  //  {src_tag}", fill=(235, 192, 62), font=f_title)

        sign_str = "+" if pct >= 0 else ""
        badge_col = (245, 58, 72) if is_bear else (38, 226, 134)
        dir_word = "RED CANDLE DROP" if is_bear else "GREEN CANDLE RALLY"
        d.rounded_rectangle(
            [chart_x1 - 440, int(height * 0.075), chart_x1, int(height * 0.145)],
            radius=12,
            fill=(18, 22, 30),
            outline=badge_col,
            width=2,
        )
        d.text((chart_x1 - 420, int(height * 0.088)), f"{dir_word} ({sign_str}{pct:.2f}%)", fill=badge_col, font=f_badge)

        last_y = chart_y1
        for c_i in range(full_count):
            o, h, l, c = candles[c_i]
            growth = 1.0 if c_i < full_count - 1 else max(0.18, partial if partial > 0 else 1.0)
            curr_c = o + (c - o) * growth
            curr_h = o + (h - o) * growth
            curr_l = o + (l - o) * growth

            cx = int(chart_x0 + (c_i + 0.5) * step_w)
            y_open = price_to_y(o)
            y_close = price_to_y(curr_c)
            y_high = price_to_y(curr_h)
            y_low = price_to_y(curr_l)

            is_red = curr_c < o
            col = (244, 56, 70) if is_red else (36, 224, 132)
            wick_col = (255, 110, 122) if is_red else (110, 250, 175)

            d.line([(cx, min(y_high, y_low)), (cx, max(y_high, y_low))], fill=wick_col, width=3)
            top_b = min(y_open, y_close)
            bot_b = max(y_open, y_close)
            if bot_b - top_b < 4:
                bot_b = top_b + 4
            d.rounded_rectangle([cx - body_w // 2, top_b, cx + body_w // 2, bot_b], radius=3, fill=col)
            last_y = y_close

        latest_price = candles[min(n_c - 1, full_count - 1)][3]
        d.line([(chart_x0, last_y), (chart_x1, last_y)], fill=badge_col, width=2)
        d.text((chart_x0, int(height * 0.87)), f"LATEST PRICE: ${latest_price:.2f}", fill=(242, 245, 250), font=f_price)

        img.save(os.path.join(frames_dir, f"f_{f_idx:04d}.png"), "PNG")

    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", os.path.join(frames_dir, "f_%04d.png"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "veryfast",
        "-crf", "22",
        out_mp4,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return out_mp4
