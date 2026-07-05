import pytest
from ..api import Client


@pytest.mark.asyncio
async def test_playlist():
    client = Client()
    playlist = await client.get_collection("https://www.youporn.com/collections/videos/38771091/")

    assert isinstance(playlist.total_videos_count, str)
    assert isinstance(playlist.url, str)
    assert isinstance(playlist.rating, str)
    assert isinstance(playlist.name, str)
    assert isinstance(playlist.last_updated, str)
    assert isinstance(playlist.view_count, str)

    idx = 0
    async for video in playlist.videos(pages=2):
        idx += 1
        assert isinstance(video.video.title, str)
        if idx >= 3:
            break
