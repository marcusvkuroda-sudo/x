import base64
import io
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from PIL import Image
from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import documents, extractor  # noqa: E402


class FakeStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def fake_client(monkeypatch, response):
    calls = []

    def stream(**kwargs):
        calls.append(kwargs)
        return FakeStream(response)

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))
    monkeypatch.setattr(extractor.anthropic, "Anthropic", lambda **_: client)
    return calls


def message(data, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=json.dumps(data))],
        model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
    )


STATEMENT = {
    "document_type": "fatura_cartao",
    "issuer": "Nubank",
    "reference_month": "2026-09-20",
    "due_date": "2026-09-31",
    "statement_total": 123.45,
    "transactions": [
        {"date": "2026-09-02", "description": "UBER *TRIP", "merchant": "Uber", "amount": 23.4,
         "category": "transporte", "installment": None, "notes": ""},
        {"date": "2026-09-05", "description": "SAMSUNG PARC 03 DE 10", "merchant": "Samsung", "amount": 299.9,
         "category": "compras", "installment": "PARC 03 DE 10", "notes": ""},
        {"date": "2026-02-30", "description": "LOJA", "merchant": "", "amount": 10,
         "category": "inexistente", "installment": "7/5", "notes": ""},
        {"date": "2026-09-09", "description": "PAGAMENTO", "merchant": "", "amount": 0,
         "category": "outros", "installment": None, "notes": ""},
    ],
    "warnings": [],
}


def test_extract_sanitizes_model_output(monkeypatch):
    calls = fake_client(monkeypatch, message(STATEMENT))
    result = extractor.extract([{"type": "text", "text": "x"}], ["fatura.pdf"])

    request = calls[0]
    assert request["fallbacks"] == "default"
    assert request["output_config"]["format"]["type"] == "json_schema"

    uber, samsung, loja = result["transactions"]  # the zero-value line is dropped
    assert uber == {"date": "2026-09-02", "description": "UBER *TRIP", "merchant": "Uber", "amount_cents": 2340,
                    "category": "transporte", "installment": None, "notes": ""}
    assert samsung["installment"] == "3/10"
    assert loja["date"] == "" and loja["category"] == "outros" and loja["installment"] is None
    assert "7/5" in loja["notes"]
    assert any("sem data" in w for w in result["warnings"])
    assert result["reference_month"] == "2026-09"
    assert result["due_date"] is None  # 31/09 does not exist
    assert result["statement_total_cents"] == 12345


def _status_error(cls, status, msg):
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    return cls(msg, response=response, body=None)


@pytest.mark.parametrize(
    "error, expected",
    [
        (_status_error(anthropic.BadRequestError, 400, "Your credit balance is too low to access the API"), "créditos"),
        (_status_error(anthropic.AuthenticationError, 401, "invalid x-api-key"), "Chave da API"),
        (_status_error(anthropic.NotFoundError, 404, "model not found"), "EXTRACTION_MODEL"),
        (_status_error(anthropic.RateLimitError, 429, "rate limited"), "Limite de uso"),
        (_status_error(anthropic.OverloadedError, 529, "overloaded"), "sobrecarregada"),
        (anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com")), "internet"),
        (TypeError("Could not resolve authentication method. Expected one of api_key"), "não configurada"),
    ],
)
def test_api_errors_become_friendly_messages(monkeypatch, error, expected):
    fake_client(monkeypatch, error)
    with pytest.raises(extractor.ExtractionError, match=expected):
        extractor.extract([], ["fatura.pdf"])


def test_refusal_and_truncation(monkeypatch):
    fake_client(monkeypatch, message(STATEMENT, stop_reason="refusal"))
    with pytest.raises(extractor.ExtractionError):
        extractor.extract([], ["x.pdf"])
    fake_client(monkeypatch, message(STATEMENT, stop_reason="max_tokens"))
    with pytest.raises(extractor.ExtractionError, match="menos páginas"):
        extractor.extract([], ["x.pdf"])


def _photo(width, height):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 180, 160)).save(buf, format="JPEG")
    return documents.Upload("foto.jpg", "image/jpeg", buf.getvalue())


def _decoded_size(block):
    return Image.open(io.BytesIO(base64.b64decode(block["source"]["data"]))).size


def test_photos_are_sized_to_what_the_model_sees():
    (block,) = documents.to_content_blocks([_photo(4032, 3024)])
    w, h = _decoded_size(block)
    assert max(w, h) <= 2576
    assert math.ceil(w / 28) * math.ceil(h / 28) <= 4784
    assert w * h > 3_500_000  # not shrunk more than needed

    # Small images are left alone.
    (block,) = documents.to_content_blocks([_photo(800, 600)])
    assert _decoded_size(block) == (800, 600)


def test_many_photos_use_the_stricter_limit_and_get_labels():
    blocks = documents.to_content_blocks([_photo(3000, 2000) for _ in range(21)])
    images = [b for b in blocks if b["type"] == "image"]
    labels = [b["text"] for b in blocks if b["type"] == "text"]
    assert len(images) == 21 and labels[0] == "Arquivo 1 de 21 (foto.jpg):"
    assert all(max(_decoded_size(b)) <= 2000 for b in images)


def test_too_many_pages_is_refused():
    w = PdfWriter()
    for _ in range(documents.MAX_PAGES + 1):
        w.add_blank_page(100, 100)
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(documents.DocumentError, match="páginas"):
        documents.to_content_blocks([documents.Upload("grande.pdf", "application/pdf", buf.getvalue())])


def test_unreadable_files():
    with pytest.raises(documents.DocumentError, match="Formato não suportado"):
        documents.to_content_blocks([documents.Upload("planilha.xlsx", "", b"PK\x03\x04 not an image")])
    with pytest.raises(documents.DocumentError, match="corrompido"):
        documents.to_content_blocks([documents.Upload("fatura.pdf", "application/pdf", b"%PDF-1.4 broken")])
