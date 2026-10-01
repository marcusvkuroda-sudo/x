import base64
import csv
import hashlib
import io
import json
import os
import re
import secrets
import shutil
from contextlib import asynccontextmanager
from datetime import date as Date
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import config, db, documents, extractor, rules
from .categories import CATEGORIES, CATEGORY_KEYS

CategoryKey = Literal[tuple(CATEGORY_KEYS)]  # type: ignore[valid-type]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init()
    db.backup_daily()
    # Extractions interrupted by a restart will never finish.
    with db.session() as conn:
        conn.execute(
            "UPDATE imports SET status = 'error', error = 'Leitura interrompida. Envie novamente.' "
            "WHERE status = 'processing'"
        )
    yield


app = FastAPI(title="Nossos Gastos", lifespan=lifespan)


@app.middleware("http")
async def password_guard(request: Request, call_next):
    if not config.APP_PASSWORD:
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            _, _, password = base64.b64decode(header[6:]).decode().partition(":")
            if secrets.compare_digest(password, config.APP_PASSWORD):
                return await call_next(request)
        except ValueError:
            pass
    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Nossos Gastos"'})


# ---------------------------------------------------------------- models


class TransactionIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date: Date
    description: str = Field(min_length=1, max_length=300)
    merchant: str = Field(default="", max_length=200)
    amount_cents: int
    category: CategoryKey = "outros"
    source: str = Field(default="", max_length=100)
    installment: str | None = None
    notes: str = Field(default="", max_length=500)

    @field_validator("amount_cents")
    @classmethod
    def non_zero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("O valor não pode ser zero.")
        return v

    @field_validator("installment")
    @classmethod
    def installment_format(cls, v: str | None) -> str | None:
        if not v:
            return None
        m = re.fullmatch(r"0*(\d+)\s*/\s*0*(\d+)", v)
        if not m:
            raise ValueError("Parcela deve estar no formato 3/10.")
        k, n = int(m.group(1)), int(m.group(2))
        if n < 2:
            return None
        if not 1 <= k <= n:
            raise ValueError("Parcela inválida: o número da parcela deve ficar entre 1 e o total.")
        return f"{k}/{n}"


class ImportTransactionIn(TransactionIn):
    # True when the couple changed the category Claude suggested: remember it.
    remember: bool = False


class ImportConfirm(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source: str = Field(default="", max_length=100)
    transactions: list[ImportTransactionIn]


def _row(r) -> dict:
    return dict(r) if r is not None else None


def _insert_transaction(conn, t: TransactionIn, origin: str, import_id: int | None = None) -> int:
    cur = conn.execute(
        """INSERT INTO transactions
           (date, description, merchant, amount_cents, category, source, installment, notes, origin, import_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            t.date.isoformat(),
            t.description.strip(),
            t.merchant.strip(),
            t.amount_cents,
            t.category,
            t.source.strip(),
            t.installment,
            t.notes.strip(),
            origin,
            import_id,
        ),
    )
    return cur.lastrowid


# ---------------------------------------------------------------- meta


@app.get("/api/meta")
def meta():
    with db.session() as conn:
        sources = [
            r[0]
            for r in conn.execute(
                "SELECT source FROM transactions WHERE source != '' GROUP BY source ORDER BY COUNT(*) DESC"
            )
        ]
    return {
        "categories": CATEGORIES,
        "sources": sources,
        "model": config.CLAUDE_MODEL,
        "api_key_configured": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
    }


# ---------------------------------------------------------------- transactions


@app.get("/api/transactions")
def list_transactions():
    with db.session() as conn:
        rows = conn.execute("SELECT * FROM transactions ORDER BY date DESC, id DESC").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/transactions", status_code=201)
def create_transaction(t: TransactionIn):
    with db.session() as conn:
        new_id = _insert_transaction(conn, t, "manual")
        return _row(conn.execute("SELECT * FROM transactions WHERE id = ?", (new_id,)).fetchone())


@app.put("/api/transactions/{tx_id}")
def update_transaction(tx_id: int, t: TransactionIn, apply_to_similar: bool = False):
    if apply_to_similar:
        db.backup_daily()
    with db.session() as conn:
        old = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
        if not old:
            raise HTTPException(404, "Lançamento não encontrado.")
        conn.execute(
            """UPDATE transactions SET date = ?, description = ?, merchant = ?, amount_cents = ?,
               category = ?, source = ?, installment = ?, notes = ? WHERE id = ?""",
            (
                t.date.isoformat(),
                t.description,
                t.merchant,
                t.amount_cents,
                t.category,
                t.source,
                t.installment,
                t.notes,
                tx_id,
            ),
        )
        updated_similar = 0
        if old["category"] != t.category:
            # A correction: remember it for future statements.
            rules.learn(conn, t.description, t.merchant, t.category)
            if apply_to_similar:
                for r in rules.similar(conn, old["description"], old["merchant"], tx_id):
                    if r["category"] != t.category:
                        conn.execute("UPDATE transactions SET category = ? WHERE id = ?", (t.category, r["id"]))
                        updated_similar += 1
        row = _row(conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone())
    return {**row, "updated_similar": updated_similar}


@app.get("/api/transactions/{tx_id}/similar")
def similar_transactions(tx_id: int):
    """Other transactions from the same place, for "apply to all" when recategorizing."""
    with db.session() as conn:
        tx = conn.execute("SELECT description, merchant FROM transactions WHERE id = ?", (tx_id,)).fetchone()
        if not tx:
            raise HTTPException(404, "Lançamento não encontrado.")
        found = rules.similar(conn, tx["description"], tx["merchant"], tx_id)
    return {"similar": [{"id": r["id"], "category": r["category"]} for r in found]}


@app.delete("/api/transactions/{tx_id}", status_code=204)
def delete_transaction(tx_id: int):
    with db.session() as conn:
        if conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,)).rowcount == 0:
            raise HTTPException(404, "Lançamento não encontrado.")


@app.get("/api/export.csv")
def export_csv():
    labels = {c["key"]: c["label"] for c in CATEGORIES}
    with db.session() as conn:
        rows = conn.execute("SELECT * FROM transactions ORDER BY date, id").fetchall()
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(["data", "descricao", "estabelecimento", "valor", "categoria", "fonte", "parcela", "observacoes", "origem"])
    for r in rows:
        writer.writerow(
            [
                r["date"],
                r["description"],
                r["merchant"],
                f"{r['amount_cents'] / 100:.2f}".replace(".", ","),
                labels.get(r["category"], r["category"]),
                r["source"],
                r["installment"] or "",
                r["notes"],
                r["origin"],
            ]
        )
    return Response(
        "﻿" + out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="nossos-gastos.csv"'},
    )


# ---------------------------------------------------------------- imports


def _import_summary(r) -> dict:
    d = dict(r)
    extracted = json.loads(d.pop("extracted_json") or "null")
    d["filenames"] = json.loads(d["filenames"])
    d["transaction_count"] = len(extracted["transactions"]) if extracted else 0
    d["warnings"] = extracted["warnings"] if extracted else []
    pricing = config.PRICING.get(d.get("model") or "")
    if pricing and d.get("input_tokens") is not None:
        d["cost_usd"] = round(
            d["input_tokens"] / 1e6 * pricing[0] + d["output_tokens"] / 1e6 * pricing[1], 4
        )
    else:
        d["cost_usd"] = None
    return d


def _run_extraction(import_id: int, uploads: list[documents.Upload], password: str) -> None:
    try:
        blocks = documents.to_content_blocks(uploads, password)
        result = extractor.extract(blocks, [u.filename for u in uploads])
    except (documents.DocumentError, extractor.ExtractionError) as exc:
        message = str(exc)
    except Exception as exc:  # keep the import visible instead of stuck in "processing"
        message = f"Erro inesperado: {exc}"
    else:
        with db.session() as conn:
            # Categories the couple corrected before win over Claude's guess.
            for t in result["transactions"]:
                remembered = rules.lookup(conn, t["description"], t["merchant"])
                t["category_source"] = "rule" if remembered else "claude"
                if remembered:
                    t["category"] = remembered
            conn.execute(
                """UPDATE imports SET status = 'review', issuer = ?, reference_month = ?, due_date = ?,
                   statement_total_cents = ?, extracted_json = ?, input_tokens = ?, output_tokens = ?, model = ?
                   WHERE id = ?""",
                (
                    result["issuer"],
                    result["reference_month"],
                    result["due_date"],
                    result["statement_total_cents"],
                    json.dumps(
                        {"transactions": result["transactions"], "warnings": result["warnings"],
                         "document_type": result["document_type"]},
                        ensure_ascii=False,
                    ),
                    result["input_tokens"],
                    result["output_tokens"],
                    result["model"],
                    import_id,
                ),
            )
        return
    with db.session() as conn:
        conn.execute("UPDATE imports SET status = 'error', error = ? WHERE id = ?", (message, import_id))


@app.post("/api/imports", status_code=202)
async def create_import(
    background: BackgroundTasks,
    files: list[UploadFile] = File(...),
    source: str = Form(""),
    password: str = Form(""),
):
    uploads = []
    total = 0
    for f in files:
        data = await f.read()
        if not data:
            continue
        total += len(data)
        if len(data) > 30_000_000 or total > 100_000_000:
            raise HTTPException(413, "Arquivos grandes demais. Envie a fatura em PDF ou menos fotos por vez.")
        uploads.append(documents.Upload(f.filename or "arquivo", f.content_type or "", data))
    if not uploads:
        raise HTTPException(400, "Nenhum arquivo enviado.")

    digest = hashlib.sha256()
    for u in sorted(uploads, key=lambda u: hashlib.sha256(u.data).hexdigest()):
        digest.update(hashlib.sha256(u.data).digest())
    file_hash = digest.hexdigest()

    with db.session() as conn:
        existing = conn.execute(
            "SELECT id, status FROM imports WHERE file_hash = ? AND status != 'error' ORDER BY id DESC",
            (file_hash,),
        ).fetchone()
        if existing:
            raise HTTPException(
                409,
                {
                    "message": "Este documento já foi enviado"
                    + (" e importado." if existing["status"] == "confirmed" else " e está aguardando revisão."),
                    "import_id": existing["id"],
                },
            )
        cur = conn.execute(
            "INSERT INTO imports (filenames, file_hash, source, status, model) VALUES (?, ?, ?, 'processing', ?)",
            (json.dumps([u.filename for u in uploads], ensure_ascii=False), file_hash, source.strip(), config.CLAUDE_MODEL),
        )
        import_id = cur.lastrowid

    folder = config.UPLOAD_DIR / str(import_id)
    folder.mkdir(parents=True, exist_ok=True)
    for i, u in enumerate(uploads):
        safe = re.sub(r"[^\w.\-]+", "_", u.filename)[-80:] or "arquivo"
        (folder / f"{i + 1:02d}_{safe}").write_bytes(u.data)

    background.add_task(_run_extraction, import_id, uploads, password)
    return {"id": import_id, "status": "processing"}


@app.get("/api/imports")
def list_imports():
    with db.session() as conn:
        rows = conn.execute("SELECT * FROM imports ORDER BY id DESC").fetchall()
    return [_import_summary(r) for r in rows]


@app.get("/api/imports/{import_id}")
def get_import(import_id: int):
    with db.session() as conn:
        row = conn.execute("SELECT * FROM imports WHERE id = ?", (import_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Importação não encontrada.")
        detail = _import_summary(row)
        extracted = json.loads(row["extracted_json"] or "null")
        txs = extracted["transactions"] if extracted else []
        for t in txs:
            # Same day and value already recorded (outside this import) -> probable duplicate.
            dup = conn.execute(
                """SELECT description FROM transactions
                   WHERE date = ? AND amount_cents = ? AND (import_id IS NULL OR import_id != ?) LIMIT 1""",
                (t["date"], t["amount_cents"], import_id),
            ).fetchone()
            t["possible_duplicate"] = dup["description"] if dup else None
        detail["transactions"] = txs
        detail["document_type"] = extracted.get("document_type") if extracted else None
    return detail


@app.post("/api/imports/{import_id}/confirm")
def confirm_import(import_id: int, body: ImportConfirm):
    with db.session() as conn:
        # Take the write lock first: if both of you confirm the same statement at the
        # same time, only one of the confirmations goes through.
        conn.execute("BEGIN IMMEDIATE")
        claimed = conn.execute(
            "UPDATE imports SET status = 'confirmed', source = ? WHERE id = ? AND status = 'review'",
            (body.source, import_id),
        ).rowcount
        if not claimed:
            if not conn.execute("SELECT 1 FROM imports WHERE id = ?", (import_id,)).fetchone():
                raise HTTPException(404, "Importação não encontrada.")
            raise HTTPException(409, "Esta fatura já foi importada (ou descartada) em outro aparelho.")
        for t in body.transactions:
            if not t.source:
                t.source = body.source
            _insert_transaction(conn, t, "import", import_id)
            if t.remember:
                rules.learn(conn, t.description, t.merchant, t.category)
    return {"imported": len(body.transactions)}


@app.delete("/api/imports/{import_id}", status_code=204)
def delete_import(import_id: int):
    db.backup_daily()
    with db.session() as conn:
        if conn.execute("DELETE FROM imports WHERE id = ?", (import_id,)).rowcount == 0:
            raise HTTPException(404, "Importação não encontrada.")
    shutil.rmtree(config.UPLOAD_DIR / str(import_id), ignore_errors=True)


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"message": exc.detail}
    return JSONResponse(detail, status_code=exc.status_code, headers=exc.headers)


# ---------------------------------------------------------------- frontend

app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(config.STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")
