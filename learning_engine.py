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
    "golden_hour_shorts_et": 20,
    "golden_hour_long_et": 20,
    "top_hours_shorts_et": [20, 17, 12, 8],
    "top_hours_long_et": [20, 14],
    "hourly_stats": {"shorts": {}, "long": {}},
    "scheduled_slots": {},
    "last_updated_utc": "",
}


def load_strategy_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = dict(DEFAULT_MEMORY)
            merged.update(data)
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


def fetch_youtube_autocomplete_keywords(seed_topic, max_results=14):
    """Fetches real-time high-demand US YouTube Search autocomplete keywords for SEO ranking."""
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
    hrs = int(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    secs = int(m.group(3) or 0)
    return hrs * 3600 + mins * 60 + secs


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
    """Pulls 1-3 real viewer comments from recent videos so AI can shout out the community."""
    comments_out = []
    for vid in video_ids[:5]:
        try:
            c_resp = youtube_service.commentThreads().list(
                part="snippet",
                videoId=vid,
                order="relevance",
                maxResults=3,
                textFormat="plainText",
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


def update_strategy_from_youtube(youtube_service=None):
    """100x Self-Learning Brain: learns formats, title hooks, SEO keywords, viewer comments & US Golden Hours."""
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
            part="snippet,statistics,contentDetails,status",
            id=",".join(vid_ids[:50]),
        ).execute()

        now_utc = datetime.now(timezone.utc)
        shorts_views, long_views = [], []
        hourly_raw = {"shorts": {}, "long": {}}
        pattern_scores = {}
        keyword_scores = {}
        top_performing = []
        live_scheduled_slots = {}
        public_vid_ids = []

        for v in v_resp.get("items", []):
            vid_id = v.get("id", "")
            snip = v.get("snippet", {})
            stats = v.get("statistics", {})
            cdet = v.get("contentDetails", {})
            status = v.get("status", {})

            dur_s = _parse_iso_duration_seconds(cdet.get("duration", ""))
            v_fmt = "shorts" if dur_s <= 120 else "long"

            pub_at_str = status.get("publishAt")
            if pub_at_str:
                sched_dt = _parse_utc_dt(pub_at_str)
                if sched_dt and sched_dt > now_utc:
                    sched_et = sched_dt.astimezone(US_EASTERN)
                    d_key = sched_et.strftime("%Y-%m-%d")
                    live_scheduled_slots.setdefault(d_key, []).append({
                        "hour_et": sched_et.hour,
                        "format": v_fmt,
                        "publish_at_utc": pub_at_str,
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

            if v_fmt == "shorts":
                shorts_views.append(views)
            else:
                long_views.append(views)

            pub_et = pub_dt.astimezone(US_EASTERN)
            hr_key = str(pub_et.hour)
            bucket = hourly_raw[v_fmt].setdefault(hr_key, {"views_sum": 0, "reach_sum": 0.0, "count": 0})
            bucket["views_sum"] += views
            bucket["reach_sum"] += reach_score
            bucket["count"] += 1

            title_clean = re.sub(r"#\w+", "", snip.get("title", "")).strip()
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
        print(
            f"[LearningEngine] 100x Sync -> Shorts avg: {mem['shorts_score']} | Long avg: {mem['long_score']} | "
            f"Golden ET: Shorts={mem['golden_hour_shorts_et']:02d}:00, Long={mem['golden_hour_long_et']:02d}:00 | "
            f"Top Hooks: {', '.join(mem.get('winning_title_patterns', []))}"
        )
    except Exception as e:
        print(f"[LearningEngine] Stats sync skipped: {e}")

    return mem


def _gemini_seo_rewrite(gemini_api_key, old_title, old_desc, seo_keywords, is_shorts, winning_patterns):
    """Calls Gemini to craft a higher-CTR, search-optimized Title, Description & Tags within 48h window."""
    if not gemini_api_key:
        return None

    kw_str = ", ".join(seo_keywords[:12]) if seo_keywords else "tech news, ai news, gaming, stock market"
    prompt = f"""You are a YouTube US SEO & CTR Optimization Specialist.
An uploaded {'YouTube Short' if is_shorts else 'Long-Form YouTube Video'} is underperforming in its first 48 hours.
Rewrite its Title, SEO Description (keep any existing timestamps intact), and Tags to maximize US Search ranking and Browse/Shorts Feed CTR.

Current Title: {old_title}
Current Description: {old_desc[:1200]}
Live US YouTube Autocomplete Keywords: {kw_str}
Channel's Best-Performing Title Hook Styles: {', '.join(winning_patterns or ['curiosity_contrast'])}

Rules:
- Title: Punchy, high curiosity, under 88 chars, naturally include the strongest search keyword. {'End with #Shorts.' if is_shorts else 'No #Shorts tag.'}
- Description: First 2 lines must be ultra-SEO friendly with natural keywords + call to action, preserve any 00:00 chapter lines if present, end with 4-6 relevant hashtags.
- Tags: 15-20 high-relevance US search keywords (no # symbols).

Return ONLY valid JSON:
{{
  "title": "string",
  "description": "string",
  "tags": ["kw1", "kw2"]
}}
"""
    models = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-flash-lite", "gemma-3-27b-it"]
    for model in models:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_api_key}"
            cfg = {"temperature": 0.7, "maxOutputTokens": 1200}
            if "gemma" not in model:
                cfg["responseMimeType"] = "application/json"
            resp = requests.post(
                url,
                json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": cfg},
                timeout=45,
            )
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
    """
    Auto-scans public videos published 6h to 48h ago.
    If views lag behind channel benchmark, researches live YouTube Autocomplete keywords
    and updates Title + SEO Description + Tags once to revive search & feed ranking.
    """
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
        pl_resp = youtube_service.playlistItems().list(
            part="contentDetails", playlistId=uploads_pl, maxResults=20
        ).execute()
        vid_ids = [it["contentDetails"]["videoId"] for it in pl_resp.get("items", []) if it.get("contentDetails")]
        if not vid_ids:
            return

        v_resp = youtube_service.videos().list(
            part="snippet,statistics,contentDetails,status",
            id=",".join(vid_ids[:20]),
        ).execute()

        now_utc = datetime.now(timezone.utc)
        repaired = 0
        shorts_thresh = max(80.0, float(mem.get("shorts_score", 100.0)) * 0.60)
        long_thresh = max(35.0, float(mem.get("long_score", 30.0)) * 0.70)

        for v in v_resp.get("items", []):
            if repaired >= max_repairs_per_run:
                break
            vid_id = v.get("id", "")
            if not vid_id or vid_id in healed_ids:
                continue

            status = v.get("status", {})
            if status.get("privacyStatus") != "public":
                continue

            snip = v.get("snippet", {})
            stats = v.get("statistics", {})
            cdet = v.get("contentDetails", {})

            pub_dt = _parse_utc_dt(snip.get("publishedAt", ""))
            if not pub_dt:
                continue
            age_h = (now_utc - pub_dt).total_seconds() / 3600.0
            if not (6.0 <= age_h <= 48.0):
                continue

            dur_s = _parse_iso_duration_seconds(cdet.get("duration", ""))
            is_shorts = dur_s <= 120
            views = int(stats.get("viewCount", 0))
            thresh = shorts_thresh if is_shorts else long_thresh

            if views >= thresh:
                continue

            old_title = snip.get("title", "")
            old_desc = snip.get("description", "")
            cat_id = snip.get("categoryId", "28")

            live_kws = fetch_youtube_autocomplete_keywords(old_title, max_results=14)
            rewritten = _gemini_seo_rewrite(
                gemini_api_key,
                old_title,
                old_desc,
                live_kws,
                is_shorts,
                mem.get("winning_title_patterns", []),
            )
            if not rewritten:
                continue

            new_title = str(rewritten["title"]).strip()[:98]
            if is_shorts and "#shorts" not in new_title.lower() and len(new_title) <= 90:
                new_title += " #Shorts"
            new_desc = str(rewritten["description"]).strip()[:4900]
            new_tags = [str(t).strip() for t in (rewritten.get("tags") or live_kws) if str(t).strip()][:25]

            try:
                youtube_service.videos().update(
                    part="snippet",
                    body={
                        "id": vid_id,
                        "snippet": {
                            "title": new_title,
                            "description": new_desc,
                            "tags": new_tags,
                            "categoryId": cat_id,
                            "defaultLanguage": "en",
                        },
                    },
                ).execute()
                healed_ids.add(vid_id)
                repaired += 1
                print(
                    f"[SEO-SelfHeal 48h] Refreshed ({age_h:.1f}h old, {views} views) -> "
                    f"'{old_title[:45]}' => '{new_title[:55]}'"
                )
            except Exception as upd_e:
                print(f"[SEO-SelfHeal 48h] Update skipped for {vid_id} (check OAuth scope): {upd_e}")
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

    chosen_dt = None
    reason = ""

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
        day_list.append({
            "hour_et": int(hour_et),
            "format": fmt,
            "publish_at_utc": publish_iso,
        })
    mem["scheduled_slots"] = sched
    save_strategy_memory(mem)
