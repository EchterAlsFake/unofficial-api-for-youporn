import pytest
from ..api import Client

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
    async for result in channel.videos():
        idx += 1
        assert isinstance(result.video.title, str)

        if idx >= 3:
            break
