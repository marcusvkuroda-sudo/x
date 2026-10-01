import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
DB_PATH = DATA_DIR / "gastos.db"
UPLOAD_DIR = DATA_DIR / "uploads"
STATIC_DIR = ROOT / "static"

# How statements are read: "local" (free, reads the PDF text / CSV / OFX), "claude" (paid API,
# also reads photos) or "auto" (Claude when an API key is configured, local otherwise).
EXTRACTION_MODE = os.environ.get("EXTRACTION_MODE", "auto").strip().lower()

CLAUDE_MODEL = os.environ.get("EXTRACTION_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = os.environ.get("EXTRACTION_EFFORT", "medium")

# Optional: when set, the browser asks for this password (any username).
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

# USD per million tokens (input, output), used only to show an estimated cost per import.
PRICING = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def use_claude() -> bool:
    return EXTRACTION_MODE == "claude" or (EXTRACTION_MODE == "auto" and has_api_key())
