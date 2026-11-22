import json
import os
import re
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from config import YOUTUBE_TOKEN_JSON, TOKEN_FILE, PRIVACY_STATUS, YOUTUBE_CATEGORIES


def get_youtube_service():
    """Authenticates with YouTube Data API v3 using GitHub Secret YOUTUBE_TOKEN_JSON or local token.json."""
    token_data = None
    if YOUTUBE_TOKEN_JSON:
        token_data = json.loads(YOUTUBE_TOKEN_JSON)
    elif os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            token_data = json.load(f)
    else:
        raise RuntimeError(
            "YouTube credentials not found! Add YOUTUBE_TOKEN_JSON to GitHub Secrets "
            "or save token.json locally."
        )

    creds = Credentials.from_authorized_user_info(token_data)
    if not creds.valid or creds.expired:
        if creds.refresh_token:
            print("[YouTube] Refreshing OAuth access token...")
            creds.refresh(Request())
        else:
            raise RuntimeError("Token is expired and has no refresh_token!")

    return build("youtube", "v3", credentials=creds)


def _sanitize_tags(tags):
    """Cleans tags and keeps total character count safely under YouTube's 500-char limit."""
    cleaned = []
    total_len = 0
    for tag in tags or []:
        t = re.sub(r"[<>#]", "", str(tag)).strip()
        if not t or len(t) > 60:
            continue
        if total_len + len(t) + 2 > 460:
            break
        cleaned.append(t)
        total_len += len(t) + 2
    return cleaned


def upload_video_with_thumbnail(video_path, thumbnail_path, title, description, tags, category="tech"):
    youtube = get_youtube_service()
    safe_tags = _sanitize_tags(tags)
    privacy = PRIVACY_STATUS if PRIVACY_STATUS in ("public", "unlisted", "private") else "unlisted"
    category_id = YOUTUBE_CATEGORIES.get(category, "28")

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": safe_tags,
            "categoryId": category_id,
            "defaultLanguage": "en-US",
            "defaultAudioLanguage": "en-US",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, mimetype="video/mp4", chunksize=4 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    print(f"[YouTube] Uploading US Bulletin ({privacy} | Category {category_id}): {title}")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[YouTube] Upload progress: {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"[YouTube] Video Uploaded! URL: https://www.youtube.com/watch?v={video_id}")

    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
            ).execute()
            print(f"[YouTube] Custom thumbnail applied to video {video_id}!")
        except HttpError as e:
            print(
                f"[YouTube] Thumbnail skipped (verify your YouTube channel phone number at "
                f"https://www.youtube.com/verify to enable custom thumbnails). Details: {e}"
            )
        except Exception as e:
            print(f"[YouTube] Thumbnail upload warning: {e}")

    return video_id
