"""Reads a credit card statement (or receipt / bill) with Claude and returns
structured transactions."""

import json
from datetime import date

import anthropic

from . import config
from .categories import CATEGORIES, CATEGORY_KEYS


class ExtractionError(Exception):
    pass


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string", "enum": ["fatura_cartao", "cupom_fiscal", "conta", "outro"]},
        "issuer": _nullable({"type": "string"}),
        "reference_month": _nullable({"type": "string", "description": "YYYY-MM"}),
        "due_date": _nullable({"type": "string", "description": "YYYY-MM-DD"}),
        "statement_total": _nullable({"type": "number"}),
        "transactions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "description": {"type": "string"},
                    "merchant": {"type": "string"},
                    "amount": {"type": "number"},
                    "category": {"type": "string", "enum": CATEGORY_KEYS},
                    "installment": _nullable({"type": "string", "description": "k/N"}),
                    "notes": {"type": "string"},
                },
                "required": ["date", "description", "merchant", "amount", "category", "installment", "notes"],
                "additionalProperties": False,
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "document_type",
        "issuer",
        "reference_month",
        "due_date",
        "statement_total",
        "transactions",
        "warnings",
    ],
    "additionalProperties": False,
}

_category_lines = "\n".join(f"- {c['key']}: {c['label']} ({c['hint']})" for c in CATEGORIES)

SYSTEM_PROMPT = f"""Você transforma documentos financeiros brasileiros em dados estruturados para o \
controle de gastos de um casal. Na maioria das vezes o documento é uma fatura de cartão de crédito \
(PDF ou fotos das páginas), mas também pode ser um cupom fiscal ou uma conta de consumo.

Extraia cada gasto como um lançamento:
- date: data no formato YYYY-MM-DD. Faturas costumam mostrar só dia e mês; deduza o ano pelo \
período da fatura (compras de dezembro numa fatura de janeiro são do ano anterior).
- description: o texto do lançamento como aparece na fatura.
- merchant: nome limpo e legível do estabelecimento (ex.: "IFD*RESTAURANTE XYZ" -> "iFood - Restaurante XYZ", \
"UBER *TRIP" -> "Uber", "PG *MERCADOLIVRE" -> "Mercado Livre").
- amount: valor em reais (número com até 2 casas decimais). Gastos são positivos; estornos, \
créditos e cashback são negativos.
- category: escolha a melhor categoria entre:
{_category_lines}
- installment: "k/N" quando for compra parcelada (ex.: "PARC 03/10" -> "3/10"), senão null.
- notes: observações curtas e úteis (ex.: "compra internacional US$ 12,99", "data da compra: 2026-03-14"); \
string vazia se não houver.

Regras importantes:
- NÃO inclua pagamentos da fatura anterior ("Pagamento recebido", "Pagamento efetuado"), saldo \
anterior, total da fatura, limites ou resumos — só lançamentos de gastos, estornos, tarifas, \
IOF, juros e encargos.
- Para parcelas a partir da 2ª (ex.: 3/10), use como date a data de fechamento da fatura (ou o \
primeiro dia do mês de referência, se o fechamento não aparecer) para que o gasto conte no mês \
em que é cobrado; registre a data original da compra em notes.
- Se houver cartões adicionais/titulares diferentes na mesma fatura, inclua todos os lançamentos \
e mencione o final do cartão em notes.
- Em cupom fiscal ou conta, gere normalmente um único lançamento com o valor total.
- reference_month: mês de referência/vencimento da fatura (YYYY-MM). due_date: vencimento. \
statement_total: valor total da fatura/documento como impresso. issuer: banco/emissor \
(ex.: "Nubank", "Itaú Personnalité Visa"). Use null quando não encontrar.
- warnings: avise sobre páginas ilegíveis, valores incertos ou qualquer coisa que o casal deva \
conferir. Lista vazia se estiver tudo certo.
Não invente lançamentos: se algo estiver ilegível, registre em warnings."""


def _to_cents(value) -> int | None:
    if value is None:
        return None
    return int(round(float(value) * 100))


def extract(content_blocks: list[dict], filenames: list[str]) -> dict:
    client = anthropic.Anthropic(timeout=600)
    user_content = content_blocks + [
        {
            "type": "text",
            "text": (
                f"Data de hoje: {date.today().isoformat()}. "
                f"Arquivos: {', '.join(filenames)}. "
                "Extraia todos os lançamentos deste documento."
            ),
        }
    ]
    try:
        with client.beta.messages.stream(
            model=config.CLAUDE_MODEL,
            max_tokens=64000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={
                "effort": config.CLAUDE_EFFORT,
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        ) as stream:
            response = stream.get_final_message()
    except anthropic.AuthenticationError as exc:
        raise ExtractionError(
            "Chave da API do Claude inválida ou ausente. Configure ANTHROPIC_API_KEY no arquivo .env."
        ) from exc
    except anthropic.BadRequestError as exc:
        raise ExtractionError(f"A API recusou o documento: {exc.message}") from exc
    except anthropic.RateLimitError as exc:
        raise ExtractionError("Limite de uso da API atingido. Tente novamente em alguns minutos.") from exc
    except anthropic.APIStatusError as exc:
        raise ExtractionError(f"Erro da API do Claude ({exc.status_code}). Tente novamente.") from exc
    except anthropic.APIConnectionError as exc:
        raise ExtractionError("Sem conexão com a API do Claude. Verifique a internet.") from exc

    if response.stop_reason == "refusal":
        raise ExtractionError("O Claude não conseguiu processar este documento.")
    if response.stop_reason == "max_tokens":
        raise ExtractionError("O documento é grande demais para uma leitura. Envie menos páginas por vez.")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise ExtractionError("O Claude não retornou dados para este documento.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExtractionError("Resposta inesperada do Claude. Tente novamente.") from exc

    transactions = []
    for t in data.get("transactions", []):
        cents = _to_cents(t.get("amount"))
        if not cents:
            continue
        transactions.append(
            {
                "date": t["date"],
                "description": t["description"].strip(),
                "merchant": (t.get("merchant") or "").strip(),
                "amount_cents": cents,
                "category": t["category"] if t.get("category") in CATEGORY_KEYS else "outros",
                "installment": t.get("installment") or None,
                "notes": (t.get("notes") or "").strip(),
            }
        )

    return {
        "document_type": data.get("document_type"),
        "issuer": data.get("issuer"),
        "reference_month": data.get("reference_month"),
        "due_date": data.get("due_date"),
        "statement_total_cents": _to_cents(data.get("statement_total")),
        "transactions": transactions,
        "warnings": data.get("warnings") or [],
        "model": response.model,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
