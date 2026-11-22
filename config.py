import os

# Load local config.env if running on a laptop/local machine
try:
    from dotenv import load_dotenv
    if os.path.exists("config.env"):
        load_dotenv("config.env")
    elif os.path.exists(".env"):
        load_dotenv(".env")
except ImportError:
    pass

PROJECT_NAME = "My automation YT"
CHANNEL_NAME = "Quick Shift Creative"
TARGET_REGION = "US"

# API Keys & Credentials (Loaded from GitHub Secrets or local config.env)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "").strip()
YOUTUBE_TOKEN_JSON = os.getenv("YOUTUBE_TOKEN_JSON", "").strip()

# Runtime Settings (Configurable via GitHub Actions Manual Run dropdowns)
NEWS_CATEGORY = os.getenv("NEWS_CATEGORY", "auto").strip().lower()      # "auto", "ai", "tech", "gaming", "us_trends"
VIDEO_FORMAT = os.getenv("VIDEO_FORMAT", "horizontal").strip().lower()  # "horizontal" (16:9) or "shorts" (9:16)
VOICE_STYLE = os.getenv("VOICE_STYLE", "male_us").strip().lower()       # "male_us", "deep_us", "female_us"
PRIVACY_STATUS = os.getenv("PRIVACY_STATUS", "public").strip().lower()  # "public", "unlisted", or "private"
CUSTOM_TOPIC = os.getenv("CUSTOM_TOPIC", "").strip()

# Directories & State Files
WORK_DIR = "temp_work"
OUTPUT_DIR = "output"
HISTORY_FILE = "history.json"
TOKEN_FILE = "token.json"

# 100% US Neural Voices (Edge-TTS - Completely Free)
VOICE_MAP = {
    "male_us": "en-US-AndrewNeural",        # Crisp, high-energy US Tech/Gaming host
    "deep_us": "en-US-ChristopherNeural",   # Authoritative US News Bulletin anchor
    "female_us": "en-US-AvaNeural",         # Modern, engaging US Tech & AI presenter
}

# YouTube Category IDs (Auto-selected based on topic)
YOUTUBE_CATEGORIES = {
    "tech": "28",    # Science & Technology
    "ai": "28",      # Science & Technology
    "gaming": "20",  # Gaming
}


def get_resolution():
    if VIDEO_FORMAT == "shorts":
        return (1080, 1920)
    return (1920, 1080)
