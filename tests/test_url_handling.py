"""Offline regressions for URL identity, pagination and listing contracts."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from youporn_api import api as api


class EmptyStream:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class UrlHandlingTests(unittest.IsolatedAsyncioTestCase):
    async def test_filtered_profile_fetches_two_distinct_pages(self):
        media = api.Channel(
            url="https://de.youporn.com/channel/Example/duration/?quality=hd&page=9#videos", core=object()
        )
        capture = Mock(return_value=EmptyStream())
        from contextlib import ExitStack

        with ExitStack() as stack:
            for name in ("scrape_stream", "_scrape_stream"):
                if hasattr(api, name):
                    stack.enter_context(patch.object(api, name, capture))
            if hasattr(api, "Helper"):
                stack.enter_context(patch.object(api, "Helper", lambda **kwargs: SimpleNamespace(iterator=capture)))
            stack.enter_context(patch.object(api.Channel, "get_field", AsyncMock(return_value=2)))
            async for _ in media.videos(pages=2):
                pass
        urls = capture.call_args.kwargs["target_page_urls"]
        self.assertEqual(
            urls,
            [
                "https://de.youporn.com/channel/Example/duration/?quality=hd&page=1",
                "https://de.youporn.com/channel/Example/duration/?quality=hd&page=2",
            ],
        )


if __name__ == "__main__":
    unittest.main()
