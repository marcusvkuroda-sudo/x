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
from .categorizer import NOT_SPENDING, clean_merchant, guess_category
from .extractor import ExtractionError

API = os.environ.get("PLUGGY_API_URL", "https://api.pluggy.ai")
FIRST_SYNC_DAYS = 90
TRANSPORT: httpx.BaseTransport | None = None  # tests swap in a fake Pluggy
OVERLAP_DAYS = 10  # re-read a few days: banks post some transactions late

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


def mark_synced(when: str) -> None:
    """Records the time of the last sync, leaving the rest of the saved file as it is (settings
    that came from .env stay there)."""
    try:
        data = json.loads(settings_path().read_text("utf-8"))
    except (FileNotFoundError, ValueError):
        data = {}
    save_settings(data.get("client_id", ""), data.get("client_secret", ""), data.get("item_ids") or [], when)


def parse_item_ids(text: str) -> list[str]:
    return list(dict.fromkeys(i for i in re.split(r"[\s,;]+", text or "") if i))


def configured(settings: dict | None = None) -> bool:
    s = settings or load_settings()
    return bool(s["client_id"] and s["client_secret"] and s["item_ids"])


# ---------------------------------------------------------------- API


class Client:
    """Pluggy API session. Use it in a with block so the connection is closed."""

    def __init__(self, client_id: str, client_secret: str, transport: httpx.BaseTransport | None = None):
        self.http = httpx.Client(base_url=API, timeout=60, transport=transport or TRANSPORT)
        try:
            try:
                r = self.http.post("/auth", json={"clientId": client_id, "clientSecret": client_secret})
            except httpx.HTTPError as exc:
                raise SyncError("Não consegui falar com a Pluggy. Verifique a internet.") from exc
            if r.status_code in (400, 401, 403):
                raise SyncError("A Pluggy recusou o Client ID / Client Secret. Confira-os no dashboard.pluggy.ai.")
            self._check(r)
            api_key = r.json().get("apiKey")
            if not api_key:
                raise SyncError("Resposta inesperada da Pluggy ao entrar. Tente de novo em instantes.")
        except BaseException:
            self.close()
            raise
        self.http.headers["X-API-KEY"] = api_key

    def close(self) -> None:
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    @staticmethod
    def _check(r: httpx.Response) -> None:
        if r.status_code >= 400:
            try:
                message = r.json().get("message", "")
            except ValueError:
                message = r.text[:200]
            raise SyncError(f"Erro da Pluggy ({r.status_code}): {message}")

    def get(self, path: str, **params):
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
            if isinstance(data, list):  # endpoints without paging return the list itself
                return out + data
            out += data.get("results") or []
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


def _month(text) -> str | None:
    m = re.match(r"(\d{4})-(\d{2})", str(text or ""))
    return f"{m.group(1)}-{m.group(2)}" if m else None


def _next_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y + m // 12}-{m % 12 + 1:02d}"


def _bill_schedule(client: Client, account: dict):
    """For a credit card: bill id -> statement month (month of its due date), and a guess for
    purchases of the bill still open, which has no id yet."""
    try:
        bills = client.paged("/bills", accountId=account["id"])
    except SyncError:
        bills = []
    by_id = {b["id"]: _month(b.get("dueDate")) for b in bills if b.get("id") and _month(b.get("dueDate"))}
    credit = account.get("creditData") or {}
    open_due = _month(credit.get("balanceDueDate"))
    close = str(credit.get("balanceCloseDate") or "")[:10]
    if not open_due and by_id:
        open_due = _next_month(max(by_id.values()))

    def open_bill(tx_date: str) -> str | None:
        if not open_due:
            return None
        # Bought after the open bill closed: goes to the one after it.
        return _next_month(open_due) if close and tx_date > close else open_due

    return by_id, open_bill


# Bank account lines say how the money left before saying where it went.
_HOW = re.compile(
    r"^(pix\s+(enviado|transf\w*)|transfer[eê]ncia\s+(pix\s+)?enviada|compra\s+(no\s+)?(d[eé]bito|cart[aã]o)|"
    r"pagamento\s+(de\s+)?(boleto|conta|efetuado)|pagto\s+boleto|d[eé]bito\s+autom[aá]tico)\s*[-:–]?\s*",
    re.IGNORECASE,
)
_REFUND = re.compile(r"estorno|reembolso|devolu[cç][aã]o|cashback", re.IGNORECASE)
# Pluggy's own labels for money that is not spending.
_NOT_SPENDING_CATEGORY = re.compile(r"credit card payment|same person|investment", re.IGNORECASE)
TRANSFER_DAYS = 3


def _payee(description: str) -> str:
    return _HOW.sub("", description).strip() or description


def _days_apart(a: str, b: str) -> int:
    try:
        return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)
    except ValueError:
        return 999


def fetch(client: Client, item_ids: list[str], since: date, known_ids: set[str]) -> dict:
    """Spending in the given connections since a date, skipping what was already imported.

    Returns the same shape as the statement readers, plus bill_updates: the statement month of
    entries imported before their bill closed, now that it is known.
    """
    transactions, warnings, banks = [], [], []
    incoming = []  # money that came into one of the accounts: (account id, date, cents, label)
    bill_updates = {}
    for item in describe_items(client, item_ids):
        banks.append(item["bank"])
        if item["status"] in ("LOGIN_ERROR", "OUTDATED", "WAITING_USER_INPUT", "ERROR"):
            warnings.append(
                f"{item['bank']}: a conexão precisa ser renovada no meu.pluggy.ai (status {item['status']}); "
                "os dados podem estar desatualizados."
            )
        for account in client.paged("/accounts", itemId=item["id"]):
            card = account.get("type") == "CREDIT"
            bill_by_id, open_bill = _bill_schedule(client, account) if card else ({}, lambda _d: None)
            source = f"{item['bank']} {'cartão' if card else 'conta'}"
            for t in client.paged("/transactions", accountId=account["id"], **{"from": since.isoformat()}):
                if not t.get("id") or (t.get("status") or "POSTED") == "PENDING":
                    continue
                ext_id = f"pluggy:{t['id']}"
                tx_date = str(t.get("date", ""))[:10]
                meta = t.get("creditCardMetadata") or {}
                bill_month = bill_by_id.get(meta.get("billId") or "") if card else None
                description = re.sub(r"\s+", " ", t.get("description") or t.get("descriptionRaw") or "").strip()
                cents = int(round(abs(float(t.get("amount") or 0)) * 100))
                outgoing = (t.get("type") or "").upper() == "DEBIT"
                if not outgoing and cents and not (card and _REFUND.search(description)):
                    incoming.append((account["id"], tx_date, cents, source))
                if ext_id in known_ids:
                    if bill_month:
                        bill_updates[ext_id] = bill_month
                    continue
                if not description or not cents or NOT_SPENDING.search(description):
                    continue
                if not outgoing:
                    if not card:
                        continue  # money coming into the account (salary, Pix received): not spending
                    cents = -cents  # refund / credit on the card
                installment = None
                k, n = meta.get("installmentNumber"), meta.get("totalInstallments")
                if k and n and 1 <= int(k) <= int(n) and int(n) >= 2:
                    installment = f"{int(k)}/{int(n)}"
                notes = []
                purchase = str(meta.get("purchaseDate") or "")[:10]
                if purchase and purchase != tx_date:
                    notes.append(f"data da compra: {purchase}")
                # A bare "Pix enviado": the receiver's name says where the money went.
                receiver = (((t.get("paymentData") or {}).get("receiver") or {}).get("name") or "").strip()
                if receiver and not _HOW.sub("", description).strip():
                    description = f"{description} - {receiver}"
                payee = (t.get("merchant") or {}).get("name") or ""
                row = {
                    "date": tx_date,
                    "description": description[:300],
                    "merchant": clean_merchant(payee or _payee(description))[:200],
                    "amount_cents": cents,
                    "category": _category(description, t.get("category")),
                    "installment": installment,
                    "notes": " · ".join(notes),
                    "source": source,
                    "external_id": ext_id,
                    "bill_month": bill_month or (open_bill(tx_date) if card else None),
                    "suggest_skip": None,
                }
                if not card and outgoing and _NOT_SPENDING_CATEGORY.search(t.get("category") or ""):
                    row["suggest_skip"] = "parece pagamento de fatura, investimento ou transferência entre suas contas"
                row["_account"], row["_card"] = account["id"], card
                transactions.append(row)

    # Money leaving one account and arriving at another of yours (a Pix between your banks, the
    # card bill paid from the other bank) is not spending. Same value within a few days: suggest
    # leaving it out, but let the couple decide (it could be a coincidence).
    used = set()
    for row in sorted(transactions, key=lambda r: r["date"]):
        if row["suggest_skip"] or row["amount_cents"] <= 0 or row["_card"]:
            continue
        for i, (account_id, when, cents, label) in enumerate(incoming):
            if i in used or account_id == row["_account"] or cents != row["amount_cents"]:
                continue
            if _days_apart(when, row["date"]) <= TRANSFER_DAYS:
                used.add(i)
                row["suggest_skip"] = (
                    f"parece o pagamento da fatura do {label}" if label.endswith("cartão")
                    else f"o mesmo valor entrou em {label}: parece transferência entre suas contas"
                )
                break
    for row in transactions:
        del row["_account"], row["_card"]
    flagged = sum(1 for r in transactions if r["suggest_skip"])
    if flagged:
        warnings.append(
            f"{flagged} lançamento(s) parecem transferência entre suas contas ou pagamento de fatura "
            "e vieram desmarcados. Marque se forem gastos de verdade."
        )
    return {
        "document_type": "open_finance",
        "issuer": " + ".join(dict.fromkeys(banks)) or "Open Finance",
        "reference_month": None,
        "due_date": None,
        "statement_total_cents": None,
        "transactions": sorted(transactions, key=lambda t: t["date"]),
        "warnings": warnings,
        "bill_updates": bill_updates,
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
