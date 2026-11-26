from datetime import datetime, timedelta, timezone
import json
import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

CATEGORY_MAP = {
    "tech": "28",
    "ai": "28",
    "gaming": "20",
}


def get_youtube_service():
    raw_token = os.getenv("YOUTUBE_TOKEN_JSON", "").strip()
    if not raw_token:
        raise RuntimeError("YOUTUBE_TOKEN_JSON secret is missing!")

    info = json.loads(raw_token)
    creds = Credentials.from_authorized_user_info(info)
    if creds.expired and creds.refresh_token:
        print("[YouTube] Refreshing OAuth access token...")
        creds.refresh(Request())

    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload_video_with_thumbnail(
    video_path,
    thumbnail_path,
    title,
    description,
    tags=None,
    category="tech",
    publish_at_iso=None,
):
    youtube = get_youtube_service()
    privacy = os.getenv("PRIVACY_STATUS", "unlisted").strip().lower()
    if privacy not in ("public", "unlisted", "private"):
        privacy = "unlisted"

    lead_mins = int(os.getenv("SCHEDULE_LEAD_MINUTES", "0") or "0")
    status_body = {
        "privacyStatus": privacy,
        "selfDeclaredMadeForKids": False,
    }

    if privacy == "public":
        if publish_at_iso:
            status_body["privacyStatus"] = "private"
            status_body["publishAt"] = publish_at_iso
            print(f"[YouTube] Smart AI Schedule Locked -> {publish_at_iso}")
        elif lead_mins > 0:
            publish_dt = datetime.now(timezone.utc) + timedelta(minutes=lead_mins)
            fallback_iso = publish_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            status_body["privacyStatus"] = "private"
            status_body["publishAt"] = fallback_iso
            print(f"[YouTube] Fallback Schedule -> {fallback_iso} (+{lead_mins} min)")

    clean_tags = [str(t).strip() for t in (tags or []) if str(t).strip()][:25]
    cat_id = CATEGORY_MAP.get(str(category).lower(), "28")

    body = {
        "snippet": {
            "title": title[:99],
            "description": description[:4900],
            "tags": clean_tags,
            "categoryId": cat_id,
            "defaultLanguage": "en",
        },
        "status": status_body,
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _, response = req.next_chunk()

    video_id = response["id"]
    print(f"[YouTube] Uploaded Video ID: {video_id}")

    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            thumb_media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
            youtube.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
            print("[YouTube] Custom thumbnail attached!")
        except Exception as e:
            print(f"[YouTube] Thumbnail upload warning: {e}")

    return video_id
