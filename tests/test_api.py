import io
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "gastos.db")
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "APP_PASSWORD", "")

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def fake_extract(blocks, filenames):
    assert blocks and blocks[0]["type"] in ("document", "image")
    return {
        "document_type": "fatura_cartao",
        "issuer": "Nubank",
        "reference_month": "2026-09",
        "due_date": "2026-09-15",
        "statement_total_cents": 15990,
        "transactions": [
            {"date": "2026-08-20", "description": "IFD*PIZZARIA", "merchant": "iFood - Pizzaria", "amount_cents": 8990,
             "category": "restaurantes", "installment": None, "notes": ""},
            {"date": "2026-08-25", "description": "MAGALU PARC 02/10", "merchant": "Magazine Luiza", "amount_cents": 7000,
             "category": "casa", "installment": "2/10", "notes": "data da compra: 2026-07-25"},
        ],
        "warnings": [],
        "model": "claude-opus-5-5",
        "input_tokens": 1000,
        "output_tokens": 500,
    }


def wait_for(client, import_id, status="review"):
    for _ in range(50):
        imp = client.get(f"/api/imports/{import_id}").json()
        if imp["status"] != "processing":
            return imp
        time.sleep(0.05)
    raise AssertionError("import stuck in processing")


def test_manual_crud(client):
    r = client.post("/api/transactions", json={"date": "2026-09-10", "description": "Feira", "amount_cents": 4590, "category": "mercado"})
    assert r.status_code == 201
    tx = r.json()
    assert tx["origin"] == "manual"

    r = client.put(f"/api/transactions/{tx['id']}", json={**tx, "amount_cents": 5000, "installment": "01/03"})
    assert r.json()["amount_cents"] == 5000
    assert r.json()["installment"] == "1/3"

    assert len(client.get("/api/transactions").json()) == 1
    csv = client.get("/api/export.csv").text
    assert "Feira" in csv and "50,00" in csv

    assert client.delete(f"/api/transactions/{tx['id']}").status_code == 204
    assert client.get("/api/transactions").json() == []


def test_validation(client):
    r = client.post("/api/transactions", json={"date": "2026-09-10", "description": "x", "amount_cents": 0, "category": "mercado"})
    assert r.status_code == 422
    r = client.post("/api/transactions", json={"date": "2026-09-10", "description": "x", "amount_cents": 10, "category": "nope"})
    assert r.status_code == 422


def test_import_flow(client, monkeypatch):
    from app import extractor

    monkeypatch.setattr(extractor, "extract", fake_extract)
    # A real (blank) PDF so pypdf can open it.
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(100, 100)
    buf = io.BytesIO()
    w.write(buf)
    pdf = buf.getvalue()

    r = client.post("/api/imports", files={"files": ("fatura.pdf", pdf, "application/pdf")}, data={"source": "Nubank"})
    assert r.status_code == 202, r.text
    imp = wait_for(client, r.json()["id"])
    assert imp["status"] == "review"
    assert len(imp["transactions"]) == 2
    assert imp["cost_usd"] == pytest.approx(0.014)

    # Same file again is refused.
    r2 = client.post("/api/imports", files={"files": ("fatura.pdf", pdf, "application/pdf")})
    assert r2.status_code == 409

    txs = [{k: t[k] for k in ("date", "description", "merchant", "amount_cents", "category", "installment", "notes")} for t in imp["transactions"]]
    r = client.post(f"/api/imports/{imp['id']}/confirm", json={"source": "Nubank", "transactions": txs})
    assert r.json() == {"imported": 2}
    stored = client.get("/api/transactions").json()
    assert {t["source"] for t in stored} == {"Nubank"}
    assert "Nubank" in client.get("/api/meta").json()["sources"]

    # Deleting the import removes its transactions.
    assert client.delete(f"/api/imports/{imp['id']}").status_code == 204
    assert client.get("/api/transactions").json() == []


def test_duplicate_flag(client, monkeypatch):
    from app import extractor

    monkeypatch.setattr(extractor, "extract", fake_extract)
    client.post("/api/transactions", json={"date": "2026-08-20", "description": "Pizza", "amount_cents": 8990, "category": "restaurantes"})
    r = client.post("/api/imports", files={"files": ("foto.png", _png(), "image/png")})
    imp = wait_for(client, r.json()["id"])
    flags = [t["possible_duplicate"] for t in imp["transactions"]]
    assert flags == ["Pizza", None]


def test_encrypted_pdf_needs_password(client, monkeypatch):
    from pypdf import PdfWriter

    from app import extractor

    monkeypatch.setattr(extractor, "extract", fake_extract)
    w = PdfWriter()
    w.add_blank_page(100, 100)
    w.encrypt("12345")
    buf = io.BytesIO()
    w.write(buf)

    r = client.post("/api/imports", files={"files": ("fatura.pdf", buf.getvalue(), "application/pdf")})
    imp = wait_for(client, r.json()["id"])
    assert imp["status"] == "error"
    assert "senha" in imp["error"].lower()

    # Retrying the same file with the right password works (errored imports don't block re-upload).
    r = client.post("/api/imports", files={"files": ("fatura.pdf", buf.getvalue(), "application/pdf")}, data={"password": "12345"})
    assert r.status_code == 202
    assert wait_for(client, r.json()["id"])["status"] == "review"


def _png():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_password_guard(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "APP_PASSWORD", "segredo")
    assert client.get("/api/meta").status_code == 401
    assert client.get("/api/meta", auth=("nos", "segredo")).status_code == 200
