"""Cliente de linha de comando para verificar o streaming da API."""

from __future__ import annotations

import argparse
import os
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Consome e imprime a resposta streaming da API."
    )
    parser.add_argument(
        "document_hash",
        help="Hash MD5 retornado pelo endpoint /api/upload.",
    )
    parser.add_argument(
        "--preset",
        default="Tópicos Principais",
        help="Preset de análise (padrão: Tópicos Principais).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Timeout HTTP em segundos (padrão: 60).",
    )
    args = parser.parse_args()

    api_base_url = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
    api_url = f"{api_base_url}/api/analyze"
    payload = {
        "document_hash": args.document_hash,
        "query_or_preset": args.preset,
        "is_preset": True,
    }

    print("--- Iniciando Stream ---", flush=True)
    received_text = False

    try:
        with httpx.stream(
            "POST",
            api_url,
            json=payload,
            timeout=args.timeout,
        ) as response:
            if not response.is_success:
                response.read()
                try:
                    error_body = response.json()
                    detail = (
                        error_body.get("detail", response.text)
                        if isinstance(error_body, dict)
                        else error_body
                    )
                except ValueError:
                    detail = response.text
                print(
                    f"Erro da API (HTTP {response.status_code}): {detail}",
                    file=sys.stderr,
                )
                return 1

            print(
                f"HTTP {response.status_code} "
                f"{response.headers.get('content-type', '')}",
                file=sys.stderr,
            )
            for chunk in response.iter_text():
                if chunk:
                    received_text = True
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
    except httpx.HTTPError as exc:
        print(f"Falha ao consumir o streaming: {exc}", file=sys.stderr)
        return 1

    print("\n--- Fim do Stream ---", flush=True)
    if not received_text:
        print("A API encerrou o stream sem retornar conteúdo.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
