"""API REST para extracao e analise de documentos."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import asynccontextmanager
from typing import Any, Iterator, Literal

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from google.genai import errors
from pydantic import BaseModel, Field

from core.database import (
    add_message,
    add_messages,
    create_chat,
    delete_chat,
    get_all_chats,
    get_chat_history,
    get_document,
    init_db,
    save_document,
    set_chat_document_hash,
    update_chat_title,
)
from core.pdf_parser import (
    calculate_md5,
    estimate_tokens,
    extract_text_from_file,
    normalize_document_text,
    remove_references,
)
from core.summarizer import (
    RATE_LIMIT_MESSAGE,
    generate_chat_title,
    stream_document_analysis,
    validate_analysis_request,
)


logger = logging.getLogger(__name__)
DOCUMENT_CACHE: dict[str, str] = {}
DOCUMENT_METADATA_CACHE: dict[str, dict[str, Any]] = {}
DEFAULT_CHAT_TITLE = "Nova conversa"
RATE_LIMIT_STREAM_MESSAGE = RATE_LIMIT_MESSAGE


def _is_rate_limit_error(error: Exception) -> bool:
    error_text = str(error).upper()
    response = getattr(error, "response", None)
    status_code = getattr(error, "status_code", None) or getattr(
        response,
        "status_code",
        None,
    )
    return (
        getattr(error, "code", None) == 429
        or status_code == 429
        or getattr(error, "status", None) == "RESOURCE_EXHAUSTED"
        or "429" in error_text
        or "RESOURCE_EXHAUSTED" in error_text
    )


def _rate_limit_message_stream() -> Iterator[str]:
    yield RATE_LIMIT_STREAM_MESSAGE


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="ResumeAI API",
    version="3.0.0",
    description="Extracao e analise streaming de documentos.",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"status": "ok", "message": "ResumeAI API is online"}


class AnalyzeRequest(BaseModel):
    document_hash: str = Field(min_length=1)
    query_or_preset: str = Field(min_length=1)
    is_preset: bool = False
    chat_id: int | None = Field(default=None, gt=0)
    user_message: str | None = None


class AnalyzeDirectRequest(BaseModel):
    text: str = Field(min_length=1)
    query_or_preset: str = Field(min_length=1)
    is_preset: bool = False
    strip_refs: bool = False
    chat_id: int | None = Field(default=None, gt=0)
    user_message: str | None = None


class CreateChatRequest(BaseModel):
    title: str | None = Field(default=DEFAULT_CHAT_TITLE, max_length=120)
    first_message: str | None = None
    document_hash: str | None = None


class AddMessageRequest(BaseModel):
    role: Literal["user", "assistant"]
    content: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _generate_and_store_chat_title(chat_id: int, first_message: str) -> None:
    try:
        title = generate_chat_title(first_message)
    except Exception as exc:
        logger.warning(
            "[Auto-title] Falha ao gerar título via LLM (Rate limit/429): %s",
            exc,
        )
        title = (
            f"{first_message[:30]}..."
            if len(first_message) > 30
            else first_message
        )
    try:
        update_chat_title(chat_id, title)
    except LookupError:
        logger.info("Conversa %s removida antes da atualizacao do titulo.", chat_id)


@app.get("/api/chats")
async def list_chats() -> list[dict[str, Any]]:
    return get_all_chats()


@app.post("/api/chats", status_code=201)
async def create_new_chat(
    payload: CreateChatRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    document_hash = payload.document_hash
    if document_hash and get_document(document_hash) is None:
        raise HTTPException(status_code=404, detail="Documento nao encontrado.")
    requested_title = (payload.title or "").strip()
    should_generate_title = requested_title in {"", DEFAULT_CHAT_TITLE}
    first_message = (payload.first_message or "").strip()
    initial_title = (
        " ".join(first_message.split())[:30]
        if should_generate_title and first_message
        else requested_title or DEFAULT_CHAT_TITLE
    )
    chat_id = create_chat(
        title=initial_title,
        document_hash=document_hash,
    )
    if should_generate_title and first_message:
        background_tasks.add_task(
            _generate_and_store_chat_title,
            chat_id,
            first_message,
        )
    chat = get_chat_history(chat_id)
    return {
        "id": chat_id,
        "title": chat["title"] if chat else initial_title,
        "created_at": chat["created_at"] if chat else None,
    }


@app.get("/api/chats/{chat_id}")
async def read_chat(chat_id: int) -> dict[str, Any]:
    chat = get_chat_history(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Conversa nao encontrada.")

    document_hash = chat.get("document_hash")
    document = get_document(document_hash) if document_hash else None
    chat["document"] = (
        {
            "hash": document["hash"],
            "filename": document["filename"],
            "char_count": document["char_count"],
            "token_count": document["token_count"],
            "pages_count": document["pages_count"],
        }
        if document
        else None
    )
    if document:
        DOCUMENT_CACHE[document_hash] = document["text"]
        DOCUMENT_METADATA_CACHE[document_hash] = chat["document"]
    return chat


@app.delete("/api/chats/{chat_id}", status_code=204)
async def remove_chat(chat_id: int) -> None:
    chat = get_chat_history(chat_id)
    if not delete_chat(chat_id):
        raise HTTPException(status_code=404, detail="Conversa nao encontrada.")
    if chat and chat.get("document_hash"):
        document_hash = chat["document_hash"]
        if get_document(document_hash) is None:
            DOCUMENT_CACHE.pop(document_hash, None)
            DOCUMENT_METADATA_CACHE.pop(document_hash, None)


@app.post("/api/chats/{chat_id}/messages", status_code=201)
async def save_chat_message(
    chat_id: int,
    payload: AddMessageRequest,
) -> dict[str, str]:
    try:
        add_message(chat_id, payload.role, payload.content)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok"}


@app.post("/api/upload")
async def upload_document(
    file: UploadFile = File(...),
    strip_refs: bool = Form(False),
) -> dict[str, Any]:
    file_bytes = await file.read()
    try:
        metadata = extract_text_from_file(
            file_bytes=file_bytes,
            filename=file.filename or "",
            strip_refs=strip_refs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()

    DOCUMENT_CACHE[metadata["hash"]] = metadata["text"]
    document_metadata = {
        "hash": metadata["hash"],
        "filename": metadata["filename"],
        "char_count": metadata["char_count"],
        "token_count": metadata["token_count"],
        "pages_count": metadata["pages_count"],
    }
    DOCUMENT_METADATA_CACHE[metadata["hash"]] = document_metadata
    save_document(
        document_hash=metadata["hash"],
        text=metadata["text"],
        filename=metadata["filename"],
        char_count=metadata["char_count"],
        token_count=metadata["token_count"],
        pages_count=metadata["pages_count"],
    )
    return metadata


def _stream_analysis(
    document_text: str,
    query_or_preset: str,
    is_preset: bool,
    chat_id: int | None = None,
    user_message: str | None = None,
) -> StreamingResponse:
    if not document_text.strip():
        raise HTTPException(status_code=400, detail="O documento nao contem texto.")
    if chat_id is not None and get_chat_history(chat_id) is None:
        raise HTTPException(status_code=404, detail="Conversa nao encontrada.")
    try:
        validate_analysis_request(query_or_preset, is_preset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except errors.APIError as exc:
        if not _is_rate_limit_error(exc):
            logger.exception("Falha ao validar a requisicao para o Gemini.")
            raise HTTPException(
                status_code=502,
                detail="Falha ao iniciar a analise com o Gemini.",
            ) from exc
        logger.warning(
            "[LLM] Limite de requisicoes durante a validacao inicial: %s",
            exc,
        )
        preflight_rate_limited = True
    except Exception as exc:
        if not _is_rate_limit_error(exc):
            raise
        logger.warning(
            "[LLM] Limite de requisicoes durante a validacao inicial: %s",
            exc,
        )
        preflight_rate_limited = True
    else:
        preflight_rate_limited = False

    def generate_and_persist() -> Iterator[str]:
        response_chunks: list[str] = []
        try:
            if preflight_rate_limited:
                response_chunks.append(RATE_LIMIT_STREAM_MESSAGE)
                yield RATE_LIMIT_STREAM_MESSAGE
            else:
                for chunk in stream_document_analysis(
                    document_text=document_text,
                    prompt_or_preset=query_or_preset,
                    is_preset=is_preset,
                ):
                    response_chunks.append(chunk)
                    yield chunk
        except errors.APIError as exc:
            if not _is_rate_limit_error(exc):
                raise
            logger.warning("[LLM] Limite de requisicoes durante o stream: %s", exc)
            response_chunks.append(RATE_LIMIT_STREAM_MESSAGE)
            yield RATE_LIMIT_STREAM_MESSAGE
        except Exception as exc:
            if not _is_rate_limit_error(exc):
                raise
            logger.warning("[LLM] Limite de requisicoes durante o stream: %s", exc)
            response_chunks.append(RATE_LIMIT_STREAM_MESSAGE)
            yield RATE_LIMIT_STREAM_MESSAGE

        if chat_id is not None:
            try:
                add_messages(
                    chat_id,
                    [
                        ("user", user_message or query_or_preset),
                        ("assistant", "".join(response_chunks)),
                    ],
                )
            except (LookupError, sqlite3.Error) as exc:
                logger.exception("Falha ao salvar o historico do chat %s.", chat_id)
                raise RuntimeError(
                    "A resposta foi gerada, mas nao foi possivel salvar o historico."
                ) from exc

    return StreamingResponse(
        generate_and_persist(),
        media_type="text/plain",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.post("/api/analyze")
async def analyze_document(payload: AnalyzeRequest) -> StreamingResponse:
    document_text = DOCUMENT_CACHE.get(payload.document_hash)
    if document_text is None:
        document = get_document(payload.document_hash)
        if document is None:
            raise HTTPException(
                status_code=404,
                detail="Documento nao encontrado. Envie o arquivo novamente.",
            )
        document_text = document["text"]
        DOCUMENT_CACHE[payload.document_hash] = document_text
        DOCUMENT_METADATA_CACHE[payload.document_hash] = {
            key: document[key]
            for key in (
                "hash",
                "filename",
                "char_count",
                "token_count",
                "pages_count",
            )
        }

    return _stream_analysis(
        document_text,
        payload.query_or_preset,
        payload.is_preset,
        payload.chat_id,
        payload.user_message,
    )


@app.post("/api/analyze-direct")
async def analyze_direct(payload: AnalyzeDirectRequest) -> StreamingResponse:
    text = normalize_document_text(payload.text)
    if payload.strip_refs:
        text = remove_references(text)
    try:
        validate_analysis_request(payload.query_or_preset, payload.is_preset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except errors.APIError as exc:
        if _is_rate_limit_error(exc):
            logger.warning(
                "[LLM] Limite de requisicoes durante a validacao de texto direto: %s",
                exc,
            )
            return StreamingResponse(
                _rate_limit_message_stream(),
                media_type="text/plain",
                headers={"X-Content-Type-Options": "nosniff"},
            )
        logger.exception("Falha ao validar a requisicao para o Gemini.")
        raise HTTPException(
            status_code=502,
            detail="Falha ao iniciar a analise com o Gemini.",
        ) from exc
    except Exception as exc:
        if not _is_rate_limit_error(exc):
            raise
        logger.warning(
            "[LLM] Limite de requisicoes durante a validacao de texto direto: %s",
            exc,
        )
        return StreamingResponse(
            _rate_limit_message_stream(),
            media_type="text/plain",
            headers={"X-Content-Type-Options": "nosniff"},
        )
    if payload.chat_id is not None:
        if get_chat_history(payload.chat_id) is None:
            raise HTTPException(status_code=404, detail="Conversa nao encontrada.")
        document_hash = calculate_md5(text.encode("utf-8"))
        document_metadata = {
            "hash": document_hash,
            "filename": "Texto colado",
            "char_count": len(text),
            "token_count": estimate_tokens(text),
            "pages_count": 1 if text else 0,
        }
        save_document(
            document_hash=document_hash,
            text=text,
            filename=document_metadata["filename"],
            char_count=document_metadata["char_count"],
            token_count=document_metadata["token_count"],
            pages_count=document_metadata["pages_count"],
        )
        set_chat_document_hash(payload.chat_id, document_hash)
        DOCUMENT_CACHE[document_hash] = text
        DOCUMENT_METADATA_CACHE[document_hash] = document_metadata
    return _stream_analysis(
        text,
        payload.query_or_preset,
        payload.is_preset,
        payload.chat_id,
        payload.user_message,
    )
