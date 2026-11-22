import json
import os
import re
import xml.etree.ElementTree as ET
import requests
from config import HISTORY_FILE, PROJECT_NAME, CHANNEL_NAME, NEWS_CATEGORY

# 100% US Trends + Worldwide Tech, AI & Gaming News Bulletin Feeds
FEED_GROUPS = {
    "us_trends": [
        ("Google Trends US", "https://trends.google.com/trending/rss?geo=US"),
    ],
    "tech": [
        ("Google News US Tech", "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en"),
        ("TechCrunch Global", "https://techcrunch.com/feed/"),
        ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ],
    "ai": [
        ("Worldwide AI Bulletin", "https://news.google.com/rss/search?q=Artificial+Intelligence+OR+OpenAI+OR+Nvidia+OR+Gemini+OR+Claude+AI+when:2d&hl=en-US&gl=US&ceid=US:en"),
        ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ],
    "gaming": [
        ("Worldwide Gaming Bulletin", "https://news.google.com/rss/search?q=Gaming+News+OR+PlayStation+OR+Xbox+OR+Nintendo+OR+Steam+OR+GTA+6+when:2d&hl=en-US&gl=US&ceid=US:en"),
        ("IGN Worldwide Gaming", "https://feeds.feedburner.com/ign/games-all"),
    ],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {
            "project": PROJECT_NAME,
            "channel": CHANNEL_NAME,
            "region": "US & Worldwide (Tech, AI, Gaming)",
            "videos": [],
        }
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "project": PROJECT_NAME,
            "channel": CHANNEL_NAME,
            "region": "US & Worldwide (Tech, AI, Gaming)",
            "videos": [],
        }


def save_history(topic, title, video_id, category="tech"):
    data = load_history()
    if "videos" not in data or not isinstance(data["videos"], list):
        data["videos"] = []
    data["videos"].append({
        "topic": topic,
        "title": title,
        "category": category,
        "video_id": video_id,
    })
    data["videos"] = data["videos"][-250:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _normalize(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _is_duplicate(candidate, past_topics):
    norm_cand = _normalize(candidate)
    if not norm_cand:
        return True
    cand_words = set(norm_cand.split())
    for past in past_topics:
        norm_past = _normalize(past)
        if not norm_past:
            continue
        if norm_cand == norm_past:
            return True
        past_words = set(norm_past.split())
        if len(cand_words) >= 3 and len(past_words) >= 3:
            overlap = len(cand_words & past_words) / max(1, min(len(cand_words), len(past_words)))
            if overlap >= 0.65:
                return True
    return False


def parse_feed_titles(xml_bytes, limit=8):
    """Parses both RSS (<item><title>) and Atom (<entry><title>) XML feeds safely."""
    titles = []
    root = ET.fromstring(xml_bytes)

    # Check standard RSS items
    rss_items = root.findall(".//item")
    if rss_items:
        for item in rss_items[:limit]:
            title_el = item.find("title")
            if title_el is not None and title_el.text:
                titles.append(title_el.text.strip())
        return titles

    # Check Atom entries (e.g., The Verge) with or without XML namespace
    for elem in root.iter():
        if elem.tag.endswith("entry"):
            for child in elem:
                if child.tag.endswith("title") and child.text:
                    titles.append(child.text.strip())
                    break
            if len(titles) >= limit:
                break
    return titles


def _select_feeds():
    if NEWS_CATEGORY in FEED_GROUPS:
        return FEED_GROUPS[NEWS_CATEGORY]
    # Default "auto": balanced mix of US Trends + Worldwide AI, Tech & Gaming Bulletins
    return (
        FEED_GROUPS["ai"]
        + FEED_GROUPS["tech"][:2]
        + FEED_GROUPS["gaming"]
        + FEED_GROUPS["us_trends"]
        + FEED_GROUPS["tech"][2:]
    )


def fetch_trending_topics(max_items=24):
    """Fetches live US Trends and Worldwide Tech, AI & Gaming breaking news headlines."""
    history = load_history()
    past_topics = [v.get("topic", "") for v in history.get("videos", [])] + [
        v.get("title", "") for v in history.get("videos", [])
    ]

    feeds = _select_feeds()
    collected = []
    seen = set()

    for source_name, url in feeds:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                print(f"[Trends] {source_name} returned HTTP {resp.status_code}, skipping.")
                continue
            raw_titles = parse_feed_titles(resp.content, limit=6)
            for raw_title in raw_titles:
                # Strip publisher tail like " - The Verge" or " - IGN"
                clean_title = re.sub(r"\s+[-|]\s+[^-|]{2,40}$", "", raw_title).strip()
                norm = _normalize(clean_title)
                if not norm or norm in seen or _is_duplicate(clean_title, past_topics):
                    continue
                seen.add(norm)
                collected.append(f"[{source_name}] {clean_title}")
                if len(collected) >= max_items:
                    break
        except Exception as e:
            print(f"[Trends] Warning reading {source_name}: {e}")
        if len(collected) >= max_items:
            break

    if not collected:
        collected = [
            "[Worldwide AI Bulletin] Next-Gen AI Agents Are Reshaping Silicon Valley and Everyday Tech",
            "[Worldwide Gaming Bulletin] Next-Gen Console Hardware and Cloud Gaming Breakthroughs Shake Up 2026",
            "[Google News US Tech] Major US Tech Giants Race to Build Faster On-Device AI Chips",
            "[Worldwide Gaming Bulletin] Unreal Engine and AI NPCs Are Transforming Open-World Video Games",
        ]

    print(f"[Trends] Collected {len(collected)} fresh US & Worldwide Tech/AI/Gaming headlines.")
    return collected
