import os
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup
from PIL import Image
from config import PIXABAY_API_KEY

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _download_file(url, dest_path, timeout=25):
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, stream=True)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
    return os.path.exists(dest_path) and os.path.getsize(dest_path) > 1024


def fetch_stock_image(query, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    q = (query or "technology").strip()

    if PEXELS_API_KEY:
        try:
            r = requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": PEXELS_API_KEY, "User-Agent": USER_AGENT},
                params={"query": q, "per_page": 6, "orientation": "landscape"},
                timeout=15,
            )
            if r.status_code == 200:
                photos = r.json().get("photos", [])
                for p in photos:
                    src_url = p.get("src", {}).get("large2x") or p.get("src", {}).get("large")
                    if src_url and _download_file(src_url, out_path):
                        return out_path
        except Exception as e:
            print(f"[Media] Pexels image fallback: {e}")

    if PIXABAY_API_KEY:
        try:
            r = requests.get(
                "https://pixabay.com/api/",
                params={
                    "key": PIXABAY_API_KEY,
                    "q": q,
                    "image_type": "photo",
                    "per_page": 6,
                    "safesearch": "true",
                },
                timeout=15,
            )
            if r.status_code == 200:
                hits = r.json().get("hits", [])
                for h in hits:
                    u = h.get("largeImageURL") or h.get("webformatURL")
                    if u and _download_file(u, out_path):
                        return out_path
        except Exception as e:
            print(f"[Media] Pixabay image fallback: {e}")

    img = Image.new("RGB", (1920, 1080), (12, 15, 22))
    img.save(out_path, "JPEG", quality=90)
    return out_path


def fetch_broll_clip(query, out_mp4, used_urls=None, is_shorts=False):
    os.makedirs(os.path.dirname(out_mp4), exist_ok=True)
    if used_urls is None:
        used_urls = set()

    q = (query or "futuristic technology").strip()
    orientation = "portrait" if is_shorts else "landscape"

    if PEXELS_API_KEY:
        try:
            r = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": PEXELS_API_KEY, "User-Agent": USER_AGENT},
                params={"query": q, "per_page": 10, "orientation": orientation},
                timeout=18,
            )
            if r.status_code == 200:
                vids = r.json().get("videos", [])
                for v in vids:
                    files = v.get("video_files", [])
                    mp4s = [vf for vf in files if vf.get("file_type") == "video/mp4" and vf.get("link")]
                    mp4s.sort(key=lambda x: abs((x.get("width") or 1280) - (1080 if is_shorts else 1920)))
                    for vf in mp4s[:3]:
                        link = vf["link"]
                        if link in used_urls:
                            continue
                        if _download_file(link, out_mp4, timeout=30):
                            used_urls.add(link)
                            return out_mp4
        except Exception as e:
            print(f"[Media] Pexels video warning ({q}): {e}")

    if PIXABAY_API_KEY:
        try:
            r = requests.get(
                "https://pixabay.com/api/videos/",
                params={"key": PIXABAY_API_KEY, "q": q, "per_page": 10, "safesearch": "true"},
                timeout=18,
            )
            if r.status_code == 200:
                hits = r.json().get("hits", [])
                for h in hits:
                    vdict = h.get("videos", {})
                    for quality in ("large", "medium", "small"):
                        vinfo = vdict.get(quality, {})
                        link = vinfo.get("url")
                        if link and link not in used_urls:
                            if _download_file(link, out_mp4, timeout=30):
                                used_urls.add(link)
                                return out_mp4
        except Exception as e:
            print(f"[Media] Pixabay video warning ({q}): {e}")

    return None


def fetch_article_image(topic_query, out_path):
    if not topic_query:
        return None
    try:
        q_enc = urllib.parse.quote_plus(topic_query[:90])
        rss_url = f"https://news.google.com/rss/search?q={q_enc}&hl=en-US&gl=US&ceid=US:en"
        r = requests.get(rss_url, headers={"User-Agent": USER_AGENT}, timeout=10)
        if r.status_code != 200:
            return None
        m = re.search(r"<link>(https?://[^<]+)</link>", r.text)
        if not m:
            return None
        art_url = m.group(1)
        page = requests.get(art_url, headers={"User-Agent": USER_AGENT}, timeout=10, allow_redirects=True)
        if page.status_code != 200:
            return None
        soup = BeautifulSoup(page.text, "html.parser")
        og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
        img_url = og.get("content") if og else ""
        if img_url and img_url.startswith("http"):
            if _download_file(img_url, out_path, timeout=15):
                with Image.open(out_path) as im:
                    w, h = im.size
                    if w >= 400 and h >= 220:
                        return out_path
    except Exception:
        pass
    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except Exception:
            pass
    return None
