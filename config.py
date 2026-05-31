import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN: str = os.environ.get("TELEGRAM_TOKEN", "")
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
TIMEZONE: str = os.environ.get("TIMEZONE", "Europe/Moscow")
DB_PATH: str = os.environ.get("DB_PATH", "huntly.db")
HH_USER_AGENT: str = os.environ.get("HH_USER_AGENT", "HuntlyBot/1.0 (job search bot)")

print(f"[config] TELEGRAM_TOKEN set: {bool(TELEGRAM_TOKEN)}")
print(f"[config] ANTHROPIC_API_KEY set: {bool(ANTHROPIC_API_KEY)}")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN is not set")
if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY is not set")
