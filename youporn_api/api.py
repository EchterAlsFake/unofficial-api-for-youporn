from __future__ import annotations

import os
import re
import copy
import json
import asyncio
import logging

from dataclasses import dataclass, fields
from curl_cffi import Response, AsyncSession
from selectolax.lexbor import LexborHTMLParser
from typing import  AsyncGenerator, Literal, cast
from base_api.modules.type_hints import DownloadReport
from base_api import BaseCore, Helper, DownloadConfigHLS, DownloadConfigRAW, ScrapeResult, BaseMedia
from base_api.modules.errors import InvalidProxy, BotProtectionDetected, UnknownError, NetworkRequestError, ResourceGone

from youporn_api.modules.consts import (extractor_html, region_locked_pattern, headers, build_master_playlist,
                                        pick_best_mp4)
from youporn_api.modules.errors import (VideoUnavailable, NetworkError, ProxyError, BotDetection, UnknownNetworkError,
                                        RegionBlocked, DownloadFailed)
from youporn_api.modules.type_hints import on_error_hint


logger = logging.getLogger(name="YouPorn API")
logger.addHandler(logging.NullHandler())


async def on_error(url: str, error: Exception, attempt: int) -> bool:
    logger.error(f"URL: {url}, ERROR: {error}, Attempt: {attempt}")

    if isinstance(error, ResourceGone):
        return False

    return True


async def get_html_content(core: BaseCore, url: str) -> str | None | dict:
    # What should I do here?
    try:
        content = await core.fetch(url)
        if isinstance(content, str):
            return content

        if isinstance(content, Response):
            if content.status_code == 404:
                logger.error(f"Video: {url} is not available!")
                raise VideoUnavailable(f"Video is not available: {url}")

    except NetworkRequestError as e:
        logger.error(f"Network Request Error: {e} with: {url}")
        raise NetworkError(str(e)) from e

    except InvalidProxy as e:
        logger.error(f"Invalid Proxy: {e} with: {url}")
        raise ProxyError(str(e)) from e

    except BotProtectionDetected as e:
        logger.error(f"Bot Protection: {e} with: {url}")
        raise BotDetection(str(e)) from e

    except UnknownError as e:
        logger.error(f"Unknown Error: {e} with: {url}")
        raise UnknownNetworkError(str(e)) from e


@dataclass(slots=True, kw_only=True)
class Channel(BaseMedia):
    url: str
    core: BaseCore
    name: str | None = None
    channel_rank: str | None = None
    total_videos_count: str | None = None
    channel_view_count: str | None = None
    channel_subscribers_count: str | None = None
    description: str | None = None

    async def _perform_load(self, api: bool, html: bool, anything_else: bool):
        if html:
            logger.info(f"Loading Channel HTML from {self.url}")
            await asyncio.gather(self._fetch_html())

    async def _fetch_html(self) -> None:
        html_content = await get_html_content(core=self.core, url=self.url)
        logger.debug(f"Received HTML Content for: {self.url}")
        assert isinstance(html_content, str)
        data: dict = await asyncio.to_thread(self._extract_data, html_content)
        allowed_fields = {field.name for field in fields(self)}
        for key, value in data.items():
            if key in allowed_fields:
                setattr(self, key, value)

    @staticmethod
    def _extract_data(html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)
        name = parser.css_first("h1.name-title").text().replace("Subscribe", "").strip()
        channel_info_box = parser.css_first("div.main-stats-bar")
        channel_rank = channel_info_box.css_first("p.info-stat-data").text(strip=True)
        total_videos_count = channel_info_box.css("p.info-stat-data")[3].text(strip=True)
        channel_view_count = channel_info_box.css("p.info-stat-data")[1].text(strip=True)
        channel_subscribers_count = channel_info_box.css("p.info-stat-data")[2].text()
        description = parser.css_first("div.profile-bio.channel-description").text(strip=True)

        return {
            "name": name,
            "channel_rank": channel_rank,
            "total_videos_count": total_videos_count,
            "channel_view_count": channel_view_count,
            "channel_subscribers_count": channel_subscribers_count,
            "description": description
        }

    async def videos(self, pages: int = 2, videos_concurrency: int | None = None, pages_concurrency: int | None = None,
                     on_video_error: on_error_hint = on_error,
                     on_page_error: on_error_hint = None,
                     keep_original_order: bool = False
                     ) -> AsyncGenerator[ScrapeResult, None]:
        helper = Helper(core=self.core, constructor=Video)
        url = self.url
        page_urls = [f"{url}?page={page}" for page in range(1, pages + 1)]
        logger.info(f"Requesting channel videos from urls: {page_urls}")
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency
        async for scrape_result in helper.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                 max_page_concurrency=pages_concurrency, keep_original_order=keep_original_order,
                                 video_link_extractor=extractor_html, on_video_error=on_video_error, on_page_error=on_page_error):
            yield scrape_result


@dataclass(slots=True, kw_only=True)
class Collection(BaseMedia):
    url: str
    core: BaseCore
    name: str | None = None
    rating: str | None = None
    total_videos_count: str | None = None
    view_count: str | None = None
    last_updated: str | None = None

    async def _perform_load(self, api: bool, html: bool, anything_else: bool):
        if html:
            logger.info(f"Loading Collection HTML from {self.url}")
            await asyncio.gather(self._fetch_html())

    async def _fetch_html(self):
        html_content = await get_html_content(core=self.core, url=self.url)
        assert isinstance(html_content, str)
        data: dict = await asyncio.to_thread(self._extract_data, html_content)
        allowed_fields = {field.name for field in fields(self)}
        for key, value in data.items():
            if key in allowed_fields:
                setattr(self, key, value)
        logger.debug(f"Finished extracting attributes for Collection")

    @staticmethod
    def _extract_data(html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)

        name = parser.css_first("div.top-section").css_first("h4").text().replace("Collection:", "").strip()
        rating = parser.css_first("div.featureCollectionRating").text(strip=True)
        total_videos_count = parser.css_first("p.collection-videos-count").text(strip=True)
        view_count = parser.css_first("div.top-section").css("li")[1].css_first("p").text(strip=True)
        last_updated = parser.css_first("li.lastUpdated > p").text(strip=True)
        return {
            "name": name,
            "rating": rating,
            "total_videos_count": total_videos_count,
            "view_count": view_count,
            "last_updated": last_updated
        }

    async def videos(self, pages: int = 2, videos_concurrency: int | None = None, pages_concurrency: int | None = None,
                     on_video_error: on_error_hint = on_error,
                     on_page_error: on_error_hint = None,
                     keep_original_order: bool = False
                     ) -> AsyncGenerator[ScrapeResult, None]:

        helper = Helper(core=self.core, constructor=Video)
        url = self.url
        page_urls = [f"{url}?page={page}" for page in range(1, pages + 1)]
        logger.info(f"Requesting collection videos from urls: {page_urls}")
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency
        async for scrape_result in helper.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                 max_page_concurrency=pages_concurrency,
                                 video_link_extractor=extractor_html, keep_original_order=keep_original_order,
                                 on_video_error=on_video_error, on_page_error=on_page_error):
            yield scrape_result

@dataclass(slots=True, kw_only=True)
class Pornstar(BaseMedia):
    url: str
    core: BaseCore
    name: str | None = None
    profile_info: dict | None = None

    async def _perform_load(self, api: bool, html: bool, anything_else: bool):
        if html:
            logger.info(f"Loading Pornstar HTML from {self.url}")
            await asyncio.gather(self._fetch_html())

    async def _fetch_html(self):
        html_content = await get_html_content(core=self.core, url=self.url)
        assert isinstance(html_content, str)
        data: dict = await asyncio.to_thread(self._extract_data, html_content)
        allowed_fields = {field.name for field in fields(self)}
        for key, value in data.items():
            if key in allowed_fields:
                setattr(self, key, value)
                # Yes I know this is inefficient, but if we scale later, then I don't have to rewrite it lol
        logger.debug(f"Finished extracting attributes for Pornstar: {self.name}")

    def _extract_data(self, html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)
        name = parser.css_first("h1.name-title").text(strip=True)
        dictionary = {}

        if not "/amateur/" in self.url:
            profile_info = parser.css_first("ul.profile-info")
            li_tags = profile_info.css("li.info-stat")

            for tag in li_tags:
                stuff = tag.css("p")
                key = stuff[0].text(strip=True)
                item = stuff[1].text(strip=True)
                dictionary.update({key: item})

        return {
            "name": name,
            "profile_info": dictionary
        }

    async def videos(self, pages: int = 2, videos_concurrency: int | None = None, pages_concurrency: int | None = None,
                     on_video_error: on_error_hint = on_error,
                     on_page_error: on_error_hint = None,
                     keep_original_order: bool = False
                     ) -> AsyncGenerator[ScrapeResult, None]:
        helper = Helper(core=self.core, constructor=Video)

        page_urls = [f"{self.url}?page={page}" for page in range(1, pages + 1)]
        logger.info(f"Requesting pornstar videos from urls: {page_urls}")
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency
        async for result in helper.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency,
                                 max_page_concurrency=pages_concurrency,
                                 video_link_extractor=extractor_html, keep_original_order=keep_original_order,
                                 on_video_error=on_video_error, on_page_error=on_page_error):
            yield result


@dataclass(kw_only=True, slots=True)
class User(BaseMedia):
    url: str
    core: BaseCore
    name: str | None = None
    collection_urls: list[str] | None = None

    async def _perform_load(self, api: bool, html: bool, anything_else: bool):
        if html:
            logger.info(f"Loading User HTML from {self.url}")
            await asyncio.gather(self._fetch_html())

    async def _fetch_html(self):
        html_content = await get_html_content(core=self.core, url=self.url)
        assert isinstance(html_content, str)
        data: dict = asyncio.to_thread(self._extract_data, html_content)
        allowed_fields = {field.name for field in fields(self)}
        for key, value in data.items():
            if key in allowed_fields:
                setattr(self, key, value)

        logger.debug(f"Finished extracting attributes for User: {self.name}")

    @staticmethod
    def _extract_data(html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)
        name = parser.css_first("h1.name-title").text(strip=True)

        container = parser.css_first("ul.playlists_list")
        _collections = container.css("li.playlists-container")
        urls = []

        for collection_container in _collections:
            urls.append(f'https://youporn.com{collection_container.css_first("a").attributes.get("href")}')

        return {
            "name": name,
            "collection_urls": urls
        }

    async def get_collections(self, load_html: bool = True) -> AsyncGenerator[Collection, None]:
        logger.info(f"Getting collections for User: {self.name or self.url}")
        for collection in cast(list, self.collection_urls):
            collection = Collection(url=collection, core=self.core)
            yield await collection.load(html=load_html)


@dataclass(slots=True, kw_only=True)
class Video(BaseMedia):
    url: str
    core: BaseCore
    title: str | None = None
    publish_date: str | None = None
    length: str | None = None
    rating: str | None = None
    views: str | None = None
    thumbnail: str | None = None
    categories: list[str] | None = None
    m3u8_base_url: str | None = None
    author_link: str | None = None
    pornstars_urls: list[str] | None = None

    # Only when comming from the iterator, if they are None, it is how it is...
    uploader_id: str | None = None
    uploader_status: str | None = None
    uploader_type: str | None = None
    uploader_name: str | None = None
    video_id: str | None = None

    # You don't need this
    is_hls: bool | None = None

    async def _perform_load(self, api: bool, html: bool, anything_else: bool):
        if html:
            logger.info(f"Loading Video HTML from {self.url}")
            await asyncio.gather(self._fetch_html())

    async def _fetch_html(self) -> None:

        html_content = await get_html_content(core=self.core, url=self.url)
        assert isinstance(html_content, str)

        if region_locked_pattern.search(html_content):
            logger.warning(f"Video {self.url} is region blocked")
            raise RegionBlocked(f"The Video: {self.url} is not available in your region!")

        variants_url = await asyncio.to_thread(self._extract_variants_url, html_content)
        variants_json_str = await get_html_content(core=self.core, url=variants_url)
        assert isinstance(variants_json_str, str)
        variants = json.loads(variants_json_str)

        try:
            self.m3u8_base_url = build_master_playlist(variants)
            self.is_hls = True
            logger.debug(f"Video {self.url} is using HLS stream")

        except ValueError:
            self.m3u8_base_url = pick_best_mp4(variants)
            self.is_hls = False
            logger.debug(f"Video {self.url} is using raw MP4 stream")

        data: dict = await asyncio.to_thread(self._extract_data, html_content)
        allowed_fields = {field.name for field in fields(self)}
        for key, value in data.items():
            if key in allowed_fields:
                setattr(self, key, value)

        logger.debug(f"Finished extracting attributes for Video: {self.title}")


    @staticmethod
    def _extract_variants_url(html_content: str) -> str:
        """Runs in a background thread to prevent regex from blocking the async loop."""
        media_definitions = re.search(r'mediaDefinition:\s*(.*?)\s*poster:', html_content,
                                      re.DOTALL | re.IGNORECASE).group(1)
        url = re.search(r'videoUrl":"(.*?)"', media_definitions).group(1).replace('\\', '')
        return url

    @staticmethod
    def _extract_data(html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)
        title = parser.css_first("h1.videoTitle.tm_videoTitle").text(strip=True)
        length = re.search(r'"duration":"(.*?)"', html_content).group(1).replace("PT", "").replace("S", "").strip()
        rating = parser.css_first("span.tm_rating_percent").text(strip=True)
        views = parser.css_first("span.infoValue.tm_infoValue").text(strip=True)

        publish_date = parser.css_first("span.publishedDate").text(strip=True)
        author_link = f'https://youporn.com{parser.css_first("div.submitByLink > a").attributes.get("href")}'

        thumbnail = re.search(r"poster: '(.*?)'", html_content).group(1)
        categories_ = parser.css("a.button.bubble-button.categories-tags.tm_carousel_tag.js-pop")
        categories = []

        for category in categories_:
            categories.append(category.text(strip=True))

        pornstars_ = parser.css("a.metaDataPornstarLink.tm_pornstar_link")
        urls = []

        for pornstar_object in pornstars_:
            url = pornstar_object.attributes.get("href")
            urls.append(url)

        return {
            "title": title,
            "length": length,
            "rating": rating,
            "views": views,
            "publish_date": publish_date,
            "author_link": author_link,
            "thumbnail": thumbnail,
            "categories": categories,
            "pornstars_urls": urls
        }


    @property
    async def pornstars(self, html: bool = True) -> AsyncGenerator[Pornstar, None]:
        logger.info(f"Getting pornstars for Video: {self.title}")
        for url in cast(list[str], self.pornstars_urls):
            star = Pornstar(url=f"https://www.youporn.com{url}", core=self.core)

            yield await star.load(html=html)

    async def download(self, configuration: DownloadConfigHLS, backup_configuration: DownloadConfigRAW | None = None
                       ) -> bool | DownloadReport:
        """
        :param configuration:
        :param backup_configuration:
        :return:
        """
        config = copy.deepcopy(configuration)
        config_backup = copy.deepcopy(backup_configuration)
        logger.info(f"Starting download for video: {self.title or self.url}")
        if not config.no_title:
            config.path = os.path.join(config.path, f"{self.title}.mp4")

            if config_backup:
                config_backup.path = os.path.join(config_backup.path, f"{self.title}.mp4")

        config.m3u8_base_url = self.m3u8_base_url

        if not self.is_hls:
            assert isinstance(config_backup, DownloadConfigRAW), """
            The video you choose to download does not have an HLS stream. I tried falling back to raw video
            downloading over direct download links, but you did not provide a configuration for this case.

            Please supply a DownloadConfigRAW for the 'back_configuration' argument in this download function.
            Thanks :)
            """
            try:
                logger.info(f"Falling back to legacy download for video: {self.title or self.url}")
                return await self.core.legacy_download(configuration=config_backup, url=self.m3u8_base_url)

            except Exception as e:
                logger.error(f"Legacy download failed for video {self.title or self.url}: {e}")
                raise DownloadFailed(str(e))

        try:
            return await self.core.download(configuration=config)
        except Exception as e:
            logger.error(f"Download failed for video {self.title or self.url}: {e}")
            raise DownloadFailed(str(e))

    async def author(self, load_html: bool = True) -> Pornstar | Channel:
        link = cast(str, self.author_link)
        logger.info(f"Fetching author for video {self.title or self.url}: {link}")
        if "channel" in link:
            channel = Channel(url=link, core=self.core)
            return await channel.load(html=load_html)

        else:
            pornstar = Pornstar(url=link, core=self.core)
            return await pornstar.load(html=load_html)


class Client:
    def __init__(self, core: BaseCore = BaseCore()):
        self.core = core
        self.core.initialize_session()
        assert isinstance(self.core.session, AsyncSession)
        self.core.session.headers.update(headers)

    async def get_video(self, url: str, load_html: bool = True) -> Video:
        video = Video(url=url, core=self.core)
        return await video.load(html=load_html)

    async def get_pornstar(self, url: str, load_html: bool = True) -> Pornstar:
        pornstar = Pornstar(url=url, core=self.core)
        return await pornstar.load(html=load_html)

    async def get_channel(self, url: str, load_html: bool = True) -> Channel:
        channel = Channel(url=url, core=self.core)
        return await channel.load(html=load_html)

    async def get_collection(self, url: str, load_html: bool = True) -> Collection:
        collection = Collection(url=url, core=self.core)
        return await collection.load(html=load_html)

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
                      on_video_error: on_error_hint = on_error,
                      on_page_error: on_error_hint = None,
                      keep_original_order: bool = False,
                      fetch_html: bool = False,
                      ) -> AsyncGenerator[ScrapeResult, None]:
        # Define basic filters
        query = query.replace(" ", "+")
        res = ""
        min_minutes = ""
        max_minutes = ""

        query = f"query={query}&"

        filter = "/search/?"

        if filter_relevance:
            filter = f"/search/{filter_relevance}/?"

        if filter_resolution:
            res = f"res={filter_resolution}&"

        if filter_duration_minimum:
            min_minutes = f"min_minutes={filter_duration_minimum}&"

        if filter_duration_maximum:
            max_minutes = f"max_minutes={filter_duration_maximum}&"

        page_urls = [
            f"https://www.youporn.com{filter}{query}{res}{min_minutes}{max_minutes}page={page}"
            for page in range(1, pages + 1)
        ]

        helper = Helper(core=self.core, constructor=Video)
        videos_concurrency = videos_concurrency or self.core.configuration.videos_concurrency
        pages_concurrency = pages_concurrency or self.core.configuration.pages_concurrency
        assert videos_concurrency and pages_concurrency
        async for result in helper.iterator(target_page_urls=page_urls, max_video_concurrency=videos_concurrency, max_page_concurrency=pages_concurrency,
                                 video_link_extractor=extractor_html, keep_original_order=keep_original_order,
                                 on_video_error=on_video_error, on_page_error=on_page_error, fetch_html=fetch_html):
            yield result
