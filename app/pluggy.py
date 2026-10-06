"""Bank sync through Open Finance, using Meu Pluggy (free for your own accounts).

The couple connects their banks at meu.pluggy.ai, creates an application at
dashboard.pluggy.ai and pastes its Client ID, Client Secret and the Item IDs into the app.
Those stay on this computer (data/pluggy.json). A sync turns the accounts' transactions into
an import that goes through the usual review screen.
"""

import json
import os
import re
from datetime import date, timedelta

import httpx

from . import config
from .categorizer import clean_merchant, guess_category
from .extractor import ExtractionError

API = os.environ.get("PLUGGY_API_URL", "https://api.pluggy.ai")
FIRST_SYNC_DAYS = 90
TRANSPORT: httpx.BaseTransport | None = None  # tests swap in a fake Pluggy
OVERLAP_DAYS = 10  # re-read a few days: banks post some transactions late

# Money moving between your own accounts or paying the card bill is not spending.
NOT_SPENDING = re.compile(
    r"pagamento\s+(de\s+)?fatura|pgto\s+fatura|fatura\s+cart|pag\s+fat|pa?gto?\.?\s+cart[aã]o|"
    r"deb\.?\s*autom\w*\s+(de\s+)?fatura|"
    r"aplica[cç][aã]o|resgate|invest|poupan[cç]a|cdb|tesouro|"
    r"transfer[eê]ncia\s+entre\s+contas|mesma\s+titularidade|"
    r"pagamento\s+recebido|cr[eé]dito\s+de\s+pagamento",
    re.IGNORECASE,
)

# Pluggy's own categories, used when our keywords don't know the merchant.
PLUGGY_CATEGORIES = [
    ("supermarket", "mercado"), ("groceries", "mercado"),
    ("restaurant", "restaurantes"), ("food delivery", "restaurantes"), ("eating out", "restaurantes"),
    ("transport", "transporte"), ("gas station", "transporte"), ("taxi", "transporte"), ("parking", "transporte"),
    ("pharmacy", "saude"), ("health", "saude"), ("gym", "saude"),
    ("rent", "casa"), ("housing", "casa"), ("utilities", "casa"), ("electricity", "casa"), ("telecom", "casa"),
    ("travel", "lazer"), ("leisure", "lazer"), ("entertainment", "lazer"), ("tickets", "lazer"),
    ("shopping", "compras"), ("online shopping", "compras"), ("clothing", "compras"), ("electronics", "compras"),
    ("digital services", "assinaturas"), ("streaming", "assinaturas"), ("subscription", "assinaturas"),
    ("education", "assinaturas"),
]


class SyncError(ExtractionError):
    pass


# ---------------------------------------------------------------- settings


def settings_path():
    return config.DATA_DIR / "pluggy.json"


def load_settings() -> dict:
    """Saved settings, falling back to PLUGGY_* in .env."""
    try:
        data = json.loads(settings_path().read_text("utf-8"))
    except (FileNotFoundError, ValueError):
        data = {}
    client_id = data.get("client_id") or os.environ.get("PLUGGY_CLIENT_ID", "")
    client_secret = data.get("client_secret") or os.environ.get("PLUGGY_CLIENT_SECRET", "")
    item_ids = data.get("item_ids") or parse_item_ids(os.environ.get("PLUGGY_ITEM_IDS", ""))
    return {"client_id": client_id.strip(), "client_secret": client_secret.strip(), "item_ids": item_ids,
            "last_sync": data.get("last_sync")}


def save_settings(client_id: str, client_secret: str, item_ids: list[str], last_sync: str | None = None) -> None:
    config.ensure_dirs()
    path = settings_path()
    path.write_text(json.dumps({"client_id": client_id, "client_secret": client_secret, "item_ids": item_ids,
                                "last_sync": last_sync}, indent=2), "utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def parse_item_ids(text: str) -> list[str]:
    return list(dict.fromkeys(i for i in re.split(r"[\s,;]+", text or "") if i))


def configured(settings: dict | None = None) -> bool:
    s = settings or load_settings()
    return bool(s["client_id"] and s["client_secret"] and s["item_ids"])


# ---------------------------------------------------------------- API


class Client:
    def __init__(self, client_id: str, client_secret: str, transport: httpx.BaseTransport | None = None):
        self.http = httpx.Client(base_url=API, timeout=60, transport=transport or TRANSPORT)
        try:
            r = self.http.post("/auth", json={"clientId": client_id, "clientSecret": client_secret})
        except httpx.HTTPError as exc:
            raise SyncError("Não consegui falar com a Pluggy. Verifique a internet.") from exc
        if r.status_code in (400, 401, 403):
            raise SyncError("A Pluggy recusou o Client ID / Client Secret. Confira-os no dashboard.pluggy.ai.")
        self._check(r)
        self.http.headers["X-API-KEY"] = r.json()["apiKey"]

    @staticmethod
    def _check(r: httpx.Response) -> None:
        if r.status_code >= 400:
            try:
                message = r.json().get("message", "")
            except ValueError:
                message = r.text[:200]
            raise SyncError(f"Erro da Pluggy ({r.status_code}): {message}")

    def get(self, path: str, **params) -> dict:
        try:
            r = self.http.get(path, params={k: v for k, v in params.items() if v is not None})
        except httpx.HTTPError as exc:
            raise SyncError("Não consegui falar com a Pluggy. Verifique a internet.") from exc
        if r.status_code == 404 and path.startswith("/items/"):
            raise SyncError(f"Item ID não encontrado na Pluggy: {path.split('/')[-1]}. Confira os Item IDs.")
        self._check(r)
        return r.json()

    def paged(self, path: str, **params) -> list[dict]:
        out, page = [], 1
        while True:
            data = self.get(path, page=page, pageSize=500, **params)
            out += data.get("results", [])
            if page >= (data.get("totalPages") or 1):
                return out
            page += 1


def describe_items(client: Client, item_ids: list[str]) -> list[dict]:
    items = []
    for item_id in item_ids:
        item = client.get(f"/items/{item_id}")
        items.append(
            {
                "id": item_id,
                "bank": (item.get("connector") or {}).get("name") or "Banco",
                "status": item.get("status") or "",
                "updated_at": item.get("lastUpdatedAt") or item.get("updatedAt"),
            }
        )
    return items


# ---------------------------------------------------------------- sync


def _category(description: str, pluggy_category: str | None) -> str:
    ours = guess_category(description)
    if ours != "outros" or not pluggy_category:
        return ours
    low = pluggy_category.lower()
    for word, category in PLUGGY_CATEGORIES:
        if word in low:
            return category
    return "outros"


def _bill_months(client: Client, account_id: str) -> dict[str, str]:
    """Credit card bill id -> month of its due date, so entries count in their statement month."""
    try:
        bills = client.paged("/bills", accountId=account_id)
    except SyncError:
        return {}
    return {b["id"]: str(b.get("dueDate", ""))[:7] for b in bills if b.get("id") and b.get("dueDate")}


# Bank account lines say how the money left before saying where it went.
_HOW = re.compile(
    r"^(pix\s+(enviado|transf\w*)|transfer[eê]ncia\s+(pix\s+)?enviada|compra\s+(no\s+)?(d[eé]bito|cart[aã]o)|"
    r"pagamento\s+(de\s+)?(boleto|conta|efetuado)|pagto\s+boleto|d[eé]bito\s+autom[aá]tico)\s*[-:–]?\s*",
    re.IGNORECASE,
)


def _payee(description: str) -> str:
    return _HOW.sub("", description).strip() or description


def fetch(client: Client, item_ids: list[str], since: date, known_ids: set[str]) -> dict:
    """Spending in the given connections since a date, skipping what was already imported."""
    transactions, warnings = [], []
    banks = []
    for item in describe_items(client, item_ids):
        banks.append(item["bank"])
        if item["status"] in ("LOGIN_ERROR", "OUTDATED", "WAITING_USER_INPUT", "ERROR"):
            warnings.append(
                f"{item['bank']}: a conexão precisa ser renovada no meu.pluggy.ai (status {item['status']}); "
                "os dados podem estar desatualizados."
            )
        for account in client.paged("/accounts", itemId=item["id"]):
            card = account.get("type") == "CREDIT"
            bill_month = _bill_months(client, account["id"]) if card else {}
            kind = "cartão" if card else "conta"
            source = f"{item['bank']} {kind}"
            for t in client.paged("/transactions", accountId=account["id"], **{"from": since.isoformat()}):
                ext_id = f"pluggy:{t.get('id')}"
                if not t.get("id") or ext_id in known_ids:
                    continue
                if (t.get("status") or "POSTED") == "PENDING":
                    continue
                description = re.sub(r"\s+", " ", t.get("description") or t.get("descriptionRaw") or "").strip()
                if not description or NOT_SPENDING.search(description):
                    continue
                cents = int(round(abs(float(t.get("amount") or 0)) * 100))
                if not cents:
                    continue
                outgoing = (t.get("type") or "").upper() == "DEBIT"
                if not outgoing:
                    if not card:
                        continue  # money coming into the account (salary, Pix received): not spending
                    cents = -cents  # refund / credit on the card
                meta = t.get("creditCardMetadata") or {}
                installment = None
                k, n = meta.get("installmentNumber"), meta.get("totalInstallments")
                if k and n and 1 <= int(k) <= int(n) and int(n) >= 2:
                    installment = f"{int(k)}/{int(n)}"
                transactions.append(
                    {
                        "date": str(t.get("date", ""))[:10],
                        "description": description[:300],
                        "merchant": clean_merchant((t.get("merchant") or {}).get("name") or _payee(description))[:200],
                        "amount_cents": cents,
                        "category": _category(description, t.get("category")),
                        "installment": installment,
                        "notes": "",
                        "source": source,
                        "external_id": ext_id,
                        "bill_month": bill_month.get(meta.get("billId") or ""),
                    }
                )
    return {
        "document_type": "open_finance",
        "issuer": " + ".join(dict.fromkeys(banks)) or "Open Finance",
        "reference_month": None,
        "due_date": None,
        "statement_total_cents": None,
        "transactions": sorted(transactions, key=lambda t: t["date"]),
        "warnings": warnings,
        "model": "open-finance",
        "input_tokens": None,
        "output_tokens": None,
    }


def sync_since(last_sync: str | None) -> date:
    if last_sync:
        try:
            return date.fromisoformat(last_sync[:10]) - timedelta(days=OVERLAP_DAYS)
        except ValueError:
            pass
    return date.today() - timedelta(days=FIRST_SYNC_DAYS)
