import os
import shutil
import traceback
from config import PROJECT_NAME, CHANNEL_NAME, WORK_DIR, OUTPUT_DIR, CUSTOM_TOPIC, GEMINI_API_KEY
from trending_engine import fetch_trending_topics, save_history
from script_ai import generate_video_blueprint
from voice_engine import generate_scene_voices_and_srt
from media_fetcher import fetch_stock_image
from thumbnail_maker import create_thumbnail
from video_builder import build_final_video
from youtube_uploader import get_youtube_service, post_engagement_comment, upload_video_with_thumbnail
from learning_engine import (
    load_strategy_memory,
    pick_smart_publish_time,
    record_scheduled_slot,
    run_48h_seo_self_healing,
    update_strategy_from_youtube,
)


def _resolve_video_format():
    raw_fmt = os.getenv("VIDEO_FORMAT", "horizontal").strip().lower()
    if raw_fmt == "auto":
        mem = load_strategy_memory()
        s_score = float(mem.get("shorts_score", 1.0))
        l_score = float(mem.get("long_score", 1.0))
        chosen = "shorts" if s_score >= l_score else "horizontal"
        print(f"[Adaptive] Self-learning format pick -> {chosen.upper()} (shorts={s_score}, long={l_score})")
        return chosen
    return "shorts" if raw_fmt == "shorts" else "horizontal"


def _build_chapters_text(scene_audio_info):
    """Builds clickable YouTube timestamps for Long-form videos to boost Google/YouTube Search ranking."""
    if len(scene_audio_info) < 10:
        return ""
    step = max(4, len(scene_audio_info) // 6)
    picks = [0] + list(range(step, len(scene_audio_info) - 1, step)) + [len(scene_audio_info) - 1]
    seen = set()
    lines = ["\nChapters:"]
    for idx in picks:
        if idx in seen:
            continue
        seen.add(idx)
        sc = scene_audio_info[idx]
        t_sec = int(float(sc.get("start_time", 0)))
        mm, ss = divmod(t_sec, 60)
        lbl = "Intro & Hook" if idx == 0 else ("Final Takeaway" if idx == len(scene_audio_info) - 1 else (sc.get("highlight_text") or "Key Update"))
        lines.append(f"{mm:02d}:{ss:02d} {lbl[:48]}")
    return "\n".join(lines) + "\n"


def run_pipeline():
    print("=" * 65)
    print(f"Starting {PROJECT_NAME} | Channel: {CHANNEL_NAME}")
    print("=" * 65)

    youtube = get_youtube_service()
    print("[Pipeline] YouTube OAuth verified!")

    # 1. 100x Self-Learning sync (timing, views, hook styles, keywords & viewer comments)
    update_strategy_from_youtube(youtube_service=youtube)

    # 2. 48-Hour SEO Auto-Healing for any recent underperforming videos
    run_48h_seo_self_healing(youtube_service=youtube, gemini_api_key=GEMINI_API_KEY)

    active_format = _resolve_video_format()
    os.environ["VIDEO_FORMAT"] = active_format
    import config as cfg_mod
    cfg_mod.VIDEO_FORMAT = active_format

    if os.path.exists(WORK_DIR):
        shutil.rmtree(WORK_DIR)
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    trending_topics = [] if CUSTOM_TOPIC else fetch_trending_topics()
    blueprint = generate_video_blueprint(trending_topics, custom_topic=CUSTOM_TOPIC)

    captions_ass_path = os.path.join(WORK_DIR, "captions.ass")
    scene_audio_info, total_duration = generate_scene_voices_and_srt(
        blueprint["scenes"], WORK_DIR, captions_ass_path
    )
    print(f"[Pipeline] Total voiceover duration: {total_duration:.2f}s")

    # Append clickable Chapters to Long videos & ensure SEO hashtags exist
    final_desc = str(blueprint.get("description", "")).strip()
    if active_format != "shorts":
        chapters_txt = _build_chapters_text(scene_audio_info)
        if chapters_txt and "00:00" not in final_desc:
            final_desc = f"{final_desc}\n{chapters_txt}"
    if "#" not in final_desc:
        default_tags = "#Shorts #TechNews #AINews #QuickShiftCreative" if active_format == "shorts" else "#TechNews #AINews #Markets #QuickShiftCreative"
        final_desc = f"{final_desc}\n\n{default_tags}"

    thumb_bg_path = os.path.join(WORK_DIR, "thumb_bg.jpg")
    fetched_bg = fetch_stock_image(blueprint.get("thumbnail_query", "technology"), thumb_bg_path)
    thumbnail_path = os.path.join(OUTPUT_DIR, "thumbnail.jpg")
    create_thumbnail(
        bg_image_path=fetched_bg,
        headline=blueprint.get("thumbnail_headline", "BREAKING SHIFT"),
        subtext=blueprint.get("thumbnail_subtext", ""),
        output_path=thumbnail_path,
        bulletin_badge=blueprint.get("bulletin_badge", "TECH BULLETIN"),
    )

    final_video_path = os.path.join(OUTPUT_DIR, "final_video.mp4")
    build_final_video(
        scene_audio_info,
        captions_ass_path,
        WORK_DIR,
        final_video_path,
        music_direction=blueprint.get("music_direction", {}),
        chosen_topic=blueprint.get("chosen_topic", CUSTOM_TOPIC or blueprint["title"]),
        debate_card=blueprint.get("debate_card", {}),
    )

    privacy = os.getenv("PRIVACY_STATUS", "unlisted").strip().lower()
    lead_mins = int(os.getenv("SCHEDULE_LEAD_MINUTES", "30") or "30")
    publish_at_iso = None
    sched_hour_et = None
    sched_date_key = None

    if privacy == "public":
        publish_at_iso, sched_summary, sched_hour_et, sched_date_key = pick_smart_publish_time(
            video_format=active_format,
            min_lead_minutes=max(30, lead_mins),
        )
        print(f"[SmartSchedule] {sched_summary}")
    else:
        _, preview_summary, _, _ = pick_smart_publish_time(
            video_format=active_format,
            min_lead_minutes=30,
        )
        print(f"[SmartSchedule Preview (Unlisted Run)] Next optimal US slot -> {preview_summary}")

    video_id = upload_video_with_thumbnail(
        video_path=final_video_path,
        thumbnail_path=thumbnail_path,
        title=blueprint["title"],
        description=final_desc,
        tags=blueprint.get("tags", []),
        category=blueprint.get("category", "tech"),
        publish_at_iso=publish_at_iso,
    )

    # Auto-post debate question comment (works immediately on public/unlisted videos)
    if privacy != "private" and not publish_at_iso:
        post_engagement_comment(youtube, video_id, blueprint.get("pinned_comment", ""))

    if publish_at_iso and sched_hour_et is not None and sched_date_key:
        record_scheduled_slot(active_format, sched_hour_et, sched_date_key, publish_at_iso)

    save_history(
        topic=blueprint.get("chosen_topic", CUSTOM_TOPIC or blueprint["title"]),
        title=blueprint["title"],
        video_id=video_id,
        category=blueprint.get("category", "tech"),
    )

    print("=" * 65)
    print(f"DONE! Live/Scheduled on {CHANNEL_NAME}: https://www.youtube.com/watch?v={video_id}")
    print("=" * 65)


if __name__ == "__main__":
    try:
        run_pipeline()
    except Exception as exc:
        print(f"\n[ERROR] Pipeline failed: {exc}")
        traceback.print_exc()
        raise SystemExit(1)
