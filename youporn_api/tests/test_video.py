import pytest
from ..youporn_api import Client, Pornstar, Channel
from typing import AsyncGenerator

@pytest.mark.asyncio
async def test_everything():
    client = Client()
    video = await client.get_video("https://www.youporn.com/watch/225965571/")
    assert isinstance(video.title, str)
    assert isinstance(video.rating, str)

    async for pornstar in video.pornstars():
        assert isinstance(pornstar.name, str)

    assert isinstance(video.thumbnail, str)
    assert isinstance(video.categories, list)
    assert isinstance(video.views, str)
    assert isinstance(video.publish_date, str)

    author = await video.author()
    assert isinstance(author, Channel | Pornstar)

    assert isinstance(video.length, str)
    # Download is currently broken on yourporn