import os
import random
import re
import urllib.parse
import requests
from bs4 import BeautifulSoup
from PIL import Image
from config import PIXABAY_API_KEY

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()
FREESOUND_API_KEY = os.getenv("FREESOUND_API_KEY", "").strip()
GIPHY_API_KEY = os.getenv("GIPHY_API_KEY", "").strip()
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "").strip()

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
WIKI_USER_AGENT = "QuickShiftCreativeBot/2.0 (https://github.com/quickshiftcreative; educational-media)"

STOP_VISUAL_WORDS = {
    "a", "an", "the", "with", "over", "in", "on", "of", "and", "or", "for", "to", "at", "by",
    "from", "into", "about", "appearing", "centered", "screen", "text", "bold", "snippet",
    "capture", "message", "icon", "photo", "photos", "side", "wearing", "holding", "during",
    "background", "showing", "made", "single", "headline", "logos", "logo", "error", "warning",
    "modern", "smiling", "jacket", "lines", "glowing", "high", "low", "red", "gold", "green",
}


def _simplify_stock_query(query, max_words=3):
    clean = re.sub(r"['\"].*?['\"]", " ", str(query or ""))
    clean = re.sub(r"[^a-zA-Z0-9\s]", " ", clean)
    words = [w for w in clean.split() if len(w) > 2 and w.lower() not in STOP_VISUAL_WORDS]
    if not words:
        words = [w for w in clean.split() if len(w) > 2]
    if not words:
        return "technology"
    return " ".join(words[:max_words])


def _download_file(url, dest_path, timeout=20, min_bytes=1024, user_agent=USER_AGENT):
    resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=timeout, stream=True)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
    return os.path.exists(dest_path) and os.path.getsize(dest_path) > min_bytes


def _is_valid_raster_image(path, min_w=320, min_h=200):
    try:
        with Image.open(path) as im:
            im.load()
            return im.width >= min_w and im.height >= min_h
    except Exception:
        return False


def fetch_wikimedia_entity_image(entity_name, out_path):
    """Fetches a real photo of a person, company, product, or game via Wikipedia/Wikimedia (100% free, no key)."""
    if not entity_name:
        return None
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    clean_ent = re.sub(r"[^a-zA-Z0-9\s\-\.&]", " ", str(entity_name)).strip()
    if not clean_ent:
        return None

    headers = {"User-Agent": WIKI_USER_AGENT}
    candidate_urls = []

    # 1. Direct Wikipedia REST Summary lookup
    try:
        slug = urllib.parse.quote(clean_ent.replace(" ", "_"))
        r = requests.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}", headers=headers, timeout=8)
        if r.status_code == 200:
            data = r.json()
            for k in ("originalimage", "thumbnail"):
                src = (data.get(k) or {}).get("source", "")
                if src and not src.lower().endswith(".svg"):
                    candidate_urls.append(src)
    except Exception:
        pass

    # 2. Wikipedia Search -> PageImages fallback (handles partial names like "GTA 6" or "Jensen Huang Nvidia")
    if not candidate_urls:
        try:
            sr = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "generator": "search",
                    "gsrsearch": clean_ent,
                    "gsrlimit": 3,
                    "prop": "pageimages",
                    "pithumbsize": 1200,
                    "format": "json",
                },
                headers=headers,
                timeout=8,
            )
            if sr.status_code == 200:
                pages = (sr.json().get("query") or {}).get("pages") or {}
                for pg in pages.values():
                    src = (pg.get("thumbnail") or {}).get("source", "")
                    if src and not src.lower().endswith(".svg"):
                        candidate_urls.append(src)
        except Exception:
            pass

    for u in candidate_urls[:3]:
        try:
            if _download_file(u, out_path, timeout=12, min_bytes=4096, user_agent=WIKI_USER_AGENT):
                if _is_valid_raster_image(out_path, min_w=320, min_h=200):
                    print(f"[WikiEntity] Real photo matched for '{clean_ent}'")
                    return out_path
        except Exception:
            pass

    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except Exception:
            pass
    return None


def fetch_freesound_sfx(query, out_mp3):
    if not FREESOUND_API_KEY:
        return None
    os.makedirs(os.path.dirname(out_mp3), exist_ok=True)
    try:
        r = requests.get(
            "https://freesound.org/apiv2/search/text/",
            params={
                "query": query,
                "filter": 'license:"Creative Commons 0" duration:[0.2 TO 3.5]',
                "fields": "id,name,previews",
                "sort": "rating_desc",
                "page_size": 8,
                "token": FREESOUND_API_KEY,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=12,
        )
        if r.status_code != 200:
            return None
        results = r.json().get("results", [])
        if not results:
            return None
        random.shuffle(results)
        for item in results[:4]:
            previews = item.get("previews", {})
            mp3_url = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3")
            if mp3_url and _download_file(mp3_url, out_mp3, timeout=18, min_bytes=1024):
                print(f"[Freesound] CC0 SFX: {item.get('name', query)}")
                return out_mp3
    except Exception as e:
        print(f"[Freesound] SFX warning ({query}): {e}")
    return None


def fetch_freesound_music(query, out_mp3):
    if not FREESOUND_API_KEY:
        return None
    os.makedirs(os.path.dirname(out_mp3), exist_ok=True)
    search_queries = [
        (query or "ambient technology background").strip(),
        "ambient electronic background loop",
    ]
    for q in search_queries:
        try:
            r = requests.get(
                "https://freesound.org/apiv2/search/text/",
                params={
                    "query": q,
                    "filter": 'license:"Creative Commons 0" duration:[35 TO 240]',
                    "fields": "id,name,duration,previews",
                    "sort": "rating_desc",
                    "page_size": 10,
                    "token": FREESOUND_API_KEY,
                },
                headers={"User-Agent": USER_AGENT},
                timeout=15,
            )
            if r.status_code != 200:
                continue
            results = r.json().get("results", [])
            if not results:
                continue
            random.shuffle(results)
            for item in results[:5]:
                previews = item.get("previews", {})
                mp3_url = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3")
                if mp3_url and _download_file(mp3_url, out_mp3, timeout=30, min_bytes=40960):
                    dur_val = float(item.get("duration", 0))
                    print(f"[FreesoundMusic] Downloaded CC0 BGM: {item.get('name', q)} ({dur_val:.0f}s)")
                    return out_mp3
        except Exception as e:
            print(f"[FreesoundMusic] Warning ({q}): {e}")
    return None


def fetch_giphy_sticker(query, out_gif):
    if not GIPHY_API_KEY:
        return None
    os.makedirs(os.path.dirname(out_gif), exist_ok=True)
    q = _simplify_stock_query(query or "trending", max_words=3)

    for endpoint in ("https://api.giphy.com/v1/stickers/search", "https://api.giphy.com/v1/gifs/search"):
        try:
            r = requests.get(
                endpoint,
                params={
                    "api_key": GIPHY_API_KEY,
                    "q": q,
                    "limit": 8,
                    "rating": "pg-13",
                    "lang": "en",
                },
                headers={"User-Agent": USER_AGENT},
                timeout=10,
            )
            if r.status_code != 200:
                continue
            items = r.json().get("data", [])
            if not items:
                continue
            random.shuffle(items)
            for it in items[:4]:
                imgs = it.get("images", {})
                gif_url = (
                    imgs.get("fixed_height", {}).get("url")
                    or imgs.get("downsized", {}).get("url")
                    or imgs.get("original", {}).get("url")
                )
                if gif_url and _download_file(gif_url, out_gif, timeout=16):
                    try:
                        with Image.open(out_gif) as im:
                            if im.size[0] >= 80 and im.size[1] >= 80:
                                return out_gif
                    except Exception:
                        pass
        except Exception as e:
            print(f"[Giphy] Warning ({q}): {e}")

    if os.path.exists(out_gif):
        try:
            os.remove(out_gif)
        except Exception:
            pass
    return None


def fetch_unsplash_photo(query, out_path, orientation="landscape", used_urls=None):
    if not UNSPLASH_ACCESS_KEY:
        return None
    if used_urls is None:
        used_urls = set()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    q = _simplify_stock_query(query, max_words=3)
    try:
        r = requests.get(
            "https://api.unsplash.com/search/photos",
            headers={
                "Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}",
                "Accept-Version": "v1",
                "User-Agent": USER_AGENT,
            },
            params={
                "query": q,
                "per_page": 10,
                "orientation": orientation,
                "content_filter": "high",
            },
            timeout=10,
        )
        if r.status_code == 200:
            for item in r.json().get("results", []):
                urls = item.get("urls", {})
                u = urls.get("regular") or urls.get("full")
                if u and u not in used_urls:
                    if _download_file(u, out_path, timeout=16) and _is_valid_raster_image(out_path, 300, 200):
                        used_urls.add(u)
                        return out_path
    except Exception as e:
        print(f"[Unsplash] Photo warning ({q}): {e}")
    return None


def fetch_stock_image(query, out_path, orientation="landscape", used_urls=None):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    q = _simplify_stock_query(query, max_words=3)

    u_hit = fetch_unsplash_photo(q, out_path, orientation=orientation, used_urls=used_urls)
    if u_hit:
        return u_hit

    if PEXELS_API_KEY:
        try:
            r = requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": PEXELS_API_KEY, "User-Agent": USER_AGENT},
                params={"query": q, "per_page": 6, "orientation": orientation},
                timeout=9,
            )
            if r.status_code == 200:
                for p in r.json().get("photos", []):
                    src_url = p.get("src", {}).get("large2x") or p.get("src", {}).get("large")
                    if src_url and (used_urls is None or src_url not in used_urls):
                        if _download_file(src_url, out_path, timeout=16) and _is_valid_raster_image(out_path, 300, 200):
                            if used_urls is not None:
                                used_urls.add(src_url)
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
                    "per_page": 8,
                    "safesearch": "true",
                },
                timeout=9,
            )
            if r.status_code == 200:
                for h in r.json().get("hits", []):
                    u = h.get("largeImageURL") or h.get("webformatURL")
                    if u and (used_urls is None or u not in used_urls):
                        if _download_file(u, out_path, timeout=16) and _is_valid_raster_image(out_path, 300, 200):
                            if used_urls is not None:
                                used_urls.add(u)
                            return out_path
        except Exception as e:
            print(f"[Media] Pixabay image fallback ({q}): {e}")

    img = Image.new("RGB", (1920, 1080), (12, 15, 22))
    img.save(out_path, "JPEG", quality=90)
    return out_path


def fetch_broll_clip(query, out_mp4, used_urls=None, is_shorts=False):
    os.makedirs(os.path.dirname(out_mp4), exist_ok=True)
    if used_urls is None:
        used_urls = set()

    q = _simplify_stock_query(query, max_words=3)
    orientation = "portrait" if is_shorts else "landscape"

    if PEXELS_API_KEY:
        try:
            r = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": PEXELS_API_KEY, "User-Agent": USER_AGENT},
                params={"query": q, "per_page": 10, "orientation": orientation},
                timeout=9,
            )
            if r.status_code == 200:
                for v in r.json().get("videos", []):
                    files = v.get("video_files", [])
                    mp4s = [vf for vf in files if vf.get("file_type") == "video/mp4" and vf.get("link")]
                    mp4s.sort(key=lambda x: abs((x.get("width") or 1280) - (1080 if is_shorts else 1920)))
                    for vf in mp4s[:3]:
                        link = vf["link"]
                        if link in used_urls:
                            continue
                        if _download_file(link, out_mp4, timeout=20, min_bytes=30000):
                            used_urls.add(link)
                            return out_mp4
        except Exception as e:
            print(f"[Media] Pexels video warning ({q}): {e}")

    if PIXABAY_API_KEY:
        try:
            r = requests.get(
                "https://pixabay.com/api/videos/",
                params={"key": PIXABAY_API_KEY, "q": q, "per_page": 10, "safesearch": "true"},
                timeout=9,
            )
            if r.status_code == 200:
                for h in r.json().get("hits", []):
                    vdict = h.get("videos", {})
                    for quality in ("medium", "large", "small"):
                        vinfo = vdict.get(quality, {})
                        link = vinfo.get("url")
                        if link and link not in used_urls:
                            if _download_file(link, out_mp4, timeout=20, min_bytes=30000):
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
        r = requests.get(rss_url, headers={"User-Agent": USER_AGENT}, timeout=9)
        if r.status_code != 200:
            return None
        m = re.search(r"<link>(https?://[^<]+)</link>", r.text)
        if not m:
            return None
        art_url = m.group(1)
        page = requests.get(art_url, headers={"User-Agent": USER_AGENT}, timeout=9, allow_redirects=True)
        if page.status_code != 200:
            return None
        soup = BeautifulSoup(page.text, "html.parser")
        og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
        img_url = og.get("content") if og else ""
        if img_url and img_url.startswith("http"):
            if _download_file(img_url, out_path, timeout=14, min_bytes=5000):
                if _is_valid_raster_image(out_path, 400, 220):
                    return out_path
    except Exception:
        pass
    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except Exception:
            pass
    return None
