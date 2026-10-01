import sqlite3
from contextlib import contextmanager
from datetime import date

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filenames TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,              -- processing | review | confirmed | error
    error TEXT,
    issuer TEXT,
    reference_month TEXT,
    due_date TEXT,
    statement_total_cents INTEGER,
    extracted_json TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    model TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,                -- YYYY-MM-DD
    description TEXT NOT NULL,
    merchant TEXT NOT NULL DEFAULT '',
    amount_cents INTEGER NOT NULL,     -- positive = expense, negative = refund/credit
    category TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',   -- card / account label
    installment TEXT,                  -- e.g. "3/10"
    notes TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL,              -- manual | import
    import_id INTEGER REFERENCES imports(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_imports_hash ON imports(file_hash);

-- Category corrections made by the couple, applied to future imports.
CREATE TABLE IF NOT EXISTS category_rules (
    key TEXT PRIMARY KEY,              -- "d:<normalized description>" or "m:<normalized merchant>"
    category TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

BACKUPS_TO_KEEP = 14


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    config.ensure_dirs()
    with session() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)


def backup_daily() -> None:
    """Keeps one copy of the database per day (the last BACKUPS_TO_KEEP days).

    Called at startup and before destructive operations, so an accidental
    deletion can always be undone by restoring yesterday's file.
    """
    if not config.DB_PATH.exists():
        return
    folder = config.DATA_DIR / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"gastos-{date.today().isoformat()}.db"
    if target.exists():
        return
    src = connect()
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    for old in sorted(folder.glob("gastos-*.db"))[:-BACKUPS_TO_KEEP]:
        old.unlink(missing_ok=True)
