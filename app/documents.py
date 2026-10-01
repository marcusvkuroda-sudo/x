"""Turn uploaded files into content blocks the Claude API accepts.

PDFs are sent as-is (decrypted first when the bank protected them with a
password). Photos are converted to JPEG and sized to what the model can
actually see, which also covers iPhone HEIC pictures.
"""

import base64
import io
import math
from dataclasses import dataclass

from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # HEIC support is optional
    pass

# Claude 4.7+ models see images up to 2576 px on the long edge and 4784 patches of
# 28x28 px; anything bigger is downscaled by the API, so we do it before uploading.
MAX_IMAGE_EDGE = 2576
MAX_PATCHES = 4784
PATCH = 28
# Requests with more than 20 images get a stricter per-image limit.
MANY_IMAGES = 20
MANY_IMAGES_EDGE = 2000
MAX_IMAGE_BYTES = 5_000_000
# The API accepts requests up to 32 MB; leave room for the prompt.
MAX_PAYLOAD_BASE64 = 30_000_000
# A card statement has a handful of pages; a much bigger document is probably a mistake
# (and would make the reading slow and expensive).
MAX_PAGES = 50


class DocumentError(Exception):
    """A problem the user can fix (wrong password, unsupported file...)."""


@dataclass
class Upload:
    filename: str
    content_type: str
    data: bytes


def _is_pdf(upload: Upload) -> bool:
    return upload.data[:5] == b"%PDF-" or upload.filename.lower().endswith(".pdf")


def _read_pdf(upload: Upload, password: str) -> tuple[bytes, int]:
    """Returns the PDF bytes (decrypted when needed) and its page count."""
    try:
        reader = PdfReader(io.BytesIO(upload.data))
        if reader.is_encrypted and not reader.decrypt(password or ""):
            if password:
                raise DocumentError(f"Senha incorreta para o PDF '{upload.filename}'.")
            raise DocumentError(
                f"O PDF '{upload.filename}' é protegido por senha. "
                "Preencha o campo de senha (normalmente são dígitos do CPF do titular)."
            )
        pages = len(reader.pages)
        if not reader.is_encrypted:
            return upload.data, pages
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue(), pages
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError(f"Não consegui abrir o PDF '{upload.filename}'. Ele pode estar corrompido.") from exc


def _fit(width: int, height: int, max_edge: int) -> tuple[int, int]:
    scale = min(1.0, max_edge / max(width, height), math.sqrt(MAX_PATCHES * PATCH * PATCH / (width * height)))
    while True:
        w, h = max(1, int(width * scale)), max(1, int(height * scale))
        if math.ceil(w / PATCH) * math.ceil(h / PATCH) <= MAX_PATCHES:
            return w, h
        scale *= 0.99


def _normalize_image(upload: Upload, max_edge: int) -> bytes:
    try:
        img = Image.open(io.BytesIO(upload.data))
        img = ImageOps.exif_transpose(img)
    except Exception as exc:
        raise DocumentError(
            f"Formato não suportado em '{upload.filename}'. Envie PDF, JPG, PNG, WEBP ou HEIC."
        ) from exc
    img = img.convert("RGB")
    size = _fit(*img.size, max_edge)
    if size != img.size:
        img = img.resize(size, Image.Resampling.LANCZOS)
    quality = 90
    while True:
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality)
        if out.tell() <= MAX_IMAGE_BYTES or quality <= 60:
            return out.getvalue()
        quality -= 10


def to_content_blocks(uploads: list[Upload], password: str = "") -> list[dict]:
    images = sum(1 for u in uploads if not _is_pdf(u))
    max_edge = MANY_IMAGES_EDGE if images > MANY_IMAGES else MAX_IMAGE_EDGE
    blocks = []
    pages = 0
    payload = 0
    for i, upload in enumerate(uploads, start=1):
        if len(uploads) > 1:
            blocks.append({"type": "text", "text": f"Arquivo {i} de {len(uploads)} ({upload.filename}):"})
        if _is_pdf(upload):
            data, n = _read_pdf(upload, password)
            pages += n
            block_type, media_type = "document", "application/pdf"
        else:
            data = _normalize_image(upload, max_edge)
            pages += 1
            block_type, media_type = "image", "image/jpeg"
        encoded = base64.standard_b64encode(data).decode()
        payload += len(encoded)
        blocks.append({"type": block_type, "source": {"type": "base64", "media_type": media_type, "data": encoded}})

    if pages > MAX_PAGES:
        raise DocumentError(
            f"São {pages} páginas no total. Envie só as páginas da fatura (até {MAX_PAGES} por vez)."
        )
    if payload > MAX_PAYLOAD_BASE64:
        raise DocumentError(
            "Os arquivos ficaram grandes demais para uma leitura só. Envie menos páginas por vez "
            "ou um PDF menor."
        )
    return blocks
