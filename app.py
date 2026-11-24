"""Interface Streamlit desacoplada do backend FastAPI."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from typing import Any

import requests
import streamlit as st
from dotenv import load_dotenv

from core.summarizer import PRESETS


load_dotenv()
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8001").rstrip("/")
PRESET_OPTIONS = ["Consulta livre", *PRESETS.keys()]

st.set_page_config(
    page_title="ResumeAI",
    page_icon=":books:",
    layout="wide",
)


def _init_state() -> None:
    defaults: dict[str, Any] = {
        "document_hash": "",
        "document_metadata": None,
        "direct_text": "",
        "messages": [],
        "active_chat_id": None,
        "active_chat_title": "",
        "active_chat_created_at": "",
        "strip_refs": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _api_error(response: requests.Response) -> str:
    try:
        detail = response.json().get("detail")
        if detail:
            return str(detail)
    except ValueError:
        pass
    return response.text.strip() or f"Erro da API (HTTP {response.status_code})."


def api_request(method: str, endpoint: str, **kwargs: Any) -> Any:
    try:
        response = requests.request(
            method,
            f"{API_BASE_URL}{endpoint}",
            timeout=30,
            **kwargs,
        )
    except requests.exceptions.Timeout as exc:
        raise RuntimeError("A API demorou demais para responder.") from exc
    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError(
            "Nao foi possivel conectar a API. Confirme se o servidor FastAPI "
            "esta em execucao."
        ) from exc

    if not response.ok:
        raise RuntimeError(_api_error(response))
    if response.status_code == 204:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("A API retornou uma resposta invalida.") from exc


def _export_markdown(
    title: str,
    created_at: str,
    messages: list[dict[str, Any]],
) -> str:
    sections = [
        f"# Fichamento / Análise - {title}",
        f"*Data de criação: {created_at}*",
        "",
        "---",
        "",
    ]
    for message in messages:
        if message["role"] == "user":
            sections.extend(
                ["### 👤 Pergunta / Solicitação", message["content"], ""]
            )
        else:
            sections.extend(
                ["### 🤖 Análise Resumida", message["content"], ""]
            )
    return "\n".join(sections).rstrip() + "\n"


def _export_text(
    title: str,
    created_at: str,
    messages: list[dict[str, Any]],
) -> str:
    sections = [
        f"Fichamento / Análise - {title}",
        f"Data de criação: {created_at}",
        "=" * 60,
        "",
    ]
    for message in messages:
        label = (
            "Pergunta / Solicitação"
            if message["role"] == "user"
            else "Análise Resumida"
        )
        sections.extend([f"{label}:", message["content"], "", "-" * 60, ""])
    return "\n".join(sections).rstrip() + "\n"


def _safe_filename(title: str, chat_id: int, extension: str) -> str:
    filename = re.sub(r'[<>:"/\\|?*]+', "_", title).strip(" .")
    return f"{filename or f'conversa_{chat_id}'}.{extension}"


def upload_document(uploaded_file: Any) -> dict[str, Any]:
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/upload",
            files={
                "file": (
                    uploaded_file.name,
                    uploaded_file.getvalue(),
                    uploaded_file.type or "application/octet-stream",
                )
            },
            data={"strip_refs": str(st.session_state.strip_refs).lower()},
            timeout=300,
        )
    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError(
            "Nao foi possivel conectar a API. Confirme se o servidor FastAPI "
            "esta em execucao."
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise RuntimeError("A API demorou demais para processar o arquivo.") from exc

    if not response.ok:
        raise RuntimeError(_api_error(response))
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("A API retornou uma resposta de upload invalida.") from exc


def stream_analysis(
    endpoint: str,
    payload: dict[str, Any],
) -> Iterator[str]:
    """Solicita analise HTTP e entrega cada fragmento ao st.write_stream."""
    try:
        response = requests.post(
            f"{API_BASE_URL}{endpoint}",
            json=payload,
            stream=True,
            timeout=(10, 300),
        )
    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError(
            "Nao foi possivel conectar a API. Confirme se o servidor FastAPI "
            "esta em execucao."
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise RuntimeError("A API demorou demais para iniciar a analise.") from exc

    with response:
        if response.status_code == 429:
            yield (
                "⚠️ **Limite de requisições atingido (HTTP 429):** A cota da "
                "API do Gemini foi temporariamente excedida. Por favor, "
                "aguarda 30 a 60 segundos antes de tentar novamente."
            )
            return
        elif response.status_code != 200:
            yield f"❌ **Erro na API ({response.status_code}):** {response.text}"
            return

        response.encoding = "utf-8"
        try:
            for chunk in response.iter_content(
                chunk_size=None,
                decode_unicode=True,
            ):
                if chunk:
                    yield chunk
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(
                "A conexao foi interrompida durante a resposta da API."
            ) from exc


_init_state()

with st.sidebar:
    if st.session_state.active_chat_id is not None:
        try:
            active_chat = api_request(
                "GET",
                f"/api/chats/{st.session_state.active_chat_id}",
            )
        except RuntimeError as exc:
            st.warning(f"Nao foi possivel atualizar os dados da conversa: {exc}")
        else:
            st.session_state.active_chat_title = active_chat["title"]
            st.session_state.active_chat_created_at = active_chat["created_at"]

    if st.button("➕ Novo Chat", use_container_width=True):
        st.session_state.active_chat_id = None
        st.session_state.active_chat_title = ""
        st.session_state.active_chat_created_at = ""
        st.session_state.document_hash = ""
        st.session_state.document_metadata = None
        st.session_state.direct_text = ""
        st.session_state.messages = []
        st.rerun()

    st.title("Configuracoes")
    selected_preset = st.selectbox("Modo de analise", PRESET_OPTIONS)
    st.session_state.strip_refs = st.toggle(
        "Remover secao final de referencias",
        value=st.session_state.strip_refs,
    )

    with st.expander("Ou cole um documento"):
        pasted_text = st.text_area(
            "Texto para analisar",
            height=220,
            placeholder="Cole aqui o texto completo do documento...",
        )
        if st.button("Usar texto colado", use_container_width=True):
            if not pasted_text.strip():
                st.warning("Cole o texto do documento antes de continuar.")
            else:
                st.session_state.direct_text = pasted_text
                st.session_state.document_hash = ""
                st.session_state.active_chat_id = None
                st.session_state.active_chat_title = ""
                st.session_state.active_chat_created_at = ""
                st.session_state.messages = []
                st.session_state.document_metadata = {
                    "filename": "Texto colado",
                    "char_count": len(pasted_text),
                    "token_count": len(pasted_text) // 4,
                    "pages_count": None,
                    "hash": "",
                }
                st.success("Texto pronto para consulta.")

    st.divider()
    st.subheader("Historico de Conversas")
    try:
        chat_history = api_request("GET", "/api/chats")
    except RuntimeError as exc:
        chat_history = []
        st.error(str(exc))

    if not chat_history:
        st.caption("Nenhuma conversa salva.")
    for chat in chat_history:
        chat_id = chat["id"]
        chat_columns = st.columns([0.84, 0.16], gap="small")
        with chat_columns[0]:
            if st.button(
                f"💬 {chat['title']}",
                key=f"load_chat_{chat_id}",
                use_container_width=True,
            ):
                try:
                    selected_chat = api_request("GET", f"/api/chats/{chat_id}")
                except RuntimeError as exc:
                    st.error(str(exc))
                else:
                    st.session_state.active_chat_id = selected_chat["id"]
                    st.session_state.active_chat_title = selected_chat["title"]
                    st.session_state.active_chat_created_at = selected_chat[
                        "created_at"
                    ]
                    st.session_state.messages = selected_chat["messages"]
                    st.session_state.document_hash = (
                        selected_chat.get("document_hash") or ""
                    )
                    st.session_state.document_metadata = selected_chat.get(
                        "document"
                    )
                    st.session_state.direct_text = ""
                    st.rerun()
        with chat_columns[1]:
            if st.button(
                "🗑️",
                key=f"delete_chat_{chat_id}",
                help="Excluir conversa",
                use_container_width=True,
            ):
                try:
                    api_request("DELETE", f"/api/chats/{chat_id}")
                except RuntimeError as exc:
                    st.error(str(exc))
                else:
                    if st.session_state.active_chat_id == chat_id:
                        st.session_state.active_chat_id = None
                        st.session_state.active_chat_title = ""
                        st.session_state.active_chat_created_at = ""
                        st.session_state.document_hash = ""
                        st.session_state.document_metadata = None
                        st.session_state.direct_text = ""
                        st.session_state.messages = []
                    st.rerun()

    if st.session_state.active_chat_id and st.session_state.messages:
        active_title = (
            st.session_state.active_chat_title or "Fichamento ou análise"
        )
        active_created_at = st.session_state.active_chat_created_at or "Indisponível"
        safe_base = _safe_filename(
            active_title,
            st.session_state.active_chat_id,
            "md",
        ).rsplit(".", 1)[0]
        st.divider()
        st.subheader("Exportar conversa")
        st.download_button(
            label="📥 Baixar em Markdown (.md)",
            data=_export_markdown(
                active_title,
                active_created_at,
                st.session_state.messages,
            ),
            file_name=f"{safe_base}.md",
            mime="text/markdown",
            key=f"download_markdown_{st.session_state.active_chat_id}",
            use_container_width=True,
        )
        st.download_button(
            label="📥 Baixar em Texto (.txt)",
            data=_export_text(
                active_title,
                active_created_at,
                st.session_state.messages,
            ),
            file_name=f"{safe_base}.txt",
            mime="text/plain",
            key=f"download_text_{st.session_state.active_chat_id}",
            use_container_width=True,
        )


st.title("ResumeAI")
st.caption("Analise científica e técnica baseada no documento fornecido.")

metadata = st.session_state.document_metadata
if metadata:
    page_description = (
        f" | {metadata['pages_count']} paginas"
        if metadata.get("pages_count") is not None
        else ""
    )
    st.info(
        f"Documento ativo: **{metadata['filename']}** | "
        f"{metadata['char_count']:,} caracteres | "
        f"{metadata['token_count']:,} tokens estimados"
        f"{page_description}"
    )
elif st.session_state.document_hash:
    st.warning(
        "O documento associado a esta conversa nao foi encontrado no banco."
    )
else:
    st.info("Anexe um documento PDF, TXT ou MD usando a entrada abaixo.")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

chat_input = st.chat_input(
    "Anexe um documento ou escreva sua pergunta",
    accept_file=True,
    file_type=["pdf", "txt", "md"],
)

if chat_input:
    attached_file = chat_input.files[0] if chat_input.files else None
    submitted_text = chat_input.text.strip()

    if attached_file is not None:
        try:
            with st.spinner("Enviando e extraindo o documento..."):
                metadata = upload_document(attached_file)
            st.session_state.document_hash = metadata["hash"]
            st.session_state.document_metadata = metadata
            st.session_state.direct_text = ""
            st.session_state.active_chat_id = None
            st.session_state.active_chat_title = ""
            st.session_state.active_chat_created_at = ""
            st.session_state.messages = []
            st.success(
                f"{metadata['filename']} carregado. Hash MD5: `{metadata['hash']}`"
            )
        except RuntimeError as exc:
            st.error(str(exc))
            st.stop()

    metadata = st.session_state.document_metadata
    if not metadata:
        st.warning("Envie ou cole um documento antes de solicitar uma analise.")
    elif selected_preset == "Consulta livre" and not submitted_text:
        st.warning("Digite uma pergunta sobre o documento.")
    elif selected_preset != "Consulta livre" and attached_file is None and not submitted_text:
        st.warning("Envie uma mensagem para executar o preset selecionado.")
    else:
        is_preset = selected_preset != "Consulta livre"
        analysis_task = selected_preset if is_preset else submitted_text
        title_source = submitted_text or selected_preset
        shown_user_text = (
            f"Executar preset: **{selected_preset}**"
            if is_preset
            else submitted_text
        )
        if st.session_state.active_chat_id is None:
            try:
                new_chat = api_request(
                    "POST",
                    "/api/chats",
                    json={
                        "title": "Nova conversa",
                        "first_message": title_source,
                        "document_hash": st.session_state.document_hash or None,
                    },
                )
            except RuntimeError as exc:
                st.error(f"Nao foi possivel criar a conversa: {exc}")
                st.stop()
            st.session_state.active_chat_id = new_chat["id"]
            st.session_state.active_chat_title = new_chat["title"]
            st.session_state.active_chat_created_at = new_chat["created_at"] or ""

        st.session_state.messages.append(
            {"role": "user", "content": shown_user_text}
        )
        with st.chat_message("user"):
            st.markdown(shown_user_text)

        request_payload: dict[str, Any] = {
            "query_or_preset": analysis_task,
            "is_preset": is_preset,
            "chat_id": st.session_state.active_chat_id,
            "user_message": shown_user_text,
        }
        if st.session_state.document_hash:
            endpoint = "/api/analyze"
            request_payload["document_hash"] = st.session_state.document_hash
        else:
            endpoint = "/api/analyze-direct"
            request_payload["text"] = st.session_state.direct_text
            request_payload["strip_refs"] = st.session_state.strip_refs

        with st.chat_message("assistant"):
            try:
                with st.spinner("🤖 Analisando o documento e gerando resposta..."):
                    answer = st.write_stream(
                        stream_analysis(endpoint, request_payload)
                    )
            except RuntimeError as exc:
                answer = f"Nao foi possivel concluir a analise: {exc}"
                st.error(answer)

        st.session_state.messages.append(
            {"role": "assistant", "content": answer}
        )
        try:
            updated_chat = api_request(
                "GET",
                f"/api/chats/{st.session_state.active_chat_id}",
            )
        except RuntimeError as exc:
            st.warning(
                "A resposta foi concluida, mas nao foi possivel atualizar "
                f"os metadados da conversa: {exc}"
            )
        else:
            st.session_state.active_chat_title = updated_chat["title"]
            st.session_state.active_chat_created_at = updated_chat["created_at"]
            if not st.session_state.document_hash:
                st.session_state.document_hash = (
                    updated_chat.get("document_hash") or ""
                )
                st.session_state.document_metadata = updated_chat.get("document")
                st.session_state.direct_text = ""
        st.rerun()
