import unittest
from unittest.mock import call, patch

from google.genai import errors

from core import summarizer


class StreamRateLimitTests(unittest.TestCase):
    def test_primary_503_uses_existing_backoff_and_fallback(self) -> None:
        unavailable_error = errors.APIError(
            503,
            {"message": "temporarily unavailable", "status": "UNAVAILABLE"},
        )

        with (
            patch.object(summarizer, "_get_client", return_value=object()),
            patch.object(
                summarizer,
                "_stream_model_response",
                side_effect=[
                    unavailable_error,
                    unavailable_error,
                    ["fallback answer"],
                ],
            ),
            patch.object(summarizer.time, "sleep") as sleep,
        ):
            response = "".join(
                summarizer.stream_document_analysis(
                    "document text",
                    "question",
                    max_retries=1,
                )
            )

        self.assertEqual(response, "fallback answer")
        self.assertEqual(sleep.call_args_list, [call(1.5)])

    def test_primary_retries_then_fallback_429_returns_friendly_message(self) -> None:
        quota_error = errors.APIError(
            429,
            {"message": "quota exceeded", "status": "RESOURCE_EXHAUSTED"},
        )

        with (
            patch.object(summarizer, "_get_client", return_value=object()),
            patch.object(
                summarizer,
                "_stream_model_response",
                side_effect=[quota_error, quota_error, quota_error],
            ) as stream_model,
            patch.object(summarizer.time, "sleep") as sleep,
        ):
            response = "".join(
                summarizer.stream_document_analysis(
                    "document text",
                    "question",
                    max_retries=1,
                )
            )

        self.assertEqual(
            response,
            "⚠️ **Limite de requisições por minuto atingido (HTTP 429):** "
            "A cota da API do Gemini foi temporariamente excedida. Por favor, "
            "aguarde cerca de 30 a 60 segundos e tente novamente.",
        )
        self.assertEqual(sleep.call_args_list, [call(3.0)])
        self.assertEqual(stream_model.call_count, 3)


if __name__ == "__main__":
    unittest.main()
