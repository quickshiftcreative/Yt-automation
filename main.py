import os
import shutil
import traceback
from config import PROJECT_NAME, CHANNEL_NAME, WORK_DIR, OUTPUT_DIR, CUSTOM_TOPIC
from trending_engine import fetch_trending_topics, save_history
from script_ai import generate_video_blueprint
from voice_engine import generate_scene_voices_and_srt
from media_fetcher import fetch_stock_image
from thumbnail_maker import create_thumbnail
from video_builder import build_final_video
from youtube_uploader import get_youtube_service, upload_video_with_thumbnail
from learning_engine import load_strategy_memory, update_strategy_from_youtube


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


def run_pipeline():
    print("=" * 65)
    print(f"Starting {PROJECT_NAME} | Channel: {CHANNEL_NAME}")
    print("=" * 65)

    youtube = get_youtube_service()
    print("[Pipeline] YouTube OAuth verified!")

    update_strategy_from_youtube(youtube_service=youtube)

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

    srt_path = os.path.join(WORK_DIR, "captions.srt")
    scene_audio_info, total_duration = generate_scene_voices_and_srt(
        blueprint["scenes"], WORK_DIR, srt_path
    )
    print(f"[Pipeline] Total voiceover duration: {total_duration:.2f}s")

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
    build_final_video(scene_audio_info, srt_path, WORK_DIR, final_video_path)

    video_id = upload_video_with_thumbnail(
        video_path=final_video_path,
        thumbnail_path=thumbnail_path,
        title=blueprint["title"],
        description=blueprint["description"],
        tags=blueprint.get("tags", []),
        category=blueprint.get("category", "tech"),
    )

    save_history(
        topic=blueprint.get("chosen_topic", CUSTOM_TOPIC or blueprint["title"]),
        title=blueprint["title"],
        video_id=video_id,
        category=blueprint.get("category", "tech"),
    )

    print("=" * 65)
    print(f"DONE! Live on {CHANNEL_NAME}: https://www.youtube.com/watch?v={video_id}")
    print("=" * 65)


if __name__ == "__main__":
    try:
        run_pipeline()
    except Exception as exc:
        print(f"\n[ERROR] Pipeline failed: {exc}")
        traceback.print_exc()
        raise SystemExit(1)
