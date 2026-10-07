"""Remembers category corrections so the next statements come out right.

A rule maps a normalized description ("IFD*PIZZARIA BELLA" -> "d:ifd pizzaria bella")
or a normalized merchant ("iFood - Pizzaria Bella" -> "m:ifood pizzaria bella") to a
category. Descriptions printed by the bank are the most stable key, so they win;
merchant names (cleaned up by Claude) catch the variations.
"""

import re
import sqlite3
import unicodedata

MIN_KEY_LENGTH = 3
IGNORED_WORDS = {"parc", "parcela"}
# Words that say how money moved, not where: "PIX ENVIADO" alone would teach a rule for every Pix.
GENERIC_WORDS = {
    "pix", "enviado", "enviada", "recebido", "recebida", "transferencia", "transf", "ted", "doc", "boleto",
    "pagamento", "pagto", "pgto", "pag", "compra", "debito", "deb", "credito", "cred", "cartao", "conta",
    "saque", "internet", "app", "via", "de", "do", "da", "dos", "das", "no", "na", "em", "para", "a", "o", "e",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    words = re.sub(r"[^a-z]+", " ", text).split()
    return " ".join(w for w in words if w not in IGNORED_WORDS)


def keys(description: str, merchant: str) -> list[str]:
    out = []
    for prefix, text in (("d:", description), ("m:", merchant)):
        key = normalize(text)
        if len(key) >= MIN_KEY_LENGTH and not set(key.split()) <= GENERIC_WORDS:
            out.append(prefix + key)
    return out


def lookup(conn: sqlite3.Connection, description: str, merchant: str) -> str | None:
    for key in keys(description, merchant):
        row = conn.execute("SELECT category FROM category_rules WHERE key = ?", (key,)).fetchone()
        if row:
            return row["category"]
    return None


def learn(conn: sqlite3.Connection, description: str, merchant: str, category: str) -> None:
    for key in keys(description, merchant):
        conn.execute(
            """INSERT INTO category_rules (key, category) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET category = excluded.category,
                                              updated_at = datetime('now', 'localtime')""",
            (key, category),
        )


def similar(conn: sqlite3.Connection, description: str, merchant: str, exclude_id: int) -> list[sqlite3.Row]:
    """Transactions (id, category) sharing the description or the merchant of the given one."""
    wanted = set(keys(description, merchant))
    if not wanted:
        return []
    return [
        r
        for r in conn.execute("SELECT id, category, description, merchant FROM transactions")
        if r["id"] != exclude_id and wanted & set(keys(r["description"], r["merchant"]))
    ]
