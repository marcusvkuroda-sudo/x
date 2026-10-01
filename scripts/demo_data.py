"""Fills a database with 12 months of fictitious expenses to preview the dashboard.

Usage (keeps your real data untouched by writing to a separate folder):
    DATA_DIR=data-demo python scripts/demo_data.py
    DATA_DIR=data-demo python run.py
"""

import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db  # noqa: E402

MERCHANTS = {
    "mercado": [("Pão de Açúcar", 180, 520), ("Hortifruti", 40, 140), ("Padaria Real", 15, 60), ("Assaí Atacadista", 250, 700)],
    "restaurantes": [("iFood", 45, 130), ("Outback", 180, 320), ("Starbucks", 25, 60), ("Boteco do Zé", 70, 200)],
    "transporte": [("Uber", 15, 60), ("Posto Shell", 150, 320), ("Sem Parar", 40, 110), ("99", 12, 45)],
    "casa": [("Enel", 180, 320), ("Vivo Fibra", 120, 120), ("Comgás", 50, 110), ("Leroy Merlin", 60, 400)],
    "lazer": [("Cinemark", 50, 120), ("Sympla", 90, 380), ("Airbnb", 600, 1800)],
    "saude": [("Drogasil", 30, 180), ("Smart Fit", 129.9, 129.9), ("Clínica Sorriso", 200, 450)],
    "compras": [("Amazon", 60, 450), ("Mercado Livre", 40, 380), ("Renner", 120, 420), ("Shopee", 20, 120)],
    "assinaturas": [("Netflix", 55.9, 55.9), ("Spotify Família", 34.9, 34.9), ("iCloud", 14.9, 14.9)],
    "outros": [("Petz", 80, 260), ("IOF compra internacional", 3, 15)],
}

FREQUENCY = {"mercado": 9, "restaurantes": 10, "transporte": 12, "casa": 4, "lazer": 2, "saude": 4, "compras": 5, "assinaturas": 3, "outros": 2}


def main() -> None:
    db.init()
    with db.session() as conn:
        if conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]:
            sys.exit(f"{config.DB_PATH} já tem lançamentos; use outro DATA_DIR para a demonstração.")
        rng = random.Random(42)
        today = date.today()
        start = (today.replace(day=1) - timedelta(days=330)).replace(day=1)
        rows = []
        d = start
        while d <= today:
            month_end = min(today, (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1))
            days = (month_end - d).days + 1
            for cat, freq in FREQUENCY.items():
                n = max(1, int(rng.gauss(freq, freq / 4) * days / 30))
                for _ in range(n):
                    name, lo, hi = rng.choice(MERCHANTS[cat])
                    day = d + timedelta(days=rng.randrange(days))
                    if day.weekday() >= 4 and cat in ("restaurantes", "lazer"):
                        hi *= 1.3
                    amount = round(rng.uniform(lo, hi), 2)
                    rows.append((day.isoformat(), name.upper(), name, int(amount * 100), cat, rng.choice(["Nubank", "Itaú Visa"]), None))
            d = month_end + timedelta(days=1)
        # Installment purchases still running: one installment on the 1st of each month, the
        # latest one this month (the 1st is never in the future).
        for name, cat, total_n, paid, value in (("Magazine Luiza - Geladeira", "casa", 10, 6, 389.9), ("Decolar - Passagens", "lazer", 6, 2, 412.5), ("Apple - iPhone", "compras", 12, 9, 541.58)):
            for k in range(1, paid + 1):
                back = paid - k
                year, month = divmod(today.year * 12 + today.month - 1 - back, 12)
                day = date(year, month + 1, 1)
                rows.append((day.isoformat(), f"{name.upper()} PARC {k:02d}/{total_n:02d}", name, int(value * 100), cat, "Nubank", f"{k}/{total_n}"))
        conn.executemany(
            "INSERT INTO transactions (date, description, merchant, amount_cents, category, source, installment, origin) VALUES (?, ?, ?, ?, ?, ?, ?, 'manual')",
            rows,
        )
    print(f"{len(rows)} lançamentos de exemplo criados em {config.DB_PATH}")


if __name__ == "__main__":
    main()
