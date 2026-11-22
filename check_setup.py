import shutil
import requests
from config import GEMINI_API_KEY, PIXABAY_API_KEY, PROJECT_NAME, CHANNEL_NAME
from youtube_uploader import get_youtube_service


def check():
    print(f"=== {PROJECT_NAME} ({CHANNEL_NAME} - US Edition) Health Check ===")

    ffmpeg = shutil.which("ffmpeg")
    print(f"[1/4] FFmpeg: {'OK -> ' + ffmpeg if ffmpeg else 'MISSING! Install ffmpeg.'}")

    if GEMINI_API_KEY:
        r = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}",
            timeout=15,
        )
        print(f"[2/4] Gemini API: {'OK' if r.status_code == 200 else f'FAILED (HTTP {r.status_code})'}")
    else:
        print("[2/4] Gemini API: MISSING GEMINI_API_KEY")

    if PIXABAY_API_KEY:
        r = requests.get(
            f"https://pixabay.com/api/?key={PIXABAY_API_KEY}&q=technology&per_page=3",
            timeout=15,
        )
        print(f"[3/4] Pixabay API: {'OK' if r.status_code == 200 else f'FAILED (HTTP {r.status_code})'}")
    else:
        print("[3/4] Pixabay API: MISSING PIXABAY_API_KEY")

    try:
        yt = get_youtube_service()
        ch = yt.channels().list(part="snippet", mine=True).execute()
        items = ch.get("items", [])
        if items:
            print(f"[4/4] YouTube Auth: OK -> Connected Channel: {items[0]['snippet']['title']}")
        else:
            print("[4/4] YouTube Auth: Connected, but no channel found on this account.")
    except Exception as e:
        print(f"[4/4] YouTube Auth: FAILED -> {e}")


if __name__ == "__main__":
    check()
