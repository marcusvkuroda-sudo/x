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
    # Open bill purchases come PENDING, without a bill.
    {"id": "c5", "date": "2026-10-06T10:00:00.000Z", "description": "UBER *TRIP", "amount": 23.0, "type": "DEBIT",
     "status": "PENDING"},
    {"id": "c6", "date": "2026-09-07T10:00:00.000Z", "description": "ESTAB 4421 SP", "amount": 80.0, "type": "DEBIT",
     "status": "POSTED", "category": "Supermarket"},
    # Bill still open (no billId). The card closes on the 9th and is due on the 17th.
    {"id": "c7", "date": "2026-09-20T10:00:00.000Z", "description": "DROGASIL", "amount": 30.0, "type": "DEBIT",
     "status": "POSTED"},
    {"id": "c8", "date": "2026-10-10T10:00:00.000Z", "description": "NETFLIX", "amount": 55.9, "type": "DEBIT",
     "status": "POSTED"},
    # The merchant's MCC says what it is, even when the name and Pluggy don't.
    {"id": "c9", "date": "2026-09-08T10:00:00.000Z", "description": "ESTAB XPTO 77", "amount": 64.0, "type": "DEBIT",
     "status": "POSTED", "category": "Shopping", "creditCardMetadata": {"payeeMCC": 5812}},
    # An installment dated on the original purchase: the bank's forecast wins over the cycle.
    {"id": "c10", "date": "2026-06-15T10:00:00.000Z", "description": "PADARIA REAL", "amount": 18.0, "type": "DEBIT",
     "status": "POSTED", "creditCardMetadata": {"billForecastDate": "2026-10", "installmentNumber": 4,
                                                "totalInstallments": 6}},
]
ACCOUNT_TXS = [
    {"id": "a1", "date": "2026-09-01", "description": "Pix enviado - Padaria", "amount": -15.5, "type": "DEBIT",
     "operationType": "PIX"},
    {"id": "a2", "date": "2026-09-01", "description": "Salário", "amount": 5000.0, "type": "CREDIT"},
    {"id": "a3", "date": "2026-09-02", "description": "Aplicação CDB", "amount": -1000.0, "type": "DEBIT"},
    {"id": "a4", "date": "2026-09-10", "description": "Pagamento fatura cartão", "amount": -1500.0, "type": "DEBIT"},
    {"id": "a5", "date": "2026-09-04", "description": "Pagamento de boleto - BANCO SANTANDER", "amount": -1500.0,
     "type": "DEBIT"},
    {"id": "a6", "date": "2026-09-05", "description": "Aluguel setembro", "amount": -3200.0, "type": "DEBIT",
     "paymentData": {"paymentMethod": "PIX"}},
    {"id": "a9", "date": "2026-09-06", "description": "PAGAMENTO CONTA LUZ", "amount": -230.0, "type": "DEBIT",
     "operationType": "OUTROS"},
    # Debit card purchases: these come in.
    {"id": "a7", "date": "2026-09-12", "description": "COMPRA CARTAO DEBITO - ESTAPAR", "amount": -25.0,
     "type": "DEBIT", "operationType": "CARTAO"},
    {"id": "a8", "date": "2026-09-13", "description": "COMPRA NO DEBITO PADARIA BELA", "amount": -12.0, "type": "DEBIT"},
    # In the account, PENDING is just an authorization: left out.
    {"id": "a10", "date": "2026-09-14", "description": "COMPRA NO DEBITO POSTO", "amount": -90.0, "type": "DEBIT",
     "status": "PENDING"},
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
            # Connected through Meu Pluggy: the connector doesn't name the bank, the accounts do.
            return httpx.Response(200, json={"id": "santander", "status": "OUTDATED", "connector": {"name": "MeuPluggy"}})
        if path.startswith("/items/"):
            return httpx.Response(404, json={"message": "not found"})
        if path == "/accounts":
            if q["itemId"] == "inter":
                return httpx.Response(200, json={"results": [{"id": "acc", "type": "BANK"}], "totalPages": 1})
            card = {"id": "card", "type": "CREDIT", "name": "SANTANDER SX VISA",
                    # Stale "current balance" dates: the bills' own dates must win.
                    "creditData": {"balanceCloseDate": "2026-09-28T00:00:00.000Z", "balanceDueDate": "2026-11-08"}}
            return httpx.Response(200, json={"results": [card, {"id": "sacc", "type": "BANK"}], "totalPages": 1})
        if path == "/bills":
            # Not paged, on purpose.
            # The open bill (b10) is listed too, before it closes.
            return httpx.Response(200, json=[
                {"id": "b9", "dueDate": "2026-09-17", "billClosingDate": "2026-09-09"},
                {"id": "b10", "dueDate": "2026-10-17T00:00:00.000Z", "billClosingDate": "2026-10-09"},
            ])
        if path == "/transactions":
            return httpx.Response(410, json={"message": "This endpoint is deprecated. Use GET /v2/transactions"})
        if path == "/v2/transactions":
            assert "dateFrom" in q and "page" not in q
            txs = {"card": CARD_TXS, "acc": ACCOUNT_TXS, "sacc": SANTANDER_ACCOUNT_TXS}[q["accountId"]]
            # two pages, to exercise the cursor (a base64 cursor with "+" and "=")
            half = len(txs) // 2
            if q.get("after") == "c2Vn+dW5kYQ==":
                return httpx.Response(200, json={"results": txs[half:], "next": None})
            assert "after" not in q
            nxt = f"?accountId={q['accountId']}&after=c2Vn%2BdW5kYQ%3D%3D"
            return httpx.Response(200, json={"results": txs[:half], "next": nxt})
        return httpx.Response(500)

    return httpx.MockTransport(handler)


@pytest.fixture()
def calls(monkeypatch):
    for var in ("PLUGGY_CLIENT_ID", "PLUGGY_CLIENT_SECRET", "PLUGGY_ITEM_IDS"):
        monkeypatch.delenv(var, raising=False)
    log = []
    monkeypatch.setattr(pluggy, "TRANSPORT", fake_pluggy(log))
    return log


def test_fetch_keeps_card_purchases_only(calls):
    from datetime import date

    with pluggy.Client("id", "segredo") as client:
        result = pluggy.fetch(client, ["inter", "santander"], date(2026, 8, 1), known_ids={"pluggy:c6", "pluggy:c1"})
    by_id = {t["external_id"]: t for t in result["transactions"]}
    # From the accounts only the debit card purchases: no Pix, boleto, rent, bills or income.
    assert set(by_id) == {"pluggy:a7", "pluggy:a8", "pluggy:c2", "pluggy:c3", "pluggy:c5", "pluggy:c7", "pluggy:c8",
                          "pluggy:c9", "pluggy:c10"}
    assert by_id["pluggy:c5"]["bill_month"] == "2026-10"  # pending, bought 06/10 -> due 17/10
    # Open bill total per card, to compare with the bank's app (c5 23,00 + c7 30,00 + c10 18,00).
    assert any("vence em 10/2026 soma R$ 71,00" in w for w in result["warnings"])
    assert any("4 movimenta" in w and "Gastos fixos" in w for w in result["warnings"])
    assert by_id["pluggy:a7"]["amount_cents"] == 2500 and by_id["pluggy:a7"]["source"] == "Banco Inter débito"
    assert by_id["pluggy:a7"]["merchant"] == "Estapar" and by_id["pluggy:a7"]["category"] == "transporte"
    assert by_id["pluggy:a8"]["merchant"] == "Padaria Bela"
    assert by_id["pluggy:c2"]["installment"] == "2/10" and by_id["pluggy:c2"]["bill_month"] == "2026-10"
    assert by_id["pluggy:c3"]["amount_cents"] == -3990 and by_id["pluggy:c2"]["date"] == "2026-09-03"
    assert result["issuer"] == "Banco Inter + Santander"
    assert any("Santander" in w and "renovada" in w for w in result["warnings"])
    # Open bill: statement month from the card's cycle (closes on the 9th, due on the 17th).
    assert by_id["pluggy:c7"]["bill_month"] == "2026-10"  # bought 20/09 -> due 17/10
    assert by_id["pluggy:c8"]["bill_month"] == "2026-11"  # bought 10/10, after the closing -> due 17/11
    assert by_id["pluggy:c10"]["bill_month"] == "2026-10"
    # Already imported: their statement month is (re)computed, which fixes it once the bill closes.
    assert result["bill_updates"] == {"pluggy:c1": "2026-09", "pluggy:c6": "2026-09"}


def test_categories_prefer_mcc_then_pluggy(calls):
    from datetime import date

    with pluggy.Client("id", "segredo") as client:
        result = pluggy.fetch(client, ["santander"], date(2026, 8, 1), set())
    cat = {t["external_id"]: t["category"] for t in result["transactions"]}
    assert cat["pluggy:c9"] == "restaurantes"  # MCC 5812 beats Pluggy's "Shopping"
    assert cat["pluggy:c6"] == "mercado"  # Pluggy's "Supermarket"
    assert cat["pluggy:c1"] == "restaurantes"  # 99Food, whatever the rest says
    assert cat["pluggy:c7"] == "saude"  # our keywords, when nothing else knows


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
    assert len(rows) == 11

    # A second sync while the first waits for review brings nothing twice.
    second = wait(client, client.post("/api/bank/sync").json()["id"])
    assert second["transactions"] == []

    # Import all but one (left unchecked in the review).
    payload = [{**{k: t[k] for k in ("date", "description", "merchant", "amount_cents", "category", "installment",
                                      "notes", "source", "external_id", "bill_month")}, "remember": False}
               for t in rows if t["external_id"] != "pluggy:c8"]
    r = client.post(f"/api/imports/{import_id}/confirm", json={"source": "", "transactions": payload})
    assert r.json()["imported"] == 10
    txs = {t["external_id"]: t for t in client.get("/api/transactions").json()}
    assert txs["pluggy:c2"]["bill_month"] == "2026-10"
    assert txs["pluggy:a7"]["bill_month"] == "2026-09"  # debit: month of the date
    assert txs["pluggy:a7"]["source"] == "Banco Inter débito"

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


def test_statement_month_from_cycle():
    month = pluggy.statement_month
    assert [month(d, 9, 17) for d in ("2026-09-09", "2026-09-10", "2026-10-09", "2026-12-20")] == [
        "2026-09", "2026-10", "2026-10", "2027-01"]
    # Cards that close at the end of the month and are due early the next one.
    assert [month(d, 26, 5) for d in ("2026-10-20", "2026-10-28")] == ["2026-11", "2026-12"]
    assert month("2026-02-27", 30, 7) == "2026-03"  # closing day past the month's end
