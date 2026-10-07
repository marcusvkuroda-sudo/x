"""Bank sync through Open Finance, using Meu Pluggy (free for your own accounts).

The couple connects their banks at meu.pluggy.ai, creates an application at
dashboard.pluggy.ai and pastes its Client ID, Client Secret and the Item IDs into the app.
Those stay on this computer (data/pluggy.json). A sync turns the accounts' transactions into
an import that goes through the usual review screen.
"""

import calendar
import json
import os
import re
from datetime import date, timedelta

from urllib.parse import parse_qs, urlsplit

import httpx

from . import config
from .categorizer import NOT_SPENDING, clean_merchant, guess_category, raw_category
from .extractor import ExtractionError

API = os.environ.get("PLUGGY_API_URL", "https://api.pluggy.ai")
FIRST_SYNC_DAYS = 90
TRANSPORT: httpx.BaseTransport | None = None  # tests swap in a fake Pluggy
# Re-read the last weeks on every sync: banks post some transactions late, and purchases of the
# open bill get their final statement month once it closes.
OVERLAP_DAYS = 40

# Card purchases carry the merchant's MCC (the card networks' merchant category): the most
# reliable hint there is. Ranges are inclusive.
MCC_RANGES = [
    ((5411, 5411), "mercado"), ((5422, 5422), "mercado"), ((5441, 5462), "mercado"), ((5499, 5499), "mercado"),
    ((5300, 5300), "mercado"),
    ((5811, 5814), "restaurantes"),
    ((4111, 4131), "transporte"), ((4784, 4784), "transporte"), ((5511, 5599), "transporte"),
    ((7511, 7549), "transporte"), ((3351, 3500), "transporte"),
    ((5912, 5912), "saude"), ((5122, 5122), "saude"), ((8011, 8099), "saude"), ((7230, 7230), "saude"),
    ((7297, 7298), "saude"), ((7997, 7997), "saude"), ((5975, 5977), "saude"), ((8050, 8050), "saude"),
    ((4812, 4815), "casa"), ((4899, 4900), "casa"), ((5200, 5261), "casa"), ((5712, 5722), "casa"),
    ((1520, 1799), "casa"), ((7623, 7699), "casa"),
    ((3000, 3350), "lazer"), ((3501, 3999), "lazer"), ((4411, 4411), "lazer"), ((4511, 4511), "lazer"),
    ((4722, 4722), "lazer"), ((7011, 7033), "lazer"), ((7832, 7841), "lazer"), ((7911, 7996), "lazer"),
    ((7998, 7999), "lazer"), ((5813, 5813), "restaurantes"),
    ((4816, 4816), "assinaturas"), ((5815, 5818), "assinaturas"), ((5968, 5968), "assinaturas"),
    ((8211, 8299), "assinaturas"), ((7372, 7372), "assinaturas"),
    ((5310, 5399), "compras"), ((5611, 5699), "compras"), ((5732, 5735), "compras"), ((5940, 5949), "compras"),
    ((5970, 5974), "compras"), ((5978, 5999), "compras"), ((5045, 5045), "compras"), ((5137, 5139), "compras"),
    ((5651, 5661), "compras"), ((5311, 5311), "compras"), ((5964, 5969), "compras"),
    ((5995, 5995), "outros"), ((742, 742), "outros"), ((6300, 6399), "outros"), ((9311, 9399), "outros"),
    ((6010, 6012), "outros"),
]

# Pluggy's own categories (its names, in English), most specific first.
PLUGGY_CATEGORIES = [
    ("food delivery", "restaurantes"), ("eating out", "restaurantes"), ("food and drinks", "restaurantes"),
    ("groceries", "mercado"), ("supermarket", "mercado"),
    ("pet supplies", "outros"), ("bank fees", "outros"), ("credit card fees", "outros"), ("interests", "outros"),
    ("late payment", "outros"), ("tax", "outros"), ("insurance", "outros"),
    ("video streaming", "assinaturas"), ("music streaming", "assinaturas"), ("digital services", "assinaturas"),
    ("software", "assinaturas"), ("online courses", "assinaturas"), ("education", "assinaturas"),
    ("university", "assinaturas"), ("school", "assinaturas"), ("gaming", "assinaturas"),
    ("telecommunications", "casa"), ("internet", "casa"), ("mobile", "casa"), ("tv", "casa"), ("rent", "casa"),
    ("housing", "casa"), ("utilities", "casa"), ("water", "casa"), ("electricity", "casa"), ("houseware", "casa"),
    ("urban land", "casa"),
    ("pharmacy", "saude"), ("dentist", "saude"), ("optometry", "saude"), ("hospital", "saude"),
    ("healthcare", "saude"), ("gyms", "saude"), ("wellness", "saude"), ("sports practice", "saude"),
    ("airport", "lazer"), ("airlines", "lazer"), ("accomodation", "lazer"), ("accommodation", "lazer"),
    ("travel", "lazer"), ("bus tickets", "lazer"), ("tickets", "lazer"), ("cinema", "lazer"), ("museums", "lazer"),
    ("stadiums", "lazer"), ("leisure", "lazer"),
    ("taxi", "transporte"), ("ride-hailing", "transporte"), ("public transportation", "transporte"),
    ("car rental", "transporte"), ("gas station", "transporte"), ("parking", "transporte"), ("tolls", "transporte"),
    ("vehicle", "transporte"), ("automotive", "transporte"), ("transportation", "transporte"),
    ("bicycle", "transporte"), ("traffic", "transporte"),
    ("online shopping", "compras"), ("electronics", "compras"), ("clothing", "compras"), ("kids and toys", "compras"),
    ("bookstore", "compras"), ("sports goods", "compras"), ("office supplies", "compras"), ("shopping", "compras"),
]

# Bank account: only purchases with the debit card count (parking, a coffee). Pix, boletos,
# transfers, deposits and the like are left out: big payments are registered as fixed expenses.
_DEBIT_CARD = re.compile(
    r"compra\s+(no\s+|com\s+)?(cart[aã]o\s+(de\s+)?)?d[eé]b|compra\s+(no\s+)?cart[aã]o|cart[aã]o\s+d[eé]b|"
    r"\bdeb(ito)?\s+(visa|master|elo)|visa\s+electron|maestro|elo\s+d[eé]b",
    re.IGNORECASE,
)
_NOT_A_PURCHASE = re.compile(r"\bpix\b|boleto|\bted\b|\bdoc\b|transf|pagamento|pagto|pgto|saque|dep[oó]sito", re.IGNORECASE)
_TRANSFER_METHODS = {"PIX", "TED", "DOC", "TEF", "BOLETO"}


# Paying the card bill, seen from either side: "PAGAMENTO RECEBIDO" / "PAGTO DEB AUTOMATICO" on the
# card, "PAGAMENTO FATURA CARTAO" / "DEB AUT FATURA" in the account.
_BILL_PAYMENT = re.compile(
    r"pagamento|pagto|pgto|\bpag\b|\bpgt\b|deb\.?\s*aut|d[eé]bito\s+autom|\bfatura\b|cr[eé]dito\s+de\s+pagamento",
    re.IGNORECASE,
)


def _bill_payment(t: dict, description: str, card: bool, outgoing: bool) -> bool:
    if NOT_SPENDING.search(description) or "credit card payment" in (t.get("category") or "").lower():
        return True
    # A card's own purchases may carry those words ("MP *PAGAMENTO..."): only its credits are checked.
    return (not card or not outgoing) and bool(_BILL_PAYMENT.search(description))


def _debit_card_purchase(t: dict, description: str) -> bool:
    op = (t.get("operationType") or "").upper()
    if op == "CARTAO":
        return True
    if op and op != "OUTROS":
        return False  # PIX, BOLETO, TED, TRANSFERENCIA_..., SAQUE, TARIFA_...
    payment = t.get("paymentData") or {}
    if (payment.get("paymentMethod") or "").upper() in _TRANSFER_METHODS or payment.get("boletoMetadata"):
        return False
    return bool(_DEBIT_CARD.search(description)) and not _NOT_A_PURCHASE.search(description)


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

    def cursor(self, path: str, **params) -> list[dict]:
        """Endpoints with cursor paging (GET /v2/...): each page says where the next one starts."""
        out, after = [], None
        for _ in range(1000):  # safety net against a cursor that never ends
            data = self.get(path, after=after, **params)
            out += data.get("results") or []
            nxt = data.get("next")
            after = parse_qs(urlsplit(nxt).query).get("after", [None])[0] if nxt else None
            if not after:
                break
        return out


# Banks we can recognize in account names (Meu Pluggy connections are all named "MeuPluggy").
_BANKS = [("inter", "Inter"), ("santander", "Santander"), ("nubank", "Nubank"), ("nu pagamentos", "Nubank"),
          ("itau", "Itaú"), ("itaú", "Itaú"), ("bradesco", "Bradesco"), ("caixa", "Caixa"), ("c6", "C6 Bank"),
          ("banco do brasil", "Banco do Brasil"), ("ourocard", "Banco do Brasil"), ("btg", "BTG"), ("xp", "XP"),
          ("mercado pago", "Mercado Pago"), ("picpay", "PicPay"), ("sicredi", "Sicredi"), ("sicoob", "Sicoob"),
          ("neon", "Neon"), ("pan", "Banco Pan"), ("original", "Original"), ("safra", "Safra")]


def _bank_name(client: Client, item: dict, position: int) -> str:
    name = ((item.get("connector") or {}).get("name") or "").strip()
    if name and "pluggy" not in name.lower():
        return name
    # Meu Pluggy: look for the bank in the accounts' names.
    try:
        accounts = client.paged("/accounts", itemId=item.get("id"))
    except SyncError:
        accounts = []
    text = " " + " ".join(
        str(a.get(k) or "") for a in accounts for k in ("name", "marketingName", "number")
    ).lower() + " "
    text = re.sub(r"[^a-z0-9à-ú]+", " ", text)
    for key, bank in _BANKS:
        if f" {key} " in text:
            return bank
    return f"Banco {position}"


def describe_items(client: Client, item_ids: list[str]) -> list[dict]:
    items = []
    for position, item_id in enumerate(item_ids, start=1):
        item = client.get(f"/items/{item_id}")
        items.append(
            {
                "id": item_id,
                "bank": _bank_name(client, {**item, "id": item_id}, position),
                "status": item.get("status") or "",
                "updated_at": item.get("lastUpdatedAt") or item.get("updatedAt"),
            }
        )
    return items


# ---------------------------------------------------------------- sync


def _mcc_category(mcc) -> str | None:
    try:
        code = int(mcc)
    except (TypeError, ValueError):
        return None
    for (low, high), category in MCC_RANGES:
        if low <= code <= high:
            return category
    return None


def _category(description: str, t: dict) -> str:
    """Known brands first (99Food is food, not a ride), then the merchant's MCC, Pluggy's
    category and, last, our keywords. Corrections the couple made still win over all of it."""
    special = raw_category(description)
    if special:
        return special
    mcc = _mcc_category((t.get("creditCardMetadata") or {}).get("payeeMCC"))
    if mcc:
        return mcc
    low = (t.get("category") or "").lower()
    for word, category in PLUGGY_CATEGORIES:
        if re.search(rf"\b{re.escape(word)}\b", low):
            return category
    return guess_category(description)


def _month(text) -> str | None:
    m = re.match(r"(\d{4})-(\d{2})", str(text or ""))
    return f"{m.group(1)}-{m.group(2)}" if m else None


def _next_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y + m // 12}-{m % 12 + 1:02d}"


def _day(text) -> int | None:
    m = re.match(r"\d{4}-\d{2}-(\d{2})", str(text or ""))
    return int(m.group(1)) if m else None


def _on_day(year: int, month: int, day: int) -> date:
    while month > 12:
        year, month = year + 1, month - 12
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def statement_month(tx_date: str, closing_day: int, due_day: int) -> str | None:
    """Month of the bill a purchase goes to, from the card's closing and due days: the first
    closing on or after the purchase, then the first due date after that closing."""
    try:
        d = date.fromisoformat(tx_date[:10])
    except ValueError:
        return None
    closing = _on_day(d.year, d.month, closing_day)
    if d > closing:
        closing = _on_day(d.year, d.month + 1, closing_day)
    due = _on_day(closing.year, closing.month, due_day)
    if due <= closing:
        due = _on_day(closing.year, closing.month + 1, due_day)
    return f"{due.year}-{due.month:02d}"


def _bill_schedule(client: Client, account: dict):
    """For a credit card: bill id -> statement month (month of its due date), and the statement
    month of purchases still in the open bill (no bill id yet), from the card's cycle."""
    try:
        bills = client.paged("/bills", accountId=account["id"])
    except SyncError:
        bills = []
    by_id = {b["id"]: _month(b.get("dueDate")) for b in bills if b.get("id") and _month(b.get("dueDate"))}
    # The cycle (closing and due days) of the most recent bill, else of the card's current balance.
    latest = max(bills, key=lambda b: str(b.get("dueDate") or ""), default={})
    credit = account.get("creditData") or {}
    due_day = _day(latest.get("dueDate")) or _day(credit.get("balanceDueDate"))
    closing_day = _day(latest.get("billClosingDate")) or _day(credit.get("balanceCloseDate"))
    if due_day and not closing_day:
        closing_day = (due_day - 8 - 1) % 28 + 1  # most cards close about a week before the due date

    def open_bill(tx_date: str) -> str | None:
        return statement_month(tx_date, closing_day, due_day) if due_day else None

    open_bill.cycle = (closing_day, due_day)  # shown by check()
    open_bill.bills = bills
    return by_id, open_bill


def check(client: Client, item_ids: list[str]) -> list[dict]:
    """What the banks say about each card: total of each closed bill, the card's cycle and its
    current balance, to compare with what was imported."""
    cards = []
    for item in describe_items(client, item_ids):
        for account in client.paged("/accounts", itemId=item["id"]):
            if account.get("type") != "CREDIT":
                continue
            _by_id, open_bill = _bill_schedule(client, account)
            credit = account.get("creditData") or {}
            bills = sorted(
                (
                    {
                        "month": _month(b.get("dueDate")),
                        "due_date": str(b.get("dueDate") or "")[:10],
                        "closing_date": str(b.get("billClosingDate") or "")[:10] or None,
                        "total_cents": int(round(float(b.get("totalAmount") or 0) * 100)),
                    }
                    for b in open_bill.bills
                    if _month(b.get("dueDate"))
                ),
                key=lambda b: b["month"],
            )
            balance = account.get("balance")
            cards.append(
                {
                    "source": f"{item['bank']} cartão",
                    "closing_day": open_bill.cycle[0],
                    "due_day": open_bill.cycle[1],
                    "open_month": open_bill(date.today().isoformat()),
                    "balance_cents": int(round(float(balance) * 100)) if balance is not None else None,
                    "balance_close_date": str(credit.get("balanceCloseDate") or "")[:10] or None,
                    "balance_due_date": str(credit.get("balanceDueDate") or "")[:10] or None,
                    "bills": bills[-4:],
                }
            )
    return cards


def fetch(client: Client, item_ids: list[str], since: date, known_ids: set[str]) -> dict:
    """Card purchases (and debit card purchases from the accounts) since a date, skipping what
    was already imported.

    Returns the same shape as the statement readers, plus bill_updates: the statement month of
    entries imported before their bill closed, now that it is known.
    """
    transactions, warnings, banks = [], [], []
    bill_updates = {}
    left_out = 0
    open_bills = {}  # (card, statement month) -> cents of the purchases not billed yet
    remove_ids = set()
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
            source = f"{item['bank']} {'cartão' if card else 'débito'}"
            for t in client.cursor("/v2/transactions", accountId=account["id"], dateFrom=since.isoformat()):
                # The open bill's purchases come as PENDING (no bill yet) and turn POSTED, keeping
                # their id, when it closes. In the account, PENDING is only an authorization.
                pending = (t.get("status") or "POSTED") == "PENDING"
                if not t.get("id") or (pending and not card):
                    continue
                ext_id = f"pluggy:{t['id']}"
                tx_date = str(t.get("date", ""))[:10]
                meta = t.get("creditCardMetadata") or {}
                bill_month = None
                if card:
                    # Installments may carry the original purchase date: for them the bank's own
                    # forecast is safer than the card's cycle.
                    later_installment = int(meta.get("installmentNumber") or 1) >= 2
                    forecast = _month(meta.get("billForecastDate"))
                    cycle = open_bill(str(meta.get("billPostDate") or tx_date))
                    bill_month = bill_by_id.get(meta.get("billId") or "") or (
                        (forecast or cycle) if later_installment else (cycle or forecast)
                    )
                description = re.sub(r"\s+", " ", t.get("description") or t.get("descriptionRaw") or "").strip()
                cents = int(round(abs(float(t.get("amount") or 0)) * 100))
                outgoing = (t.get("type") or "").upper() == "DEBIT"
                payment = _bill_payment(t, description, card, outgoing)
                # Card: purchases and refunds. Account: only debit card purchases (money coming in,
                # Pix, boletos and transfers are not spending).
                spending = bool(description and cents and not payment) and (
                    card or (outgoing and _debit_card_purchase(t, description))
                )
                if not card and outgoing and description and cents and not spending and not NOT_SPENDING.search(description):
                    left_out += 1  # Pix, boletos, transfers: told apart from bill payments and investments
                if spending and card and pending and bill_month:
                    open_bills.setdefault((source, bill_month), []).append(cents if outgoing else -cents)
                if ext_id in known_ids:
                    if not spending:
                        remove_ids.add(ext_id)  # imported by an older version (a bill payment, a Pix)
                    elif bill_month:
                        bill_updates[ext_id] = bill_month  # fixes the month once the bill closes
                    continue
                if not spending:
                    continue
                if card and not outgoing:
                    cents = -cents  # refund / credit on the card
                installment = None
                k, n = meta.get("installmentNumber"), meta.get("totalInstallments")
                if k and n and 1 <= int(k) <= int(n) and int(n) >= 2:
                    installment = f"{int(k)}/{int(n)}"
                notes = []
                purchase = str(meta.get("purchaseDate") or "")[:10]
                if purchase and purchase != tx_date:
                    notes.append(f"data da compra: {purchase}")
                payee = (t.get("merchant") or {}).get("name") or ""
                transactions.append(
                    {
                        "date": tx_date,
                        "description": description[:300],
                        "merchant": clean_merchant(payee or _DEBIT_PREFIX.sub("", description) or description)[:200],
                        "amount_cents": cents,
                        "category": _category(description, t),
                        "installment": installment,
                        "notes": " · ".join(notes),
                        "source": source,
                        "external_id": ext_id,
                        "bill_month": bill_month,
                    }
                )
    for (source, month), amounts in sorted(open_bills.items()):
        y, m = month.split("-")
        total = f"{sum(amounts) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        warnings.append(
            f"{source}: fatura aberta que vence em {m}/{y} soma R$ {total} até agora "
            f"({len(amounts)} lançamento(s)). Compare com o app do banco."
        )
    if left_out:
        warnings.append(
            f"{left_out} movimentação(ões) da conta (Pix, boletos, transferências) ficaram de fora: "
            "da conta só entram compras no cartão de débito. Aluguel e contas vão em Gastos fixos."
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
        "remove_ids": sorted(remove_ids),
        "model": "open-finance",
        "input_tokens": None,
        "output_tokens": None,
    }


# "COMPRA CARTAO DEBITO - ESTAPAR" -> "ESTAPAR"
_DEBIT_PREFIX = re.compile(
    r"^(compra\s+(no\s+|com\s+)?(cart[aã]o\s+(de\s+)?)?d[eé]bito|compra\s+(no\s+)?cart[aã]o(\s+d[eé]bito)?)\s*[-:–]?\s*",
    re.IGNORECASE,
)


def sync_since(last_sync: str | None) -> date:
    if last_sync:
        try:
            return date.fromisoformat(last_sync[:10]) - timedelta(days=OVERLAP_DAYS)
        except ValueError:
            pass
    return date.today() - timedelta(days=FIRST_SYNC_DAYS)
