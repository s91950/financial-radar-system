import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # API Keys
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    NEWS_API_KEY: str = os.getenv("NEWS_API_KEY", "")

    # Gemini AI
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    DEFAULT_AI_MODEL: str = os.getenv("DEFAULT_AI_MODEL", "gemini")

    # Google Apps Script Web App (for Sheets write)
    GOOGLE_APPS_SCRIPT_URL: str = os.getenv("GOOGLE_APPS_SCRIPT_URL", "")

    # Notification
    LINE_NOTIFY_TOKEN: str = os.getenv("LINE_NOTIFY_TOKEN", "")
    LINE_CHANNEL_ACCESS_TOKEN: str = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    LINE_TARGET_ID: str = os.getenv("LINE_TARGET_ID", "")  # User ID / Group ID / Room ID
    # Minimum severity to trigger LINE Messaging API push: critical | high | all
    LINE_NOTIFY_MIN_SEVERITY: str = os.getenv("LINE_NOTIFY_MIN_SEVERITY", "critical")
    LINE_CHANNEL_SECRET: str = os.getenv("LINE_CHANNEL_SECRET", "")
    EMAIL_SMTP_HOST: str = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
    EMAIL_SMTP_PORT: int = int(os.getenv("EMAIL_SMTP_PORT", "587"))
    EMAIL_SENDER: str = os.getenv("EMAIL_SENDER", "")
    EMAIL_PASSWORD: str = os.getenv("EMAIL_PASSWORD", "")
    EMAIL_RECIPIENT: str = os.getenv("EMAIL_RECIPIENT", "")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./data/financial_radar.db")

    # Google Sheets
    GOOGLE_SHEETS_CREDENTIALS_FILE: str = os.getenv("GOOGLE_SHEETS_CREDENTIALS_FILE", "credentials.json")
    GOOGLE_SHEETS_SPREADSHEET_ID: str = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
    GOOGLE_SHEETS_POSITION_SHEET: str = os.getenv("GOOGLE_SHEETS_POSITION_SHEET", "positions")
    GOOGLE_SHEETS_NEWS_SHEET: str = os.getenv("GOOGLE_SHEETS_NEWS_SHEET", "news_archive")

    # Scheduler
    RADAR_INTERVAL_MINUTES: int = int(os.getenv("RADAR_INTERVAL_MINUTES", "5"))
    MARKET_CHECK_INTERVAL_MINUTES: int = int(os.getenv("MARKET_CHECK_INTERVAL_MINUTES", "60"))
    NEWS_SCHEDULE_HOUR: int = int(os.getenv("NEWS_SCHEDULE_HOUR", "8"))
    NEWS_SCHEDULE_MINUTE: int = int(os.getenv("NEWS_SCHEDULE_MINUTE", "0"))


settings = Settings()
