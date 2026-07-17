import pytest
from ..api import Client, Pornstar


@pytest.mark.asyncio
async def test_all():
    client = Client()
    pornstar_real = await client.get_pornstar("https://www.youporn.com/pornstar/eva-elfie/", load_html=True)
    assert isinstance(pornstar_real.name, str)
    idx = 0
    async for result in pornstar_real.videos():
        idx += 1

        assert isinstance(result.video.title, str)

        if idx == 1:
            break

    assert isinstance(pornstar_real.name, str)
    assert isinstance(pornstar_real.profile_info, dict)
