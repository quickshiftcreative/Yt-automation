import os
import random
import urllib.parse
import requests
from config import PIXABAY_API_KEY, VIDEO_FORMAT

FALLBACK_QUERIES = [
    "futuristic technology",
    "artificial intelligence",
    "gaming computer",
    "digital circuit",
    "cyberpunk neon",
    "server room",
]


def _download_file(url, dest_path):
    resp = requests.get(url, stream=True, timeout=45)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 64):
            if chunk:
                f.write(chunk)
    return dest_path


def fetch_stock_video(query, dest_path, used_ids=None):
    """Fetch an HD Tech/AI/Gaming stock video from Pixabay. Falls back to HD image if needed."""
    if used_ids is None:
        used_ids = set()
    if not PIXABAY_API_KEY:
        raise RuntimeError("PIXABAY_API_KEY is missing! Add it to GitHub Secrets or config.env.")

    queries_to_try = [query] + [q for q in query.split()[:1] if len(q) > 3] + [random.choice(FALLBACK_QUERIES)]

    for q in queries_to_try:
        encoded = urllib.parse.quote(q)
        url = (
            f"https://pixabay.com/api/videos/?key={PIXABAY_API_KEY}"
            f"&q={encoded}&per_page=10&safesearch=true&video_type=film"
        )
        try:
            resp = requests.get(url, timeout=20)
            if resp.status_code != 200:
                continue
            hits = resp.json().get("hits", [])
            random.shuffle(hits)
            for hit in hits:
                vid_id = hit.get("id")
                if vid_id in used_ids:
                    continue
                videos = hit.get("videos", {})
                candidate = (
                    videos.get("medium", {}).get("url")
                    or videos.get("large", {}).get("url")
                    or videos.get("small", {}).get("url")
                )
                if candidate:
                    used_ids.add(vid_id)
                    _download_file(candidate, dest_path)
                    print(f"[Pixabay] Downloaded stock video for '{q}' (id={vid_id})")
                    return dest_path, "video"
        except Exception as e:
            print(f"[Pixabay] Video search warning for '{q}': {e}")

    img_path = os.path.splitext(dest_path)[0] + ".jpg"
    fetched_img = fetch_stock_image(query, img_path)
    if fetched_img:
        return fetched_img, "image"
    return None, "fallback"


def fetch_stock_image(query, dest_path):
    """Fetch a high-resolution Tech/AI/Gaming image from Pixabay."""
    if not PIXABAY_API_KEY:
        return None

    orientation = "vertical" if VIDEO_FORMAT == "shorts" and "thumb" not in dest_path.lower() else "horizontal"
    queries_to_try = [query, random.choice(FALLBACK_QUERIES), "dark futuristic technology"]

    for q in queries_to_try:
        encoded = urllib.parse.quote(q)
        url = (
            f"https://pixabay.com/api/?key={PIXABAY_API_KEY}"
            f"&q={encoded}&image_type=photo&orientation={orientation}&per_page=10&safesearch=true"
        )
        try:
            resp = requests.get(url, timeout=20)
            if resp.status_code != 200:
                continue
            hits = resp.json().get("hits", [])
            if hits:
                pick = random.choice(hits[:5])
                img_url = pick.get("largeImageURL") or pick.get("webformatURL")
                if img_url:
                    _download_file(img_url, dest_path)
                    print(f"[Pixabay] Downloaded image for '{q}'")
                    return dest_path
        except Exception as e:
            print(f"[Pixabay] Image search warning for '{q}': {e}")
    return None
