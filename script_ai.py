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
    scene_count = "5" if is_shorts else "36"
    words_per_scene = "22-28" if is_shorts else "38-45"
    duration_hint = (
        "45-55 seconds total (fast-paced US YouTube Shorts news bulletin)"
        if is_shorts
        else "8.5 to 10 minutes total (~1,400 to 1,550 spoken words — high-retention US Tech/AI/Gaming Deep-Dive)"
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

    format_label = "YouTube Shorts (9:16 vertical)" if is_shorts else "Long-Form Horizontal YouTube Video (16:9, 8-10 minutes)"
    shorts_hash = " and #Shorts" if is_shorts else ""

    if is_shorts:
        structure_guide = """
   - Scene 1: Instant 3-second breaking-news hook.
   - Scenes 2-4: Key facts, numbers, and global impact.
   - Scene 5: Sharp verdict + Subscribe CTA."""
    else:
        structure_guide = """
   Structure the 36 scenes like a top US YouTube tech/gaming documentary (ColdFusion / TechLinked / Gameranx pacing):
   - Scenes 1-3 (The Hook): Explosive cold open with the shocking headline, exact numbers/stakes, and a compelling reason to watch till the end. (NEVER say "Hey guys welcome back".)
   - Scenes 4-10 (What Just Happened): Full detailed breakdown of the breaking announcement, specs, leaks, pricing, or release details.
   - Scenes 11-18 (The Hidden Backstory): Why this happened right now, past industry mistakes or breakthroughs, and how rival giants (NVIDIA, OpenAI, Apple, Microsoft, Sony, Rockstar, etc.) are connected.
   - Scenes 19-26 (Deep Impact Analysis): How this actually changes things for everyday US consumers, developers, gamers, and Wall Street / the global market.
   - Scenes 27-33 (Controversies, Risks & What Comes Next): Real criticism, potential flaws, bold predictions for 2026-2027, and what competitors will do to strike back.
   - Scenes 34-36 (Final Verdict & Community Engagement): Memorable takeaway, a sharp debate question for the comments section, and a smooth Subscribe CTA for Quick Shift Creative."""

    prompt = f"""You are the Executive Producer, Lead Documentary Scriptwriter, and YouTube SEO Director for "{CHANNEL_NAME}" — a premier US-based YouTube channel delivering in-depth US Trends and Worldwide Tech, AI, and Gaming analysis.

{topic_block}

Target Audience: 100% US & Global English-speaking viewers (natural, sharp, authoritative American English — zero fluff, zero filler, constant curiosity loops between sections).
Format: {format_label}
Target Length: {duration_hint}
Number of Scenes: EXACTLY {scene_count} scenes. Do NOT stop early — you MUST output all {scene_count} scenes!

Requirements:
1. Select ONE blockbuster breaking story from the live headlines (or use the mandatory topic).
2. Classify the story into exact "category": one of "ai", "tech", or "gaming".
3. Choose a short 2-word uppercase "bulletin_badge" for the thumbnail corner (e.g., "AI DEEP DIVE", "TECH ALERT", "GAMING NEWS", "US TRENDING").
4. Create an ultra-high-CTR US YouTube Title (max 82 characters, main trending keyword/company/game right at the start, strong curiosity gap, zero fake clickbait).
5. Create a complete US/Global SEO-optimized YouTube Description:
   - Punchy 2-line hook packed with high-volume US search keywords
   - 5 concise bullet-point highlights covered in this deep dive
   - Subscribe CTA for "{CHANNEL_NAME}"
   - 6 high-traffic hashtags at the bottom (#QuickShiftCreative #TechNews #AINews #GamingNews #USTrends{shorts_hash})
6. Create 15 high-search-volume US/Global YouTube SEO tags (array of short strings, NO # symbols).
7. Create high-CTR Thumbnail copy:
   - thumbnail_headline: 2 to 4 BOLD ALL-CAPS punchy words (max 22 chars total).
   - thumbnail_subtext: 2 to 4 short supporting words (max 24 chars, e.g., "EVERYTHING CHANGES", "FULL BREAKDOWN", "HUGE LEAK").
   - thumbnail_query: 2 simple English words for a dramatic Pixabay photo (e.g., "futuristic microchip", "gaming setup", "cyberpunk neon").
8. Write EXACTLY {scene_count} tightly paced scenes:
{structure_guide}
   - Each scene MUST include:
     * "narration": {words_per_scene} spoken words in smooth, conversational US broadcast English (NO emojis, NO markdown, NO stage directions, NO scene numbers spoken aloud).
     * "visual_query": 2 simple, DIFFERENT English keywords per scene for Pixabay HD stock video (NEVER repeat the same visual_query in nearby scenes — vary between hardware, coding, data center, neon city, gaming setup, smartphone, stock chart, robotics, astronaut, studio desk, server rack, esports arena, microchip, laboratory, futuristic car, etc.).

Return ONLY a valid JSON object matching this exact schema:
{{
  "chosen_topic": "string",
  "category": "ai",
  "bulletin_badge": "AI DEEP DIVE",
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
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
        },
    }

    models_to_try = _discover_gemini_models()
    last_error = None

    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        try:
            print(f"[Gemini] Building 8-10 min US Deep-Dive with {model}...")
            resp = requests.post(url, json=payload, timeout=120)
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
            blueprint["bulletin_badge"] = str(blueprint.get("bulletin_badge", "TECH DEEP DIVE")).upper().strip()[:18]

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

            total_words = sum(len(s["narration"].split()) for s in blueprint["scenes"])
            print(f"[Gemini] Chosen Story ({blueprint['category'].upper()}): {blueprint.get('chosen_topic')}")
            print(f"[Gemini] Generated {len(blueprint['scenes'])} scenes (~{total_words} words)")
            print(f"[Gemini] SEO Title: {blueprint['title']}")
            return blueprint
        except Exception as e:
            last_error = f"{model} error: {e}"
            print(f"[Gemini] {last_error}")

    raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")
