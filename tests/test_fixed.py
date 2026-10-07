"""Fixed monthly expenses: one entry per month, up to the current month."""

from datetime import date

from app import fixed


def months_ago(n: int) -> str:
    t = date.today()
    y, m = divmod(t.year * 12 + t.month - 1 - n, 12)
    return f"{y}-{m + 1:02d}"


def fixed_entries(client):
    return sorted((t for t in client.get("/api/transactions").json() if t["origin"] == "fixed"), key=lambda t: t["date"])


def test_helpers():
    assert fixed.months_between("2026-11", "2027-02") == ["2026-11", "2026-12", "2027-01", "2027-02"]
    assert fixed.entry_date("2026-02", 31) == "2026-02-28"


def test_fixed_expense_fills_every_month(client):
    rent = {"description": "Aluguel", "amount_cents": 320000, "category": "casa", "day": 5, "start_month": months_ago(2)}
    r = client.post("/api/fixed", json=rent)
    assert r.status_code == 201, r.text
    assert r.json()["created_entries"] == 3
    entries = fixed_entries(client)
    assert [t["bill_month"] for t in entries] == [months_ago(2), months_ago(1), months_ago(0)]
    assert all(t["amount_cents"] == 320000 and t["date"].endswith("-05") for t in entries)

    # Listing again creates nothing new.
    assert len(fixed_entries(client)) == 3

    # One month's entry deleted by hand doesn't come back.
    client.delete(f"/api/transactions/{entries[0]['id']}")
    assert len(fixed_entries(client)) == 2

    # A raise applies from this month on; the months before keep what was paid.
    fid = r.json()["id"]
    r = client.put(f"/api/fixed/{fid}", json={**rent, "amount_cents": 350000})
    assert r.status_code == 200, r.text
    assert [t["amount_cents"] for t in fixed_entries(client)] == [320000, 350000]
    # ...or to every month, when asked.
    client.put(f"/api/fixed/{fid}?apply_to_past=true", json={**rent, "amount_cents": 350000})
    assert [t["amount_cents"] for t in fixed_entries(client)] == [350000, 350000]

    # Ended last month: this month's entry goes away.
    client.put(f"/api/fixed/{fid}", json={**rent, "amount_cents": 350000, "end_month": months_ago(1)})
    assert [t["bill_month"] for t in fixed_entries(client)] == [months_ago(1)]

    # Deleting keeps what was already paid, unless asked.
    assert client.delete(f"/api/fixed/{fid}").status_code == 204
    assert client.get("/api/fixed").json() == []
    assert len([t for t in client.get("/api/transactions").json() if t["description"] == "Aluguel"]) == 1


def test_delete_with_entries_and_validation(client):
    r = client.post("/api/fixed", json={"description": "Internet", "amount_cents": 12000, "start_month": months_ago(1)})
    assert r.json()["category"] == "casa"
    client.delete(f"/api/fixed/{r.json()['id']}?remove_entries=true")
    assert client.get("/api/transactions").json() == []

    bad = client.post("/api/fixed", json={"description": "X", "amount_cents": 100, "start_month": months_ago(0),
                                          "end_month": months_ago(1)})
    assert bad.status_code == 422
    assert client.post("/api/fixed", json={"description": "X", "amount_cents": 0, "start_month": "2026-01"}).status_code == 422


def test_future_start_creates_nothing_yet(client):
    t = date.today()
    nxt = f"{t.year + (t.month == 12)}-{t.month % 12 + 1:02d}"
    r = client.post("/api/fixed", json={"description": "Academia", "amount_cents": 9900, "category": "saude",
                                        "start_month": nxt})
    assert r.json()["created_entries"] == 0 and fixed_entries(client) == []
