"""Turn uploaded files into content blocks the Claude API accepts.

PDFs are sent as-is (decrypted first when the bank protected them with a
password). Photos are converted to JPEG and downscaled, which also covers
iPhone HEIC pictures.
"""

import base64
import io
from dataclasses import dataclass

from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # HEIC support is optional
    pass

MAX_IMAGE_EDGE = 2576
MAX_IMAGE_BYTES = 4_500_000


class DocumentError(Exception):
    """A problem the user can fix (wrong password, unsupported file...)."""


@dataclass
class Upload:
    filename: str
    content_type: str
    data: bytes


def _is_pdf(upload: Upload) -> bool:
    return upload.data[:5] == b"%PDF-" or upload.filename.lower().endswith(".pdf")


def _decrypt_pdf(upload: Upload, password: str) -> bytes:
    try:
        reader = PdfReader(io.BytesIO(upload.data))
    except Exception as exc:
        raise DocumentError(f"Não consegui abrir o PDF '{upload.filename}'.") from exc
    if not reader.is_encrypted:
        return upload.data
    if not reader.decrypt(password or ""):
        if password:
            raise DocumentError(f"Senha incorreta para o PDF '{upload.filename}'.")
        raise DocumentError(
            f"O PDF '{upload.filename}' é protegido por senha. "
            "Preencha o campo de senha (normalmente são dígitos do CPF do titular)."
        )
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _normalize_image(upload: Upload) -> bytes:
    try:
        img = Image.open(io.BytesIO(upload.data))
        img = ImageOps.exif_transpose(img)
    except Exception as exc:
        raise DocumentError(
            f"Formato não suportado em '{upload.filename}'. Envie PDF, JPG, PNG, WEBP ou HEIC."
        ) from exc
    img = img.convert("RGB")
    img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    quality = 90
    while True:
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality)
        if out.tell() <= MAX_IMAGE_BYTES or quality <= 50:
            return out.getvalue()
        quality -= 10


def to_content_blocks(uploads: list[Upload], password: str = "") -> list[dict]:
    blocks = []
    for upload in uploads:
        if _is_pdf(upload):
            data = _decrypt_pdf(upload, password)
            blocks.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.standard_b64encode(data).decode(),
                    },
                }
            )
        else:
            data = _normalize_image(upload)
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.standard_b64encode(data).decode(),
                    },
                }
            )
    return blocks
