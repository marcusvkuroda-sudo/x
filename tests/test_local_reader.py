import io
import sys
import time
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import categorizer, documents, local_reader  # noqa: E402
from app.extractor import ExtractionError  # noqa: E402

reportlab = pytest.importorskip("reportlab")
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402


def make_pdf(pages: list[list[tuple[float, str]]], password: str | None = None) -> bytes:
    """Each line is (x, text); lines go top to bottom. Columns come from separate drawString calls."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, encrypt=password)
    for lines in pages:
        y = 800
        for row in lines:
            for x, text in row if isinstance(row, list) else [row]:
                c.drawString(x, y, text)
            y -= 18
        c.showPage()
    c.save()
    return buf.getvalue()


# Nubank-like: "02 SET  •••• 1234  Uber* Trip  R$ 23,40", due date written out.
NUBANK = [
    [
        (40, "Nubank - Fatura do cartão"),
        (40, "Data de vencimento: 15 OUT 2026"),
        (40, "Total da fatura R$ 1.274,47"),
        (40, "Pagamento recebido 05 SET  -R$ 980,00"),
        [(40, "02 SET"), (100, "•••• 1234"), (180, "Uber* Trip"), (460, "R$ 23,40")],
        [(40, "03 SET"), (100, "•••• 1234"), (180, "Ifd*Pizzaria Bella"), (460, "R$ 89,90")],
        [(40, "05 SET"), (100, "•••• 9876"), (180, "Pao de Acucar 1234"), (460, "R$ 412,37")],
        [(40, "12 JUN"), (100, "•••• 1234"), (180, "Samsung - Parcela 4/10"), (460, "R$ 299,90")],
        [(40, "20 SET"), (100, "•••• 1234"), (180, "Estorno Amazon"), (460, "-R$ 59,90")],
        [(40, "28 DEZ"), (100, "•••• 1234"), (180, "Airbnb"), (460, "R$ 452,90")],
    ],
    [
        [(40, "21 SET"), (100, "•••• 1234"), (180, "IOF de compra internacional"), (460, "R$ 0,00")],
        [(40, "22 SET"), (100, "•••• 1234"), (180, "Netflix.com"), (460, "R$ 55,90")],
        (40, "Próximas faturas"),
        [(40, "12 NOV"), (180, "Samsung - Parcela 5/10"), (460, "R$ 299,90")],
    ],
]

# Itaú-like: "12/09 UBER *TRIP 23,40", international line with two amounts.
ITAU = [
    [
        (40, "Itau Personnalite Visa"),
        (40, "Vencimento 10/01/2027"),
        (40, "Total desta fatura 1.051,40"),
        [(40, "12/12"), (100, "UBER *TRIP"), (480, "23,40")],
        [(40, "15/12"), (100, "DROGASIL 0451"), (480, "76,50")],
        [(40, "20/12"), (100, "AMAZON US$ 12,99"), (480, "65,10")],
        [(40, "28/06"), (100, "MAGALU 07/10"), (480, "389,90")],
        [(40, "02/01"), (100, "POSTO SHELL"), (480, "200,00")],
        [(40, "03/01"), (100, "SMART FIT"), (480, "129,90")],
        [(40, "05/01"), (100, "PAGAMENTO EFETUADO"), (480, "500,00 -")],
        [(40, "06/01"), (100, "CASAS BAHIA 02/12"), (480, "166,60")],
    ],
]


def read_pdf(pages, password=""):
    data = make_pdf(pages, password=password or None)
    return local_reader.read([documents.Upload("fatura.pdf", "application/pdf", data)], password)


def test_nubank_like_statement():
    r = read_pdf(NUBANK)
    assert r["issuer"] == "Nubank"
    assert r["due_date"] == "2026-10-15"
    txs = {t["merchant"]: t for t in r["transactions"]}
    assert set(txs) == {"Uber", "iFood - Pizzaria Bella", "Pao de Acucar", "Samsung", "Estorno Amazon", "Airbnb", "Netflix"}
    assert txs["Uber"] == {**txs["Uber"], "date": "2026-09-02", "amount_cents": 2340, "category": "transporte"}
    assert txs["iFood - Pizzaria Bella"]["category"] == "restaurantes"
    assert txs["Pao de Acucar"]["notes"] == "cartão 9876"
    assert txs["Samsung"]["installment"] == "4/10"
    assert txs["Samsung"]["date"] == "2026-10-05"  # counted when charged (due date - 10 days)
    assert "data da compra: 2026-06-12" in txs["Samsung"]["notes"]
    assert txs["Estorno Amazon"]["amount_cents"] == -5990
    assert txs["Airbnb"]["date"] == "2025-12-28"  # December on an October statement: last year
    # Payment, zero IOF and the future installment are not spending, so the sum matches the printed total.
    assert sum(t["amount_cents"] for t in r["transactions"]) == r["statement_total_cents"] == 127447


def test_itau_like_statement_matches_printed_total():
    r = read_pdf(ITAU)
    assert r["issuer"] == "Itaú"
    assert r["due_date"] == "2027-01-10"
    by = {t["description"]: t for t in r["transactions"]}
    assert "PAGAMENTO EFETUADO" not in by
    assert by["UBER *TRIP"]["date"] == "2026-12-12"
    assert by["AMAZON US$ 12,99"]["amount_cents"] == 6510
    assert by["MAGALU 07/10"]["installment"] == "7/10"
    assert by["POSTO SHELL"]["date"] == "2027-01-02"
    assert sum(t["amount_cents"] for t in r["transactions"]) == r["statement_total_cents"] == 105140


def test_password_protected_pdf():
    locked = make_pdf(ITAU, password="123")
    with pytest.raises(documents.DocumentError, match="senha"):
        local_reader.read([documents.Upload("f.pdf", "application/pdf", locked)], "")
    r = read_pdf(ITAU, password="123")
    assert len(r["transactions"]) == 7


def test_pdf_without_transactions_explains_what_to_do():
    with pytest.raises(ExtractionError, match="CSV/OFX"):
        read_pdf([[(40, "Contrato de prestação de serviços"), (40, "Cláusula 1")]])


def test_photos_need_the_paid_reader():
    with pytest.raises(ExtractionError, match="claude.ai"):
        local_reader.read([documents.Upload("foto.jpg", "image/jpeg", b"\xff\xd8\xff")])


def test_nubank_card_csv():
    csv = b"date,title,amount\n2026-09-02,Uber *Trip,23.40\n2026-09-05,Pagamento recebido,-980.00\n2026-09-10,Estorno Amazon,-59.90\n2026-09-12,Netflix.com,55.90\n"
    r = local_reader.read([documents.Upload("Nubank_2026-10-15.csv", "text/csv", csv)])
    assert [(t["merchant"], t["amount_cents"], t["category"]) for t in r["transactions"]] == [
        ("Uber", 2340, "transporte"), ("Estorno Amazon", -5990, "compras"), ("Netflix", 5590, "assinaturas")]
    assert r["issuer"] == "Nubank"


def test_bank_account_csv_with_semicolons_and_negative_spending():
    csv = "Data;Descrição;Valor\n02/09/2026;Pix recebido - Salário;5.000,00\n03/09/2026;Compra no débito - Padaria Real;-18,50\n04/09/2026;Conta de luz ENEL;-210,33\n".encode("cp1252")
    r = local_reader.read([documents.Upload("extrato.csv", "text/csv", csv)])
    assert [(t["date"], t["amount_cents"], t["category"]) for t in r["transactions"]] == [
        ("2026-09-03", 1850, "mercado"), ("2026-09-04", 21033, "casa")]
    assert any("entrada" in w for w in r["warnings"])


def test_ofx():
    ofx = b"""OFXHEADER:100
<OFX><CREDITCARDMSGSRSV1><CCSTMTTRNRS><CCSTMTRS><BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260902120000[-3:BRT]<TRNAMT>-23.40<MEMO>UBER *TRIP</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260905<TRNAMT>-412.37<MEMO>PAO DE ACUCAR</STMTTRN>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260910<TRNAMT>980.00<MEMO>PAGAMENTO RECEBIDO</STMTTRN>
</BANKTRANLIST></CCSTMTRS></CCSTMTTRNRS></CREDITCARDMSGSRSV1></OFX>"""
    r = local_reader.read([documents.Upload("fatura.ofx", "", ofx)])
    assert [(t["date"], t["amount_cents"], t["category"]) for t in r["transactions"]] == [
        ("2026-09-02", 2340, "transporte"), ("2026-09-05", 41237, "mercado")]


def test_unknown_csv_columns():
    with pytest.raises(ExtractionError, match="colunas"):
        local_reader.read([documents.Upload("x.csv", "text/csv", b"a,b\n1,2\n")])


@pytest.mark.parametrize("text, category", [
    ("MERCADOLIVRE*LOJA", "compras"), ("PAO DE ACUCAR", "mercado"), ("AMAZON PRIME", "assinaturas"),
    ("99 APP *99POP", "transporte"), ("DIARIA HOTEL", "lazer"), ("ALGO DESCONHECIDO", "outros"),
])
def test_categories(text, category):
    assert categorizer.guess_category(text) == category


def test_free_reader_through_the_api(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "EXTRACTION_MODE", "local")
    r = client.post("/api/imports", files={"files": ("fatura.pdf", make_pdf(ITAU), "application/pdf")})
    assert r.status_code == 202
    for _ in range(100):
        imp = client.get(f"/api/imports/{r.json()['id']}").json()
        if imp["status"] != "processing":
            break
        time.sleep(0.05)
    assert imp["status"] == "review", imp.get("error")
    assert len(imp["transactions"]) == 7 and imp["model"] == "local" and imp["cost_usd"] is None
    assert client.get("/api/meta").json()["reader"] == "local"
