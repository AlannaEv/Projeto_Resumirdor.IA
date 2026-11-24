"""Persistencia SQLite para conversas e documentos."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from dotenv import load_dotenv


load_dotenv()

_PROJECT_DB_PATH = Path(__file__).resolve().parent.parent / "chats.db"
_CONTAINER_DATA_PATH = Path("/app/data/chats.db")


def _database_path() -> Path:
    configured_path = os.getenv("DB_PATH")
    if configured_path:
        return Path(configured_path).expanduser()
    if _CONTAINER_DATA_PATH.parent.is_dir():
        return _CONTAINER_DATA_PATH
    return _PROJECT_DB_PATH


DB_PATH = _database_path()


@contextmanager
def _connection() -> Generator[sqlite3.Connection, None, None]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with _connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                hash TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                filename TEXT NOT NULL,
                char_count INTEGER NOT NULL,
                token_count INTEGER NOT NULL,
                pages_count INTEGER
            );

            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                document_hash TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            );
            """
        )


def create_chat(title: str, document_hash: str | None = None) -> int:
    normalized_title = title.strip()[:30] or "Nova conversa"
    with _connection() as connection:
        cursor = connection.execute(
            "INSERT INTO chats (title, document_hash) VALUES (?, ?)",
            (normalized_title, document_hash),
        )
        return int(cursor.lastrowid)


def update_chat_title(chat_id: int, title: str) -> None:
    normalized_title = " ".join(title.split())[:120]
    if not normalized_title:
        raise ValueError("O titulo da conversa nao pode estar vazio.")
    with _connection() as connection:
        cursor = connection.execute(
            "UPDATE chats SET title = ? WHERE id = ?",
            (normalized_title, chat_id),
        )
        if cursor.rowcount == 0:
            raise LookupError(f"Conversa {chat_id} nao encontrada.")


def get_all_chats() -> list[dict[str, Any]]:
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT id, title, document_hash, created_at
            FROM chats
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_chat_history(chat_id: int) -> dict[str, Any] | None:
    with _connection() as connection:
        chat_row = connection.execute(
            """
            SELECT id, title, document_hash, created_at
            FROM chats
            WHERE id = ?
            """,
            (chat_id,),
        ).fetchone()
        if chat_row is None:
            return None

        message_rows = connection.execute(
            """
            SELECT role, content, created_at
            FROM messages
            WHERE chat_id = ?
            ORDER BY id
            """,
            (chat_id,),
        ).fetchall()

    chat = dict(chat_row)
    chat["messages"] = [dict(row) for row in message_rows]
    return chat


def _validate_role(role: str) -> None:
    if role not in {"user", "assistant"}:
        raise ValueError("O papel da mensagem deve ser 'user' ou 'assistant'.")


def add_message(chat_id: int, role: str, content: str) -> None:
    _validate_role(role)
    add_messages(chat_id, [(role, content)])


def add_messages(chat_id: int, messages: list[tuple[str, str]]) -> None:
    for role, _ in messages:
        _validate_role(role)
    with _connection() as connection:
        chat_exists = connection.execute(
            "SELECT 1 FROM chats WHERE id = ?",
            (chat_id,),
        ).fetchone()
        if chat_exists is None:
            raise LookupError(f"Conversa {chat_id} nao encontrada.")
        connection.executemany(
            "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
            [(chat_id, role, content) for role, content in messages],
        )


def delete_chat(chat_id: int) -> bool:
    with _connection() as connection:
        row = connection.execute(
            "SELECT document_hash FROM chats WHERE id = ?",
            (chat_id,),
        ).fetchone()
        if row is None:
            return False
        document_hash = row["document_hash"]
        connection.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        if document_hash:
            other_references = connection.execute(
                "SELECT 1 FROM chats WHERE document_hash = ? LIMIT 1",
                (document_hash,),
            ).fetchone()
            if other_references is None:
                connection.execute(
                    "DELETE FROM documents WHERE hash = ?",
                    (document_hash,),
                )
        return True


def save_document(
    document_hash: str,
    text: str,
    filename: str,
    char_count: int,
    token_count: int,
    pages_count: int | None,
) -> None:
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO documents (
                hash, text, filename, char_count, token_count, pages_count
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(hash) DO UPDATE SET
                text = excluded.text,
                filename = excluded.filename,
                char_count = excluded.char_count,
                token_count = excluded.token_count,
                pages_count = excluded.pages_count
            """,
            (
                document_hash,
                text,
                filename,
                char_count,
                token_count,
                pages_count,
            ),
        )


def get_document(document_hash: str) -> dict[str, Any] | None:
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT hash, text, filename, char_count, token_count, pages_count
            FROM documents
            WHERE hash = ?
            """,
            (document_hash,),
        ).fetchone()
    return dict(row) if row is not None else None


def set_chat_document_hash(chat_id: int, document_hash: str) -> None:
    with _connection() as connection:
        cursor = connection.execute(
            "UPDATE chats SET document_hash = ? WHERE id = ?",
            (document_hash, chat_id),
        )
        if cursor.rowcount == 0:
            raise LookupError(f"Conversa {chat_id} nao encontrada.")
