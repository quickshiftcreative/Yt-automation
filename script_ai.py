import glob
import json
import os
import re
import time
import xml.etree.ElementTree as ET
import requests
from config import GEMINI_API_KEY, CHANNEL_NAME
from learning_engine import load_strategy_memory

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


def _list_local_music_tracks():
    root = os.path.dirname(os.path.abspath(__file__))
    tracks = []
    for folder in (os.path.join(root, "assets", "music"), os.path.join(root, "assets", "music_beds")):
        if os.path.isdir(folder):
            for ext in ("*.mp3", "*.wav", "*.m4a"):
                for p in sorted(glob.glob(os.path.join(folder, ext))):
                    name = os.path.basename(p)
                    if name not in tracks:
                        tracks.append(name)
    return tracks


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
    """Discovers available Flash, Pro, and Gemma-3 models across separate backend pools."""
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
    if not ordered:
        ordered = list(PRIORITY_MODELS)
    return ordered[:10]


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


def _build_mode_instructions(mode, is_shorts):
    if mode == "trending_viral":
        role_desc = (
            "Viral Trend & Culture Producer — capturing whatever is genuinely blowing up right now "
            "(games, pop culture, viral moments, or major US talking points) with sharp, human commentary."
        )
        if is_shorts:
            structure = """
   - Scene 1 (tone: hook): Immediate 3-second conflict hook naming what is blowing up and why it matters.
   - Scenes 2-4 (tones: excited / urgent / serious): Key details, real crowd reaction, and the unexpected twist.
   - Scene 5 (tone: calm): Sharp verdict + viewer question + Quick Shift Creative CTA."""
        else:
            structure = """
   Structure the 36 scenes around the #1 viral/trending topic exploding right now:
   - Scenes 1-3 (Cold Hook): Drop straight into the tension — zero "welcome back" intros.
   - Scenes 4-10 (What Sparked It): How the trend, game, or creator moment took off so fast.
   - Scenes 11-18 (Internet & Crowd Reaction): Real perspectives, debates, and standout moments.
   - Scenes 19-26 (Why It Hit So Hard): Psychological, cultural, or market reasons behind the hype.
   - Scenes 27-33 (Where It Goes Next): Will it fade in a week or reshape the space?
   - Scenes 34-36 (Closing Take): Honest wrap-up, comment question, and Quick Shift Creative subscribe cue."""
        return role_desc, structure

    if mode == "deep_dive_evergreen":
        role_desc = (
            "High-RPM Evergreen & Documentary Storyteller — crafting high-retention stories "
            "across finance, AI/tech strategy, business models, and high-interest topics."
        )
        if is_shorts:
            structure = """
   - Scene 1 (tone: hook): High-curiosity money/strategy hook.
   - Scenes 2-4 (tones: analytical / serious / excited): Clear breakdown of how it works and the hidden catch.
   - Scene 5 (tone: calm): Strong takeaway + Quick Shift Creative subscribe cue."""
        else:
            structure = """
   Structure the 36 scenes for maximum watch time, US RPM, and subscriber conversion:
   - Scenes 1-3 (Irresistible Hook): Start with a striking insight, stat, or contradiction that pulls viewers in.
   - Scenes 4-10 (Origin & Core Mechanics): Explain the backstory and how the system/business actually operates.
   - Scenes 11-18 (The Numbers & Leverage): Break down margins, incentives, market forces, or key comparisons.
   - Scenes 19-26 (Hidden Bottlenecks & Competition): What most people overlook and how rivals respond.
   - Scenes 27-33 (Future Outlook): Realistic scenarios and what to watch next.
   - Scenes 34-36 (Final Takeaway): Crisp summary, comment prompt, and Quick Shift Creative subscribe cue."""
        return role_desc, structure

    role_desc = (
        "Broadcast News & Markets Host — covering Gaming, Tech, AI, and Business/Market news "
        "in a natural, conversational human voice like Vox or ColdFusion."
    )
    if is_shorts:
        structure = """
   - Scene 1 (tone: hook): Fast breaking hook across Gaming, Tech, AI, or Market/Business news.
   - Scenes 2-4 (tones: urgent / analytical / serious): Key numbers, market reaction, and real-world impact.
   - Scene 5 (tone: calm): Bottom-line takeaway + Quick Shift Creative CTA."""
    else:
        structure = """
   Structure the 36 scenes as a crisp multi-segment briefing covering Gaming, Tech, AI, and Business/Market news:
   - Scenes 1-3 (Opening Hook): Drop right into the biggest headline and stakes without cliché intros.
   - Scenes 4-11 (Tech & AI Segment): Key product, model, or infrastructure developments and real-world impact.
   - Scenes 12-19 (Gaming Segment): Major game, studio, or industry updates and why players care.
   - Scenes 20-27 (Market & Business Segment): Stock/index moves, earnings, and business strategy.
   - Scenes 28-33 (Cross-Sector Connections): How tech, AI, gaming, and capital markets intersect right now.
   - Scenes 34-36 (Sign-Off): Concise wrap-up, audience question, and Quick Shift Creative subscribe cue."""
    return role_desc, structure


def _build_emergency_headline_blueprint(combined_topics, custom_topic, is_shorts, content_mode):
    """Zero-crash fallback: constructs a clean broadcast briefing from live headlines if Gemini is 100% down."""
    print("[ScriptAI] All AI pools temporarily overloaded (503) — activating Live Headlines Backup Blueprint!")
    clean_heads = []
    for raw in combined_topics:
        h = re.sub(r"\s+-\s+[^-]+$", "", raw).strip()
        h = _clean_narration(h)
        if len(h) > 15 and h not in clean_heads:
            clean_heads.append(h)

    if not clean_heads:
        clean_heads = [
            custom_topic or "Major AI and Semiconductor Shift Rattles Tech Markets Today",
            "Gaming Studios Rethink Next-Gen Releases Amid Rising Hardware Demand",
            "Wall Street Watches Tech Earnings and Cloud Infrastructure Spending Closely",
            "New AI Tools Reshape Software Workflows Across Silicon Valley",
        ]

    lead_story = custom_topic.strip() if custom_topic else clean_heads[0]
    s2 = clean_heads[1 % len(clean_heads)]
    s3 = clean_heads[2 % len(clean_heads)]
    s4 = clean_heads[3 % len(clean_heads)]

    base_scenes = [
        {
            "narration": f"Big moves just hit the tech and market radar today. Here is what everyone is watching: {lead_story}.",
            "visual_query": "breaking tech news studio",
            "tone": "hook",
            "highlight_text": lead_story[:68],
        },
        {
            "narration": f"Look closer at the momentum building right now. {s2}. That shift is already forcing rivals to react fast.",
            "visual_query": "artificial intelligence data center",
            "tone": "urgent",
            "highlight_text": s2[:68],
        },
        {
            "narration": f"Meanwhile, another major story is catching serious attention across the industry. {s3}.",
            "visual_query": "stock market trading chart",
            "tone": "analytical",
            "highlight_text": s3[:68],
        },
        {
            "narration": f"And here is the angle most people miss at first glance. {s4}. Numbers like these rarely stay quiet for long.",
            "visual_query": "gaming setup neon hardware",
            "tone": "serious",
            "highlight_text": s4[:68],
        },
        {
            "narration": f"Which of these shifts hits biggest next week? Drop your take below and follow {CHANNEL_NAME} for daily updates.",
            "visual_query": "futuristic technology abstract",
            "tone": "calm",
            "highlight_text": "What happens next in Tech & Markets?",
        },
    ]

    if is_shorts:
        scenes = base_scenes
    else:
        scenes = []
        for k in range(36):
            h_pick = clean_heads[k % len(clean_heads)]
            tone = "hook" if k == 0 else ("calm" if k >= 34 else ("urgent" if k % 3 == 1 else "analytical"))
            scenes.append({
                "narration": (
                    f"Another key development shaping today's briefing is this: {h_pick}. "
                    f"When you connect the dots across tech, gaming, and capital markets, the bigger pattern becomes clear."
                ),
                "visual_query": "technology business market chart" if k % 2 == 0 else "modern gaming ai hardware",
                "tone": tone,
                "highlight_text": h_pick[:68],
            })

    title = lead_story[:88]
    if is_shorts and "#shorts" not in title.lower():
        title += " #Shorts"

    return {
        "chosen_topic": lead_story,
        "category": "tech",
        "bulletin_badge": "DAILY BULLETIN",
        "title": title,
        "description": f"{lead_story}\n\nDaily Tech, AI, Gaming & Market Briefing by {CHANNEL_NAME}.",
        "tags": ["tech news", "ai news", "gaming news", "stock market", "quick shift creative"],
        "thumbnail_headline": lead_story.upper()[:34],
        "thumbnail_subtext": "TECH • AI • MARKETS",
        "thumbnail_query": "technology market chart",
        "music_direction": {
            "music_query": "ambient technology electronic loop",
            "track_file": "auto",
            "mood": "news",
            "intensity": "balanced",
            "volume_scale": 0.08,
            "reason": "Clean editorial news bed",
        },
        "scenes": scenes,
    }


def generate_video_blueprint(trending_topics, custom_topic=""):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing!")

    content_mode = os.getenv("CONTENT_MODE", "news_bulletin").strip().lower()
    if content_mode not in ("news_bulletin", "trending_viral", "deep_dive_evergreen"):
        content_mode = "news_bulletin"

    is_shorts = os.getenv("VIDEO_FORMAT", "horizontal").strip().lower() == "shorts"
    scene_count = "5" if is_shorts else "36"
    words_per_scene = "22-28" if is_shorts else "38-45"
    duration_hint = (
        "45-55 seconds total (fast-paced YouTube Shorts)"
        if is_shorts
        else "8.5 to 10 minutes total (~1,400 to 1,550 spoken words)"
    )

    memory = load_strategy_memory()
    mem_hint = (
        f"Self-Learning Channel Memory -> Winning topics/angles: {', '.join(memory.get('winning_topics', [])[:4])}. "
        f"Avoid: {', '.join(memory.get('avoid_patterns', [])[:3])}."
    )

    local_tracks = _list_local_music_tracks()
    local_hint = (
        f"Optional local tracks in assets/music/: {', '.join(local_tracks)}."
        if local_tracks
        else "The pipeline fetches CC0 background music automatically via Freesound API."
    )

    extra_headlines = [] if custom_topic else _fetch_extra_mode_headlines(content_mode)
    combined_topics = []
    for t in extra_headlines + (trending_topics or []):
        if t and t not in combined_topics:
            combined_topics.append(t)

    if custom_topic:
        topic_block = f"MANDATORY TOPIC: {custom_topic}"
    else:
        topics_list = "\n".join(f"- {t}" for t in combined_topics[:28])
        topic_block = f"LIVE HEADLINES & TRENDS:\n{topics_list}"

    role_desc, structure_guide = _build_mode_instructions(content_mode, is_shorts)
    format_label = "YouTube Shorts (9:16 vertical)" if is_shorts else "Long-Form Horizontal YouTube Video (16:9, 8-10 minutes)"

    prompt = f"""You are the {role_desc} for "{CHANNEL_NAME}".
{mem_hint}

Active Mode: {content_mode.upper()}
Format: {format_label}
Target Length: {duration_hint}
Number of Scenes: EXACTLY {scene_count} scenes ({words_per_scene} words per scene). Output ALL {scene_count} scenes!

Scene Structure Guide:
{structure_guide}

{topic_block}

{local_hint}

Human-Like Spoken Script Rules (CRITICAL):
- Write like a real YouTube host talking to a smart friend — NEVER like a formal article or AI essay.
- Sprinkle natural human conversational bridges across the script (e.g., "Wait, look at that number again.", "Sounds great on paper, right? Not quite.", "Here is where it gets messy.", "Think about what that actually means.").
- Mix short 4-word punchy sentences with medium explanatory sentences so the voice rhythm feels alive.
- NEVER use AI clichés: "delve", "game-changer", "landscape", "buckle up", "revolutionary", "let's dive in", "in conclusion", "ever-evolving", "tapestry", "testament", "welcome back".
- NO emojis, NO markdown, NO stage directions in narration.
- For each scene, set `"tone"` to one of: `"hook"`, `"urgent"`, `"excited"`, `"serious"`, `"analytical"`, `"calm"`.
- For each scene, set `"highlight_text"` to a short 4-8 word punchy stat or headline phrase for an editorial Newsroom Highlight Card.
- For each scene, set `"visual_query"` to 2-4 concrete English keywords for HD B-roll/photos.

AI Background Music Direction Rules (CRITICAL):
- Generate `"music_query"`: 3-4 English keywords to search a CC0 instrumental background track on Freesound API matching the exact emotion of this story.
- Choose `"mood"` from: `"news"`, `"tense"`, `"energetic"`, `"deep_dive"`, `"business"`, `"calm"`.
- Choose `"intensity"` from: `"subtle"`, `"balanced"`, `"energetic"`.
- Choose `"volume_scale"` strictly between `0.06` and `0.11`.

Return ONLY valid JSON (no markdown fences, no commentary):
{{
  "chosen_topic": "string",
  "category": "tech",
  "bulletin_badge": "DAILY BULLETIN",
  "title": "string",
  "description": "string",
  "tags": ["tag1", "tag2"],
  "thumbnail_headline": "string",
  "thumbnail_subtext": "string",
  "thumbnail_query": "string",
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
      "narration": "string",
      "visual_query": "string",
      "tone": "hook",
      "highlight_text": "string"
    }}
  ]
}}
"""

    max_tokens = 2800 if is_shorts else 7600
    models_to_try = _discover_gemini_models()
    last_error = None
    valid_tones = {"hook", "urgent", "excited", "serious", "analytical", "calm"}

    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        gen_cfg = {
            "temperature": 0.78,
            "maxOutputTokens": max_tokens,
        }
        if "gemma" not in model.lower():
            gen_cfg["responseMimeType"] = "application/json"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_cfg,
        }

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
                for idx_s, sc in enumerate(blueprint["scenes"]):
                    nar = _clean_narration(sc.get("narration", ""))
                    if not nar:
                        continue
                    tone = str(sc.get("tone", "hook" if idx_s == 0 else "analytical")).strip().lower()
                    if tone not in valid_tones:
                        tone = "analytical"
                    cleaned_scenes.append({
                        "narration": nar,
                        "visual_query": str(sc.get("visual_query", "technology")).strip() or "technology",
                        "tone": tone,
                        "highlight_text": _clean_narration(sc.get("highlight_text", ""))[:72],
                    })

                blueprint["scenes"] = cleaned_scenes
                if not blueprint["scenes"]:
                    raise ValueError("Empty scenes")
                print(
                    f"[ScriptAI] Blueprint generated with {model} ({len(blueprint['scenes'])} scenes) | "
                    f"MusicAI -> '{blueprint['music_direction']['music_query']}' ({blueprint['music_direction']['intensity']})"
                )
                return blueprint
            except Exception as e:
                last_error = f"{model} error: {e}"
                break

    print(f"[ScriptAI] Warning ({last_error})")
    return _build_emergency_headline_blueprint(combined_topics, custom_topic, is_shorts, content_mode)
