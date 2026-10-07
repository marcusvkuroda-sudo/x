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


# ---------------------------------------------------------------- Santander-like statement

# (date, description, installment, R$ value, US$ value) — what the statement really charges.
SANTANDER_CHARGES = [
    ("02/09", "PAO DE ACUCAR 1234", "", "412,37", ""),
    ("03/09", "DROGASIL 0451", "", "76,50", ""),
    ("12/09", "UBER *TRIP", "", "23,40", ""),
    ("15/09", "IFD*PIZZARIA BELLA", "", "89,90", ""),
    ("14/06", "MERCADOLIVRE*LOJA", "04/10", "120,00", ""),
    ("18/09", "AMAZON MARKETPLACE", "", "65,10", "12,99"),
    ("18/09", "IOF DESPESA NO EXTERIOR", "", "2,28", ""),
    ("20/09", "POSTO SHELL", "", "200,00", ""),
    ("21/09", "NETFLIX.COM", "", "55,90", ""),
    ("08/07", "ANUIDADE DIFERENCIADA", "03/12", "39,90", ""),
    ("25/09", "ESTORNO DE COMPRA", "", "-25,00", ""),
    ("26/09", "SMART FIT", "", "129,90", ""),
    ("27/09", "OUTBACK STEAKHOUSE", "", "248,70", ""),
    ("28/09", "SEM PARAR", "", "47,35", ""),
]


def santander_pdf(password: str | None = "12345") -> tuple[bytes, int]:
    """Two columns of transactions per page, with Parcela, R$ and US$ columns. Returns (pdf, total cents)."""
    total = sum(int(v.replace(".", "").replace(",", "")) for *_, v, _ in SANTANDER_CHARGES)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, encrypt=None)
    if password:
        from reportlab.lib.pdfencrypt import StandardEncryption

        c = canvas.Canvas(buf, pagesize=A4, encrypt=StandardEncryption(password, ownerPassword="banco", strength=128))
    c.setFont("Helvetica", 7)
    brl = f"{total / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    y = 810
    for text in ("Santander", "Fatura do Cartão SANTANDER SX VISA", f"Vencimento 10/10/2026     Total a Pagar R$ {brl}",
                 "Saldo anterior 1.500,00", "Detalhamento da Fatura", "FULANO DE TAL - 1111 XXXX XXXX 1111"):
        c.drawString(40, y, text)
        y -= 12
    columns = (40, 310)

    def row(x, cells):
        for dx, cell in zip((0, 30, 150, 185, 230), cells):
            if cell:
                c.drawString(x + dx, y, cell)

    for x in columns:
        row(x, ("Data", "Descrição", "Parcela", "R$", "US$"))
    y -= 12
    row(columns[0], ("05/09", "PAGAMENTO DE FATURA-INTERNET", "", "-1.500,00", ""))
    lines = SANTANDER_CHARGES[:]
    half = (len(lines) + 1) // 2
    left, right = lines[:half], lines[half:]
    row(columns[1], right[0])
    y -= 12
    for i, item in enumerate(left):
        row(columns[0], item)
        if i + 1 < len(right):
            row(columns[1], right[i + 1])
        y -= 12
    c.drawString(40, y, "Compras parceladas - próximas faturas")
    y -= 12
    row(columns[0], ("14/06", "MERCADOLIVRE*LOJA", "05/10", "120,00", ""))
    c.showPage()
    c.save()
    return buf.getvalue(), total


def test_santander_like_two_columns_with_password():
    data, total = santander_pdf("12345")
    with pytest.raises(documents.DocumentError, match="senha"):
        local_reader.read([documents.Upload("fatura.pdf", "application/pdf", data)], "")
    r = local_reader.read([documents.Upload("fatura.pdf", "application/pdf", data)], " 12345 ")
    assert r["issuer"] == "Santander" and r["due_date"] == "2026-10-10"
    got = sorted((t["description"], t["amount_cents"]) for t in r["transactions"])
    want = sorted((d if not p else f"{d} {p}", int(v.replace(",", "").replace(".", ""))) for _, d, p, v, _ in SANTANDER_CHARGES)
    assert got == want  # each column read separately, R$ value (not US$), payment and future installment left out
    assert sum(t["amount_cents"] for t in r["transactions"]) == r["statement_total_cents"] == total
    by = {t["description"]: t for t in r["transactions"]}
    assert by["MERCADOLIVRE*LOJA 04/10"]["installment"] == "4/10"
    assert by["MERCADOLIVRE*LOJA 04/10"]["date"] == "2026-09-30"
    assert by["ESTORNO DE COMPRA"]["amount_cents"] == -2500
    assert by["AMAZON MARKETPLACE"]["amount_cents"] == 6510


@pytest.mark.parametrize("typed", ["12345", " 12345 ", "123.45", "senha-errada-mas-pdf-abre-sem-senha"])
def test_password_slips_are_forgiven(typed):
    from pypdf import PdfReader, PdfWriter

    plain, _ = santander_pdf(None)
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(plain)))
    # The last case: a PDF that only restricts printing (no password to open it).
    user = "" if typed.startswith("senha") else "12345"
    w.encrypt(user_password=user, owner_password="banco", algorithm="AES-256")
    out = io.BytesIO()
    w.write(out)
    r = local_reader.read([documents.Upload("f.pdf", "application/pdf", out.getvalue())], typed)
    assert len(r["transactions"]) == len(SANTANDER_CHARGES)


def test_minus_inside_description_is_not_a_refund():
    (rec,) = local_reader._records("12 JUN Samsung - Parcela 4/10 R$ 299,90")
    assert rec["amounts"] == [29990] and rec["installment"] == "4/10"


def test_statement_month_comes_with_each_transaction(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "EXTRACTION_MODE", "local")
    data, total = santander_pdf("12345")
    r = client.post("/api/imports", files={"files": ("fatura.pdf", data, "application/pdf")}, data={"password": "12345"})
    for _ in range(100):
        imp = client.get(f"/api/imports/{r.json()['id']}").json()
        if imp["status"] != "processing":
            break
        time.sleep(0.05)
    payload = [{k: t[k] for k in ("date", "description", "merchant", "amount_cents", "category", "installment", "notes")} for t in imp["transactions"]]
    client.post(f"/api/imports/{imp['id']}/confirm", json={"source": "Santander", "transactions": payload})
    client.post("/api/transactions", json={"date": "2026-09-15", "description": "Feira", "amount_cents": 3000, "category": "mercado"})
    txs = client.get("/api/transactions").json()
    assert {t["bill_month"] for t in txs if t["origin"] == "import"} == {"2026-10"}
    assert next(t["bill_month"] for t in txs if t["origin"] == "manual") == "2026-09"
    assert sum(t["amount_cents"] for t in txs if t["bill_month"] == "2026-10") == total


# Text exactly as pypdf extracts a real Santander statement (layout mode), with made-up
# merchants and values: headers above their values, the previous bill paid by automatic
# debit, a marker column glued to amounts ("-0,023", "0,00314/08...") and two columns mixed.
SANTANDER_REAL_LAYOUT = [
    """                                                                                1/4
      Olá, Fulano! Esta é a fatura do seu cartão SANTANDER                      FULANO DE TAL - 1111 XXXX XXXX 1111
      ELITE MASTERCARD contendo compras e pagamentos
      realizados até 10/09.                                        Total a Pagar          Vencimento            Seu limite é
                                                                   R$ 2.097,05            17/09/2026            R$30.000,00
      1    Pagamento Total                    R$2.097,05Limite utilizadoLimite Disponível:Melhor dia para
      Histórico de Faturas      Pagamento     Período das compras
      AGO.      R$ 900,00        R$900,00      11/07/26 a 10/08/26
      SET.      R$ 2.097,05      Esta Fatura   11/08/26 a 10/09/26
      OUT.      R$ 310,70        Fatura Aberta 11/09/26 a 09/10/26
""",
    """                                                                                2/4
      Detalhamento da Fatura
      FULANO DE TAL -     1111 XXXX XXXX 1111          20/07      AMAZON BR                 02/02      54,34
        Pagamento e Demais Créditos                  3   24/07      LAB VETERINARIO           02/03      111,68
        Compra    Data     Descrição      Parcela    R$      US$          27/08    MP *MERCADOLIVRE    01/03    30,73
      17/08    DEB    AUTOM    DE FATURA EM C/            -900,00         27/08    AMAZONMKTPLC*LOJA   01/06    40,97
      VALOR TOTAL                                          0,00     0,00
      Despesas
      Compra    Data     Descrição      Parcela    R$      US$
      08/08      TIM*11999999999                     66,99
        Parcelamentos                                         09/08      IFD*PIZZARIA CENTRAL     0,90
      18/12      MERCADOLIVRE*MERCADOL      09/12      46,37      3   09/08    MERCADO EXTRA 1765     33,58
      VALOR TOTAL                                  113,27          0,00314/08RESTURANTE CENTRAL         196,91
        Pagamento e Demais Créditos                  3   15/08      SUPERMERCADO BOM        938,64
        Compra    Data     Descrição      Parcela    R$      US$3   13/08      PADARIA SOL      36,73
      15/06      DL*ALIEXPRESS BR                    -7,29     3    15/08    POSTO SHELL      63,60
      24/07      LAB VETERINARIO                     -0,023    15/08    99FOOD *BURGER CENTRO    31,49
      05/09      99FOOD *ZAMP S A                    -19,70
""",
    """                                                                                3/4
      Despesas
      Compra    Data     Descrição      Parcela    R$      US$
      21/08      99FOOD *PIZZARIA NOVA        10,98       VALOR TOTAL        1.091,51       0,00
      23/08      GOOGLE YOUTUBEPREMIUM        53,90       Resumo da Fatura
      24/08      AMAZONMKTPLC*LOJA            21,99       Saldo Anterior                       900,00
      31/08      AMAZONMKTPLC*LOJA            -21,99      (+) Total Despesas/Débitos no Brasil  2.146,05
      06/09      CONTA VIVO                   110,99      (-) Total de pagamentos              900,00
      08/09      PORTO ALUGUEL                295,26      (-) Total de créditos                49,00
                                                          (=) Saldo Desta Fatura               2.097,05
      Compras parceladas com e sem juros: operações de        472,33
""",
]


def test_real_santander_layout_adds_up_to_the_statement():
    r = local_reader.parse_statement_text(SANTANDER_REAL_LAYOUT, today=date(2026, 10, 5))
    txs = r["transactions"]
    assert r["due_date"] == "2026-09-17" and r["reference_month"] == "2026-09"
    assert r["statement_total_cents"] == 209705
    assert not any("DEB" in t["description"] for t in txs)  # the paid previous bill is not spending
    assert sum(t["amount_cents"] for t in txs if t["amount_cents"] > 0) == 214605  # Despesas no Brasil
    assert sum(t["amount_cents"] for t in txs if t["amount_cents"] < 0) == -4900  # Créditos
    assert sum(t["amount_cents"] for t in txs) == 209705 and r["warnings"] == []
    by = {t["description"]: t for t in txs}
    assert by["RESTURANTE CENTRAL"]["amount_cents"] == 19691  # glued to "0,00 3 14/08"
    assert by["RESTURANTE CENTRAL"]["category"] == "restaurantes"
    assert by["LAB VETERINARIO"]["amount_cents"] == -2  # "-0,023" is -0,02 plus a marker
    assert by["99FOOD *BURGER CENTRO"]["category"] == "restaurantes"
    assert by["99FOOD *BURGER CENTRO"]["merchant"] == "99Food - Burger Centro"
    # 9th installment of a December purchase: counted when charged, purchase date kept in the notes.
    assert by["MERCADOLIVRE*MERCADOL 09/12"]["date"] == "2026-09-07"
    assert "data da compra: 2025-12-18" in by["MERCADOLIVRE*MERCADOL 09/12"]["notes"]


def test_mismatch_with_the_statement_total_is_reported():
    pages = [SANTANDER_REAL_LAYOUT[0], SANTANDER_REAL_LAYOUT[1].replace("RESTURANTE CENTRAL         196,91", "")]
    r = local_reader.parse_statement_text(pages, today=date(2026, 10, 5))
    assert any("não bate" in w for w in r["warnings"])


def test_account_extract_keeps_bills_and_each_month():
    data = """data;descricao;valor
05/07/2026;Pix enviado - Padaria;-15,50
10/07/2026;Pagamento de boleto ENEL;-230,00
01/08/2026;Salario;5000,00
12/08/2026;Compra no debito MERCADO;-120,00
10/09/2026;Pagamento fatura cartao;-1500,00
11/09/2026;Aplicacao CDB;-300,00
15/09/2026;Saldo do dia;-30,00
""".encode()
    r = local_reader.parse_csv(data, "extrato.csv")
    assert [t["description"] for t in r["transactions"]] == [
        "Pix enviado - Padaria", "Pagamento de boleto ENEL", "Compra no debito MERCADO"]
    # Three months of an account: each entry counts in its own month, not all in September.
    assert r["reference_month"] is None


def test_card_export_still_skips_the_bill_payment():
    data = "date,title,amount\n2026-09-01,Uber,23.40\n2026-09-05,Pagamento recebido,-500.00\n2026-09-06,Estorno Uber,-23.40\n".encode()
    r = local_reader.parse_csv(data, "nubank.csv")
    assert [(t["description"], t["amount_cents"]) for t in r["transactions"]] == [("Uber", 2340), ("Estorno Uber", -2340)]
    assert r["reference_month"] == "2026-09"


def test_ofx_with_brazilian_amounts():
    ofx = b"""OFXHEADER:100
<OFX><BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260912<TRNAMT>-1.234,56<MEMO>ALUGUEL</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260913<TRNAMT>-12,50<MEMO>PADARIA</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260914<TRNAMT>-7.50<MEMO>CAFE</STMTTRN>
</BANKTRANLIST></OFX>"""
    r = local_reader.parse_ofx(ofx, "x.ofx")
    assert [t["amount_cents"] for t in r["transactions"]] == [123456, 1250, 750]


def test_credit_card_charges_are_not_refunds():
    pages = ["""Vencimento 17/09/2026
12/08 ANUIDADE CARTAO DE CREDITO 10/12 35,00
15/08 JUROS DE CREDITO ROTATIVO 45,10
16/08 ESTORNO ANUIDADE 35,00
17/08 CREDITO LOJA Y 10,00
Total a pagar R$ 35,10
"""]
    r = local_reader.parse_statement_text(pages)
    assert [t["amount_cents"] for t in r["transactions"]] == [3500, 4510, -3500, -1000]
    assert r["warnings"] == []


def test_mismatch_message_keeps_its_punctuation():
    r = local_reader.parse_statement_text(["Vencimento 17/09/2026\n12/08 LOJA 1.035,00\nTotal a pagar R$ 5,00\n"])
    assert "R$ 1.030,00 sobrando. Confira" in r["warnings"][0]
