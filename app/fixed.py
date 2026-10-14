"""Fixed monthly expenses: registered once, they show up as an entry in every month.

Entries are created month by month up to the current one (never ahead of time), each one a
regular transaction that can be edited on its own (an electricity bill that came higher).
"""

import calendar
import sqlite3
from datetime import date


def month_key(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def months_between(start: str, end: str) -> list[str]:
    y, m = int(start[:4]), int(start[5:7])
    out = []
    while f"{y}-{m:02d}" <= end:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def entry_date(month: str, day: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return date(y, m, min(day, calendar.monthrange(y, m)[1])).isoformat()


def materialize(conn: sqlite3.Connection, today: date | None = None) -> int:
    """Creates the entries still missing up to the current month. Returns how many."""
    current = month_key(today or date.today())
    created = 0
    for f in conn.execute("SELECT * FROM fixed_expenses").fetchall():
        last = min(f["end_month"] or current, current)
        done = {r[0] for r in conn.execute("SELECT month FROM fixed_months WHERE fixed_id = ?", (f["id"],))}
        for month in months_between(f["start_month"], last):
            if month in done:
                continue
            conn.execute(
                """INSERT INTO transactions
                   (date, description, merchant, amount_cents, category, source, notes, origin, fixed_id, bill_month)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'fixed', ?, ?)""",
                (entry_date(month, f["day"]), f["description"], f["description"], f["amount_cents"], f["category"],
                 f["source"], f["notes"], f["id"], month),
            )
            conn.execute("INSERT INTO fixed_months (fixed_id, month) VALUES (?, ?)", (f["id"], month))
            created += 1
    return created


def apply_changes(conn: sqlite3.Connection, fixed_id: int, from_month: str | None, today: date | None = None) -> None:
    """After an edit: entries outside the new period go away, and entries from from_month on
    (None = all of them) take the new description, value, category, day and card."""
    f = conn.execute("SELECT * FROM fixed_expenses WHERE id = ?", (fixed_id,)).fetchone()
    outside = "bill_month < ? OR (? IS NOT NULL AND bill_month > ?)"
    conn.execute(
        f"DELETE FROM transactions WHERE fixed_id = ? AND ({outside})",
        (fixed_id, f["start_month"], f["end_month"], f["end_month"]),
    )
    conn.execute(
        "DELETE FROM fixed_months WHERE fixed_id = ? AND (month < ? OR (? IS NOT NULL AND month > ?))",
        (fixed_id, f["start_month"], f["end_month"], f["end_month"]),
    )
    rows = conn.execute(
        "SELECT id, bill_month FROM transactions WHERE fixed_id = ? AND bill_month >= ?",
        (fixed_id, from_month or ""),
    ).fetchall()
    for r in rows:
        conn.execute(
            """UPDATE transactions SET date = ?, description = ?, merchant = ?, amount_cents = ?, category = ?,
               source = ?, notes = ? WHERE id = ?""",
            (entry_date(r["bill_month"], f["day"]), f["description"], f["description"], f["amount_cents"],
             f["category"], f["source"], f["notes"], r["id"]),
        )
    materialize(conn, today)
