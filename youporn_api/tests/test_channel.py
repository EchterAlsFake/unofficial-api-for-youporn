import pytest
from ..youporn_api import Client

@pytest.mark.asyncio
async def test_everything():
    client = Client()
    channel = await client.get_channel("https://www.youporn.com/channel/mia-khalifa/")

    assert isinstance(channel.name, str)
    assert isinstance(channel.description, str)
    assert isinstance(channel.channel_rank, str)
    assert isinstance(channel.channel_subscribers_count, str)
    assert isinstance(channel.channel_view_count, str)
    assert isinstance(channel.total_videos_count, str)

    idx = 0
    async for video in channel.videos():
        idx += 1

        if idx >= 1:
            break
