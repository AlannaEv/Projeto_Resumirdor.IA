# API Integration Guide

## Overview

- **Base URL:** `http://localhost:8001`
- **JSON endpoints:** use and expect `application/json`.
- **Streaming endpoint:** `POST /api/analyze` returns UTF-8 text chunks with
  `Content-Type: text/plain; charset=utf-8`.
- **Errors:** FastAPI returns a JSON body such as `{"detail": "..."}` for
  non-streaming request errors.
- **CORS:** the API currently allows requests from any origin.

The upload response currently calls the MD5 field `hash` and the token estimate
`token_count`. Use `hash` as `document_hash` in analysis requests; `token_count`
is the value referred to as `estimated_tokens` in some client specifications.
The response also includes the extracted `text`.

## REST Endpoints

### `GET /health`

Checks that the API is running.

**Response (`200`):**

```json
{
  "status": "ok"
}
```

### `POST /api/upload`

Uploads a PDF, TXT, or MD file and extracts its text.

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---:|---|
| `file` | File | Yes | PDF, TXT, or MD document |
| `strip_refs` | Boolean | No | Remove a detected final references section; defaults to `false` |

**Response (`200`):**

```json
{
  "text": "Extracted document text...",
  "char_count": 1234,
  "token_count": 309,
  "pages_count": 5,
  "hash": "e10adc3949ba59abbe56e057f20f883e",
  "filename": "article.pdf"
}
```

Save `hash` as the document identifier for `POST /api/analyze`. Unsupported or
unreadable files return `400`.

### `POST /api/analyze`

Analyzes a document uploaded previously. The response is a streaming sequence
of UTF-8 text chunks, not a JSON object. Set `is_preset` to `true` when
`query_or_preset` is one of `Tópicos Principais`, `Fichamento Científico`,
`Glossário de Termos Complexos`, `Gerar Questões de Estudo`, or
`Perguntas e Respostas`.

**Request (`application/json`):**

```json
{
  "document_hash": "e10adc3949ba59abbe56e057f20f883e",
  "query_or_preset": "What methodology does the document describe?",
  "is_preset": false,
  "chat_id": 12,
  "user_message": "What methodology does the document describe?"
}
```

`chat_id` and `user_message` are optional. When `chat_id` is provided, the
question and completed assistant response are saved to that chat. A missing
document returns `404`; an invalid prompt returns `400`; missing Gemini
configuration returns `503`.

### `POST /api/analyze-direct`

Analyzes pasted text without uploading a file.

**Request (`application/json`):**

```json
{
  "text": "Document text to analyze...",
  "query_or_preset": "Tópicos Principais",
  "is_preset": true,
  "strip_refs": false,
  "chat_id": 12,
  "user_message": "Summarize the document"
}
```

The response uses the same text streaming format as `/api/analyze`. With a
`chat_id`, the text is saved as the chat's associated document and the
conversation is persisted.

### `GET /api/chats`

Lists chats, newest first.

**Response (`200`):**

```json
[
  {
    "id": 12,
    "title": "Research methodology",
    "document_hash": "e10adc3949ba59abbe56e057f20f883e",
    "created_at": "2026-11-24 10:30:00"
  }
]
```

### `POST /api/chats`

Creates a chat. If `title` is `null`, blank, or `Nova conversa`, the API
initially uses a short fallback title and schedules title generation when
`first_message` is provided.

**Request (`application/json`):**

```json
{
  "title": null,
  "first_message": "Explain the methodology used in this paper",
  "document_hash": "e10adc3949ba59abbe56e057f20f883e"
}
```

`first_message` is optional and is used for automatic titling. A supplied
`document_hash` must refer to an uploaded or persisted document.

**Response (`201`):**

```json
{
  "id": 12,
  "title": "Explain the methodology used",
  "created_at": "2026-11-24 10:30:00"
}
```

### `GET /api/chats/{chat_id}`

Returns chat metadata, its messages in chronological order, and document
metadata when a document is associated.

**Response (`200`):**

```json
{
  "id": 12,
  "title": "Research methodology",
  "document_hash": "e10adc3949ba59abbe56e057f20f883e",
  "created_at": "2026-11-24 10:30:00",
  "messages": [
    {
      "role": "user",
      "content": "What methodology does the document describe?",
      "created_at": "2026-11-24 10:31:00"
    },
    {
      "role": "assistant",
      "content": "The document describes...",
      "created_at": "2026-11-24 10:32:00"
    }
  ],
  "document": {
    "hash": "e10adc3949ba59abbe56e057f20f883e",
    "filename": "article.pdf",
    "char_count": 1234,
    "token_count": 309,
    "pages_count": 5
  }
}
```

`document` is `null` when no persisted document is associated. A missing chat
returns `404`.

### `DELETE /api/chats/{chat_id}`

Deletes the chat and its messages. The associated document is also removed
from SQLite when no other chat references it.

**Response:** `204 No Content`. A missing chat returns `404`.

### `POST /api/chats/{chat_id}/messages`

Adds a message directly to an existing chat.

**Request (`application/json`):**

```json
{
  "role": "user",
  "content": "A message to save"
}
```

`role` must be `user` or `assistant`.

**Response (`201`):**

```json
{
  "status": "ok"
}
```

## JavaScript Streaming Example

```javascript
async function streamAnalysis(documentHash, prompt, chatId) {
  const response = await fetch("http://localhost:8001/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      document_hash: documentHash,
      query_or_preset: prompt,
      is_preset: false,
      chat_id: chatId
    })
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || `HTTP ${response.status}`);
  }
  if (!response.body) {
    throw new Error("The browser did not provide a response stream.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value, { stream: true });
    console.log("Chunk received:", chunk);
    // Update the UI state here.
  }

  const finalChunk = decoder.decode();
  if (finalChunk) {
    console.log("Chunk received:", finalChunk);
    // Update the UI state here.
  }
}
```
