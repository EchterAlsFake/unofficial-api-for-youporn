import pytest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from youporn_api import api


def test_search_query_is_one_value():
    client = object.__new__(api.Client)
    client.core = object()
    with patch.object(api, "scrape_stream") as stream:
        client.search_videos("a&b/# 日本", pages=2)
    urls = stream.call_args.kwargs["target_page_urls"]
    assert len(urls) == len(set(urls)) == 2
    for url in urls:
        assert parse_qs(urlsplit(url).query)["query"] == ["a&b/# 日本"]
        assert not urlsplit(url).fragment


def test_default_search_has_a_page():
    client = object.__new__(api.Client)
    client.core = object()
    with patch.object(api, "scrape_stream") as stream:
        client.search_videos("test")
    assert len(stream.call_args.kwargs["target_page_urls"]) == 1


@pytest.mark.parametrize(
    "html",
    [
        "",
        "<div class='full-row-thumbs'></div>",
        "<article class='video-box pc js_video-box js-pop'></article>",
    ],
)
def test_empty_listing(html):
    assert api.extractor_html(html) == []


@pytest.mark.parametrize(
    "html", ["", '<div class="top-section"><h4>Collection: Empty</h4></div>']
)
def test_empty_collection_metadata(html):
    data = api.Collection._extract_data(html)
    assert data["total_videos_count"] is None


def test_user_without_public_collections():
    data = api.User._extract_data('<h1 class="name-title">Example</h1>')
    assert data == {"name": "Example", "collection_urls": []}


def test_user_collection_absolute_links():
    html = '<ul class="playlists_list"><li class="playlists-container"><a href="https://www.youporn.com/collections/videos/123/">Test</a></li></ul>'
    assert api.User._extract_data(html)["collection_urls"] == [
        "https://www.youporn.com/collections/videos/123/"
    ]


@pytest.mark.asyncio
async def test_cli_closes_session_and_reports_false_download(capsys, tmp_path):
    from unittest.mock import AsyncMock, MagicMock
    from base_api import BaseCore
    from base_api.modules.config import RuntimeConfig

    core = BaseCore(RuntimeConfig())
    video = MagicMock(title="Example", length="10", url="https://example.com/video")
    video.load_fields = AsyncMock()
    video.download = AsyncMock(return_value=False)
    client = MagicMock()
    client.get_video = AsyncMock(return_value=video)
    with (
        patch.object(api, "BaseCore", return_value=core),
        patch.object(api, "Client", return_value=client),
    ):
        await api.run_main(
            ["--download", "https://example.com/video", "--output", str(tmp_path)]
        )
    assert core.session is None
    output = capsys.readouterr().out
    assert "Download complete:" not in output
    assert "Done ->" not in output
    assert "Download did not complete" in output


@pytest.mark.asyncio
async def test_author_resolution_and_performers():
    for segment, kind in [("channel", api.Channel), ("pornstar", api.Pornstar)]:
        video = api.Video(
            url="https://www.youporn.com/watch/123/",
            core=object(),
            author_link="https://www.youporn.com/" + segment + "/example/",
            pornstars_urls=["/pornstar/example/"],
        )
        assert isinstance(await video.author(load_html=False), kind)


@pytest.mark.asyncio
async def test_public_user_collection_objects():
    user = api.User(
        url="https://www.youporn.com/user/example/",
        core=object(),
        collection_urls=["https://www.youporn.com/collections/videos/123/"],
    )
    collections = [c async for c in user.get_collections(load_html=False)]
    assert len(collections) == 1 and isinstance(collections[0], api.Collection)


@pytest.mark.asyncio
async def test_performers_resolve_relative_links_without_title():
    from unittest.mock import AsyncMock

    video = api.Video(
        url="https://www.youporn.com/watch/123/",
        core=object(),
        pornstars_urls=["/pornstar/example/"],
    )
    with patch.object(api.Pornstar, "load_sources", AsyncMock()) as loader:
        stars = [s async for s in video.pornstars]
    assert stars[0].url == "https://www.youporn.com/pornstar/example/"
    loader.assert_awaited_once_with("html")


@pytest.mark.asyncio
async def test_public_user_html_loader_handles_empty_collections():
    from unittest.mock import AsyncMock

    user = api.User(url="https://www.youporn.com/user/example/", core=object())
    with patch.object(
        api,
        "get_html_content",
        AsyncMock(return_value='<h1 class="name-title">Example</h1>'),
    ):
        data = await user._load_html()
    assert data == {"name": "Example", "collection_urls": []}
