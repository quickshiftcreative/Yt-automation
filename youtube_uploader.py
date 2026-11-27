from datetime import datetime, timedelta, timezone
import json
import os
import re
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
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


def _sanitize_youtube_tags(tags, max_total_chars=430, max_tags=18):
    cleaned = []
    seen = set()
    total_len = 0

    for raw in (tags or []):
        s = str(raw or "")
        s = re.sub(r"[<>#\"'\r\n\t|]+", " ", s)
        s = re.sub(r"[^\x20-\x7E]", "", s)
        s = re.sub(r"\s+", " ", s).strip(" ,.-")
        if len(s) < 2 or len(s) > 45:
            continue
        low = s.lower()
        if low in seen:
            continue

        item_cost = (len(s) + 2 if " " in s else len(s)) + (1 if cleaned else 0)
        if total_len + item_cost > max_total_chars:
            continue

        seen.add(low)
        cleaned.append(s)
        total_len += item_cost
        if len(cleaned) >= max_tags:
            break

    return cleaned or ["tech news", "ai news", "gaming", "markets"]


def _execute_resumable_upload(youtube, video_path, body):
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = req.next_chunk()
    return response


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

    clean_tags = _sanitize_youtube_tags(tags)
    cat_id = CATEGORY_MAP.get(str(category).lower(), "28")

    safe_title = re.sub(r"[<>]+", "", str(title or "Daily Tech Shift")).strip()[:99]
    safe_desc = re.sub(r"[<>]+", "", str(description or "")).strip()[:4900]

    body = {
        "snippet": {
            "title": safe_title,
            "description": safe_desc,
            "tags": clean_tags,
            "categoryId": cat_id,
            "defaultLanguage": "en-US",
            "defaultAudioLanguage": "en-US",
        },
        "status": status_body,
    }

    try:
        response = _execute_resumable_upload(youtube, video_path, body)
    except HttpError as e:
        err_txt = str(e)
        if "invalidTags" in err_txt or "invalid video keywords" in err_txt:
            print("[YouTube] Tag keyword warning — retrying immediately with safe tags...")
            body["snippet"]["tags"] = ["tech news", "ai news", "gaming", "stock market"]
            response = _execute_resumable_upload(youtube, video_path, body)
        elif "defaultLanguage" in err_txt or "defaultAudioLanguage" in err_txt:
            body["snippet"]["defaultLanguage"] = "en"
            body["snippet"]["defaultAudioLanguage"] = "en"
            response = _execute_resumable_upload(youtube, video_path, body)
        else:
            raise

    video_id = response["id"]
    print(f"[YouTube] Uploaded Video ID: {video_id} (Lang: en-US | Tags: {len(body['snippet']['tags'])})")

    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            thumb_media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
            youtube.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
            print("[YouTube] Custom thumbnail attached!")
        except Exception as e:
            print(f"[YouTube] Thumbnail upload warning: {e}")

    return video_id


def post_engagement_comment(youtube, video_id, comment_text):
    if not youtube or not video_id or not comment_text:
        return
    try:
        youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {"textOriginal": str(comment_text).strip()[:400]}
                    },
                }
            },
        ).execute()
        print(f"[CommentBot] Posted engagement comment on {video_id}!")
    except Exception as e:
        print(f"[CommentBot] Skipped (requires youtube.force-ssl scope): {e}")


def sync_channel_branding(youtube, winning_keywords=None, trailer_video_id=None):
    """
    Sets Channel Country to India ('IN') for safe AdSense/monetization verification,
    while targeting US English ('en-US') for US audience reach + SEO Description & Keywords.
    """
    if not youtube:
        return False
    try:
        ch_resp = youtube.channels().list(part="brandingSettings,snippet", mine=True).execute()
        items = ch_resp.get("items", [])
        if not items:
            return False

        ch = items[0]
        ch_id = ch["id"]
        current_title = (
            ch.get("brandingSettings", {}).get("channel", {}).get("title")
            or ch.get("snippet", {}).get("title", "Quick Shift Creative")
        )

        base_kws = [
            "Quick Shift Creative", "US Tech News", "AI News", "Gaming News",
            "Stock Market News", "Nvidia", "Semiconductors", "Tech Explainers",
            "Business Strategy", "Wall Street", "Viral Tech", "YouTube Shorts",
        ]
        extra = [str(k).strip() for k in (winning_keywords or []) if len(str(k).strip()) >= 3][:8]
        all_kws = list(dict.fromkeys(base_kws + extra))
        kw_string = " ".join(f'"{k}"' if " " in k else k for k in all_kws)[:480]

        seo_description = (
            "Welcome to Quick Shift Creative — your daily edge on Technology, AI, Gaming, and US Markets.\n\n"
            "Every single day, we break down the biggest shifts shaping Silicon Valley, chip manufacturing, "
            "Wall Street movers, and gaming culture — fast, visual, and straight to the point.\n\n"
            "What you get here:\n"
            "- Daily Tech, AI & Semiconductor Deep Dives\n"
            "- Stock Market & Big-Tech Business Breakdowns\n"
            "- High-Speed 60-Second Gaming & Viral Tech Shorts\n\n"
            "Subscribe and turn on notifications so you never miss the next big shift!"
        )

        for lang_code in ("en-US", "en"):
            channel_branding = {
                "title": current_title,
                "description": seo_description,
                "keywords": kw_string,
                "country": "IN",
                "defaultLanguage": lang_code,
            }
            if trailer_video_id:
                channel_branding["unsubscribedTrailer"] = trailer_video_id

            try:
                youtube.channels().update(
                    part="brandingSettings",
                    body={
                        "id": ch_id,
                        "brandingSettings": {"channel": channel_branding},
                    },
                ).execute()
                print(
                    f"[ChannelSEO] Updated Branding for '{current_title}' | "
                    f"Country: IN (Monetization Safe) | Language: {lang_code}"
                )
                return True
            except HttpError as he:
                if lang_code == "en-US" and ("defaultLanguage" in str(he) or "invalidBrandingOption" in str(he)):
                    continue
                raise
    except Exception as e:
        print(f"[ChannelSEO] Channel branding update skipped (needs full youtube scope): {e}")
        return False
