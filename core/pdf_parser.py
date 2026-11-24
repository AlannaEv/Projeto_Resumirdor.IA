"""Leitura, normalizacao e metadados para documentos enviados."""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any

import pymupdf


SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}
REFERENCE_HEADING = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?(?:\d+(?:\.\d+)*[.)]?[ \t]+)?"
    r"(?:refer[eê]ncias(?:[ \t]+bibliogr[aá]ficas)?|bibliografia|"
    r"works?[ \t]+cited|references|literatura[ \t]+citada)"
    r"[ \t]*:?[ \t]*$"
)


def calculate_md5(content: bytes) -> str:
    """Calcula o MD5 do conteudo original do arquivo."""
    return hashlib.md5(content).hexdigest()


def estimate_tokens(text: str) -> int:
    """Estima tokens por aproximadamente quatro caracteres por token."""
    if not text:
        return 0
    return math.ceil(len(text) / 4)


def normalize_document_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00ad", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def remove_references(text: str) -> str:
    """Remove o conteudo da secao final de referencias, quando identificada."""
    normalized = normalize_document_text(text)
    match = REFERENCE_HEADING.search(normalized)
    if not match:
        return normalized

    preceding_text = normalized[: match.start()].rstrip()
    return preceding_text or normalized


def _extract_pdf_text(file_bytes: bytes) -> tuple[str, int]:
    try:
        with pymupdf.open(stream=file_bytes, filetype="pdf") as document:
            pages_count = document.page_count
            page_texts = []
            for page_number, page in enumerate(document, start=1):
                page_text = page.get_text("text")
                if page_text.strip():
                    page_texts.append(f"[Pagina {page_number}]\n{page_text}")
    except Exception as exc:
        raise ValueError(f"Nao foi possivel ler o PDF: {exc}") from exc

    text = normalize_document_text("\n".join(page_texts))
    if not text:
        raise ValueError(
            "Nao foi possivel extrair texto deste PDF. "
            "Ele pode conter apenas imagens ou estar protegido."
        )
    return text, pages_count


def extract_text_from_file(
    file_bytes: bytes,
    filename: str,
    strip_refs: bool = False,
) -> dict[str, Any]:
    """Extrai texto e retorna contagens, hash e identificacao do arquivo."""
    if not file_bytes:
        raise ValueError("O arquivo enviado esta vazio.")
    if not filename or not filename.strip():
        raise ValueError("O nome do arquivo esta vazio.")

    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError("Formato nao suportado. Envie um arquivo PDF, TXT ou MD.")

    if extension == ".pdf":
        text, pages_count = _extract_pdf_text(file_bytes)
    else:
        try:
            decoded_text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError(
                "O arquivo de texto nao esta codificado em UTF-8."
            ) from exc
        text = normalize_document_text(decoded_text)
        pages_count = 1 if text else 0

    if strip_refs:
        text = remove_references(text)
    if not text:
        raise ValueError("Nenhum texto util foi encontrado no arquivo.")

    return {
        "text": text,
        "char_count": len(text),
        "token_count": estimate_tokens(text),
        "pages_count": pages_count,
        "hash": calculate_md5(file_bytes),
        "filename": filename,
    }
