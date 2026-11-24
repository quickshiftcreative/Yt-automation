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
    "gemini-3.0-flash",
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
    ordered = list(PRIORITY_MODELS)
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
                if "generateContent" in methods and "flash" in lname and not any(k in lname for k in skip_keywords):
                    if name not in ordered:
                        ordered.append(name)
    except Exception:
        pass
    return ordered[:8]


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
            "Viral Trend & Culture Producer — capturing whatever is genuinely trending right now "
            "(games, pop culture, viral moments, or major US talking points) with sharp, human commentary."
        )
        if is_shorts:
            structure = """
   - Scene 1: Immediate 3-second hook naming what is blowing up right now and why it matters.
   - Scenes 2-4: Key details, public/creator reaction, and the real twist.
   - Scene 5: Sharp punchline + viewer question + Quick Shift Creative CTA."""
        else:
            structure = """
   Structure the 36 scenes around the #1 non-news viral/trending topic exploding right now:
   - Scenes 1-3 (Cold Hook): Open right on the viral wave and why people cannot stop talking about it.
   - Scenes 4-10 (What Sparked It): How the trend or game/creator moment took off so fast.
   - Scenes 11-18 (Internet & Crowd Reaction): Real perspectives, debates, and funny/intense moments around it.
   - Scenes 19-26 (Why It Hit So Hard): Psychological, cultural, or market reasons behind the hype.
   - Scenes 27-33 (Where It Goes Next): Will it fade in a week or reshape the space?
   - Scenes 34-36 (Closing Take): Honest wrap-up, comment question, and Quick Shift Creative subscribe cue."""
        return role_desc, structure

    if mode == "deep_dive_evergreen":
        role_desc = (
            "High-RPM Evergreen & Subscriber Growth Strategist — crafting high-retention stories "
            "with strong reach and subscriber appeal across finance, AI/tech strategy, business models, and high-interest topics."
        )
        if is_shorts:
            structure = """
   - Scene 1: High-curiosity money/strategy or high-reach hook.
   - Scenes 2-4: Clear, memorable breakdown of how it works or why it matters.
   - Scene 5: Strong takeaway + Quick Shift Creative subscribe cue."""
        else:
            structure = """
   Structure the 36 scenes for maximum watch time, US RPM, and subscriber conversion:
   - Scenes 1-3 (Irresistible Hook): Start with a striking insight, number, or question that pulls viewers in.
   - Scenes 4-10 (Origin & Core Mechanics): Explain the backstory and how the system/business actually operates.
   - Scenes 11-18 (The Numbers & Leverage): Break down margins, incentives, market forces, or key comparisons.
   - Scenes 19-26 (Hidden Bottlenecks & Competition): What most people overlook and how rivals respond.
   - Scenes 27-33 (Future Outlook): Realistic scenarios and what to watch next.
   - Scenes 34-36 (Final Takeaway): Crisp summary, comment prompt, and Quick Shift Creative subscribe cue."""
        return role_desc, structure

    role_desc = (
        "Broadcast News & Markets Anchor — covering Gaming, Tech, AI, and Business/Market news "
        "in a natural, conversational human voice."
    )
    if is_shorts:
        structure = """
   - Scene 1: Fast breaking hook across Gaming, Tech, AI, or Market/Business news.
   - Scenes 2-4: Key numbers, market reaction (green/red candles or business impact), and core facts.
   - Scene 5: Bottom-line takeaway + Quick Shift Creative CTA."""
    else:
        structure = """
   Structure the 36 scenes as a multi-segment briefing covering Gaming, Tech, AI, and Business/Market news:
   - Scenes 1-3 (Opening Briefing): Tease the key stories across Tech/AI, Gaming, and Markets without cliché intros.
   - Scenes 4-11 (Tech & AI Segment): Key product, model, or infrastructure developments and real-world impact.
   - Scenes 12-19 (Gaming Segment): Major game, studio, or industry updates and why players care.
   - Scenes 20-27 (Market & Business Segment): Stock/index moves (red/green candle shifts), earnings, and business strategy.
   - Scenes 28-33 (Cross-Sector Connections): How tech, AI, gaming, and capital markets intersect right now.
   - Scenes 34-36 (Sign-Off): Concise wrap-up, audience question, and Quick Shift Creative subscribe cue."""
    return role_desc, structure


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

Human-Like Writing Rules (CRITICAL):
- Sound like an articulate, sharp human creator/analyst speaking naturally — NOT an AI template.
- NEVER use AI clichés such as: "delve", "game-changer", "landscape", "buckle up", "revolutionary", "let's dive in", "in conclusion", "ever-evolving", "tapestry", "testament".
- Vary sentence lengths naturally (mix short punchy sentences with clear explanatory sentences).
- NO emojis, NO markdown, NO stage directions in narration.
- Each scene's "visual_query" must be 2-4 concrete English keywords for stock B-roll/photos (e.g., "nvidia gpu server", "wall street trading screen", "gaming controller neon").

Return ONLY valid JSON:
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
  "scenes": [
    {{
      "narration": "string",
      "visual_query": "string"
    }}
  ]
}}
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.75,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
        },
    }

    models_to_try = _discover_gemini_models()
    last_error = None

    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        for attempt in range(3):
            try:
                resp = requests.post(url, json=payload, timeout=120)
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_error = f"{model} HTTP {resp.status_code} (attempt {attempt + 1})"
                    print(f"[ScriptAI] {last_error}, retrying in {4 * (attempt + 1)}s...")
                    time.sleep(4 * (attempt + 1))
                    continue
                if resp.status_code != 200:
                    last_error = f"{model} HTTP {resp.status_code}: {resp.text[:220]}"
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

                for sc in blueprint["scenes"]:
                    sc["narration"] = _clean_narration(sc.get("narration", ""))
                    sc["visual_query"] = sc.get("visual_query", "technology").strip()

                blueprint["scenes"] = [s for s in blueprint["scenes"] if s["narration"]]
                if not blueprint["scenes"]:
                    raise ValueError("Empty scenes")
                print(f"[ScriptAI] Blueprint generated with {model} ({len(blueprint['scenes'])} scenes)")
                return blueprint
            except Exception as e:
                last_error = f"{model} error: {e}"
                break

    raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")
