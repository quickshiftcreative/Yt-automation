import json
import os
from datetime import datetime, timezone

MEMORY_FILE = "strategy_memory.json"


def load_strategy_memory():
    default_mem = {
        "updated_at": "",
        "winning_topics": ["AI & GPU economics", "GTA 6 & viral gaming shifts", "US market & tech earnings"],
        "avoid_patterns": ["generic filler intros", "repetitive stock loops"],
        "preferred_format": "auto",
        "shorts_score": 1.0,
        "long_score": 1.0,
        "notes": "Self-learning engine initialized for Quick Shift Creative.",
    }
    if not os.path.exists(MEMORY_FILE):
        return default_mem
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            default_mem.update(data)
            return default_mem
    except Exception:
        return default_mem


def update_strategy_from_youtube(youtube_service=None, gemini_api_key=""):
    """Audits recent channel uploads via YouTube API and updates strategy_memory.json."""
    mem = load_strategy_memory()
    if youtube_service is None:
        mem["updated_at"] = datetime.now(timezone.utc).isoformat()
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(mem, f, indent=2)
        return mem

    try:
        ch_res = youtube_service.channels().list(part="contentDetails,statistics", mine=True).execute()
        items = ch_res.get("items", [])
        if not items:
            return mem
        uploads_pid = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        pl_res = youtube_service.playlistItems().list(
            part="snippet,contentDetails", playlistId=uploads_pid, maxResults=25
        ).execute()
        vids = []
        for it in pl_res.get("items", []):
            title = it["snippet"].get("title", "")
            vid = it["contentDetails"].get("videoId", "")
            if vid:
                vids.append({"video_id": vid, "title": title})

        if not vids:
            return mem

        ids_csv = ",".join(v["video_id"] for v in vids[:25])
        st_res = youtube_service.videos().list(part="statistics,contentDetails", id=ids_csv).execute()
        stats_map = {x["id"]: x for x in st_res.get("items", [])}

        shorts_views, shorts_cnt = 0, 0
        long_views, long_cnt = 0, 0
        scored = []

        for v in vids:
            info = stats_map.get(v["video_id"], {})
            stt = info.get("statistics", {})
            views = int(stt.get("viewCount", 0))
            likes = int(stt.get("likeCount", 0))
            comments = int(stt.get("commentCount", 0))
            eng = views + likes * 15 + comments * 30
            tl = v["title"].lower()
            is_sh = "#shorts" in tl or "short" in tl
            if is_sh:
                shorts_views += views
                shorts_cnt += 1
            else:
                long_views += views
                long_cnt += 1
            scored.append({"title": v["title"], "views": views, "engagement": eng, "is_shorts": is_sh})

        scored.sort(key=lambda x: x["engagement"], reverse=True)
        top_titles = [x["title"] for x in scored[:5] if x["title"]]
        if top_titles:
            mem["winning_topics"] = top_titles

        avg_s = (shorts_views / shorts_cnt) if shorts_cnt else 0.0
        avg_l = (long_views / long_cnt) if long_cnt else 0.0
        mem["shorts_score"] = round(avg_s, 2)
        mem["long_score"] = round(avg_l, 2)
        mem["updated_at"] = datetime.now(timezone.utc).isoformat()

        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(mem, f, indent=2)
        print(f"[LearningEngine] Updated memory -> Shorts avg: {avg_s:.1f} | Long avg: {avg_l:.1f}")
    except Exception as e:
        print(f"[LearningEngine] Audit warning: {e}")

    return mem
