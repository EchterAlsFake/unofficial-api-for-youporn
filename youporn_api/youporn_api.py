from __future__ import annotations
import os
import json
import logging
import threading

from functools import cached_property
from curl_cffi import Response, AsyncSession
from base_api.modules.type_hints import DownloadReport
from base_api.base import BaseCore, setup_logger, Helper
from typing import List, AsyncGenerator, Generator, Literal, Dict, Tuple, cast
from base_api.modules.errors import InvalidProxy, BotProtectionDetected, UnknownError, NetworkingError

try:
    from .modules.consts import *
    from .modules.errors import *
    from .modules.type_hints import *

except (ModuleNotFoundError, ImportError):
    from modules.consts import *
    from modules.errors import *
    from modules.type_hints import *

try:
    import lxml
    parser = "lxml"

except (ModuleNotFoundError, ImportError):
    parser = "html.parser"


def parse_bitrate_from_url(url: str) -> int | None:
    """
    Try to pull something like 4000K or 2000k out of the URL and convert to bps.
    """
    m = re.search(r'(\d+)\s*[kK](?![a-zA-Z])', url)
    if m:
        return int(m.group(1)) * 1000
    return None


def variant_key(item: Dict) -> Tuple[int, int]:
    """
    Sort key: default first (False>True trick with tuple), then by quality descending.
    We invert defaultQuality so True sorts before False.
    """
    return 0 if item.get("defaultQuality") else 1, -(int(item.get("quality", 0)))


def build_master_playlist(variants: List[Dict]) -> str:
    """
    Build an HLS master playlist string from a list of dicts like the one you provided.
    Each item should have: defaultQuality (bool), format (e.g., 'hls'), videoUrl, quality (e.g., '720').
    """
    # Keep only HLS entries with a URL
    items = [v for v in variants if v.get("format") == "hls" and v.get("videoUrl")]
    if not items:
        raise ValueError("No HLS variants found")

    # Sort: default first, then highest quality
    items.sort(key=variant_key)

    lines = ["#EXTM3U", "#EXT-X-VERSION:3"]

    for v in items:
        q = int(v.get("quality", 0))
        w, h = RES_BY_QUALITY.get(q, (0, 0))
        bw = parse_bitrate_from_url(v["videoUrl"]) or BPS_FALLBACK.get(q, 1_000_000)

        # You can add CODECS, FRAME-RATE, AUDIO, SUBTITLES if you know them.
        attrs = [
            f"BANDWIDTH={bw}",
            f"AVERAGE-BANDWIDTH={bw}",
        ]
        if w and h:
            attrs.append(f"RESOLUTION={w}x{h}")
        # Add NAME (for players that show labels)
        attrs.append(f'NAME="{q}p"')

        lines.append(f"#EXT-X-STREAM-INF:{','.join(attrs)}")
        lines.append(v["videoUrl"])

    return "\n".join(lines) + "\n"


def pick_best_mp4(variants: List[Dict]) -> str | None:
    """
    Select the best-quality direct MP4 URL from a list of media definitions.
    Returns the URL string or None if no MP4 variants are available.
    """
    items = [v for v in variants if v.get("format") == "mp4" and v.get("videoUrl")]
    if not items:
        return None

    # Sort: default first, then highest quality
    items.sort(key=variant_key)
    return items[0]["videoUrl"]


async def get_html_content(core: BaseCore, url: str) -> str | None | dict:
    # What should I do here?
    try:
        content = await core.fetch(url)
        if isinstance(content, str):
            return content

        if isinstance(content, Response):
            if content.status_code == 404:
                raise VideoUnavailable(f"Video is not available: {url}")

    except NetworkingError as e:
        raise NetworkError(str(e)) from e

    except InvalidProxy as e:
        raise ProxyError(str(e)) from e

    except BotProtectionDetected as e:
        raise BotDetection(str(e)) from e

    except UnknownError as e:
        raise UnknownNetworkError(str(e)) from e


class Channel(Helper):
    def __init__(self, url: str, core: BaseCore, html_content: str | None = None):
        super(Channel, self).__init__(core, video_constructor=Video)
        self.url = url
        self.core = core
        self.html_content = html_content
        self._soup = None

    @property
    def soup(self) -> BeautifulSoup:
        if not self._soup:
            raise ValueError("You probably forgot to call init")

        return self._soup

    @property
    def channel_info_box(self) -> BeautifulSoup:
        return cast(BeautifulSoup, self.soup.find("div", class_="main-stats-bar"))

    async def init(self):
        if not self.html_content:
            self.html_content = await get_html_content(core=self.core, url=self.url)

        assert isinstance(self.html_content, str)
        self._soup = BeautifulSoup(self.html_content, parser)
        return self

    @cached_property
    def name(self) -> str:
        return self.soup.find("h1", class_="name-title").text.replace("Subscribe", "").strip()

    @cached_property
    def channel_rank(self) -> str:
        return self.channel_info_box.find("p", class_="info-stat-data").text.strip()

    @cached_property
    def total_videos_count(self) -> str:
        return self.channel_info_box.find_all("p", class_="info-stat-data")[3].text.strip()

    @cached_property
    def channel_view_count(self) -> str:
        return self.channel_info_box.find_all("p", class_="info-stat-data")[1].text.strip()

    @cached_property
    def channel_subscribers_count(self) -> str:
        return self.channel_info_box.find_all("p", class_="info-stat-data")[2].text.strip()

    @cached_property
    def description(self) -> str:
        return self.soup.find("div", class_="profile-bio channel-description").text.strip()

    async def videos(self, pages: int = 2, videos_concurrency: int | None = None, pages_concurrency: int | None = None) -> AsyncGenerator[Video, None]:
        page_urls = [f"{self.url}?page={page}" for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency
        async for video in self.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency, max_page_concurrency=pages_concurrency,
                                 video_link_extractor=extractor_html):
            yield video


class Collection(Helper):
    def __init__(self, url: str, core: BaseCore, html_content: str | None = None):
        super(Collection, self).__init__(core, video_constructor=Video)
        self.url = url
        self.core = core
        self.html_content = html_content
        self._soup = None

    @property
    def soup(self) -> BeautifulSoup:
        if not self._soup:
            raise ValueError("You probably forgot to call init")

        return self._soup

    async def init(self):
        if not self.html_content:
            self.html_content = await get_html_content(core=self.core, url=self.url)

        assert isinstance(self.html_content, str)
        self._soup = BeautifulSoup(self.html_content, parser)
        return self

    @cached_property
    def name(self) -> str:
        return self.soup.find("div", class_="top-section").find("h4").text.replace("Collection:", "").strip()

    @cached_property
    def rating(self) -> str:
        return self.soup.find("div", class_="featureCollectionRating").text.strip()

    @cached_property
    def total_videos_count(self) -> str:
        return self.soup.find("p", class_="collection-videos-count").text.strip()

    @cached_property
    def view_count(self) -> str:
        return self.soup.find("div", class_="top-section").find_all("li")[1].find("p").text.strip()

    @cached_property
    def last_updated(self) -> str:
        return self.soup.find("li", class_="lastUpdated").find("p").text.strip()

    async def videos(self, pages: int = 2, videos_concurrency: int | None = None, pages_concurrency: int | None = None) -> AsyncGenerator[Video, None]:
        page_urls = [f"{self.url}?page={page}" for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency
        async for video in self.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                 max_page_concurrency=pages_concurrency,
                                 video_link_extractor=extractor_html):
            yield video


class Pornstar(Helper):
    def __init__(self, url: str, core: BaseCore, html_content: str | None = None):
        super(Pornstar, self).__init__(core, video_constructor=Video)
        self.url = url
        self.core = core
        self.logger = setup_logger(name="YOUPORN API - [Pornstar]", level=logging.ERROR)
        self.html_content = html_content
        self._soup = None

    @property
    def soup(self) -> BeautifulSoup:
        if not self._soup:
            raise ValueError("You probably forgot to call init")

        return self._soup

    async def init(self):
        if not self.html_content:
            self.html_content = await get_html_content(core=self.core, url=self.url)

        assert isinstance(self.html_content, str)
        self._soup = BeautifulSoup(self.html_content, parser)
        return self

    @cached_property
    def name(self) -> str:
        return self.soup.find("h1", class_="name-title").text.strip()

    @cached_property
    def pornstar_profile_info(self) -> dict:
        profile_info = self.soup.find("ul", class_="profile-info")
        li_tags = profile_info.find_all("li", class_="info-stat")
        dictionary = {}

        for tag in li_tags:
            stuff = tag.find_all("p")
            key = stuff[0].text.strip()
            item = stuff[1].text.strip()
            dictionary.update({key: item})

        return dictionary

    async def videos(self, pages: int = 2, videos_concurrency: int | None = None, pages_concurrency: int | None = None) -> AsyncGenerator[Video, None]:
        page_urls = [f"{self.url}?page={page}" for page in range(1, pages + 1)]
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency
        async for video in self.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                 max_page_concurrency=pages_concurrency,
                                 video_link_extractor=extractor_html):
            yield video

class User:
    def __init__(self, url: str, core: BaseCore, html_content: str | None = None):
        self.url = url
        self.core = core
        self.html_content = html_content
        self._soup = None

    @property
    def soup(self) -> BeautifulSoup:
        if not self._soup:
            raise ValueError("You probably forgot to call init")

        return self._soup

    async def init(self):
        if not self.html_content:
            self.html_content = await get_html_content(core=self.core, url=self.url)

        assert isinstance(self.html_content, str)
        self._soup = BeautifulSoup(self.html_content, parser)
        return self

    @cached_property
    def name(self) -> str:
        return self.soup.find("h1", class_="name-title").text.strip()

    @cached_property
    def collections(self) -> Generator[Collection, None, None]:
        container = self.soup.find("ul", class_="playlists_list")
        _collections = container.find_all("li", class_="playlists-container")

        for collection_container in _collections:
            yield Collection(f'https://youporn.com{collection_container.find("a").get("href")}', core=self.core)


class Video:
    _UNSET = object()  # sentinel for "not yet cached"

    def __init__(self, url: str, core: BaseCore, html_content: str | None = None):
        self.url = url
        self.core = core
        self.logger = setup_logger(name="YOUPORN API - [Video]", level=logging.ERROR)
        self.html_content = html_content
        self._direct_mp4_url: str | None = None
        self._soup = None
        self._m3u8_base_url_cache: str | None = self._UNSET  # type: ignore[assignment]

    @property
    def soup(self) -> BeautifulSoup:
        if not self._soup:
            raise ValueError("You probably forgot to call init")

        return self._soup

    async def init(self):
        if not self.html_content:
            self.html_content = await get_html_content(core=self.core, url=self.url)

        if region_locked_pattern.search(self.html_content):
            raise RegionBlocked(f"The Video: {self.url} is not available in your region!")

        assert isinstance(self.html_content, str)
        self._soup = BeautifulSoup(self.html_content, parser)
        return self

    @cached_property
    def title(self) -> str:
        try:
            return self.soup.find("h1", class_="videoTitle tm_videoTitle").text.strip()

        except AttributeError:
            raise f"URL: {self.url} raised an error!"

    @cached_property
    def length(self) -> str:
        assert isinstance(self.html_content, str)
        return re.search(r'"duration":"(.*?)"', self.html_content).group(1).replace("PT", "").replace("S", "").strip()

    @cached_property
    def rating(self) -> str:
        return self.soup.find("span", class_="tm_rating_percent").text.strip()

    @cached_property
    def views(self) -> str:
        return self.soup.find("span", class_="infoValue tm_infoValue").text.strip()

    @cached_property
    def publish_date(self) -> str:
        return self.soup.find("span", class_="publishedDate").text.strip()

    async def author(self) -> Pornstar | Channel:
        link = f'https://youporn.com{self.soup.find("div", class_="submitByLink").find("a").get("href")}'
        if "channel" in link:
            channel = Channel(url=link, core=self.core)
            return await channel.init()

        else:
            pornstar = Pornstar(link, core=self.core)
            return await pornstar.init()

    async def m3u8_base_url(self) -> str | None:
        if self._m3u8_base_url_cache is not self._UNSET:
            return self._m3u8_base_url_cache

        assert isinstance(self.html_content, str)
        media_definitions = re.search(r'mediaDefinition: (.*?) poster:', self.html_content, re.DOTALL | re.IGNORECASE).group(1)
        url = re.search(r'videoUrl":"(.*?)"', media_definitions).group(1).replace('\\', '')

        content = await get_html_content(core=self.core, url=url)
        assert isinstance(content, str)

        variants = json.loads(content)
        try:
            result = build_master_playlist(variants)
            self._m3u8_base_url_cache = result
            return result
        except ValueError:
            # No HLS variants found – fall back to direct MP4
            mp4_url = pick_best_mp4(variants)
            if mp4_url:
                self._direct_mp4_url = mp4_url
                self._m3u8_base_url_cache = None
                return None

            raise ValueError("No HLS or MP4 variants found in media definitions")

    @cached_property
    def thumbnail(self) -> str:
        assert isinstance(self.html_content, str)
        return re.search(r"poster: '(.*?)'", self.html_content).group(1)

    @cached_property
    def categories(self) -> List[str]:
        categories_ = self.soup.find_all("a", class_="button bubble-button categories-tags tm_carousel_tag js-pop")
        categories = []

        for category in categories_:
            categories.append(category.text)

        return categories

    async def pornstars(self) -> AsyncGenerator[Pornstar, None]:
        pornstars_ = self.soup.find_all("a", class_="button bubble-button tm_carousel_tag")

        for pornstar_object in pornstars_:
            pornstar = Pornstar(f'https://youporn.com{pornstar_object["href"]}', core=self.core)
            yield await pornstar.init()

    async def download(self, quality, path="./", callback: callback_hint=None, no_title=False, remux: bool = False,
                 callback_remux: callback_hint=None, start_segment: int = 0, stop_event: threading.Event | None = None,
                 segment_state_path: str | None = None, segment_dir: str | None = None,
                 return_report: bool = False, cleanup_on_stop: bool = True, keep_segment_dir: bool = False
                 ) -> bool | DownloadReport:
        """
        :param callback:
        :param quality:
        :param path:
        :param no_title:
        :param remux:
        :param callback_remux:
        :param start_segment:
        :param stop_event:
        :param segment_state_path:
        :param segment_dir:
        :param return_report:
        :param cleanup_on_stop:
        :param keep_segment_dir:
        :return:
        """
        if not no_title:
            path = os.path.join(path, f"{self.title}.mp4")

        # Ensure m3u8_base_url has been resolved so _direct_mp4_url is populated if needed
        m3u8 = await self.m3u8_base_url()

        if self._direct_mp4_url:
            # Direct MP4 stream – use legacy (non-HLS) download
            return await self.core.legacy_download(path=path, url=self._direct_mp4_url, callback=callback,
                                                   stop_event=stop_event, allow_multipart=False)

        return await self.core.download(video=self, quality=quality, path=path, callback=callback, remux=remux,
                           callback_remux=callback_remux, start_segment=start_segment, stop_event=stop_event,
                           segment_state_path=segment_state_path, segment_dir=segment_dir, return_report=return_report,
                           cleanup_on_stop=cleanup_on_stop, keep_segment_dir=keep_segment_dir)


    async def get_segments(self, quality) -> list:
        """
        :param quality: (str, Quality) The video quality
        :return: (list) A list of segments (the .ts files)
        """
        segments = await self.core.get_segments(quality=quality, m3u8_url_master=await self.m3u8_base_url())
        return segments


class Client(Helper):
    def __init__(self, core: BaseCore = BaseCore()):
        super().__init__(core, video_constructor=Video)
        self.core = core
        self.core.initialize_session()
        assert isinstance(self.core.session, AsyncSession)
        self.core.session.headers.update(headers)

    async def get_video(self, url: str) -> Video:
        video = Video(url, core=self.core)
        return await video.init()

    async def get_pornstar(self, url: str) -> Pornstar:
        pornstar = Pornstar(url, core=self.core)
        return await pornstar.init()

    async def get_channel(self, url: str) -> Channel:
        channel = Channel(url, core=self.core)
        return await channel.init()

    async def get_collection(self, url: str) -> Collection:
        collection = Collection(url, core=self.core)
        return await collection.init()

    async def search_videos(self, query: str, pages: int = 0,
                      filter_relevance: Literal[
                          "views", "rating", "date", "duration"
                      ] | None = None,
                      filter_duration_minimum: Literal[
                          "10", "20", "30", "40", "50", "60"
                      ] | None = None,
                      filter_duration_maximum: Literal[
                          "10", "20", "30", "40", "50", "60"
                      ] | None = None,
                      filter_resolution: Literal[
                          "VR", "HD"
                      ] | None = None,
                      videos_concurrency: int | None = None,
                      pages_concurrency: int | None = None,
                      ) -> AsyncGenerator[Video, None]:
        # Define basic filters
        res = ""
        min_minutes = ""
        max_minutes = ""
        query = f"query={query}&"
        filter = "/?"

        if filter_relevance:
            filter = f"/{filter_relevance}/?"

        if filter_resolution:
            res = f"res={filter_resolution}&"

        if filter_duration_minimum:
            min_minutes = f"min_minutes={filter_duration_minimum}&"

        if filter_duration_maximum:
            max_minutes = f"max_minutes={filter_duration_maximum}&"

        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency
        page_urls = [f"https://youporn.com{filter}{query}{res}{min_minutes}{max_minutes}&page={page}" for page in range(1, pages + 1)]
        async for video in self.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency, max_page_concurrency=pages_concurrency,
                                 video_link_extractor=extractor_html):
            yield video.init()
