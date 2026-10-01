"""Reads a credit card statement (or receipt / bill) with Claude and returns
structured transactions."""

import json
import re
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
- NÃO inclua lançamentos futuros: seções como "Próximas faturas", "Lançamentos futuros", \
"Compras parceladas a vencer" ou "Saldo parcelado" listam parcelas que ainda serão cobradas em \
outras faturas. Inclua apenas o que é cobrado nesta fatura.
- Se a mesma compra aparecer em mais de uma página (por exemplo, numa lista resumida e na lista \
detalhada), registre-a uma vez só.
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
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


def _iso_date(value) -> str | None:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def _month(value) -> str | None:
    value = str(value or "")
    return value[:7] if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value[:7]) else None


def _installment(value) -> str | None:
    m = re.search(r"(\d{1,3})\s*(?:/|de|of)\s*(\d{1,3})", str(value or ""), re.IGNORECASE)
    if not m:
        return None
    k, n = int(m.group(1)), int(m.group(2))
    return f"{k}/{n}" if 1 <= k <= n and n >= 2 else None


def _api_error(exc: anthropic.APIError) -> str:
    message = getattr(exc, "message", "") or str(exc)
    if "credit balance" in message.lower():
        return "Acabaram os créditos da conta da Anthropic. Adicione créditos em console.anthropic.com e tente de novo."
    if isinstance(exc, anthropic.AuthenticationError):
        return "Chave da API do Claude inválida. Confira ANTHROPIC_API_KEY no arquivo .env e reinicie o app."
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "A chave da API não tem permissão para usar este modelo. Confira a conta em console.anthropic.com."
    if isinstance(exc, anthropic.NotFoundError):
        return f"O modelo '{config.CLAUDE_MODEL}' não foi encontrado. Confira EXTRACTION_MODEL no arquivo .env."
    if isinstance(exc, anthropic.RateLimitError):
        return "Limite de uso da API atingido. Tente novamente em alguns minutos."
    if isinstance(exc, (anthropic.OverloadedError, anthropic.InternalServerError, anthropic.ServiceUnavailableError)):
        return "A API do Claude está sobrecarregada agora. Tente novamente em alguns minutos."
    if isinstance(exc, anthropic.APIConnectionError):
        return "Sem conexão com a API do Claude. Verifique a internet."
    if isinstance(exc, anthropic.BadRequestError):
        return f"A API recusou o documento: {message}"
    status = getattr(exc, "status_code", None)
    return f"Erro da API do Claude{f' ({status})' if status else ''}. Tente novamente."


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
    except anthropic.APIError as exc:
        raise ExtractionError(_api_error(exc)) from exc
    except TypeError as exc:
        # The SDK raises TypeError when it finds no API key at all.
        if "authentication" not in str(exc).lower():
            raise
        raise ExtractionError(
            "Chave da API do Claude não configurada. Coloque ANTHROPIC_API_KEY no arquivo .env e reinicie o app."
        ) from exc

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

    warnings = [str(w) for w in data.get("warnings") or []]
    transactions = []
    undated = 0
    for t in data.get("transactions", []):
        cents = _to_cents(t.get("amount"))
        if not cents:
            continue
        tx_date = _iso_date(t.get("date"))
        if not tx_date:
            undated += 1
        description = str(t.get("description") or "").strip()
        merchant = str(t.get("merchant") or "").strip()
        notes = str(t.get("notes") or "").strip()
        installment = _installment(t.get("installment"))
        if t.get("installment") and not installment:
            notes = f"{notes} · parcela: {t['installment']}".strip(" ·")
        transactions.append(
            {
                "date": tx_date or "",
                "description": (description or merchant or "Lançamento")[:300],
                "merchant": merchant[:200],
                "amount_cents": cents,
                "category": t["category"] if t.get("category") in CATEGORY_KEYS else "outros",
                "installment": installment,
                "notes": notes[:500],
            }
        )
    if undated:
        warnings.append(f"{undated} lançamento(s) ficaram sem data legível; preencha antes de importar.")

    return {
        "document_type": data.get("document_type"),
        "issuer": (str(data["issuer"])[:100] if data.get("issuer") else None),
        "reference_month": _month(data.get("reference_month")),
        "due_date": _iso_date(data.get("due_date")) if data.get("due_date") else None,
        "statement_total_cents": _to_cents(data.get("statement_total")),
        "transactions": transactions,
        "warnings": warnings,
        "model": response.model,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
