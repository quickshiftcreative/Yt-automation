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
    f"What is your take on this? Drop a quick like, share this video, and subscribe to {CHANNEL_NAME} for more. Thank you for watching.",
    f"Stay ahead of the next big shift. Tap like, share this with someone who needs to see it, and subscribe to {CHANNEL_NAME}. Thank you for watching.",
]

LONG_CASUAL_OUTROS = [
    f"If this video gave you a clearer picture of what's really happening, go ahead and hit like, share it with a friend, and subscribe to {CHANNEL_NAME} so you don't miss the next deep dive. Thank you for watching.",
    f"I'd love to hear your side in the comments below. If you found this breakdown useful, please like, share, and subscribe to {CHANNEL_NAME} for daily updates. Thank you for watching.",
    f"That wraps up today's breakdown. If you liked hanging out with us, drop a like, share this episode, and hit subscribe on {CHANNEL_NAME}. Thank you for watching.",
]


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


def _ensure_interactive_and_outro(scenes, is_shorts):
    """Guarantees casual outro, countdown/debate interactive moments, music drop, and dual-host beats."""
    if not scenes:
        return scenes

    # Ensure at least 1 countdown, 1 music_drop, and 1 debate card exist cleanly
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

    # For Long videos, ensure occasional Co-Host Analyst interrupts for conversational podcast rhythm
    if not is_shorts and n >= 12:
        has_cohost = any(s.get("speaker") == "cohost" for s in scenes)
        if not has_cohost:
            for pos in (7, 15, 23, 30):
                if pos < n - 2:
                    scenes[pos]["speaker"] = "cohost"

    # Mandatory casual outro + Thank you for watching
    last = scenes[-1]
    last["speaker"] = "main"
    last["interactive_type"] = "none"
    low = last["narration"].lower()
    has_cta = ("subscribe" in low and "like" in low and "share" in low)
    has_thanks = ("thank you for watching" in low or "thanks for watching" in low)

    if has_cta and has_thanks:
        last["tone"] = "calm"
        return scenes

    outro_line = random.choice(SHORTS_CASUAL_OUTROS if is_shorts else LONG_CASUAL_OUTROS)
    if has_cta and not has_thanks:
        last["narration"] = last["narration"].rstrip(".!? ") + ". Thank you for watching."
        last["tone"] = "calm"
    elif is_shorts and len(scenes) >= 6:
        last["narration"] = last["narration"].rstrip(".!? ") + ". " + outro_line
        last["tone"] = "calm"
    else:
        scenes.append({
            "narration": outro_line,
            "visual_query": "modern dark minimalist studio background",
            "tone": "calm",
            "highlight_text": "Like, Share & Subscribe",
            "speaker": "main",
            "interactive_type": "none",
        })
    return scenes


def _build_mode_instructions(mode, is_shorts):
    if mode == "trending_viral":
        role_desc = (
            "Viral Trend & Culture Producer — capturing what is genuinely blowing up right now "
            "with sharp, opinionated, conversational commentary."
        )
        if is_shorts:
            structure = """
   - Scene 1 (tone: hook): Immediate 3-second conflict hook naming what's blowing up right now.
   - Scene 2 (tone: excited): The backstory and what triggered the internet reaction.
   - Scene 3 (tone: analytical, interactive_type: countdown): End with a quick 2-second viewer guess prompt (e.g., "Take two seconds and guess the real number...").
   - Scene 4 (tone: serious, interactive_type: music_drop): The big reveal or twist that flips expectations.
   - Scene 5 (tone: urgent, interactive_type: debate): Split debate angle asking viewers to comment 1 or 2.
   - Scene 6 (tone: calm): Crisp wrap-up + casual ask to like, share, and subscribe + end with "Thank you for watching." """
        else:
            structure = """
   Structure 36 scenes around the #1 viral/trending topic exploding right now:
   - Scenes 1-3 (Cold Hook): Drop straight into the tension — zero "welcome back" intros.
   - Scenes 4-11 (What Sparked It): Include 1 Co-Host analyst interrupt (speaker: "cohost") highlighting a sharp stat.
   - Scenes 12-19 (Crowd Reaction + Quiz): Include 1 interactive_type: "countdown" guess moment and 1 interactive_type: "music_drop" twist reveal.
   - Scenes 20-27 (Why It Hit So Hard): Psychological, cultural, or financial reasons + 1 cohost analyst reality check.
   - Scenes 28-33 (Debate & Future): Include 1 interactive_type: "debate" (Comment 1 or 2) prompt.
   - Scenes 34-36 (Warm Outro): Honest wrap-up, casual ask to like, share, and subscribe, ending clearly with "Thank you for watching." """
        return role_desc, structure

    if mode == "deep_dive_evergreen":
        role_desc = (
            "High-RPM Evergreen & Documentary Storyteller — crafting high-retention stories "
            "across finance, AI/tech strategy, and business models."
        )
        if is_shorts:
            structure = """
   - Scene 1 (tone: hook): High-curiosity money/strategy hook.
   - Scene 2 (tone: analytical): How the system actually works behind the scenes.
   - Scene 3 (tone: urgent, interactive_type: countdown): Ask viewers to guess the surprising figure in 2 seconds.
   - Scene 4 (tone: serious, interactive_type: music_drop): Drop the real shocking number or catch.
   - Scene 5 (tone: excited, interactive_type: debate): Ask viewers to pick side 1 or 2 in comments.
   - Scene 6 (tone: calm): Memorable takeaway + casual ask to like, share, and subscribe + end with "Thank you for watching." """
        else:
            structure = """
   Structure 36 scenes for maximum watch time, US RPM, and subscriber conversion:
   - Scenes 1-3 (Irresistible Hook): Start with a striking insight, stat, or contradiction.
   - Scenes 4-11 (Origin & Mechanics): Explain how the business operates + 1 cohost analyst stat check.
   - Scenes 12-19 (The Numbers + Quiz): Include 1 interactive_type: "countdown" guess moment and 1 interactive_type: "music_drop" reveal.
   - Scenes 20-27 (Hidden Bottlenecks): What most people miss + 1 cohost counter-point.
   - Scenes 28-33 (Debate & Outlook): Include 1 interactive_type: "debate" (Comment 1 or 2) prompt.
   - Scenes 34-36 (Warm Outro): Crisp summary, casual ask to like, share, and subscribe, ending clearly with "Thank you for watching." """
        return role_desc, structure

    role_desc = (
        "Broadcast News & Markets Host — covering Gaming, Tech, AI, and Business/Market news "
        "in a natural, conversational human voice like Vox or ColdFusion."
    )
    if is_shorts:
        structure = """
   - Scene 1 (tone: hook): Fast breaking hook across Gaming, Tech, AI, or Market news.
   - Scene 2 (tone: urgent): Key facts and why everyone in the industry is talking.
   - Scene 3 (tone: analytical, interactive_type: countdown): Quick 2-second viewer guess prompt on the key stat/impact.
   - Scene 4 (tone: serious, interactive_type: music_drop): The big market/tech reveal or hidden catch.
   - Scene 5 (tone: excited, interactive_type: debate): Clear 1-vs-2 debate prompt for comments.
   - Scene 6 (tone: calm): Bottom-line takeaway + casual ask to like, share, and subscribe + end with "Thank you for watching." """
    else:
        structure = """
   Structure 36 scenes as a lively dual-host briefing covering Gaming, Tech, AI, and Markets:
   - Scenes 1-3 (Opening Hook): Drop right into the biggest headline and stakes.
   - Scenes 4-11 (Tech & AI Segment): Major AI/chip moves + 1 cohost analyst stat interrupt (speaker: "cohost").
   - Scenes 12-19 (Gaming Segment + Quiz): Include 1 interactive_type: "countdown" guess and 1 interactive_type: "music_drop" twist.
   - Scenes 20-27 (Market & Business Segment): Stock moves & strategy + 1 cohost reality check.
   - Scenes 28-33 (Debate & Cross-Sector Impact): Include 1 interactive_type: "debate" (Comment 1 or 2) prompt.
   - Scenes 34-36 (Warm Sign-Off): Concise wrap-up, casual ask to like, share, and subscribe, ending clearly with "Thank you for watching." """
    return role_desc, structure


def _build_emergency_headline_blueprint(combined_topics, custom_topic, is_shorts, seo_keywords):
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
            "Hardware Supply Chains Brace For Next Quarter Demand Spike",
        ]

    lead_story = custom_topic.strip() if custom_topic else clean_heads[0]
    s2 = clean_heads[1 % len(clean_heads)]
    s3 = clean_heads[2 % len(clean_heads)]
    s4 = clean_heads[3 % len(clean_heads)]

    base_scenes = [
        {
            "narration": f"Big moves just hit the tech and market radar today, and honestly, this one is moving fast. Here's what everyone is watching right now: {lead_story}.",
            "visual_query": "breaking tech news studio",
            "tone": "hook",
            "highlight_text": lead_story[:68],
            "speaker": "main",
            "interactive_type": "none",
        },
        {
            "narration": f"Look closer at the momentum building behind the scenes. {s2}. That shift is already forcing major rivals to rethink their next move.",
            "visual_query": "artificial intelligence data center",
            "tone": "urgent",
            "highlight_text": s2[:68],
            "speaker": "main",
            "interactive_type": "none",
        },
        {
            "narration": f"Now pause for two seconds and ask yourself: is Wall Street overreacting, or is this just the start? Here's what's unfolding with {s3}.",
            "visual_query": "stock market trading chart",
            "tone": "analytical",
            "highlight_text": "Take 2 seconds: Overreaction or just starting?",
            "speaker": "main",
            "interactive_type": "countdown",
        },
        {
            "narration": f"Here's the twist most people miss at first glance. {s4}. Numbers like these rarely stay quiet for long.",
            "visual_query": "gaming setup neon hardware",
            "tone": "serious",
            "highlight_text": s4[:68],
            "speaker": "main",
            "interactive_type": "music_drop",
        },
        {
            "narration": "So where do you stand right now? Comment 1 if you think this is a real breakthrough, or comment 2 if it's pure short-term hype.",
            "visual_query": "futuristic microchip technology",
            "tone": "excited",
            "highlight_text": "Real Shift vs Short-Term Hype",
            "speaker": "main",
            "interactive_type": "debate",
        },
        {
            "narration": random.choice(SHORTS_CASUAL_OUTROS),
            "visual_query": "modern dark minimalist studio background",
            "tone": "calm",
            "highlight_text": "Like, Share & Subscribe",
            "speaker": "main",
            "interactive_type": "none",
        },
    ]

    scenes = base_scenes if is_shorts else []
    if not is_shorts:
        for k in range(35):
            h_pick = clean_heads[k % len(clean_heads)]
            scenes.append({
                "narration": f"Another key story shaping today's briefing: {h_pick}. When you connect the dots across tech, gaming, and capital markets, the bigger pattern gets hard to ignore.",
                "visual_query": "technology business market chart" if k % 2 == 0 else "modern gaming ai hardware",
                "tone": "hook" if k == 0 else ("urgent" if k % 3 == 1 else "analytical"),
                "highlight_text": h_pick[:68],
                "speaker": "cohost" if k in (7, 15, 23, 30) else "main",
                "interactive_type": "countdown" if k == 14 else ("music_drop" if k == 15 else ("debate" if k == 31 else "none")),
            })
        scenes.append({
            "narration": random.choice(LONG_CASUAL_OUTROS),
            "visual_query": "modern dark minimalist studio background",
            "tone": "calm",
            "highlight_text": "Like, Share & Subscribe",
            "speaker": "main",
            "interactive_type": "none",
        })

    title = lead_story[:88]
    if is_shorts and "#shorts" not in title.lower():
        title += " #Shorts"

    tags = list(dict.fromkeys((seo_keywords or []) + ["tech news", "ai news", "gaming news", "stock market", "quick shift creative"]))[:22]
    return {
        "chosen_topic": lead_story,
        "category": "tech",
        "bulletin_badge": "DAILY BULLETIN",
        "title": title,
        "description": f"{lead_story}\n\nDaily Tech, AI, Gaming & Market Briefing by {CHANNEL_NAME}.\n\n#TechNews #AINews #Markets #QuickShiftCreative",
        "tags": tags,
        "thumbnail_headline": lead_story.upper()[:34],
        "thumbnail_subtext": "TECH • AI • MARKETS",
        "thumbnail_query": "technology market chart",
        "pinned_comment": "Quick vote: Comment 1 if you think this shift is the real deal, or 2 if it's overhyped! 👇",
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
        "scenes": scenes,
    }


def generate_video_blueprint(trending_topics, custom_topic=""):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing!")

    content_mode = os.getenv("CONTENT_MODE", "news_bulletin").strip().lower()
    if content_mode not in ("news_bulletin", "trending_viral", "deep_dive_evergreen"):
        content_mode = "news_bulletin"

    is_shorts = os.getenv("VIDEO_FORMAT", "horizontal").strip().lower() == "shorts"
    scene_count = "6" if is_shorts else "36"
    words_per_scene = "25-30" if is_shorts else "38-45"
    duration_hint = (
        "55-62 seconds total (stretched, high-retention YouTube Shorts with interactive beats & smooth casual outro)"
        if is_shorts
        else "8.5 to 10 minutes total (~1,400 to 1,550 spoken words with dual-host analyst beats & warm outro)"
    )

    memory = load_strategy_memory()
    extra_headlines = [] if custom_topic else _fetch_extra_mode_headlines(content_mode)
    combined_topics = []
    for t in extra_headlines + (trending_topics or []):
        if t and t not in combined_topics:
            combined_topics.append(t)

    # Pre-upload live YouTube Search Autocomplete SEO Research!
    seed_for_seo = custom_topic.strip() if custom_topic else (combined_topics[0] if combined_topics else "tech AI news")
    live_seo_keywords = fetch_youtube_autocomplete_keywords(seed_for_seo, max_results=14)
    print(f"[SEO-Research] Live US YouTube Autocomplete ({len(live_seo_keywords)} keywords): {', '.join(live_seo_keywords[:6])}")

    recent_comments = memory.get("recent_viewer_comments") or []
    comment_hint = (
        f"Real Recent Viewer Comment (naturally mention/react to this briefly in 1 scene if relevant): {recent_comments[0]}"
        if recent_comments
        else "Address the viewer directly as 'you' to spark comments."
    )

    mem_hint = (
        f"100x Channel Memory -> Winning topics: {', '.join(memory.get('winning_topics', [])[:4])} | "
        f"Best title hook styles: {', '.join(memory.get('winning_title_patterns', ['curiosity_contrast']))} | "
        f"High-performing tags: {', '.join(memory.get('winning_keywords', [])[:8])} | "
        f"Avoid: {', '.join(memory.get('avoid_patterns', [])[:3])}."
    )

    if custom_topic:
        topic_block = f"MANDATORY TOPIC: {custom_topic}"
    else:
        topics_list = "\n".join(f"- {t}" for t in combined_topics[:28])
        topic_block = f"LIVE HEADLINES & TRENDS:\n{topics_list}"

    role_desc, structure_guide = _build_mode_instructions(content_mode, is_shorts)
    format_label = "YouTube Shorts (9:16 vertical, ~58 seconds)" if is_shorts else "Long-Form Horizontal YouTube Video (16:9, 8-10 minutes)"

    prompt = f"""You are the {role_desc} for "{CHANNEL_NAME}".
{mem_hint}
{comment_hint}

LIVE US YOUTUBE SEARCH AUTOCOMPLETE KEYWORDS (use naturally in Title, SEO Description & Tags to maximize Search & Feed ranking):
{', '.join(live_seo_keywords) if live_seo_keywords else 'tech news, ai news, gaming news, stock market'}

Active Mode: {content_mode.upper()}
Format: {format_label}
Target Length: {duration_hint}
Number of Scenes: EXACTLY {scene_count} scenes ({words_per_scene} words per scene). Output ALL {scene_count} scenes!

Scene Structure Guide:
{structure_guide}

{topic_block}

Ultra-Human Spoken Script & SEO Rules (CRITICAL):
- Sound like a sharp, opinionated US YouTube creator talking to a smart friend — use natural contractions ("don't", "won't", "here's", "that's", "you're") and honest skepticism ("Sounds too clean, right?", "Honestly, this part surprised me too.").
- Mix short 4-word punchlines ("Yeah. Four billion dollars.", "Nobody saw that coming.") with clear conversational explanations.
- NEVER use AI clichés: "delve", "game-changer", "landscape", "buckle up", "revolutionary", "let's dive in", "in conclusion", "ever-evolving", "tapestry", "testament", "welcome back".
- MANDATORY OUTRO RULE: The FINAL scene MUST sound warm and casual, invite viewers to like, share, and subscribe to {CHANNEL_NAME}, and end with "Thank you for watching."
- SEO TITLE: High-curiosity, US search-friendly, under 88 chars, naturally containing the strongest search keyword.
- SEO DESCRIPTION: 3-4 punchy, keyword-rich sentences optimized for YouTube search + a viewer debate question + 5-7 relevant hashtags at the bottom.
- TAGS: 18-22 high-search-intent US keywords blending live autocomplete keywords and topic terms.
- PINNED COMMENT: One punchy, polarizing question for the Auto-Comment Bot (e.g., "Quick vote: Comment 1 for X or 2 for Y! 👇").
- DEBATE CARD: Short uppercase `option_a` (2-3 words) and `option_b` (2-3 words) for the split-screen A vs B Debate Card.
- INTERACTIVE SCENE TAGS: Set `interactive_type` to `"countdown"` on 1 mid-video viewer guess scene, `"music_drop"` on the shocking twist scene right after, `"debate"` on the 1-vs-2 debate scene, and `"none"` elsewhere.
- SPEAKER TAGS: Set `speaker` to `"main"` on most scenes. {'For Long videos, set `speaker` to `"cohost"` on 3-4 analytical stat-check scenes so a second US voice jumps in briefly.' if not is_shorts else 'Keep `speaker` as `"main"` for Shorts.'}

Return ONLY valid JSON (no markdown fences):
{{
  "chosen_topic": "string",
  "category": "tech",
  "bulletin_badge": "DAILY BULLETIN",
  "title": "string",
  "description": "string",
  "tags": ["kw1", "kw2"],
  "thumbnail_headline": "string",
  "thumbnail_subtext": "string",
  "thumbnail_query": "string",
  "pinned_comment": "string",
  "debate_card": {{
    "option_a": "REAL BREAKTHROUGH",
    "option_b": "OVERHYPED",
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
      "narration": "string",
      "visual_query": "string",
      "tone": "hook",
      "highlight_text": "string",
      "speaker": "main",
      "interactive_type": "none"
    }}
  ]
}}
"""

    max_tokens = 3600 if is_shorts else 8192
    models_to_try = _discover_gemini_models()
    last_error = None
    valid_tones = {"hook", "urgent", "excited", "serious", "analytical", "calm"}
    valid_inter = {"none", "countdown", "debate", "music_drop"}

    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        gen_cfg = {"temperature": 0.78, "maxOutputTokens": max_tokens}
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

                # Merge live YouTube Autocomplete keywords into tags for stronger Search & Feed indexing
                raw_tags = [str(t).strip() for t in (blueprint.get("tags") or []) if str(t).strip()]
                merged_tags = list(dict.fromkeys(raw_tags + live_seo_keywords))[:24]
                blueprint["tags"] = merged_tags

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
                for idx_s, sc in enumerate(blueprint["scenes"]):
                    nar = _clean_narration(sc.get("narration", ""))
                    if not nar:
                        continue
                    tone = str(sc.get("tone", "hook" if idx_s == 0 else "analytical")).strip().lower()
                    if tone not in valid_tones:
                        tone = "analytical"
                    spk = str(sc.get("speaker", "main")).strip().lower()
                    if spk not in ("main", "cohost") or is_shorts:
                        spk = "main"
                    itype = str(sc.get("interactive_type", "none")).strip().lower()
                    if itype not in valid_inter:
                        itype = "none"
                    cleaned_scenes.append({
                        "narration": nar,
                        "visual_query": str(sc.get("visual_query", "technology")).strip() or "technology",
                        "tone": tone,
                        "highlight_text": _clean_narration(sc.get("highlight_text", ""))[:72],
                        "speaker": spk,
                        "interactive_type": itype,
                    })

                cleaned_scenes = _ensure_interactive_and_outro(cleaned_scenes, is_shorts)
                blueprint["scenes"] = cleaned_scenes
                if not blueprint["scenes"]:
                    raise ValueError("Empty scenes")
                print(
                    f"[ScriptAI] Blueprint ready with {model} ({len(blueprint['scenes'])} scenes) | "
                    f"Tags: {len(merged_tags)} | MusicAI -> '{blueprint['music_direction']['music_query']}'"
                )
                return blueprint
            except Exception as e:
                last_error = f"{model} error: {e}"
                break

    print(f"[ScriptAI] Warning ({last_error})")
    return _build_emergency_headline_blueprint(combined_topics, custom_topic, is_shorts, live_seo_keywords)
