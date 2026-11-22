import os
import subprocess
from PIL import Image, ImageDraw
from config import get_resolution, VIDEO_FORMAT
from media_fetcher import fetch_stock_video


def _run_ffmpeg(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed:\n{result.stderr[-1200:]}")


def _create_fallback_frame(path, width, height):
    img = Image.new("RGB", (width, height), (14, 14, 20))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, 16], fill=(245, 197, 66))
    draw.rectangle([0, height - 16, width, height], fill=(245, 197, 66))
    img.save(path, "JPEG", quality=90)
    return path


def build_final_video(scene_audio_info, srt_path, work_dir, output_video_path):
    """Downloads Pixabay HD clips per scene and builds a clean 1080p MP4 with synced voice & subtitles."""
    width, height = get_resolution()
    used_ids = set()
    normalized_clips = []
    audio_files = []

    scale_crop = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps=30,format=yuv420p"
    )

    for info in scene_audio_info:
        idx = info["index"]
        dur = max(1.0, info["duration"])
        query = info["visual_query"]
        audio_files.append(info["audio_path"])

        raw_vid_path = os.path.join(work_dir, f"raw_{idx:02d}.mp4")
        media_path, media_type = fetch_stock_video(query, raw_vid_path, used_ids=used_ids)
        norm_clip_path = os.path.join(work_dir, f"clip_{idx:02d}.mp4")

        if media_type == "video" and media_path and os.path.exists(media_path):
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1",
                "-i", media_path,
                "-t", f"{dur:.3f}",
                "-vf", scale_crop,
                "-an",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "23",
                norm_clip_path,
            ]
            try:
                _run_ffmpeg(cmd)
            except Exception as e:
                print(f"[Video] Corrupt clip fallback on scene {idx}: {e}")
                media_type = "fallback"

        if media_type != "video":
            if media_type == "image" and media_path and os.path.exists(media_path):
                img_source = media_path
            else:
                img_source = _create_fallback_frame(os.path.join(work_dir, f"fallback_{idx:02d}.jpg"), width, height)

            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", img_source,
                "-t", f"{dur:.3f}",
                "-vf", scale_crop,
                "-an",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "23",
                norm_clip_path,
            ]
            _run_ffmpeg(cmd)

        normalized_clips.append(norm_clip_path)
        print(f"[Video] Prepared scene {idx + 1}/{len(scene_audio_info)} ({dur:.2f}s)")

    video_list_file = os.path.join(work_dir, "video_list.txt")
    with open(video_list_file, "w", encoding="utf-8") as f:
        for clip in normalized_clips:
            abs_p = os.path.abspath(clip).replace("\\", "/")
            f.write(f"file '{abs_p}'\n")

    merged_video = os.path.join(work_dir, "merged_video.mp4")
    _run_ffmpeg([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", video_list_file,
        "-c", "copy",
        merged_video,
    ])

    audio_list_file = os.path.join(work_dir, "audio_list.txt")
    with open(audio_list_file, "w", encoding="utf-8") as f:
        for aud in audio_files:
            abs_p = os.path.abspath(aud).replace("\\", "/")
            f.write(f"file '{abs_p}'\n")

    merged_audio = os.path.join(work_dir, "merged_audio.m4a")
    _run_ffmpeg([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", audio_list_file,
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        merged_audio,
    ])

    local_srt = "active_subtitles.srt"
    with open(srt_path, "r", encoding="utf-8") as src, open(local_srt, "w", encoding="utf-8") as dst:
        dst.write(src.read())

    font_size = 18 if VIDEO_FORMAT == "shorts" else 22
    margin_v = 70 if VIDEO_FORMAT == "shorts" else 34
    sub_filter = (
        f"subtitles={local_srt}:force_style="
        f"'FontName=DejaVu Sans,FontSize={font_size},Bold=1,"
        f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        f"BackColour=&H80000000,BorderStyle=1,Outline=2,Shadow=1,"
        f"Alignment=2,MarginV={margin_v}'"
    )

    try:
        _run_ffmpeg([
            "ffmpeg", "-y",
            "-i", merged_video,
            "-i", merged_audio,
            "-vf", sub_filter,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-shortest",
            output_video_path,
        ])
    except Exception as e:
        print(f"[Video] Subtitle filter warning ({e}). Muxing clean video without burned subtitles...")
        _run_ffmpeg([
            "ffmpeg", "-y",
            "-i", merged_video,
            "-i", merged_audio,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-shortest",
            output_video_path,
        ])
    finally:
        if os.path.exists(local_srt):
            os.remove(local_srt)

    print(f"[Video] Final HD video ready -> {output_video_path}")
    return output_video_path
