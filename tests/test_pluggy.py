"""Bank sync against a fake Pluggy API (the real one needs the couple's own credentials)."""

import json
import time

import httpx
import pytest

from app import pluggy

CARD_TXS = [
    {"id": "c1", "date": "2026-09-02T10:00:00.000Z", "description": "99FOOD *PIZZARIA", "amount": 54.9, "type": "DEBIT",
     "status": "POSTED", "creditCardMetadata": {"billId": "b9"}},
    {"id": "c2", "date": "2026-09-03T10:00:00.000Z", "description": "MAGALU", "amount": 120.0, "type": "DEBIT",
     "status": "POSTED", "creditCardMetadata": {"billId": "b10", "installmentNumber": 2, "totalInstallments": 10}},
    {"id": "c3", "date": "2026-09-04T10:00:00.000Z", "description": "Estorno NETFLIX", "amount": 39.9, "type": "CREDIT",
     "status": "POSTED"},
    {"id": "c4", "date": "2026-09-05T10:00:00.000Z", "description": "PAGAMENTO DE FATURA", "amount": 1500.0,
     "type": "CREDIT", "status": "POSTED"},
    {"id": "c5", "date": "2026-09-06T10:00:00.000Z", "description": "UBER *TRIP", "amount": 23.0, "type": "DEBIT",
     "status": "PENDING"},
    {"id": "c6", "date": "2026-09-07T10:00:00.000Z", "description": "ESTAB 4421 SP", "amount": 80.0, "type": "DEBIT",
     "status": "POSTED", "category": "Supermarket"},
]
ACCOUNT_TXS = [
    {"id": "a1", "date": "2026-09-01", "description": "Pix enviado - Padaria", "amount": -15.5, "type": "DEBIT"},
    {"id": "a2", "date": "2026-09-01", "description": "Salário", "amount": 5000.0, "type": "CREDIT"},
    {"id": "a3", "date": "2026-09-02", "description": "Aplicação CDB", "amount": -1000.0, "type": "DEBIT"},
    {"id": "a4", "date": "2026-09-10", "description": "Pagamento fatura cartão", "amount": -1500.0, "type": "DEBIT"},
]


def fake_pluggy(calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path, q = request.url.path, request.url.params
        if path == "/auth":
            body = json.loads(request.content)
            if body["clientSecret"] != "segredo":
                return httpx.Response(401, json={"message": "invalid credentials"})
            return httpx.Response(200, json={"apiKey": "k"})
        assert request.headers["X-API-KEY"] == "k"
        if path == "/items/inter":
            return httpx.Response(200, json={"id": "inter", "status": "UPDATED", "connector": {"name": "Banco Inter"}})
        if path == "/items/santander":
            return httpx.Response(200, json={"id": "santander", "status": "OUTDATED", "connector": {"name": "Santander"}})
        if path.startswith("/items/"):
            return httpx.Response(404, json={"message": "not found"})
        if path == "/accounts":
            if q["itemId"] == "inter":
                return httpx.Response(200, json={"results": [{"id": "acc", "type": "BANK"}], "totalPages": 1})
            return httpx.Response(200, json={"results": [{"id": "card", "type": "CREDIT"}], "totalPages": 1})
        if path == "/bills":
            return httpx.Response(200, json={"results": [{"id": "b9", "dueDate": "2026-09-20"},
                                                         {"id": "b10", "dueDate": "2026-10-20"}], "totalPages": 1})
        if path == "/transactions":
            txs = CARD_TXS if q["accountId"] == "card" else ACCOUNT_TXS
            # two pages, to exercise paging
            page = int(q["page"])
            half = len(txs) // 2
            return httpx.Response(200, json={"results": txs[:half] if page == 1 else txs[half:], "totalPages": 2})
        return httpx.Response(500)

    return httpx.MockTransport(handler)


@pytest.fixture()
def calls(monkeypatch):
    for var in ("PLUGGY_CLIENT_ID", "PLUGGY_CLIENT_SECRET", "PLUGGY_ITEM_IDS"):
        monkeypatch.delenv(var, raising=False)
    log = []
    monkeypatch.setattr(pluggy, "TRANSPORT", fake_pluggy(log))
    return log


def test_fetch_keeps_only_spending(calls):
    client = pluggy.Client("id", "segredo")
    from datetime import date

    result = pluggy.fetch(client, ["inter", "santander"], date(2026, 8, 1), known_ids={"pluggy:c6"})
    by_id = {t["external_id"]: t for t in result["transactions"]}
    assert set(by_id) == {"pluggy:a1", "pluggy:c1", "pluggy:c2", "pluggy:c3"}
    assert by_id["pluggy:a1"]["amount_cents"] == 1550 and by_id["pluggy:a1"]["source"] == "Banco Inter conta"
    assert by_id["pluggy:c1"]["category"] == "restaurantes" and by_id["pluggy:c1"]["bill_month"] == "2026-09"
    assert by_id["pluggy:c2"]["installment"] == "2/10" and by_id["pluggy:c2"]["bill_month"] == "2026-10"
    assert by_id["pluggy:c3"]["amount_cents"] == -3990
    assert by_id["pluggy:c1"]["date"] == "2026-09-02"
    assert result["issuer"] == "Banco Inter + Santander"
    assert any("Santander" in w and "renovada" in w for w in result["warnings"])


def test_pluggy_category_used_when_keywords_unknown(calls):
    from datetime import date

    result = pluggy.fetch(pluggy.Client("id", "segredo"), ["santander"], date(2026, 8, 1), set())
    assert {t["external_id"]: t for t in result["transactions"]}["pluggy:c6"]["category"] == "mercado"


def test_config_rejects_bad_credentials_and_unknown_items(client, calls):
    r = client.post("/api/bank/config", json={"client_id": "id", "client_secret": "errado", "item_ids": "inter"})
    assert r.status_code == 400 and "Client Secret" in r.json()["message"]
    r = client.post("/api/bank/config", json={"client_id": "id", "client_secret": "segredo", "item_ids": "xyz"})
    assert r.status_code == 400 and "xyz" in r.json()["message"]
    assert client.get("/api/bank").json()["configured"] is False


def test_sync_end_to_end(client, calls):
    r = client.post("/api/bank/config",
                    json={"client_id": "meu-client-id-123", "client_secret": "segredo", "item_ids": "inter\nsantander"})
    assert r.status_code == 200, r.text
    assert [i["bank"] for i in r.json()["items"]] == ["Banco Inter", "Santander"]

    status = client.get("/api/bank").json()
    assert status["configured"] and status["has_secret"]
    assert "segredo" not in json.dumps(status) and status["client_id"] != "meu-client-id-123"

    # Saving again with an empty secret keeps the saved one.
    r = client.post("/api/bank/config", json={"client_id": "", "client_secret": "", "item_ids": "inter, santander"})
    assert r.status_code == 200, r.text

    import_id = client.post("/api/bank/sync").json()["id"]
    imp = wait(client, import_id)
    assert imp["status"] == "review", imp
    assert imp["document_type"] == "open_finance"
    rows = imp["transactions"]
    assert len(rows) == 5

    # A second sync while the first waits for review brings nothing twice.
    second = wait(client, client.post("/api/bank/sync").json()["id"])
    assert second["transactions"] == []

    payload = [{**{k: t[k] for k in ("date", "description", "merchant", "amount_cents", "category", "installment",
                                      "notes", "source", "external_id", "bill_month")}, "remember": False} for t in rows]
    r = client.post(f"/api/imports/{import_id}/confirm", json={"source": "", "transactions": payload})
    assert r.json()["imported"] == 5
    txs = {t["external_id"]: t for t in client.get("/api/transactions").json()}
    assert txs["pluggy:c2"]["bill_month"] == "2026-10"
    assert txs["pluggy:a1"]["bill_month"] == "2026-09"  # bank account: month of the date
    assert txs["pluggy:a1"]["source"] == "Banco Inter conta"

    # Next sync: everything is known already.
    third = wait(client, client.post("/api/bank/sync").json()["id"])
    assert third["transactions"] == [] and client.get("/api/bank").json()["last_sync"]


def test_sync_requires_config(client, calls):
    assert client.post("/api/bank/sync").status_code == 400


def wait(client, import_id):
    for _ in range(100):
        imp = client.get(f"/api/imports/{import_id}").json()
        if imp["status"] != "processing":
            return imp
        time.sleep(0.05)
    raise AssertionError("sync stuck")
