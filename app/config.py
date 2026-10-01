import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
DB_PATH = DATA_DIR / "gastos.db"
UPLOAD_DIR = DATA_DIR / "uploads"
STATIC_DIR = ROOT / "static"

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
