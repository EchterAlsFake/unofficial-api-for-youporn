import pytest
from ..youporn_api import Client, Pornstar


@pytest.mark.asyncio
async def test_all():
    client = Client()
    pornstar_real = await client.get_pornstar("https://www.youporn.com/pornstar/eva-elfie/")
    assert isinstance(pornstar_real.name, str)
    idx = 0
    async for video in pornstar_real.videos():
        idx += 1
        if idx == 1:
            break

    assert isinstance(pornstar_real.name, str)
    assert isinstance(pornstar_real.pornstar_profile_info, dict)
