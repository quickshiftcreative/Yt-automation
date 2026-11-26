from datetime import datetime, timedelta, timezone
import json
import os
import random
import re

try:
    from zoneinfo import ZoneInfo
    US_EASTERN = ZoneInfo("America/New_York")
except Exception:
    US_EASTERN = timezone(timedelta(hours=-5))

MEMORY_FILE = "strategy_memory.json"

# Baseline US audience peak traffic weights (0-23 in America/New_York time)
# Used as smart priors and automatically blended with real channel view/reach data
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


def _get_baseline_map(video_format, is_weekend):
    if video_format == "shorts":
        return US_BASELINE_SHORTS_WEEKEND if is_weekend else US_BASELINE_SHORTS_WEEKDAY
    return US_BASELINE_LONG_WEEKEND if is_weekend else US_BASELINE_LONG_WEEKDAY


def _compute_ranked_hours(hourly_bucket, video_format, is_weekend):
    """Blends US peak traffic priors with actual channel hourly views & velocity."""
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
            # As real video samples grow, channel data overrides baseline up to 85%
            real_weight = min(0.85, cnt / (cnt + 2.5))
            blended = (1.0 - real_weight) * prior_w + real_weight * rel_perf
        else:
            blended = prior_w
        scored.append((hr, round(blended, 4)))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def update_strategy_from_youtube(youtube_service=None):
    """Learns winning formats, topics, US Eastern peak hours, and Golden Hour from live YouTube stats."""
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
        top_performing = []
        live_scheduled_slots = {}

        for v in v_resp.get("items", []):
            snip = v.get("snippet", {})
            stats = v.get("statistics", {})
            cdet = v.get("contentDetails", {})
            status = v.get("status", {})

            dur_s = _parse_iso_duration_seconds(cdet.get("duration", ""))
            v_fmt = "shorts" if dur_s <= 120 else "long"

            # Track already-scheduled upcoming YouTube videos to avoid slot collisions
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

            # Only learn audience timing & reach from public videos
            if status.get("privacyStatus") != "public":
                continue

            views = int(stats.get("viewCount", 0))
            likes = int(stats.get("likeCount", 0))
            comments = int(stats.get("commentCount", 0))
            pub_dt = _parse_utc_dt(snip.get("publishedAt", ""))
            if not pub_dt:
                continue

            age_hours = max(2.0, (now_utc - pub_dt).total_seconds() / 3600.0)
            # Engagement + age-adjusted velocity rewards videos that take off fast
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

        if shorts_views:
            mem["shorts_score"] = round(sum(shorts_views) / len(shorts_views), 2)
        if long_views:
            mem["long_score"] = round(sum(long_views) / len(long_views), 2)

        # Summarize hourly performance per format
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

        # Merge live YouTube upcoming scheduled slots into memory
        sched_mem = mem.get("scheduled_slots") or {}
        today_str = now_et.strftime("%Y-%m-%d")
        # Prune old dates (> 2 days old)
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
            f"[LearningEngine] Updated memory -> Shorts avg: {mem['shorts_score']} | Long avg: {mem['long_score']} | "
            f"US Golden Hours (ET): Shorts={mem['golden_hour_shorts_et']:02d}:00, Long={mem['golden_hour_long_et']:02d}:00"
        )
    except Exception as e:
        print(f"[LearningEngine] Stats sync skipped: {e}")

    return mem


def pick_smart_publish_time(video_format="shorts", min_lead_minutes=30):
    """
    Smart US Audience Auto-Scheduler:
    1. Guarantees 1 daily video is locked to the learned US Golden Hour (if upcoming & unclaimed).
    2. Otherwise picks the next highest-scoring unclaimed US peak hour in the next 10 hours.
    3. Leaves 15% controlled exploration on strong untested US hours so AI keeps improving.
    4. Always keeps >= 30 min lead time so YouTube finishes HD processing & copyright checks.
    Returns: (publish_at_utc_iso, human_readable_summary, chosen_hour_et, date_et_key)
    """
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
        # Pick :15 past the hour (less crowded than :00 when thousands of channels auto-drop)
        cand = earliest_et.replace(hour=hr, minute=15, second=0, microsecond=0)
        if cand < earliest_et:
            cand = earliest_et.replace(hour=hr, minute=45, second=0, microsecond=0)
        return cand

    chosen_dt = None
    reason = ""

    # Priority 1: Anchor the learned US Golden Hour once every day (within next 9 hours)
    if golden_hr not in claimed_hours_same_fmt:
        g_dt = _candidate_dt_for_hour(golden_hr)
        delta_h = (g_dt - now_et).total_seconds() / 3600.0
        if (min_lead_minutes / 60.0) <= delta_h <= 9.0:
            chosen_dt = g_dt
            reason = f"Golden Hour Lock ({golden_hr:02d}:15 ET — #1 learned reach slot)"

    # Priority 2: Smart upcoming US peak window (within next 5.5 hours)
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
            # 15% smart exploration of a strong US hour with 0 samples so AI keeps discovering better times
            untested = [c for c in upcoming_candidates if c[2] == 0]
            if untested and random.random() < 0.15:
                pick = untested[0]
                chosen_dt = pick[3]
                reason = f"Smart US Peak Exploration ({pick[0]:02d}:15 ET, score={pick[1]})"
            else:
                pick = max(upcoming_candidates, key=lambda x: x[1])
                chosen_dt = pick[3]
                reason = f"Learned US Peak Slot ({pick[0]:02d}:15 ET, score={pick[1]})"

    # Priority 3: Safe fallback (+35 min lead time rounded to next 5-min mark)
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
    """Saves the claimed US time slot in strategy_memory.json so future runs never double-book."""
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
