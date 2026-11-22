import json
import re
import requests
from config import GEMINI_API_KEY, CHANNEL_NAME, VIDEO_FORMAT, NEWS_CATEGORY

FALLBACK_MODELS = [
    "gemini-3.0-flash",
    "gemini-3-flash-preview",
    "gemini-flash-latest",
    "gemini-2.5-flash",
]


def _discover_gemini_models():
    """Auto-discovers active Gemini Flash models available for this API key."""
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
        resp = requests.get(url, timeout=20)
        if resp.status_code != 200:
            print(f"[Gemini] ListModels HTTP {resp.status_code}, using fallback list.")
            return FALLBACK_MODELS

        models = resp.json().get("models", [])
        candidates = []
        skip_keywords = (
            "embedding", "aqa", "image", "veo", "tts", "audio",
            "robotics", "computer-use", "live", "vision", "learnlm",
        )

        for m in models:
            name = m.get("name", "").replace("models/", "").strip()
            methods = m.get("supportedGenerationMethods", [])
            lname = name.lower()
            if "generateContent" not in methods:
                continue
            if not lname.startswith("gemini"):
                continue
            if any(k in lname for k in skip_keywords):
                continue
            candidates.append(name)

        def _score(model_name):
            ln = model_name.lower()
            score = 0
            if "flash" in ln:
                score += 100
            if "lite" in ln:
                score -= 10
            if "preview" in ln or "exp" in ln:
                score -= 5
            if "latest" in ln:
                score += 5
            ver_match = re.search(r"gemini-(\d+(?:\.\d+)?)", ln)
            if ver_match:
                try:
                    score += int(float(ver_match.group(1)) * 10)
                except ValueError:
                    pass
            return score

        candidates.sort(key=_score, reverse=True)
        ordered = []
        for m in candidates + FALLBACK_MODELS:
            if m not in ordered:
                ordered.append(m)

        print(f"[Gemini] Auto-discovered active models (top 5): {ordered[:5]}")
        return ordered[:8]
    except Exception as e:
        print(f"[Gemini] Model discovery warning: {e}")
        return FALLBACK_MODELS


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
    text = re.sub(r"[*_`#~>|\[\]]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def generate_video_blueprint(trending_topics, custom_topic=""):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing! Add it to GitHub Secrets or config.env.")

    is_shorts = VIDEO_FORMAT == "shorts"
    scene_count = "5" if is_shorts else "7"
    duration_hint = (
        "45-55 seconds total (fast-paced US YouTube Shorts news bulletin)"
        if is_shorts
        else "80-110 seconds total (crisp, high-retention US Tech/AI/Gaming News Bulletin)"
    )

    if custom_topic:
        topic_block = f"MANDATORY BREAKING TOPIC: {custom_topic}"
    else:
        topics_list = "\n".join(f"- {t}" for t in trending_topics)
        category_note = (
            f"Focus strictly on the '{NEWS_CATEGORY.upper()}' category if available."
            if NEWS_CATEGORY != "auto"
            else "Prioritize the #1 most viral US & Worldwide Tech, AI, or Gaming breaking story."
        )
        topic_block = (
            f"LIVE US TRENDS & WORLDWIDE TECH / AI / GAMING NEWS BULLETINS RIGHT NOW:\n"
            f"{category_note}\n"
            f"Pick the SINGLE highest-CTR, most shareable breaking story for a US and global audience:\n"
            + topics_list
        )

    format_label = "YouTube Shorts (9:16 vertical)" if is_shorts else "Standard Horizontal YouTube Video (16:9)"
    shorts_hash = " and #Shorts" if is_shorts else ""

    prompt = f"""You are the Executive Producer, Breaking News Anchor Scriptwriter, and YouTube SEO Director for "{CHANNEL_NAME}" — a fast-paced, US-based YouTube channel delivering US Trends and Worldwide Tech, AI, and Gaming News Bulletins.

{topic_block}

Target Audience: 100% US & Global English-speaking viewers (natural, sharp American English news-bulletin tone — NEVER use regional slang outside US/global tech & gaming culture).
Format: {format_label}
Target Length: {duration_hint}
Number of Scenes: Exactly {scene_count} scenes.

Requirements:
1. Select ONE blockbuster breaking story from the live headlines (or use the mandatory topic).
2. Classify the story into exact "category": one of "ai", "tech", or "gaming".
3. Choose a short 2-word uppercase "bulletin_badge" for the thumbnail corner (e.g., "AI BULLETIN", "TECH NEWS", "GAMING ALERT", "US TRENDING").
4. Create an ultra-high-CTR US YouTube Title (max 82 characters, main trending keyword/company/game right at the start, strong curiosity gap, zero fake clickbait).
5. Create a complete US/Global SEO-optimized YouTube Description:
   - Punchy 2-line breaking bulletin summary packed with search keywords
   - 3 concise bullet-point highlights from this update
   - Subscribe CTA for "{CHANNEL_NAME}" ("Subscribe to Quick Shift Creative for daily US & Worldwide Tech, AI, and Gaming News Bulletins!")
   - 6 high-traffic hashtags at the bottom (always include #QuickShiftCreative and relevant tags like #TechNews #AINews #GamingNews #USTrends{shorts_hash})
6. Create 15 high-search-volume US/Global YouTube SEO tags (array of short strings, NO # symbols).
7. Create high-CTR Thumbnail copy:
   - thumbnail_headline: 2 to 4 BOLD ALL-CAPS punchy words (max 22 chars total) readable at a glance on US mobile feeds.
   - thumbnail_subtext: 2 to 4 short supporting words (max 24 chars, e.g., "GAME CHANGER 2026", "NEW AI LEAK", "HUGE UPDATE").
   - thumbnail_query: 2 simple English words for searching a dramatic background photo on Pixabay (e.g., "futuristic microchip", "gaming controller", "server room", "cyberpunk neon").
8. Write {scene_count} tightly paced news-bulletin scenes:
   - Scene 1: Instant 3-second breaking-news hook (e.g., "Breaking in tech today..." or direct shocking fact — no boring "Hey guys welcome back").
   - Middle scenes: Crisp worldwide bulletin breakdown — what just happened, why it matters globally, industry/gamer/consumer impact, and what happens next.
   - Final scene: Sharp closing insight + smooth CTA to subscribe to "{CHANNEL_NAME}" for the next global Tech, AI & Gaming bulletin.
   - Each scene MUST include:
     * "narration": 20-32 spoken words in natural US English broadcast style (NO emojis, NO markdown, NO stage directions).
     * "visual_query": 2 simple English keywords that return great HD stock footage on Pixabay (e.g., "artificial intelligence", "esports gaming", "computer hardware", "silicon valley", "smartphone technology", "robot futuristic").

Return ONLY a valid JSON object matching this exact schema:
{{
  "chosen_topic": "string",
  "category": "ai",
  "bulletin_badge": "AI BULLETIN",
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
            "temperature": 0.72,
            "responseMimeType": "application/json",
        },
    }

    models_to_try = _discover_gemini_models()
    last_error = None

    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        try:
            print(f"[Gemini] Building US Tech/AI/Gaming Bulletin with {model}...")
            resp = requests.post(url, json=payload, timeout=60)
            if resp.status_code != 200:
                last_error = f"{model} HTTP {resp.status_code}: {resp.text[:300]}"
                print(f"[Gemini] Fallback triggered: {last_error}")
                continue
            data = resp.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            blueprint = _extract_json(raw_text)

            if not blueprint.get("title") or not blueprint.get("scenes"):
                raise ValueError("Missing title or scenes in Gemini output.")

            cat = str(blueprint.get("category", "tech")).strip().lower()
            blueprint["category"] = cat if cat in ("ai", "tech", "gaming") else "tech"
            blueprint["bulletin_badge"] = str(blueprint.get("bulletin_badge", "TECH BULLETIN")).upper().strip()[:18]

            blueprint["title"] = blueprint["title"].strip()[:98]
            if is_shorts and "#shorts" not in blueprint["title"].lower():
                if len(blueprint["title"]) <= 90:
                    blueprint["title"] += " #Shorts"

            for scene in blueprint["scenes"]:
                scene["narration"] = _clean_narration(scene.get("narration", ""))
                scene["visual_query"] = scene.get("visual_query", "futuristic technology").strip()

            blueprint["scenes"] = [s for s in blueprint["scenes"] if s["narration"]]
            if not blueprint["scenes"]:
                raise ValueError("All generated scenes had empty narration.")

            print(f"[Gemini] Chosen Story ({blueprint['category'].upper()}): {blueprint.get('chosen_topic')}")
            print(f"[Gemini] SEO Title: {blueprint['title']}")
            return blueprint
        except Exception as e:
            last_error = f"{model} error: {e}"
            print(f"[Gemini] {last_error}")

    raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")
