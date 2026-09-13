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
    assert isinstance(channel.channel_id, str)
    assert isinstance(channel.avatar, str)
    assert isinstance(channel.banner, str)
    assert channel.join_url is None or isinstance(channel.join_url, str)

    idx = 0
    async for result in channel.videos():
        idx += 1
        assert isinstance(result.unwrap().title, str)

        if idx >= 3:
            break
