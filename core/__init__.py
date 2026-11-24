"""Nucleo da aplicacao de resumo documental."""

from .pdf_parser import (
    calculate_md5,
    estimate_tokens,
    extract_text_from_file,
    normalize_document_text,
    remove_references,
)
from .summarizer import (
    MODEL_NAME,
    PRESETS,
    SYSTEM_INSTRUCTION_GROUNDING,
    stream_document_analysis,
)

__all__ = [
    "calculate_md5",
    "estimate_tokens",
    "extract_text_from_file",
    "normalize_document_text",
    "remove_references",
    "MODEL_NAME",
    "PRESETS",
    "SYSTEM_INSTRUCTION_GROUNDING",
    "stream_document_analysis",
]
