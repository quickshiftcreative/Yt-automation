from datetime import datetime, timedelta, timezone
import json
import os
import random
import re
import urllib.parse
import requests

try:
    from zoneinfo import ZoneInfo
    US_EASTERN = ZoneInfo("America/New_York")
except Exception:
    US_EASTERN = timezone(timedelta(hours=-5))

MEMORY_FILE = "strategy_memory.json"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

THUMBNAIL_FONTS = [
    "Anton",
    "Lilita One",
    "Poppins Black",
    "Bebas Neue",
    "Oswald",
    "Bangers",
]

THUMBNAIL_LAYOUTS = [
    "mrbeast_top_boom",
    "split_vs_drama",
    "upper_left_hero",
    "minimal_big_stat",
]

THUMB_EXPERIMENT_TARGET = 50

US_BASELINE_SHORTS_WEEKDAY = {
    8: 1.28, 9: 1.15, 11: 1.18, 12: 1.32, 13: 1.20,
    16: 1.22, 17: 1.36, 18: 1.28, 19: 1.30, 20: 1.40, 21: 1.34, 22: 1.22,
}
US_BASELINE_SHORTS_WEEKEND = {
    9: 1.18, 10: 1.32, 11: 1.28, 12: 1.30, 13: 1.34,
    16: 1.24, 17: 1.32, 18: 1.28, 19: 1.34, 20: 1.42, 21: 1.36, 22: 1.25,
}
US_BASELINE_LONG_WEEKDAY = {
    11: 1.12, 12: 1.22, 13: 1.26, 14: 1.34, 15: 1.28,
    17: 1.26, 18: 1.30, 19: 1.38, 20: 1.44, 21: 1.35,
}
US_BASELINE_LONG_WEEKEND = {
    10: 1.26, 11: 1.30, 12: 1.34, 13: 1.32, 14: 1.28,
    17: 1.25, 18: 1.32, 19: 1.38, 20: 1.45, 21: 1.36,
}

DEFAULT_MEMORY = {
    "shorts_score": 1.0,
    "long_score": 1.0,
    "winning_topics": ["AI chips & Nvidia", "US tech market shifts", "viral gaming releases"],
    "avoid_patterns": ["generic clickbait without proof", "slow robotic intros"],
    "winning_title_patterns": ["curiosity_contrast", "specific_number"],
    "winning_keywords": ["ai news", "nvidia", "tech news", "gaming", "stock market"],
    "recent_viewer_comments": [],
    "healed_video_ids": [],
    "best_long_video_id": "",
    "endscreen_picks": {"top": None, "boost": None},
    "last_branding_sync_utc": "",
    "golden_hour_shorts_et": 20,
    "golden_hour_long_et": 20,
    "top_hours_shorts_et": [20, 17, 12, 8],
    "top_hours_long_et": [20, 14],
    "hourly_stats": {"shorts": {}, "long": {}},
    "scheduled_slots": {},
    "thumbnail_experiments": {
        "target_videos": THUMB_EXPERIMENT_TARGET,
        "total_recorded": 0,
        "winning_font": "Anton",
        "winning_layout": "mrbeast_top_boom",
        "font_stats": {},
        "layout_stats": {},
        "records": {},
    },
    "last_updated_utc": "",
}


def load_strategy_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = dict(DEFAULT_MEMORY)
            merged.update(data)
            if "thumbnail_experiments" not in merged or not isinstance(merged["thumbnail_experiments"], dict):
                merged["thumbnail_experiments"] = dict(DEFAULT_MEMORY["thumbnail_experiments"])
            else:
                te = dict(DEFAULT_MEMORY["thumbnail_experiments"])
                te.update(merged["thumbnail_experiments"])
                if te.get("winning_layout") not in THUMBNAIL_LAYOUTS:
                    te["winning_layout"] = "mrbeast_top_boom"
                merged["thumbnail_experiments"] = te
            if "endscreen_picks" not in merged or not isinstance(merged["endscreen_picks"], dict):
                merged["endscreen_picks"] = {"top": None, "boost": None}
            return merged
        except Exception:
            pass
    return dict(DEFAULT_MEMORY)


def save_strategy_memory(mem):
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(mem, f, indent=2)
    except Exception as e:
        print(f"[LearningEngine] Warning saving memory: {e}")


def get_endscreen_pair():
    """Returns 1 top-performing Long video and 1 low-performing Long video to promote on End Screen."""
    mem = load_strategy_memory()
    picks = mem.get("endscreen_picks") or {}
    return {
        "top": picks.get("top"),
        "boost": picks.get("boost"),
    }


def fetch_youtube_autocomplete_keywords(seed_topic, max_results=14):
    clean_seed = re.sub(r"[^a-zA-Z0-9\s]", " ", str(seed_topic or "")).strip()
    words = [w for w in clean_seed.split() if len(w) > 2]
    queries = []
    if words:
        queries.append(" ".join(words[:4]))
        if len(words) >= 2:
            queries.append(" ".join(words[:2]))
        queries.append(f"{words[0]} news")
    else:
        queries.append("tech news today")

    found = []
    for q in queries[:3]:
        try:
            url = (
                "https://suggestqueries.google.com/complete/search"
                f"?client=firefox&ds=yt&hl=en&gl=us&q={urllib.parse.quote_plus(q)}"
            )
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=8)
            if r.status_code == 200:
                payload = r.json()
                suggestions = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
                for s in suggestions:
                    s_clean = re.sub(r"\s+", " ", str(s)).strip()
                    if s_clean and s_clean.lower() not in [x.lower() for x in found]:
                        found.append(s_clean)
        except Exception:
            continue

    return found[:max_results]


def _parse_iso_duration_seconds(dur_str):
    if not dur_str:
        return 0
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur_str)
    if not m:
        return 0
    return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)


def _parse_utc_dt(iso_str):
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _classify_title_pattern(title):
    t = (title or "").strip()
    low = t.lower()
    if "?" in t:
        return "curiosity_question"
    if re.search(r"\b\d+[%$BMKbm]?\b", t):
        return "specific_number"
    if any(w in low for w in ("vs", "versus", "secret", "truth", "hidden", "why", "scandal", "crash")):
        return "curiosity_contrast"
    if any(w in low for w in ("breaking", "just", "alert", "update", "today")):
        return "urgent_breaking"
    return "direct_statement"


def _get_baseline_map(video_format, is_weekend):
    if video_format == "shorts":
        return US_BASELINE_SHORTS_WEEKEND if is_weekend else US_BASELINE_SHORTS_WEEKDAY
    return US_BASELINE_LONG_WEEKEND if is_weekend else US_BASELINE_LONG_WEEKDAY


def _compute_ranked_hours(hourly_bucket, video_format, is_weekend):
    priors = _get_baseline_map(video_format, is_weekend)
    all_avgs = [v["avg_reach"] for v in hourly_bucket.values() if v.get("count", 0) > 0 and v.get("avg_reach", 0) > 0]
    global_avg = (sum(all_avgs) / len(all_avgs)) if all_avgs else 0.0

    scored = []
    for hr in range(24):
        prior_w = priors.get(hr, 0.72)
        stat = hourly_bucket.get(str(hr))
        if stat and stat.get("count", 0) > 0 and global_avg > 0:
            cnt = int(stat["count"])
            rel_perf = float(stat["avg_reach"]) / global_avg
            real_weight = min(0.85, cnt / (cnt + 2.5))
            blended = (1.0 - real_weight) * prior_w + real_weight * rel_perf
        else:
            blended = prior_w
        scored.append((hr, round(blended, 4)))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _fetch_recent_viewer_comments(youtube_service, video_ids):
    comments_out = []
    for vid in video_ids[:5]:
        try:
            c_resp = youtube_service.commentThreads().list(
                part="snippet", videoId=vid, order="relevance", maxResults=3, textFormat="plainText"
            ).execute()
            for item in c_resp.get("items", []):
                top = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
                author = str(top.get("authorDisplayName", "")).strip()
                txt = re.sub(r"\s+", " ", str(top.get("textDisplay", ""))).strip()
                if len(txt) >= 12 and "quick shift creative" not in author.lower():
                    comments_out.append(f"{author}: {txt[:120]}")
                if len(comments_out) >= 3:
                    return comments_out
        except Exception:
            continue
    return comments_out


def _update_thumbnail_experiment_scores(mem, live_video_metrics):
    te = mem.get("thumbnail_experiments") or dict(DEFAULT_MEMORY["thumbnail_experiments"])
    records = te.get("records") or {}
    if not records:
        return

    shorts_base = max(10.0, float(mem.get("shorts_score", 50.0)))
    long_base = max(5.0, float(mem.get("long_score", 15.0)))

    for vid_id, rec in records.items():
        m = live_video_metrics.get(vid_id)
        if not m:
            continue
        views = m["views"]
        velocity = m["velocity"]
        base_avg = shorts_base if rec.get("is_shorts") else long_base
        ctr_proxy = round((views / base_avg) * 0.55 + (velocity / max(1.0, base_avg * 0.12)) * 0.45, 3)
        rec["views"] = views
        rec["ctr_proxy"] = ctr_proxy

    font_agg, layout_agg = {}, {}
    for rec in records.values():
        if rec.get("ctr_proxy") is None:
            continue
        fn = rec.get("font", "Anton")
        ly = rec.get("layout", "mrbeast_top_boom")
        score = float(rec["ctr_proxy"])
        views = int(rec.get("views", 0))

        fa = font_agg.setdefault(fn, {"count": 0, "score_sum": 0.0, "views_sum": 0})
        fa["count"] += 1
        fa["score_sum"] += score
        fa["views_sum"] += views

        if ly in THUMBNAIL_LAYOUTS:
            la = layout_agg.setdefault(ly, {"count": 0, "score_sum": 0.0, "views_sum": 0})
            la["count"] += 1
            la["score_sum"] += score
            la["views_sum"] += views

    te["font_stats"] = {
        k: {"count": v["count"], "avg_ctr_proxy": round(v["score_sum"] / max(1, v["count"]), 3), "avg_views": round(v["views_sum"] / max(1, v["count"]), 1)}
        for k, v in font_agg.items()
    }
    te["layout_stats"] = {
        k: {"count": v["count"], "avg_ctr_proxy": round(v["score_sum"] / max(1, v["count"]), 3), "avg_views": round(v["views_sum"] / max(1, v["count"]), 1)}
        for k, v in layout_agg.items()
    }
    te["total_recorded"] = len(records)

    if te["font_stats"]:
        te["winning_font"] = max(te["font_stats"].items(), key=lambda x: x[1]["avg_ctr_proxy"])[0]
    if te["layout_stats"]:
        te["winning_layout"] = max(te["layout_stats"].items(), key=lambda x: x[1]["avg_ctr_proxy"])[0]

    mem["thumbnail_experiments"] = te


def pick_thumbnail_experiment_config(topic_text="", category="tech"):
    mem = load_strategy_memory()
    te = mem.get("thumbnail_experiments") or {}
    records = te.get("records") or {}
    total_done = len(records)
    target = int(te.get("target_videos", THUMB_EXPERIMENT_TARGET))

    font_counts = {f: 0 for f in THUMBNAIL_FONTS}
    layout_counts = {l: 0 for l in THUMBNAIL_LAYOUTS}
    for rec in records.values():
        fn, ly = rec.get("font"), rec.get("layout")
        if fn in font_counts:
            font_counts[fn] += 1
        if ly in layout_counts:
            layout_counts[ly] += 1

    font_stats = te.get("font_stats") or {}
    layout_stats = te.get("layout_stats") or {}

    if total_done < target:
        phase = f"50-Video Experiment ({total_done + 1}/{target})"
        min_f, min_l = min(font_counts.values()), min(layout_counts.values())
        if min_f >= 3 and font_stats and random.random() < 0.40:
            chosen_font = te.get("winning_font", "Anton")
        else:
            chosen_font = random.choice([f for f, c in font_counts.items() if c == min_f])

        if min_l >= 4 and layout_stats and random.random() < 0.40:
            chosen_layout = te.get("winning_layout", "mrbeast_top_boom")
        else:
            chosen_layout = random.choice([l for l, c in layout_counts.items() if c == min_l])
    else:
        phase = f"Mastery Auto-Winner ({total_done} tested)"
        if random.random() < 0.80:
            chosen_font = te.get("winning_font", "Anton")
            chosen_layout = te.get("winning_layout", "mrbeast_top_boom")
        else:
            chosen_font = random.choice(THUMBNAIL_FONTS)
            chosen_layout = random.choice(THUMBNAIL_LAYOUTS)

    if chosen_layout not in THUMBNAIL_LAYOUTS:
        chosen_layout = "mrbeast_top_boom"

    low = f"{topic_text} {category}".lower()
    if any(w in low for w in ("crash", "scandal", "drop", "warning", "ban", "hack", "loss", "crisis", "risk", "exposed")):
        accent = "red"
    elif any(w in low for w in ("stock", "billion", "million", "profit", "rally", "surge", "money", "earnings", "portfolio", "business")):
        accent = "green"
    elif any(w in low for w in ("ai", "gpu", "nvidia", "chip", "robot", "gaming", "playstation", "xbox", "quantum")):
        accent = "cyan" if random.random() < 0.45 else "gold"
    else:
        accent = "gold"

    cfg = {"font": chosen_font, "layout": chosen_layout, "accent": accent, "phase": phase}
    print(f"[ThumbAI] {phase} -> Font: {chosen_font} | Layout: {chosen_layout} | Accent: {accent}")
    return cfg


def record_thumbnail_experiment(video_id, thumb_cfg, topic="", is_shorts=False):
    if not video_id or not thumb_cfg:
        return
    mem = load_strategy_memory()
    te = mem.get("thumbnail_experiments") or dict(DEFAULT_MEMORY["thumbnail_experiments"])
    records = te.get("records") or {}

    records[video_id] = {
        "font": thumb_cfg.get("font", "Anton"),
        "layout": thumb_cfg.get("layout", "mrbeast_top_boom"),
        "accent": thumb_cfg.get("accent", "gold"),
        "topic": str(topic or "")[:70],
        "is_shorts": bool(is_shorts),
        "uploaded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "views": 0,
        "ctr_proxy": None,
    }

    if len(records) > 100:
        sorted_keys = sorted(records.keys(), key=lambda k: records[k].get("uploaded_utc", ""))
        for old_k in sorted_keys[:-100]:
            records.pop(old_k, None)

    te["records"] = records
    te["total_recorded"] = len(records)
    mem["thumbnail_experiments"] = te
    save_strategy_memory(mem)
    print(f"[ThumbAI] Recorded experiment #{te['total_recorded']} for video {video_id}")


def should_sync_channel_branding():
    mem = load_strategy_memory()
    last_s = mem.get("last_branding_sync_utc", "")
    if not last_s:
        return True
    dt = _parse_utc_dt(last_s)
    if not dt:
        return True
    return (datetime.now(timezone.utc) - dt) >= timedelta(days=7)


def mark_channel_branding_synced():
    mem = load_strategy_memory()
    mem["last_branding_sync_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_strategy_memory(mem)


def update_strategy_from_youtube(youtube_service=None):
    mem = load_strategy_memory()
    if youtube_service is None:
        return mem

    try:
        ch_resp = youtube_service.channels().list(part="contentDetails", mine=True).execute()
        items = ch_resp.get("items", [])
        if not items:
            return mem

        uploads_pl = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        pl_resp = youtube_service.playlistItems().list(
            part="contentDetails", playlistId=uploads_pl, maxResults=50
        ).execute()
        vid_ids = [it["contentDetails"]["videoId"] for it in pl_resp.get("items", []) if it.get("contentDetails")]
        if not vid_ids:
            return mem

        v_resp = youtube_service.videos().list(
            part="snippet,statistics,contentDetails,status", id=",".join(vid_ids[:50])
        ).execute()

        now_utc = datetime.now(timezone.utc)
        shorts_views, long_views = [], []
        hourly_raw = {"shorts": {}, "long": {}}
        pattern_scores, keyword_scores = {}, {}
        top_performing, live_scheduled_slots, public_vid_ids, live_video_metrics = [], {}, [], {}
        long_catalog = []

        for v in v_resp.get("items", []):
            vid_id = v.get("id", "")
            snip, stats = v.get("snippet", {}), v.get("statistics", {})
            cdet, status = v.get("contentDetails", {}), v.get("status", {})

            dur_s = _parse_iso_duration_seconds(cdet.get("duration", ""))
            v_fmt = "shorts" if dur_s <= 120 else "long"

            pub_at_str = status.get("publishAt")
            if pub_at_str:
                sched_dt = _parse_utc_dt(pub_at_str)
                if sched_dt and sched_dt > now_utc:
                    sched_et = sched_dt.astimezone(US_EASTERN)
                    d_key = sched_et.strftime("%Y-%m-%d")
                    live_scheduled_slots.setdefault(d_key, []).append({
                        "hour_et": sched_et.hour, "format": v_fmt, "publish_at_utc": pub_at_str,
                    })
                continue

            if status.get("privacyStatus") != "public":
                continue

            public_vid_ids.append(vid_id)
            views = int(stats.get("viewCount", 0))
            likes = int(stats.get("likeCount", 0))
            comments = int(stats.get("commentCount", 0))
            pub_dt = _parse_utc_dt(snip.get("publishedAt", ""))
            if not pub_dt:
                continue

            age_hours = max(2.0, (now_utc - pub_dt).total_seconds() / 3600.0)
            eng_boost = 1.0 + min(0.5, ((likes + comments * 3.0) / max(1, views)) * 5.0)
            velocity = (views / (age_hours ** 0.65)) * eng_boost
            reach_score = (views * 0.55 + velocity * 12.0) * eng_boost

            live_video_metrics[vid_id] = {"views": views, "velocity": velocity, "reach_score": reach_score}
            raw_title = str(snip.get("title", "")).strip()

            if v_fmt == "shorts":
                shorts_views.append(views)
            else:
                long_views.append(views)
                long_catalog.append({
                    "id": vid_id,
                    "title": raw_title[:85],
                    "views": views,
                    "reach": reach_score,
                })

            pub_et = pub_dt.astimezone(US_EASTERN)
            hr_key = str(pub_et.hour)
            bucket = hourly_raw[v_fmt].setdefault(hr_key, {"views_sum": 0, "reach_sum": 0.0, "count": 0})
            bucket["views_sum"] += views
            bucket["reach_sum"] += reach_score
            bucket["count"] += 1

            title_clean = re.sub(r"#\w+", "", raw_title).strip()
            if title_clean:
                top_performing.append((reach_score, title_clean))
                pat = _classify_title_pattern(title_clean)
                p_b = pattern_scores.setdefault(pat, {"sum": 0.0, "cnt": 0})
                p_b["sum"] += reach_score
                p_b["cnt"] += 1

            for tg in (snip.get("tags") or [])[:12]:
                tg_low = str(tg).strip().lower()
                if len(tg_low) >= 3:
                    k_b = keyword_scores.setdefault(tg_low, {"sum": 0.0, "cnt": 0})
                    k_b["sum"] += reach_score
                    k_b["cnt"] += 1

        if shorts_views:
            mem["shorts_score"] = round(sum(shorts_views) / len(shorts_views), 2)
        if long_views:
            mem["long_score"] = round(sum(long_views) / len(long_views), 2)

        # Pick 1 Top-Performing Long Video + 1 Low-Performing Long Video for End Screen Promotion
        if long_catalog:
            sorted_long = sorted(long_catalog, key=lambda x: (x["views"], x["reach"]), reverse=True)
            top_vid = sorted_long[0]
            boost_vid = sorted_long[-1] if len(sorted_long) >= 2 else None
            mem["best_long_video_id"] = top_vid["id"]
            mem["endscreen_picks"] = {
                "top": {"id": top_vid["id"], "title": top_vid["title"], "views": top_vid["views"]},
                "boost": (
                    {"id": boost_vid["id"], "title": boost_vid["title"], "views": boost_vid["views"]}
                    if boost_vid else None
                ),
            }

        _update_thumbnail_experiment_scores(mem, live_video_metrics)

        hourly_summary = {"shorts": {}, "long": {}}
        for fmt in ("shorts", "long"):
            for hr_k, b in hourly_raw[fmt].items():
                cnt = max(1, b["count"])
                hourly_summary[fmt][hr_k] = {
                    "count": b["count"],
                    "avg_views": round(b["views_sum"] / cnt, 1),
                    "avg_reach": round(b["reach_sum"] / cnt, 2),
                }
        mem["hourly_stats"] = hourly_summary

        now_et = now_utc.astimezone(US_EASTERN)
        is_wknd = now_et.weekday() >= 5
        ranked_shorts = _compute_ranked_hours(hourly_summary["shorts"], "shorts", is_wknd)
        ranked_long = _compute_ranked_hours(hourly_summary["long"], "long", is_wknd)

        mem["golden_hour_shorts_et"] = ranked_shorts[0][0]
        mem["golden_hour_long_et"] = ranked_long[0][0]
        mem["top_hours_shorts_et"] = [h for h, _ in ranked_shorts[:6]]
        mem["top_hours_long_et"] = [h for h, _ in ranked_long[:4]]

        if top_performing:
            top_performing.sort(key=lambda x: x[0], reverse=True)
            mem["winning_topics"] = [t[:65] for _, t in top_performing[:5]]
        if pattern_scores:
            ranked_pats = sorted(pattern_scores.items(), key=lambda x: x[1]["sum"] / max(1, x[1]["cnt"]), reverse=True)
            mem["winning_title_patterns"] = [p for p, _ in ranked_pats[:3]]
        if keyword_scores:
            ranked_kws = sorted(keyword_scores.items(), key=lambda x: x[1]["sum"] / max(1, x[1]["cnt"]), reverse=True)
            mem["winning_keywords"] = [k for k, _ in ranked_kws[:10]]
        if public_vid_ids:
            fresh_comments = _fetch_recent_viewer_comments(youtube_service, public_vid_ids)
            if fresh_comments:
                mem["recent_viewer_comments"] = fresh_comments

        sched_mem = mem.get("scheduled_slots") or {}
        today_str = now_et.strftime("%Y-%m-%d")
        sched_mem = {k: v for k, v in sched_mem.items() if k >= today_str}
        for d_k, entries in live_scheduled_slots.items():
            existing = sched_mem.setdefault(d_k, [])
            for ent in entries:
                if not any(e.get("hour_et") == ent["hour_et"] and e.get("format") == ent["format"] for e in existing):
                    existing.append(ent)
        mem["scheduled_slots"] = sched_mem
        mem["last_updated_utc"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

        save_strategy_memory(mem)
        te = mem.get("thumbnail_experiments") or {}
        es = mem.get("endscreen_picks") or {}
        print(
            f"[LearningEngine] 100x Sync -> Shorts avg: {mem['shorts_score']} | Long avg: {mem['long_score']} | "
            f"Golden ET: S={mem['golden_hour_shorts_et']:02d}:00, L={mem['golden_hour_long_et']:02d}:00 | "
            f"ThumbAI ({te.get('total_recorded', 0)}/50): {te.get('winning_font')} + {te.get('winning_layout')} | "
            f"EndScreen Pair: Top={bool(es.get('top'))}, Boost={bool(es.get('boost'))}"
        )
    except Exception as e:
        print(f"[LearningEngine] Stats sync skipped: {e}")

    return mem


def _gemini_seo_rewrite(gemini_api_key, old_title, old_desc, seo_keywords, is_shorts, winning_patterns):
    if not gemini_api_key:
        return None
    kw_str = ", ".join(seo_keywords[:12]) if seo_keywords else "tech news, ai news, gaming, stock market"
    prompt = f"""You are a YouTube US SEO & CTR Optimization Specialist.
An uploaded {'YouTube Short' if is_shorts else 'Long-Form YouTube Video'} is underperforming in its first 48 hours.
Rewrite its Title, SEO Description (keep any existing timestamps and Watch Next links intact), and Tags to maximize US Search ranking and Browse/Shorts Feed CTR.

Current Title: {old_title}
Current Description: {old_desc[:1200]}
Live US YouTube Autocomplete Keywords: {kw_str}
Channel's Best-Performing Title Hook Styles: {', '.join(winning_patterns or ['curiosity_contrast'])}

Return ONLY valid JSON:
{{"title": "string", "description": "string", "tags": ["kw1", "kw2"]}}
"""
    models = ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.6-flash", "gemini-flash-latest", "gemma-3-27b-it"]
    for model in models:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_api_key}"
            cfg = {"temperature": 0.7, "maxOutputTokens": 1200}
            if "gemma" not in model:
                cfg["responseMimeType"] = "application/json"
            resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": cfg}, timeout=45)
            if resp.status_code != 200:
                continue
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\s*```$", "", raw)
            s, e = raw.find("{"), raw.rfind("}")
            if s != -1 and e != -1:
                raw = raw[s : e + 1]
            data = json.loads(raw)
            if data.get("title") and data.get("description"):
                return data
        except Exception:
            continue
    return None


def run_48h_seo_self_healing(youtube_service, gemini_api_key, max_repairs_per_run=2):
    if not youtube_service or not gemini_api_key:
        return
    mem = load_strategy_memory()
    healed_ids = set(mem.get("healed_video_ids") or [])

    try:
        ch_resp = youtube_service.channels().list(part="contentDetails", mine=True).execute()
        items = ch_resp.get("items", [])
        if not items:
            return
        uploads_pl = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        pl_resp = youtube_service.playlistItems().list(part="contentDetails", playlistId=uploads_pl, maxResults=20).execute()
        vid_ids = [it["contentDetails"]["videoId"] for it in pl_resp.get("items", []) if it.get("contentDetails")]
        if not vid_ids:
            return

        v_resp = youtube_service.videos().list(part="snippet,statistics,contentDetails,status", id=",".join(vid_ids[:20])).execute()
        now_utc = datetime.now(timezone.utc)
        repaired = 0
        shorts_thresh = max(80.0, float(mem.get("shorts_score", 100.0)) * 0.60)
        long_thresh = max(35.0, float(mem.get("long_score", 30.0)) * 0.70)

        for v in v_resp.get("items", []):
            if repaired >= max_repairs_per_run:
                break
            vid_id = v.get("id", "")
            if not vid_id or vid_id in healed_ids or v.get("status", {}).get("privacyStatus") != "public":
                continue

            snip, stats, cdet = v.get("snippet", {}), v.get("statistics", {}), v.get("contentDetails", {})
            pub_dt = _parse_utc_dt(snip.get("publishedAt", ""))
            if not pub_dt:
                continue
            age_h = (now_utc - pub_dt).total_seconds() / 3600.0
            if not (6.0 <= age_h <= 48.0):
                continue

            is_shorts = _parse_iso_duration_seconds(cdet.get("duration", "")) <= 120
            views = int(stats.get("viewCount", 0))
            if views >= (shorts_thresh if is_shorts else long_thresh):
                continue

            old_title, old_desc = snip.get("title", ""), snip.get("description", "")
            live_kws = fetch_youtube_autocomplete_keywords(old_title, max_results=14)
            rewritten = _gemini_seo_rewrite(gemini_api_key, old_title, old_desc, live_kws, is_shorts, mem.get("winning_title_patterns", []))
            if not rewritten:
                continue

            new_title = str(rewritten["title"]).strip()[:98]
            if is_shorts and "#shorts" not in new_title.lower() and len(new_title) <= 90:
                new_title += " #Shorts"
            new_desc = str(rewritten["description"]).strip()[:4900]
            new_tags = [re.sub(r"[<>#\"']+", "", str(t)).strip() for t in (rewritten.get("tags") or live_kws) if str(t).strip()][:16]

            try:
                youtube_service.videos().update(
                    part="snippet",
                    body={
                        "id": vid_id,
                        "snippet": {
                            "title": new_title,
                            "description": new_desc,
                            "tags": new_tags,
                            "categoryId": snip.get("categoryId", "28"),
                            "defaultLanguage": "en-US",
                            "defaultAudioLanguage": "en-US",
                        },
                    },
                ).execute()
                healed_ids.add(vid_id)
                repaired += 1
                print(f"[SEO-SelfHeal 48h] Refreshed ({age_h:.1f}h old, {views} views) -> '{new_title[:55]}'")
            except Exception as upd_e:
                print(f"[SEO-SelfHeal 48h] Update skipped for {vid_id}: {upd_e}")
                break

        if repaired > 0:
            mem["healed_video_ids"] = list(healed_ids)[-120:]
            save_strategy_memory(mem)
    except Exception as e:
        print(f"[SEO-SelfHeal 48h] Check skipped: {e}")


def pick_smart_publish_time(video_format="shorts", min_lead_minutes=30):
    mem = load_strategy_memory()
    fmt = "shorts" if str(video_format).strip().lower() == "shorts" else "long"

    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(US_EASTERN)
    earliest_et = now_et + timedelta(minutes=max(25, int(min_lead_minutes)))

    is_wknd = earliest_et.weekday() >= 5
    hourly_bucket = (mem.get("hourly_stats") or {}).get(fmt, {})
    ranked = _compute_ranked_hours(hourly_bucket, fmt, is_wknd)
    golden_hr = ranked[0][0]

    sched_mem = mem.get("scheduled_slots") or {}
    d_key = earliest_et.strftime("%Y-%m-%d")
    claimed_today = sched_mem.get(d_key, [])
    claimed_hours_same_fmt = {int(x["hour_et"]) for x in claimed_today if x.get("format") == fmt}
    claimed_hours_any = {int(x["hour_et"]) for x in claimed_today}

    def _candidate_dt_for_hour(hr):
        cand = earliest_et.replace(hour=hr, minute=15, second=0, microsecond=0)
        if cand < earliest_et:
            cand = earliest_et.replace(hour=hr, minute=45, second=0, microsecond=0)
        return cand

    chosen_dt, reason = None, ""

    if golden_hr not in claimed_hours_same_fmt:
        g_dt = _candidate_dt_for_hour(golden_hr)
        delta_h = (g_dt - now_et).total_seconds() / 3600.0
        if (min_lead_minutes / 60.0) <= delta_h <= 9.0:
            chosen_dt = g_dt
            reason = f"Golden Hour Lock ({golden_hr:02d}:15 ET — #1 learned reach slot)"

    if chosen_dt is None:
        upcoming_candidates = []
        for hr, score in ranked[:12]:
            if hr in claimed_hours_any:
                continue
            c_dt = _candidate_dt_for_hour(hr)
            delta_h = (c_dt - now_et).total_seconds() / 3600.0
            if (min_lead_minutes / 60.0) <= delta_h <= 5.5:
                samples = int((hourly_bucket.get(str(hr)) or {}).get("count", 0))
                upcoming_candidates.append((hr, score, samples, c_dt))

        if upcoming_candidates:
            untested = [c for c in upcoming_candidates if c[2] == 0]
            if untested and random.random() < 0.15:
                pick = untested[0]
                chosen_dt = pick[3]
                reason = f"Smart US Peak Exploration ({pick[0]:02d}:15 ET, score={pick[1]})"
            else:
                pick = max(upcoming_candidates, key=lambda x: x[1])
                chosen_dt = pick[3]
                reason = f"Learned US Peak Slot ({pick[0]:02d}:15 ET, score={pick[1]})"

    if chosen_dt is None:
        raw_dt = now_et + timedelta(minutes=max(35, int(min_lead_minutes)))
        rem = raw_dt.minute % 5
        if rem != 0:
            raw_dt += timedelta(minutes=(5 - rem))
        chosen_dt = raw_dt.replace(second=0, microsecond=0)
        reason = f"Next Immediate Safe Window ({chosen_dt.strftime('%H:%M')} ET)"

    publish_utc = chosen_dt.astimezone(timezone.utc)
    publish_iso = publish_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    summary = f"{chosen_dt.strftime('%Y-%m-%d %I:%M %p %Z')} ({publish_iso}) | {reason}"
    return publish_iso, summary, chosen_dt.hour, chosen_dt.strftime("%Y-%m-%d")


def record_scheduled_slot(video_format, hour_et, date_et_key, publish_iso):
    mem = load_strategy_memory()
    sched = mem.get("scheduled_slots") or {}
    day_list = sched.setdefault(date_et_key, [])
    fmt = "shorts" if str(video_format).strip().lower() == "shorts" else "long"
    if not any(x.get("hour_et") == hour_et and x.get("format") == fmt for x in day_list):
        day_list.append({"hour_et": int(hour_et), "format": fmt, "publish_at_utc": publish_iso})
    mem["scheduled_slots"] = sched
    save_strategy_memory(mem)
