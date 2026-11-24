import asyncio
import unittest
from collections.abc import AsyncIterable
from unittest.mock import patch

from google.genai import errors

import api


def _quota_error() -> errors.APIError:
    return errors.APIError(
        429,
        {"message": "quota exceeded", "status": "RESOURCE_EXHAUSTED"},
    )


async def _collect_stream(body_iterator: AsyncIterable[str]) -> list[str]:
    return [chunk async for chunk in body_iterator]


class ApiRateLimitTests(unittest.TestCase):
    def test_preflight_rate_limit_is_returned_as_stream_text(self) -> None:
        with patch.object(api, "validate_analysis_request", side_effect=_quota_error()):
            response = api._stream_analysis("document text", "question", False)
            chunks = asyncio.run(_collect_stream(response.body_iterator))

        self.assertEqual(chunks, [api.RATE_LIMIT_STREAM_MESSAGE])

    def test_stream_rate_limit_is_returned_as_friendly_text(self) -> None:
        with (
            patch.object(api, "validate_analysis_request"),
            patch.object(api, "stream_document_analysis", side_effect=_quota_error()),
        ):
            response = api._stream_analysis("document text", "question", False)
            chunks = asyncio.run(_collect_stream(response.body_iterator))

        self.assertEqual(chunks, [api.RATE_LIMIT_STREAM_MESSAGE])

    def test_auto_title_failure_uses_message_fallback(self) -> None:
        first_message = "A" * 40
        with (
            patch.object(api, "generate_chat_title", side_effect=RuntimeError("429")),
            patch.object(api, "update_chat_title") as update_title,
        ):
            api._generate_and_store_chat_title(1, first_message)

        update_title.assert_called_once_with(1, f"{first_message[:30]}...")


if __name__ == "__main__":
    unittest.main()
