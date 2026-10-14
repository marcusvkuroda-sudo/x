"""Monthly income: recurring or for a single month."""


def test_income_crud_and_validation(client):
    r = client.post("/api/incomes", json={"description": "Salário Marcus", "amount_cents": 800000, "start_month": "2026-01"})
    assert r.status_code == 201 and r.json()["end_month"] is None
    bonus = client.post("/api/incomes", json={"description": "Bônus", "amount_cents": 150000,
                                              "start_month": "2026-12", "end_month": "2026-12"}).json()
    assert len(client.get("/api/incomes").json()) == 2

    r = client.put(f"/api/incomes/{bonus['id']}", json={**bonus, "amount_cents": 200000, "end_month": ""})
    assert r.status_code == 200 and r.json()["amount_cents"] == 200000 and r.json()["end_month"] is None

    bad = client.post("/api/incomes", json={"description": "X", "amount_cents": 1, "start_month": "2026-05",
                                             "end_month": "2026-04"})
    assert bad.status_code == 422
    assert client.post("/api/incomes", json={"description": "X", "amount_cents": 0, "start_month": "2026-05"}).status_code == 422

    assert client.delete(f"/api/incomes/{bonus['id']}").status_code == 204
    assert client.delete(f"/api/incomes/{bonus['id']}").status_code == 404
    assert [i["description"] for i in client.get("/api/incomes").json()] == ["Salário Marcus"]


def test_meta_has_card_cycles(client, monkeypatch):
    from app import pluggy

    for var in ("PLUGGY_CLIENT_ID", "PLUGGY_CLIENT_SECRET", "PLUGGY_ITEM_IDS"):
        monkeypatch.delenv(var, raising=False)
    assert client.get("/api/meta").json()["cards"] == {}
    pluggy.mark_synced("2026-10-14T10:00:00", {"Santander cartão": {"closing_day": 9, "due_day": 17}})
    pluggy.mark_synced("2026-10-15T10:00:00", {"Inter cartão": {"closing_day": 11, "due_day": 18}})
    assert client.get("/api/meta").json()["cards"] == {
        "Santander cartão": {"closing_day": 9, "due_day": 17}, "Inter cartão": {"closing_day": 11, "due_day": 18}}
