import pytest
from ..api import Client, Pornstar


@pytest.mark.asyncio
async def test_all():
    client = Client()
    pornstar_real = await client.get_pornstar("https://www.youporn.com/pornstar/eva-elfie/", load_html=True)
    assert isinstance(pornstar_real.name, str)
    assert isinstance(pornstar_real.pornstar_id, str)
    assert isinstance(pornstar_real.avatar, str)
    assert isinstance(pornstar_real.banner, str)
    assert isinstance(pornstar_real.rank, str)
    assert isinstance(pornstar_real.pornstar_rank, str)
    assert isinstance(pornstar_real.view_count, str)
    assert isinstance(pornstar_real.subscribers_count, str)
    assert isinstance(pornstar_real.featured_in, list)
    assert pornstar_real.official_site is None or isinstance(pornstar_real.official_site, str)
    assert pornstar_real.more_of_me is None or isinstance(pornstar_real.more_of_me, str)
    assert pornstar_real.description is None or isinstance(pornstar_real.description, str)
    assert isinstance(pornstar_real.profile_info, dict)

    idx = 0
    async for result in pornstar_real.videos():
        idx += 1

        assert isinstance(result.unwrap().title, str)

        if idx == 1:
            break
