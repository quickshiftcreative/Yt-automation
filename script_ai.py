import glob
import json
import os
import random
import re
import time
import xml.etree.ElementTree as ET
import requests
from config import GEMINI_API_KEY, CHANNEL_NAME
from learning_engine import fetch_youtube_autocomplete_keywords, load_strategy_memory

PRIORITY_MODELS = [
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-2.5-pro",
    "gemini-pro-latest",
    "gemma-3-27b-it",
]

MODE_RSS_FEEDS = {
    "news_bulletin": [
        "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=stock+market+OR+tech+earnings+OR+AI+business+when:1d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=gaming+industry+OR+video+game+news+when:1d&hl=en-US&gl=US&ceid=US:en",
    ],
    "trending_viral": [
        "https://news.google.com/rss/search?q=viral+game+OR+trending+streamer+OR+esports+OR+Twitch+OR+YouTube+gaming+when:2d&hl=en-US&gl=US&ceid=US:en",
        "https://trends.google.com/trending/rss?geo=US",
        "https://news.google.com/rss/search?q=trending+tech+OR+viral+AI+tool+when:2d&hl=en-US&gl=US&ceid=US:en",
    ],
    "deep_dive_evergreen": [
        "https://news.google.com/rss/search?q=high+RPM+business+OR+AI+economics+OR+chip+war+OR+market+strategy&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en",
    ],
}

SHORTS_CASUAL_OUTROS = [
    f"If you enjoyed this quick breakdown, hit like, share it with a friend, and subscribe to {CHANNEL_NAME}. Thank you for watching.",
    f"What's your take on this? Drop a quick like, share this video, and subscribe to {CHANNEL_NAME} for more. Thank you for watching.",
    f"Stay ahead of the next big shift. Tap like, share this with someone who needs to see it, and subscribe to {CHANNEL_NAME}. Thank you for watching.",
]

LONG_CASUAL_OUTROS = [
    f"If this video gave you a clearer picture of what's really happening, go ahead and hit like, share it with a friend, and subscribe to {CHANNEL_NAME} so you don't miss the next deep dive. Thank you for watching.",
    f"I'd love to hear your side in the comments below. If you found this breakdown useful, please like, share, and subscribe to {CHANNEL_NAME} for daily updates. Thank you for watching.",
    f"That wraps up today's breakdown. If you liked hanging out with us, drop a like, share this episode, and hit subscribe on {CHANNEL_NAME}. Thank you for watching.",
]

# Known high-recognition entities for real Wikimedia photo matching
KNOWN_ENTITIES = [
    ("jensen huang", "Jensen Huang"),
    ("sam altman", "Sam Altman"),
    ("elon musk", "Elon Musk"),
    ("tim cook", "Tim Cook"),
    ("satya nadella", "Satya Nadella"),
    ("sundar pichai", "Sundar Pichai"),
    ("mark zuckerberg", "Mark Zuckerberg"),
    ("dario amodei", "Dario Amodei"),
    ("nvidia", "Nvidia"),
    ("openai", "OpenAI"),
    ("anthropic", "Anthropic"),
    ("playstation", "PlayStation 5"),
    ("xbox", "Xbox Series X"),
    ("nintendo", "Nintendo Switch"),
    ("gta 6", "Grand Theft Auto VI"),
    ("grand theft auto", "Grand Theft Auto VI"),
    ("tesla", "Tesla, Inc."),
    ("apple", "Apple Inc."),
    ("microsoft", "Microsoft"),
    ("google", "Google"),
    ("amazon", "Amazon"),
    ("intel", "Intel"),
    ("amd", "Advanced Micro Devices"),
    ("bitcoin", "Bitcoin"),
    ("wall street", "Wall Street"),
    ("steam", "Steam (service)"),
]

VALID_VISUAL_TYPES = {
    "chart_down", "chart_up", "kpi_slam", "entity_photo", "news_card", "stock_video", "editorial_photo"
}


def _fetch_extra_mode_headlines(mode):
    feeds = MODE_RSS_FEEDS.get(mode, [])
    collected = []
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in feeds:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item")[:8]:
                title_el = item.find("title")
                if title_el is not None and title_el.text:
                    clean_title = re.sub(r"\s+", " ", title_el.text).strip()
                    if clean_title and clean_title not in collected:
                        collected.append(clean_title)
        except Exception as e:
            print(f"[Trends+] Extra RSS skipped ({mode}): {e}")
    return collected[:16]


def _discover_gemini_models():
    available = set()
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            skip_keywords = (
                "embedding", "aqa", "image", "veo", "tts", "audio",
                "robotics", "computer-use", "live", "vision", "learnlm",
            )
            for m in resp.json().get("models", []):
                name = m.get("name", "").replace("models/", "").strip()
                methods = m.get("supportedGenerationMethods", [])
                lname = name.lower()
                if "generateContent" in methods and not any(k in lname for k in skip_keywords):
                    if any(k in lname for k in ("flash", "pro", "gemma-3")):
                        available.add(name)
    except Exception:
        pass

    ordered = [m for m in PRIORITY_MODELS if not available or m in available]
    for name in sorted(available):
        if name not in ordered:
            ordered.append(name)
    return ordered[:10] if ordered else list(PRIORITY_MODELS)


def _extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


def _clean_narration(text):
    text = re.sub(r"[*_`#~>|[\]]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _auto_enrich_beat(beat):
    """
    Semantic Beat Analyzer: guarantees exact spoken numbers, market drops/rallies, and real entities
    always trigger matching live charts, KPI counters, or real photos instead of generic stock clips.
    """
    text = beat.get("text", "")
    low = text.lower()
    vtype = str(beat.get("visual_type", "stock_video")).strip().lower()
    if vtype not in VALID_VISUAL_TYPES:
        vtype = "stock_video"

    m_val = str(beat.get("metric_value", "")).strip()
    m_lbl = str(beat.get("metric_label", "")).strip()
    query = str(beat.get("query", "technology")).strip() or "technology"

    # Extract exact spoken metrics: points, %, or $B/$M/$T
    pts_m = re.search(r"\b(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:points?|pts?)\b", low)
    pct_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent)\b", low)
    dol_m = re.search(r"\$(\d+(?:,\d+)*(?:\.\d+)?)\s*(trillion|billion|million|[tbm])\b", low)

    drop_words = ("fell", "fall", "drop", "dropped", "crash", "crashed", "plunge", "plunged", "down", "lost", "slump", "tumbled", "wiped")
    rise_words = ("rose", "surge", "surged", "jump", "jumped", "rally", "rallied", "soar", "soared", "gained", "climbed", "record high", "up ")
    mkt_words = ("market", "stock", "index", "s&p", "nasdaq", "dow", "shares", "wall street", "trading", "price", "points", "pts")

    is_drop = any(w in low for w in drop_words)
    is_rise = any(w in low for w in rise_words)
    is_mkt = any(w in low for w in mkt_words)

    # 1. Exact Market Drop / Rally -> Force live directional Candlestick Chart with exact number!
    if (is_mkt or pts_m) and (is_drop or is_rise):
        vtype = "chart_down" if is_drop else "chart_up"
        sign = "-" if is_drop else "+"
        if not m_val:
            if pts_m:
                m_val = f"{sign}{pts_m.group(1)} PTS"
            elif pct_m:
                m_val = f"{sign}{pct_m.group(1)}%"
            elif dol_m:
                u = dol_m.group(2)[0].upper()
                m_val = f"{sign}${dol_m.group(1)}{u}"
        if not m_lbl:
            m_lbl = "MARKET SELL-OFF" if is_drop else "MARKET RALLY"

    # 2. Big Standalone Dollar / Percent Stat -> Force Animated KPI Counter Slam!
    elif vtype in ("stock_video", "editorial_photo") and (dol_m or pct_m):
        vtype = "kpi_slam"
        if not m_val:
            if dol_m:
                u = dol_m.group(2)[0].upper()
                m_val = f"-${dol_m.group(1)}{u}" if is_drop else f"${dol_m.group(1)}{u}"
            elif pct_m:
                m_val = f"-{pct_m.group(1)}%" if is_drop else f"{pct_m.group(1)}%"
        if not m_lbl:
            m_lbl = "MAJOR IMPACT" if is_drop else "KEY FIGURE"

    # 3. Named Real-World Entity -> Force Real Wikimedia/News Entity Spotlight!
    elif vtype in ("stock_video", "editorial_photo"):
        for kw, wiki_title in KNOWN_ENTITIES:
            if kw in low:
                vtype = "entity_photo"
                query = wiki_title
                if not m_lbl:
                    m_lbl = wiki_title.upper()
                break

    beat["visual_type"] = vtype
    beat["query"] = query
    beat["metric_value"] = m_val[:16]
    beat["metric_label"] = m_lbl[:34]
    return beat


def _split_narration_to_beats(narration, fallback_query, default_vtype="stock_video"):
    """Splits a flat scene narration into crisp 1-2 sentence beats if Gemini omitted explicit beats."""
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", narration) if s.strip()]
    if len(sents) <= 1:
        return [_auto_enrich_beat({"text": narration, "visual_type": default_vtype, "query": fallback_query, "metric_value": "", "metric_label": ""})]
    beats = []
    for s in sents:
        beats.append(_auto_enrich_beat({
            "text": s,
            "visual_type": default_vtype,
            "query": fallback_query,
            "metric_value": "",
            "metric_label": "",
        }))
    return beats


def _ensure_interactive_and_outro(scenes, is_shorts):
    if not scenes:
        return scenes

    has_countdown = any(s.get("interactive_type") == "countdown" for s in scenes)
    has_debate = any(s.get("interactive_type") == "debate" for s in scenes)
    has_drop = any(s.get("interactive_type") == "music_drop" for s in scenes)

    n = len(scenes)
    if n >= 5:
        if not has_countdown:
            scenes[min(2, n - 2)]["interactive_type"] = "countdown"
        if not has_drop:
            scenes[min(3, n - 2)]["interactive_type"] = "music_drop"
        if not has_debate:
            scenes[max(1, n - 2)]["interactive_type"] = "debate"

    if not is_shorts and n >= 10:
        has_cohost = any(s.get("speaker") == "cohost" for s in scenes)
        if not has_cohost:
            for pos in (5, 11, 17, 21):
                if pos < n - 2:
                    scenes[pos]["speaker"] = "cohost"

    last = scenes[-1]
    last["speaker"] = "main"
    last["interactive_type"] = "none"
    last_beats = last.get("beats") or []
    full_last = " ".join(b.get("text", "") for b in last_beats).lower()
    has_cta = ("subscribe" in full_last and "like" in full_last and "share" in full_last)
    has_thanks = ("thank you for watching" in full_last or "thanks for watching" in full_last)

    if has_cta and has_thanks:
        last["tone"] = "calm"
        return scenes

    outro_line = random.choice(SHORTS_CASUAL_OUTROS if is_shorts else LONG_CASUAL_OUTROS)
    outro_beat = {
        "text": outro_line,
        "visual_type": "editorial_photo",
        "query": "dark minimalist studio",
        "metric_value": "",
        "metric_label": "LIKE SHARE SUBSCRIBE",
    }
    if has_cta and not has_thanks and last_beats:
        last_beats[-1]["text"] = last_beats[-1]["text"].rstrip(".!? ") + ". Thank you for watching."
        last["tone"] = "calm"
    else:
        scenes.append({
            "narration": outro_line,
            "visual_query": "dark minimalist studio",
            "tone": "calm",
            "highlight_text": "Like, Share & Subscribe",
            "speaker": "main",
            "interactive_type": "none",
            "beats": [outro_beat],
        })
    return scenes


def _build_mode_instructions(mode, is_shorts):
    if mode == "trending_viral":
        role_desc = "Viral Trend & Culture Producer — sharp, opinionated, conversational US commentary."
        if is_shorts:
            structure = """
   - Scene 1 (tone: hook): Immediate 3-second conflict hook (2 punchy beats).
   - Scene 2 (tone: excited): What triggered the internet explosion (2 beats).
   - Scene 3 (tone: analytical, interactive_type: countdown): Quick 2-second viewer guess prompt (2 beats).
   - Scene 4 (tone: serious, interactive_type: music_drop): Big reveal / twist (2 beats).
   - Scene 5 (tone: urgent, interactive_type: debate): Split debate asking viewers to comment 1 or 2 (2 beats).
   - Scene 6 (tone: calm): Casual ask to like, share, subscribe + end with "Thank you for watching." (1-2 beats)."""
        else:
            structure = """
   24 rich scenes (2-3 beats each = ~60 synced visual cuts, ~1,400 spoken words):
   - Scenes 1-3: Cold Hook — straight into the viral tension.
   - Scenes 4-8: What Sparked It (+ 1 cohost analyst stat interrupt).
   - Scenes 9-13: Internet Reaction + 1 countdown quiz + 1 music_drop reveal.
   - Scenes 14-18: Deeper Psychology & Numbers (+ 1 cohost reality check).
   - Scenes 19-22: Future & 1 debate prompt (Comment 1 or 2).
   - Scenes 23-24: Warm Outro — like, share, subscribe + "Thank you for watching." """
        return role_desc, structure

    if mode == "deep_dive_evergreen":
        role_desc = "High-RPM Evergreen & Documentary Storyteller — finance, AI strategy, and business models."
        if is_shorts:
            structure = """
   - Scene 1 (tone: hook): High-curiosity money/strategy hook (2 beats).
   - Scene 2 (tone: analytical): How the business mechanics really work (2 beats).
   - Scene 3 (tone: urgent, interactive_type: countdown): Ask viewers to guess the key stat in 2 seconds (2 beats).
   - Scene 4 (tone: serious, interactive_type: music_drop): Shocking number / hidden catch reveal (2 beats).
   - Scene 5 (tone: excited, interactive_type: debate): Pick side 1 or 2 in comments (2 beats).
   - Scene 6 (tone: calm): Memorable takeaway + casual like/share/subscribe + "Thank you for watching." """
        else:
            structure = """
   24 rich scenes (2-3 beats each = ~60 synced visual cuts, ~1,400 spoken words):
   - Scenes 1-3: Irresistible Hook with concrete stat or contradiction.
   - Scenes 4-8: Core Mechanics (+ 1 cohost analyst stat check).
   - Scenes 9-13: Hard Numbers + 1 countdown quiz + 1 music_drop reveal.
   - Scenes 14-18: Hidden Risks & Competition (+ 1 cohost counter-point).
   - Scenes 19-22: Future Outlook + 1 debate prompt (Comment 1 or 2).
   - Scenes 23-24: Warm Outro — like, share, subscribe + "Thank you for watching." """
        return role_desc, structure

    role_desc = "Broadcast News & Markets Host — Gaming, Tech, AI & Markets like Vox/ColdFusion."
    if is_shorts:
        structure = """
   - Scene 1 (tone: hook): Fast breaking hook across Tech, AI, Gaming, or Markets (2 beats).
   - Scene 2 (tone: urgent): Key numbers & market reaction (2 beats).
   - Scene 3 (tone: analytical, interactive_type: countdown): Quick 2-second guess prompt (2 beats).
   - Scene 4 (tone: serious, interactive_type: music_drop): Hidden twist or financial catch (2 beats).
   - Scene 5 (tone: excited, interactive_type: debate): Clear 1-vs-2 debate for comments (2 beats).
   - Scene 6 (tone: calm): Takeaway + casual like/share/subscribe + "Thank you for watching." """
    else:
        structure = """
   24 rich scenes (2-3 beats each = ~60 synced visual cuts, ~1,400 spoken words):
   - Scenes 1-3: Opening Hook — straight into today's biggest shift.
   - Scenes 4-8: Tech & AI Segment (+ 1 cohost stat interrupt).
   - Scenes 9-13: Gaming Segment + 1 countdown quiz + 1 music_drop reveal.
   - Scenes 14-18: Market & Business Segment (exact point/percent moves + 1 cohost reality check).
   - Scenes 19-22: Cross-Sector Impact + 1 debate prompt (Comment 1 or 2).
   - Scenes 23-24: Warm Sign-Off — like, share, subscribe + "Thank you for watching." """
    return role_desc, structure


def _build_emergency_headline_blueprint(combined_topics, custom_topic, is_shorts, seo_keywords):
    print("[ScriptAI] All AI pools overloaded (503) — activating Beat-Synced Live Headlines Backup!")
    clean_heads = []
    for raw in combined_topics:
        h = re.sub(r"\s+-\s+[^-]+$", "", raw).strip()
        h = _clean_narration(h)
        if len(h) > 15 and h not in clean_heads:
            clean_heads.append(h)

    if not clean_heads:
        clean_heads = [
            custom_topic or "Tech stocks fell by 100 points as Nvidia faces fresh AI supply pressure",
            "Gaming studios rethink next-gen releases amid rising hardware costs",
            "Wall Street watches cloud AI spending hit $40 billion this quarter",
            "OpenAI and Google accelerate next-generation developer tools",
        ]

    lead_story = custom_topic.strip() if custom_topic else clean_heads[0]
    s2 = clean_heads[1 % len(clean_heads)]
    s3 = clean_heads[2 % len(clean_heads)]
    s4 = clean_heads[3 % len(clean_heads)]

    raw_scenes = [
        {
            "narration": f"Big moves just hit the tech radar today. {lead_story}.",
            "visual_query": "breaking news tech",
            "tone": "hook",
            "highlight_text": lead_story[:68],
            "speaker": "main",
            "interactive_type": "none",
        },
        {
            "narration": f"Look closer at what's happening right now. {s2}. That shift is forcing major rivals to react fast.",
            "visual_query": "ai data center",
            "tone": "urgent",
            "highlight_text": s2[:68],
            "speaker": "main",
            "interactive_type": "none",
        },
        {
            "narration": f"Pause for two seconds and ask yourself: is Wall Street overreacting here? {s3}.",
            "visual_query": "stock trading chart",
            "tone": "analytical",
            "highlight_text": "Overreaction or just starting?",
            "speaker": "main",
            "interactive_type": "countdown",
        },
        {
            "narration": f"Here's the twist most people miss at first glance. {s4}. Numbers like these rarely stay quiet.",
            "visual_query": "gaming hardware neon",
            "tone": "serious",
            "highlight_text": s4[:68],
            "speaker": "main",
            "interactive_type": "music_drop",
        },
        {
            "narration": "So where do you stand right now? Comment 1 if this is a real breakthrough, or 2 if it's pure hype.",
            "visual_query": "microchip technology",
            "tone": "excited",
            "highlight_text": "Real Shift vs Pure Hype",
            "speaker": "main",
            "interactive_type": "debate",
        },
        {
            "narration": random.choice(SHORTS_CASUAL_OUTROS),
            "visual_query": "dark minimalist studio",
            "tone": "calm",
            "highlight_text": "Like, Share & Subscribe",
            "speaker": "main",
            "interactive_type": "none",
        },
    ]

    if not is_shorts:
        raw_scenes = []
        for k in range(23):
            h_pick = clean_heads[k % len(clean_heads)]
            raw_scenes.append({
                "narration": f"Another major story shaping today's market: {h_pick}. When you connect tech, gaming, and capital markets, the bigger pattern becomes impossible to ignore.",
                "visual_query": "stock market chart" if k % 2 == 0 else "modern gaming hardware",
                "tone": "hook" if k == 0 else ("urgent" if k % 3 == 1 else "analytical"),
                "highlight_text": h_pick[:68],
                "speaker": "cohost" if k in (5, 11, 17, 20) else "main",
                "interactive_type": "countdown" if k == 9 else ("music_drop" if k == 10 else ("debate" if k == 21 else "none")),
            })
        raw_scenes.append({
            "narration": random.choice(LONG_CASUAL_OUTROS),
            "visual_query": "dark minimalist studio",
            "tone": "calm",
            "highlight_text": "Like, Share & Subscribe",
            "speaker": "main",
            "interactive_type": "none",
        })

    for sc in raw_scenes:
        sc["beats"] = _split_narration_to_beats(sc["narration"], sc["visual_query"])

    title = lead_story[:88]
    if is_shorts and "#shorts" not in title.lower():
        title += " #Shorts"

    tags = list(dict.fromkeys((seo_keywords or []) + ["tech news", "ai news", "gaming news", "stock market"]))[:18]
    return {
        "chosen_topic": lead_story,
        "category": "tech",
        "bulletin_badge": "DAILY BULLETIN",
        "title": title,
        "description": f"{lead_story}\n\nDaily Tech, AI, Gaming & Market Briefing by {CHANNEL_NAME}.\n\n#TechNews #AINews #Markets #QuickShiftCreative",
        "tags": tags,
        "thumbnail_headline": lead_story.upper()[:30],
        "thumbnail_subtext": "TECH • AI • MARKETS",
        "thumbnail_query": "technology market",
        "pinned_comment": "Quick vote: Comment 1 if you think this shift is real, or 2 if it's overhyped! 👇",
        "debate_card": {
            "option_a": "REAL BREAKTHROUGH",
            "option_b": "PURE HYPE",
            "question": "COMMENT 1 OR 2 BELOW",
        },
        "music_direction": {
            "music_query": "ambient technology electronic loop",
            "track_file": "auto",
            "mood": "news",
            "intensity": "balanced",
            "volume_scale": 0.08,
            "reason": "Clean editorial news bed",
        },
        "scenes": raw_scenes,
    }


def generate_video_blueprint(trending_topics, custom_topic=""):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing!")

    content_mode = os.getenv("CONTENT_MODE", "news_bulletin").strip().lower()
    if content_mode not in ("news_bulletin", "trending_viral", "deep_dive_evergreen"):
        content_mode = "news_bulletin"

    is_shorts = os.getenv("VIDEO_FORMAT", "horizontal").strip().lower() == "shorts"
    scene_count = "6" if is_shorts else "24"
    beats_per_scene = "2" if is_shorts else "2 to 3"
    words_per_beat = "13-16" if is_shorts else "20-26"
    duration_hint = (
        "55-62 seconds total (~165-185 spoken words across ~12 exact visual beats)"
        if is_shorts
        else "8.5 to 10 minutes total (~1,350-1,500 spoken words across ~55-65 exact visual beats)"
    )

    memory = load_strategy_memory()
    extra_headlines = [] if custom_topic else _fetch_extra_mode_headlines(content_mode)
    combined_topics = []
    for t in extra_headlines + (trending_topics or []):
        if t and t not in combined_topics:
            combined_topics.append(t)

    seed_for_seo = custom_topic.strip() if custom_topic else (combined_topics[0] if combined_topics else "tech AI news")
    live_seo_keywords = fetch_youtube_autocomplete_keywords(seed_for_seo, max_results=14)
    print(f"[SEO-Research] Live US YouTube Autocomplete ({len(live_seo_keywords)} keywords): {', '.join(live_seo_keywords[:6])}")

    recent_comments = memory.get("recent_viewer_comments") or []
    comment_hint = (
        f"Real Recent Viewer Comment (react to it naturally in 1 beat if relevant): {recent_comments[0]}"
        if recent_comments
        else "Address the viewer directly as 'you' to spark comments."
    )

    mem_hint = (
        f"100x Channel Memory -> Winning topics: {', '.join(memory.get('winning_topics', [])[:4])} | "
        f"Best title hook styles: {', '.join(memory.get('winning_title_patterns', ['curiosity_contrast']))} | "
        f"Top tags: {', '.join(memory.get('winning_keywords', [])[:8])}."
    )

    if custom_topic:
        topic_block = f"MANDATORY TOPIC: {custom_topic}"
    else:
        topics_list = "\n".join(f"- {t}" for t in combined_topics[:28])
        topic_block = f"LIVE HEADLINES & TRENDS:\n{topics_list}"

    role_desc, structure_guide = _build_mode_instructions(content_mode, is_shorts)
    format_label = "YouTube Shorts (9:16 vertical, ~58s)" if is_shorts else "Long-Form Horizontal YouTube Video (16:9, 8.5-10 min)"

    prompt = f"""You are the {role_desc} and Lead Video Editor for "{CHANNEL_NAME}".
{mem_hint}
{comment_hint}

LIVE US YOUTUBE SEARCH KEYWORDS (weave naturally into Title, SEO Description & Tags):
{', '.join(live_seo_keywords) if live_seo_keywords else 'tech news, ai news, gaming news, stock market'}

Active Mode: {content_mode.upper()}
Format: {format_label}
Target Length: {duration_hint}
Structure: EXACTLY {scene_count} scenes, and EACH scene MUST have a `"beats"` array with {beats_per_scene} micro-beats ({words_per_beat} spoken words per beat).

Scene Structure Guide:
{structure_guide}

{topic_block}

EXACT BEAT-BY-BEAT VISUAL SYNC RULES (100X CRITICAL):
Every single beat represents 1 exact visual cut synced to the exact millisecond the narrator speaks that line!
For EACH beat in `"beats"`, set `"visual_type"` strictly to the BEST match for what is being spoken:
- `"chart_down"`: Whenever mentioning a market drop, stock crash, falling points, or revenue loss (set `"metric_value"` like `"-100 PTS"` or `"-8.5%"`, `"metric_label"` like `"NASDAQ DROP"`, `"query"` to ticker/company like `"NVDA"` or `"SPY"`).
- `"chart_up"`: Whenever mentioning a rally, surge, growth, or jump (set `"metric_value"` like `"+14%"`, `"metric_label"` like `"STOCK RALLY"`, `"query"` to ticker/company).
- `"kpi_slam"`: Whenever mentioning a dramatic standalone number, price, or stat (set `"metric_value"` like `"$40B"` or `"300%"`, `"metric_label"` like `"AI SPENDING"`).
- `"entity_photo"`: Whenever naming a specific person, company, product, or game — set `"query"` to their exact Wikipedia name (e.g., `"Jensen Huang"`, `"Nvidia"`, `"PlayStation 5"`, `"Elon Musk"`, `"OpenAI"`, `"Grand Theft Auto VI"`).
- `"news_card"`: For major breaking headline reveals (set `"metric_label"` to a punchy 4-6 word headline).
- `"stock_video"`: For general action/mood B-roll — `"query"` MUST be ONLY 2-3 simple stock words (e.g., `"server room"`, `"stock traders"`, `"gaming setup"` — NEVER write long sentences!).
- `"editorial_photo"`: For clean HD photo backdrop — `"query"` MUST be ONLY 2-3 simple words.

Human-Like Voice & SEO Rules:
- Use natural US contractions ("don't", "here's", "that's", "you're") and punchy human phrasing. NEVER use AI clichés ("delve", "game-changer", "landscape", "buckle up", "revolutionary", "in conclusion", "welcome back").
- FINAL SCENE OUTRO: Casual, warm invite to like, share, and subscribe to {CHANNEL_NAME}, ending with "Thank you for watching."
- `thumbnail_headline`: ULTRA-SHORT 2 to 4 bold power words matching the exact topic (zero clickbait).
- `tags`: 14-18 short, clean US search keywords (no # symbols).
- `speaker`: `"main"` normally; {'for Long videos set `"cohost"` on 3-4 analytical stat-check scenes.' if not is_shorts else 'keep `"main"` for Shorts.'}

Return ONLY valid JSON:
{{
  "chosen_topic": "string",
  "category": "tech",
  "bulletin_badge": "DAILY BULLETIN",
  "title": "string",
  "description": "string",
  "tags": ["kw1", "kw2"],
  "thumbnail_headline": "NVIDIA SHOCK DROP",
  "thumbnail_subtext": "REAL IMPACT",
  "thumbnail_query": "nvidia chip",
  "pinned_comment": "string",
  "debate_card": {{
    "option_a": "REAL SHIFT",
    "option_b": "PURE HYPE",
    "question": "COMMENT 1 OR 2 BELOW"
  }},
  "music_direction": {{
    "music_query": "ambient technology electronic loop",
    "track_file": "auto",
    "mood": "news",
    "intensity": "balanced",
    "volume_scale": 0.08,
    "reason": "short explanation"
  }},
  "scenes": [
    {{
      "tone": "hook",
      "speaker": "main",
      "interactive_type": "none",
      "highlight_text": "Short 5-word highlight",
      "beats": [
        {{
          "text": "The market just fell by 100 points in under an hour.",
          "visual_type": "chart_down",
          "query": "SPY",
          "metric_value": "-100 PTS",
          "metric_label": "S&P 500 DROP"
        }},
        {{
          "text": "And Jensen Huang just stepped right into the middle of the storm.",
          "visual_type": "entity_photo",
          "query": "Jensen Huang",
          "metric_value": "",
          "metric_label": "NVIDIA CEO"
        }}
      ]
    }}
  ]
}}
"""

    max_tokens = 3800 if is_shorts else 8192
    models_to_try = _discover_gemini_models()
    last_error = None
    valid_tones = {"hook", "urgent", "excited", "serious", "analytical", "calm"}
    valid_inter = {"none", "countdown", "debate", "music_drop"}

    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        gen_cfg = {"temperature": 0.75, "maxOutputTokens": max_tokens}
        if "gemma" not in model.lower():
            gen_cfg["responseMimeType"] = "application/json"

        payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen_cfg}

        for attempt in range(2):
            try:
                resp = requests.post(url, json=payload, timeout=120)
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_error = f"{model} HTTP {resp.status_code} (attempt {attempt + 1})"
                    print(f"[ScriptAI] {last_error}, retrying in {5 * (attempt + 1)}s...")
                    time.sleep(5 * (attempt + 1))
                    continue
                if resp.status_code != 200:
                    last_error = f"{model} HTTP {resp.status_code}: {resp.text[:180]}"
                    break

                raw_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                blueprint = _extract_json(raw_text)
                if not blueprint.get("title") or not blueprint.get("scenes"):
                    raise ValueError("Missing title or scenes")

                cat = str(blueprint.get("category", "tech")).strip().lower()
                blueprint["category"] = cat if cat in ("ai", "tech", "gaming") else "tech"
                blueprint["bulletin_badge"] = str(blueprint.get("bulletin_badge", "DAILY BULLETIN")).upper().strip()[:18]
                blueprint["title"] = blueprint["title"].strip()[:98]
                if is_shorts and "#shorts" not in blueprint["title"].lower() and len(blueprint["title"]) <= 90:
                    blueprint["title"] += " #Shorts"

                raw_tags = [str(t).strip() for t in (blueprint.get("tags") or []) if str(t).strip()]
                blueprint["tags"] = list(dict.fromkeys(raw_tags + live_seo_keywords))[:18]

                blueprint["pinned_comment"] = str(
                    blueprint.get("pinned_comment", "What's your take — comment 1 or 2 below! 👇")
                ).strip()[:280]

                dc = blueprint.get("debate_card") or {}
                blueprint["debate_card"] = {
                    "option_a": str(dc.get("option_a", "REAL SHIFT")).upper().strip()[:22],
                    "option_b": str(dc.get("option_b", "PURE HYPE")).upper().strip()[:22],
                    "question": str(dc.get("question", "COMMENT 1 OR 2 BELOW")).upper().strip()[:32],
                }

                md = blueprint.get("music_direction") or {}
                try:
                    v_scale = float(md.get("volume_scale", 0.08))
                except Exception:
                    v_scale = 0.08
                blueprint["music_direction"] = {
                    "music_query": str(md.get("music_query", "ambient electronic background loop")).strip(),
                    "track_file": str(md.get("track_file", "auto")).strip(),
                    "mood": str(md.get("mood", "news")).strip().lower(),
                    "intensity": str(md.get("intensity", "balanced")).strip().lower(),
                    "volume_scale": max(0.055, min(0.115, v_scale)),
                    "reason": str(md.get("reason", "Balanced editorial music bed")).strip(),
                }

                cleaned_scenes = []
                total_beats = 0
                for idx_s, sc in enumerate(blueprint["scenes"]):
                    tone = str(sc.get("tone", "hook" if idx_s == 0 else "analytical")).strip().lower()
                    if tone not in valid_tones:
                        tone = "analytical"
                    spk = str(sc.get("speaker", "main")).strip().lower()
                    if spk not in ("main", "cohost") or is_shorts:
                        spk = "main"
                    itype = str(sc.get("interactive_type", "none")).strip().lower()
                    if itype not in valid_inter:
                        itype = "none"

                    raw_beats = sc.get("beats") or []
                    clean_beats = []
                    for b in raw_beats:
                        b_txt = _clean_narration(b.get("text", ""))
                        if not b_txt:
                            continue
                        clean_beats.append(_auto_enrich_beat({
                            "text": b_txt,
                            "visual_type": b.get("visual_type", "stock_video"),
                            "query": b.get("query", sc.get("visual_query", "technology")),
                            "metric_value": b.get("metric_value", ""),
                            "metric_label": b.get("metric_label", ""),
                        }))

                    if not clean_beats:
                        fallback_nar = _clean_narration(sc.get("narration", ""))
                        if not fallback_nar:
                            continue
                        clean_beats = _split_narration_to_beats(fallback_nar, sc.get("visual_query", "technology"))

                    total_beats += len(clean_beats)
                    cleaned_scenes.append({
                        "narration": " ".join(b["text"] for b in clean_beats),
                        "visual_query": clean_beats[0]["query"],
                        "tone": tone,
                        "highlight_text": _clean_narration(sc.get("highlight_text", ""))[:72],
                        "speaker": spk,
                        "interactive_type": itype,
                        "beats": clean_beats,
                    })

                cleaned_scenes = _ensure_interactive_and_outro(cleaned_scenes, is_shorts)
                blueprint["scenes"] = cleaned_scenes
                if not blueprint["scenes"]:
                    raise ValueError("Empty scenes")
                print(
                    f"[ScriptAI] Beat-Synced Blueprint ready with {model} "
                    f"({len(blueprint['scenes'])} scenes -> {total_beats} exact visual beats)"
                )
                return blueprint
            except Exception as e:
                last_error = f"{model} error: {e}"
                break

    print(f"[ScriptAI] Warning ({last_error})")
    return _build_emergency_headline_blueprint(combined_topics, custom_topic, is_shorts, live_seo_keywords)
