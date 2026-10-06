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
    # Bill still open (no billId): before and after its closing date (2026-09-28).
    {"id": "c7", "date": "2026-09-20T10:00:00.000Z", "description": "DROGASIL", "amount": 30.0, "type": "DEBIT",
     "status": "POSTED"},
    {"id": "c8", "date": "2026-09-29T10:00:00.000Z", "description": "NETFLIX", "amount": 55.9, "type": "DEBIT",
     "status": "POSTED"},
]
ACCOUNT_TXS = [
    {"id": "a1", "date": "2026-09-01", "description": "Pix enviado - Padaria", "amount": -15.5, "type": "DEBIT"},
    {"id": "a2", "date": "2026-09-01", "description": "Salário", "amount": 5000.0, "type": "CREDIT"},
    {"id": "a3", "date": "2026-09-02", "description": "Aplicação CDB", "amount": -1000.0, "type": "DEBIT"},
    {"id": "a4", "date": "2026-09-10", "description": "Pagamento fatura cartão", "amount": -1500.0, "type": "DEBIT"},
    # The Santander card bill paid from Inter by boleto (the card shows "PAGAMENTO DE FATURA" c4).
    {"id": "a5", "date": "2026-09-04", "description": "Pagamento de boleto - BANCO SANTANDER", "amount": -1500.0,
     "type": "DEBIT"},
    # Pix to our own Santander account (s1 below), and a bare Pix with the receiver apart.
    {"id": "a6", "date": "2026-09-11", "description": "Pix enviado", "amount": -500.0, "type": "DEBIT",
     "paymentData": {"receiver": {"name": "Fulano de Tal"}}},
    {"id": "a7", "date": "2026-09-12", "description": "Pix enviado", "amount": -42.0, "type": "DEBIT",
     "paymentData": {"receiver": {"name": "Feira do Bairro"}}},
]
SANTANDER_ACCOUNT_TXS = [
    {"id": "s1", "date": "2026-09-12", "description": "Pix recebido", "amount": 500.0, "type": "CREDIT"},
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
            card = {"id": "card", "type": "CREDIT",
                    "creditData": {"balanceCloseDate": "2026-09-28T00:00:00.000Z", "balanceDueDate": "2026-11-08"}}
            return httpx.Response(200, json={"results": [card, {"id": "sacc", "type": "BANK"}], "totalPages": 1})
        if path == "/bills":
            # Not paged, on purpose.
            return httpx.Response(200, json=[{"id": "b9", "dueDate": "2026-09-20"}, {"id": "b10", "dueDate": "2026-10-20"}])
        if path == "/transactions":
            txs = {"card": CARD_TXS, "acc": ACCOUNT_TXS, "sacc": SANTANDER_ACCOUNT_TXS}[q["accountId"]]
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
    from datetime import date

    with pluggy.Client("id", "segredo") as client:
        result = pluggy.fetch(client, ["inter", "santander"], date(2026, 8, 1), known_ids={"pluggy:c6", "pluggy:c1"})
    by_id = {t["external_id"]: t for t in result["transactions"]}
    assert set(by_id) == {"pluggy:a1", "pluggy:a5", "pluggy:a6", "pluggy:a7", "pluggy:c2", "pluggy:c3",
                          "pluggy:c7", "pluggy:c8"}
    assert by_id["pluggy:a1"]["amount_cents"] == 1550 and by_id["pluggy:a1"]["source"] == "Banco Inter conta"
    assert by_id["pluggy:a1"]["merchant"] == "Padaria"
    assert by_id["pluggy:c2"]["installment"] == "2/10" and by_id["pluggy:c2"]["bill_month"] == "2026-10"
    assert by_id["pluggy:c3"]["amount_cents"] == -3990 and by_id["pluggy:c2"]["date"] == "2026-09-03"
    assert result["issuer"] == "Banco Inter + Santander"
    assert any("Santander" in w and "renovada" in w for w in result["warnings"])
    # Open bill: statement month from the card's closing and due dates.
    assert by_id["pluggy:c7"]["bill_month"] == "2026-11" and by_id["pluggy:c8"]["bill_month"] == "2026-12"
    # Imported before its bill closed: its statement month is now known.
    assert result["bill_updates"] == {"pluggy:c1": "2026-09"}
    # Money between our own accounts comes unchecked; real spending doesn't.
    assert by_id["pluggy:a5"]["suggest_skip"] == "parece o pagamento da fatura do Santander cartão"
    assert "Santander conta" in by_id["pluggy:a6"]["suggest_skip"]  # Pix to our own account
    assert by_id["pluggy:a7"]["suggest_skip"] is None and by_id["pluggy:a1"]["suggest_skip"] is None
    assert by_id["pluggy:a7"]["description"] == "Pix enviado - Feira do Bairro"
    assert by_id["pluggy:a7"]["merchant"] == "Feira do Bairro"


def test_pluggy_category_used_when_keywords_unknown(calls):
    from datetime import date

    with pluggy.Client("id", "segredo") as client:
        result = pluggy.fetch(client, ["santander"], date(2026, 8, 1), set())
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
    assert len(rows) == 10

    # A second sync while the first waits for review brings nothing twice.
    second = wait(client, client.post("/api/bank/sync").json()["id"])
    assert second["transactions"] == []

    # Import everything but the transfers between our accounts (as the review screen suggests).
    payload = [{**{k: t[k] for k in ("date", "description", "merchant", "amount_cents", "category", "installment",
                                      "notes", "source", "external_id", "bill_month")}, "remember": False}
               for t in rows if not t["suggest_skip"]]
    r = client.post(f"/api/imports/{import_id}/confirm", json={"source": "", "transactions": payload})
    assert r.json()["imported"] == 8
    txs = {t["external_id"]: t for t in client.get("/api/transactions").json()}
    assert txs["pluggy:c2"]["bill_month"] == "2026-10"
    assert txs["pluggy:a1"]["bill_month"] == "2026-09"  # bank account: month of the date
    assert txs["pluggy:a1"]["source"] == "Banco Inter conta"

    # Next sync: everything is known already, including what was left unchecked.
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


def test_env_credentials_stay_in_env(client, calls, monkeypatch):
    monkeypatch.setenv("PLUGGY_CLIENT_ID", "id-do-env")
    monkeypatch.setenv("PLUGGY_CLIENT_SECRET", "segredo")
    monkeypatch.setenv("PLUGGY_ITEM_IDS", "inter")
    assert client.get("/api/bank").json()["configured"]
    wait(client, client.post("/api/bank/sync").json()["id"])
    saved = json.loads(pluggy.settings_path().read_text("utf-8"))
    assert saved["last_sync"] and not saved["client_secret"] and not saved["client_id"]
    # A new secret in .env is used right away.
    monkeypatch.setenv("PLUGGY_CLIENT_SECRET", "outro")
    assert pluggy.load_settings()["client_secret"] == "outro"


def test_known_entry_gets_its_statement_month(client, calls):
    client.post("/api/bank/config", json={"client_id": "id", "client_secret": "segredo", "item_ids": "santander"})
    # c1 imported earlier, while its bill was open (no statement month yet).
    client.post("/api/transactions", json={"date": "2026-09-02", "description": "99FOOD *PIZZARIA", "amount_cents": 5490,
                                            "category": "restaurantes", "external_id": "pluggy:c1"})
    wait(client, client.post("/api/bank/sync").json()["id"])
    tx = next(t for t in client.get("/api/transactions").json() if t["external_id"] == "pluggy:c1")
    assert tx["bill_month"] == "2026-09"
