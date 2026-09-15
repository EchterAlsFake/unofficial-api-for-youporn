from __future__ import annotations

import re
import json
import asyncio
import logging
import argparse
from urllib.parse import unquote

from youporn_api.modules import errors as provider_errors
from base_api.modules.provider import fetch_content, download_errors, prepare_download_config
from base_api.modules.logger import configure_app_logging, get_logger

from base_api.modules.static_functions import str_to_bool

from dataclasses import dataclass
from curl_cffi import AsyncSession
from selectolax.lexbor import LexborHTMLParser
from typing import AsyncGenerator, ClassVar, Literal
from base_api.modules.type_hints import DownloadReport
from base_api.modules.config import IteratorConfig
from base_api import (
    BaseCore,
    BaseMedia,
    DownloadConfigHLS,
    DownloadConfigRAW,
    ErrorAction,
    ErrorMode,
    Helper,
    MediaLoadError,
    MediaLoadErrors,
    RetryPolicy,
    ScrapeErrorContext,
    ScrapeResult,
    media_field,
    make_iterator_config,
    is_resource_gone,
    default_on_error,
    scrape_stream,
)

from youporn_api.modules.consts import (extractor_html, region_locked_pattern, headers, build_master_playlist,
                                        pick_best_mp4)
from youporn_api.modules.errors import (VideoUnavailable, NetworkError, ProxyError, BotDetection, UnknownNetworkError,
                                        RegionBlocked, DownloadFailed)


logger = get_logger(__name__)


_contains_resource_gone = is_resource_gone
on_error = default_on_error


async def get_html_content(core: BaseCore, url: str, *, owner=None) -> str:
    return await fetch_content(core, url, logger=logger, owner=owner,
                               error_types=provider_errors, not_found_error=VideoUnavailable)


@dataclass(slots=True, kw_only=True)
class BaseProfile(BaseMedia):
    url: str
    core: BaseCore
    name: str | None = media_field("html")
    avatar: str | None = media_field("html")
    banner: str | None = media_field("html")
    description: str | None = media_field("html")

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}

    async def _load_html(self) -> dict[str, object]:
        logger.info(f"Loading {self.__class__.__name__} HTML from {self.url}")
        html_content = await get_html_content(core=self.core, url=self.url, owner=self)
        logger.debug(f"Received HTML Content for: {self.url}")
        return await asyncio.to_thread(self._extract_data, html_content)

    def _extract_common_header(self, parser: LexborHTMLParser) -> dict:
        entity_name = self.__class__.__name__.lower()
        name_node = parser.css_first("h1.name-title") or parser.css_first("h1")
        if name_node:
            name = name_node.text(strip=True).replace("Subscribe", "").strip()
        elif btn := parser.css_first("button.js_subscribe_btn[data-entityname]"):
            name = btn.attributes.get("data-entityname")
        else:
            logger.error("Failed to extract name from %s page: %s", entity_name, self.url)
            name = None

        avatar_img = (
            parser.css_first("div.header-banner-wrapper div.avatar-wrapper img")
            or parser.css_first("div.header-banner-wrapper div.logo-wrapper img")
            or parser.css_first("img.userAvatar")
        )
        avatar = (avatar_img.attributes.get("data-src") or avatar_img.attributes.get("src")) if avatar_img else None
        if not avatar:
            logger.error("Failed to extract avatar from %s page: %s", entity_name, self.url)

        banner_img = parser.css_first("div.header-banner-wrapper div.banner-wrapper img")
        banner = (banner_img.attributes.get("data-src") or banner_img.attributes.get("src")) if banner_img else None
        if not banner:
            logger.error("Failed to extract banner from %s page: %s", entity_name, self.url)

        desc_node = parser.css_first("div.profile-bio.channel-description") or parser.css_first("div.profile-bio")
        description = desc_node.text(strip=True) if desc_node else None
        if not description:
            logger.error("Failed to extract description from %s page: %s", entity_name, self.url)

        return {
            "name": name,
            "avatar": avatar,
            "banner": banner,
            "description": description,
        }

    def _extract_stats_bar(self, parser: LexborHTMLParser) -> dict[str, str]:
        stats = {}
        info_box = parser.css_first("div.main-stats-bar")
        if info_box:
            for stat in info_box.css("li.info-stat"):
                label_node = stat.css_first("p.info-stat-label")
                data_node = stat.css_first("p.info-stat-data")
                if label_node and data_node:
                    label = label_node.text(strip=True).lower()
                    val = data_node.text(strip=True)
                    if "rank" in label:
                        stats["rank"] = val
                    elif "view" in label:
                        stats["views"] = val
                    elif "subscriber" in label:
                        stats["subscribers"] = val
                    elif "video" in label:
                        stats["videos"] = val

            data_elements = info_box.css("p.info-stat-data")
            if "rank" not in stats and len(data_elements) > 0:
                stats["rank"] = data_elements[0].text(strip=True)
            if "views" not in stats and len(data_elements) > 1:
                stats["views"] = data_elements[1].text(strip=True)
            if "subscribers" not in stats and len(data_elements) > 2:
                stats["subscribers"] = data_elements[2].text(strip=True)
            if "videos" not in stats and len(data_elements) > 3:
                stats["videos"] = data_elements[3].text(strip=True)
        else:
            logger.error("Failed to find main-stats-bar on %s page: %s", self.__class__.__name__.lower(), self.url)
        return stats

    def videos(
        self,
        pages: int = 2,
        iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult[Video], None]:
        base_url = self.url.rstrip("/")
        page_urls = [f"{base_url}/?page={page}" for page in range(1, pages + 1)]
        logger.info(f"Requesting {self.__class__.__name__.lower()} videos from urls: {page_urls}")
        if iterator_config is None:
            iterator_config = make_iterator_config()

        return scrape_stream(
            core=self.core,
            constructor=Video,
            target_page_urls=page_urls,
            item_extractor=extractor_html,
            iterator_config=iterator_config,
        )


@dataclass(slots=True, kw_only=True)
class Channel(BaseProfile):
    channel_rank: str | None = media_field("html")
    total_videos_count: str | None = media_field("html")
    channel_view_count: str | None = media_field("html")
    channel_subscribers_count: str | None = media_field("html")
    channel_id: str | None = media_field("html")
    join_url: str | None = media_field("html")

    @property
    def rank(self) -> str | None:
        return self.channel_rank

    @property
    def view_count(self) -> str | None:
        return self.channel_view_count

    @property
    def subscribers_count(self) -> str | None:
        return self.channel_subscribers_count

    @property
    def entity_id(self) -> str | None:
        return self.channel_id

    def _extract_data(self, html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)
        common = self._extract_common_header(parser)
        stats = self._extract_stats_bar(parser)

        channel_rank = stats.get("rank")
        channel_view_count = stats.get("views")
        channel_subscribers_count = stats.get("subscribers")
        total_videos_count = stats.get("videos")

        if not channel_rank:
            logger.error("Failed to extract channel_rank from channel page: %s", self.url)
        if not channel_view_count:
            logger.error("Failed to extract channel_view_count from channel page: %s", self.url)
        if not channel_subscribers_count:
            logger.error("Failed to extract channel_subscribers_count from channel page: %s", self.url)
        if not total_videos_count:
            logger.error("Failed to extract total_videos_count from channel page: %s", self.url)

        btn = parser.css_first("button.js_subscribe_btn")
        channel_id = btn.attributes.get("data-entityid") if btn else None
        if not channel_id:
            if modal := parser.css_first("v-channel-flag-modal[item-id]"):
                channel_id = modal.attributes.get("item-id")
        if not channel_id:
            logger.error("Failed to extract channel_id from channel page: %s", self.url)

        join_btn = parser.css_first("button.join-us a.join-wrapper") or parser.css_first("a.join-wrapper")
        join_url = join_btn.attributes.get("href") if join_btn else None
        if not join_url:
            logger.error("Failed to extract join_url from channel page: %s", self.url)

        return {
            **common,
            "channel_rank": channel_rank,
            "total_videos_count": total_videos_count,
            "channel_view_count": channel_view_count,
            "channel_subscribers_count": channel_subscribers_count,
            "channel_id": channel_id,
            "join_url": join_url,
        }


@dataclass(slots=True, kw_only=True)
class Collection(BaseMedia):
    url: str
    core: BaseCore
    name: str | None = media_field("html")
    rating: str | None = media_field("html")
    total_videos_count: str | None = media_field("html")
    view_count: str | None = media_field("html")
    last_updated: str | None = media_field("html")

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}

    async def _load_html(self) -> dict[str, object]:
        logger.info(f"Loading Collection HTML from {self.url}")
        html_content = await get_html_content(core=self.core, url=self.url, owner=self)
        data = await asyncio.to_thread(self._extract_data, html_content)
        logger.debug("Finished extracting attributes for Collection")
        return data

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

    def videos(
        self,
        pages: int = 2,
        iterator_config: IteratorConfig | None = None,
    ) -> AsyncGenerator[ScrapeResult[Video], None]:

        url = self.url
        page_urls = [f"{url}?page={page}" for page in range(1, pages + 1)]
        logger.info(f"Requesting collection videos from urls: {page_urls}")
        if iterator_config is None:
            iterator_config = make_iterator_config()

        return scrape_stream(
            core=self.core,
            constructor=Video,
            target_page_urls=page_urls,
            item_extractor=extractor_html,
            iterator_config=iterator_config,
        )

@dataclass(slots=True, kw_only=True)
class Pornstar(BaseProfile):
    profile_info: dict | None = media_field("html")
    pornstar_id: str | None = media_field("html")
    pornstar_rank: str | None = media_field("html")
    subscribers_count: str | None = media_field("html")
    view_count: str | None = media_field("html")
    official_site: str | None = media_field("html")
    more_of_me: str | None = media_field("html")
    featured_in: list[str] | None = media_field("html")

    @property
    def rank(self) -> str | None:
        return self.pornstar_rank

    @property
    def pornstar_subscribers_count(self) -> str | None:
        return self.subscribers_count

    @property
    def pornstar_view_count(self) -> str | None:
        return self.view_count

    @property
    def entity_id(self) -> str | None:
        return self.pornstar_id

    def _extract_data(self, html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)
        common = self._extract_common_header(parser)
        stats = self._extract_stats_bar(parser)

        pornstar_rank = stats.get("rank")
        if not pornstar_rank:
            logger.error("Failed to extract pornstar_rank from pornstar page: %s", self.url)

        view_count = stats.get("views")
        if not view_count:
            logger.error("Failed to extract view_count from pornstar page: %s", self.url)

        subscribers_count = stats.get("subscribers")
        if not subscribers_count:
            logger.error("Failed to extract subscribers_count from pornstar page: %s", self.url)

        btn = parser.css_first("button.js_subscribe_btn")
        pornstar_id = btn.attributes.get("data-entityid") if btn else None
        if not pornstar_id:
            if match := re.search(r"button_pornstar_(\d+)", html_content):
                pornstar_id = match.group(1)
        if not pornstar_id:
            logger.error("Failed to extract pornstar_id from pornstar page: %s", self.url)

        official_site_node = parser.css_first("div.main-stats-bar a.social-link") or parser.css_first("a.social-link")
        official_site = official_site_node.attributes.get("href") if official_site_node else None

        more_node = parser.css_first("div.profile-more-of-me a")
        more_of_me = None
        if more_node and (href := more_node.attributes.get("href")):
            if href.startswith("/redirect/"):
                more_of_me = unquote(href.removeprefix("/redirect/"))
            else:
                more_of_me = href

        featured_in = list(dict.fromkeys(
            a.text(strip=True)
            for a in parser.css("div.known-for-wrapper a")
            if a.text(strip=True)
        ))

        profile_info = {}
        if ul_profile := parser.css_first("ul.profile-info"):
            for tag in ul_profile.css("li.info-stat"):
                label_node = tag.css_first("p.info-stat-label")
                data_node = tag.css_first("p.info-stat-data")
                if label_node and data_node:
                    profile_info[label_node.text(strip=True)] = data_node.text(strip=True)
                else:
                    stuff = tag.css("p")
                    if len(stuff) >= 2:
                        profile_info[stuff[0].text(strip=True)] = stuff[1].text(strip=True)

        return {
            **common,
            "profile_info": profile_info,
            "pornstar_id": pornstar_id,
            "pornstar_rank": pornstar_rank,
            "subscribers_count": subscribers_count,
            "view_count": view_count,
            "official_site": official_site,
            "more_of_me": more_of_me,
            "featured_in": featured_in,
        }


@dataclass(kw_only=True, slots=True)
class User(BaseMedia):
    url: str
    core: BaseCore
    name: str | None = media_field("html")
    collection_urls: list[str] | None = media_field("html")

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}

    async def _load_html(self) -> dict[str, object]:
        logger.info(f"Loading User HTML from {self.url}")
        html_content = await get_html_content(core=self.core, url=self.url, owner=self)
        return await asyncio.to_thread(self._extract_data, html_content)

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
        collection_urls = await self.get_field("collection_urls")
        logger.info(f"Getting collections for User: {self.name or self.url}")
        for collection_url in collection_urls:
            collection = Collection(url=collection_url, core=self.core)
            if load_html:
                await collection.load_sources("html")
            yield collection


@dataclass(slots=True, kw_only=True)
class Video(BaseMedia):
    url: str
    core: BaseCore
    title: str | None = media_field("html")
    publish_date: str | None = media_field("html")
    length: str | None = media_field("html")
    rating: str | None = media_field("html")
    views: str | None = media_field("html")
    thumbnail: str | None = media_field("html")
    categories: list[str] | None = media_field("html")
    tags: list[str] | None = media_field("html")
    m3u8_base_url: str | None = media_field("html")
    author_link: str | None = media_field("html")
    pornstars_urls: list[str] | None = media_field("html")

    # Available from HTML or iterator
    uploader_id: str | None = media_field("html", default=None)
    uploader_status: str | None = None
    uploader_type: str | None = media_field("html", default=None)
    uploader_name: str | None = media_field("html", default=None)
    video_id: str | None = media_field("html", default=None)

    # You don't need this
    is_hls: bool | None = media_field("html")

    loader_methods: ClassVar[dict[str, str]] = {"html": "_load_html"}

    async def _load_html(self) -> dict[str, object]:

        logger.info(f"Loading Video HTML from {self.url}")
        html_content = await get_html_content(core=self.core, url=self.url, owner=self)

        if region_locked_pattern.search(html_content):
            logger.warning(f"Video {self.url} is region blocked")
            raise RegionBlocked(f"The Video: {self.url} is not available in your region!")

        variants_url = await asyncio.to_thread(self._extract_variants_url, html_content)
        m3u8_base_url = None
        is_hls = None

        if not variants_url:
            logger.error("Failed to extract variants URL for video %s", self.url)
        else:
            try:
                variants_json_str = await get_html_content(core=self.core, url=variants_url, owner=self)
                variants = json.loads(variants_json_str)

                try:
                    m3u8_base_url = build_master_playlist(variants)
                    is_hls = True
                    logger.debug(f"Video {self.url} is using HLS stream")

                except ValueError:
                    logger.warning("Failed to build HLS playlist for %s; trying MP4 variants from %s", self.url, variants_url, exc_info=True)
                    m3u8_base_url = pick_best_mp4(variants)
                    is_hls = False
                    logger.debug(f"Video {self.url} is using raw MP4 stream", exc_info=True)
            except Exception as e:
                logger.exception("Failed to load video stream variants for %s: %s", self.url, e)

        data: dict = await asyncio.to_thread(self._extract_data, html_content)
        data["m3u8_base_url"] = m3u8_base_url
        data["is_hls"] = is_hls
        logger.debug(f"Finished extracting attributes for Video: {data.get('title')}")
        return data


    @staticmethod
    def _extract_variants_url(html_content: str) -> str | None:
        """Runs in a background thread to prevent regex from blocking the async loop."""
        media_definitions_match = re.search(r'mediaDefinition:\s*(.*?)\s*poster:', html_content,
                                            re.DOTALL | re.IGNORECASE)
        if media_definitions_match:
            url_match = re.search(r'videoUrl":"(.*?)"', media_definitions_match.group(1))
            if url_match:
                return url_match.group(1).replace('\\', '')

        alt_match = re.search(r'"mediaDefinitions":\s*\[.*?"videoUrl":"(.*?)".*?\]', html_content, re.DOTALL)
        if alt_match:
            return alt_match.group(1).replace('\\', '')

        return None

    def _extract_data(self, html_content: str) -> dict:
        parser = LexborHTMLParser(html_content)

        title_node = parser.css_first("h1.videoTitle.tm_videoTitle") or parser.css_first("h1.videoTitle")
        if title_node:
            title = title_node.text(strip=True)
        else:
            logger.error("Failed to extract title from video page: %s", self.url)
            title = None

        length = None
        if match := re.search(r'"video_duration":\s*"(\d+)"', html_content):
            length = match.group(1)
        elif match := re.search(r'mainRoll:.*?duration:\s*[\'"](\d+)[\'"]', html_content, re.DOTALL):
            length = match.group(1)
        elif match := re.search(r'"duration":\s*"PT(\d+)S"', html_content):
            length = match.group(1)
        elif dur_node := parser.css_first("span.mgp_duration"):
            length = dur_node.text(strip=True)

        if not length:
            logger.error("Failed to extract length from video page: %s", self.url)

        rating_node = parser.css_first("span.tm_rating_percent")
        if rating_node:
            rating = rating_node.text(strip=True)
        else:
            logger.error("Failed to extract rating from video page: %s", self.url)
            rating = None

        views_node = parser.css_first("span.infoValue.tm_infoValue")
        if views_node:
            views = views_node.text(strip=True)
        else:
            logger.error("Failed to extract views from video page: %s", self.url)
            views = None

        publish_date_node = parser.css_first("span.publishedDate")
        if publish_date_node:
            publish_date = publish_date_node.text(strip=True)
        else:
            logger.error("Failed to extract publish_date from video page: %s", self.url)
            publish_date = None

        author_node = parser.css_first("div.submitByLink > a")
        if author_node and (href := author_node.attributes.get("href")):
            author_link = f"https://www.youporn.com{href}" if href.startswith("/") else href
        else:
            logger.error("Failed to extract author_link from video page: %s", self.url)
            author_link = None

        thumbnail = None
        if match := re.search(r"poster:\s*['\"](.*?)['\"]", html_content):
            thumbnail = match.group(1)
        elif match := re.search(r'"image_url":\s*"(.*?)"', html_content):
            thumbnail = match.group(1).replace(r"\/", "/")
        elif poster_img := parser.css_first("img.videoElementPoster"):
            thumbnail = poster_img.attributes.get("src")

        if not thumbnail:
            logger.error("Failed to extract thumbnail from video page: %s", self.url)

        categories = [
            c.text(strip=True)
            for c in (parser.css("div.js_categoriesWrapper a.categories-tags") or parser.css("a.categories-tags"))
            if c.text(strip=True)
        ]

        wrapper = parser.css_first("div.js_categoriesWrapper") or parser.css_first("div.video-tags-carousel")
        tags = [
            t.text(strip=True)
            for t in (wrapper.css("a[href*='/porntags/'], a[href*='/tags/']") if wrapper else parser.css("a.bubble-porntag[href*='/porntags/']"))
            if t.text(strip=True)
        ]

        pornstars_ = parser.css("a.metaDataPornstarLink.tm_pornstar_link") or parser.css("div#metaDataPornstarInfo a")
        urls = [href for p in pornstars_ if (href := p.attributes.get("href"))]

        video_id = self.video_id
        if not video_id:
            if v_node := (parser.css_first("[data-video-id]") or parser.css_first("[data-videoid]")):
                video_id = v_node.attributes.get("data-video-id") or v_node.attributes.get("data-videoid")
            elif match := re.search(r'videoId\s*=\s*(\d+)', html_content):
                video_id = match.group(1)
            elif match := re.search(r'/watch/(\d+)', getattr(self, "url", "")):
                video_id = match.group(1)

        btn = parser.css_first("button.js_subscribe_btn")
        uploader_id = self.uploader_id or (btn.attributes.get("data-entityid") if btn else None)
        uploader_name = (
            self.uploader_name
            or (author_node.text(strip=True) if author_node else None)
            or (btn.attributes.get("data-entityname") if btn else None)
        )
        uploader_type = self.uploader_type or (btn.attributes.get("data-entitytype") if btn else None)
        if not uploader_type and author_link:
            if "/channel/" in author_link:
                uploader_type = "channel"
            elif "/pornstar/" in author_link:
                uploader_type = "pornstar"
            elif "/amateur/" in author_link:
                uploader_type = "amateur"

        return {
            "title": title,
            "length": length,
            "rating": rating,
            "views": views,
            "publish_date": publish_date,
            "author_link": author_link,
            "thumbnail": thumbnail,
            "categories": categories,
            "tags": tags,
            "pornstars_urls": urls,
            "video_id": video_id,
            "uploader_id": uploader_id,
            "uploader_name": uploader_name,
            "uploader_type": uploader_type,
        }


    @property
    async def pornstars(self, html: bool = True) -> AsyncGenerator[Pornstar, None]:
        pornstars_urls = await self.get_field("pornstars_urls") or []
        logger.info(f"Getting pornstars for Video: {self.title}")
        for url in pornstars_urls:
            star_url = url if url.startswith("http") else f"https://www.youporn.com{url}"
            star = Pornstar(url=star_url, core=self.core)
            if html:
                await star.load_sources("html")
            yield star

    @download_errors(DownloadFailed)
    async def download(self, configuration: DownloadConfigHLS, backup_configuration: DownloadConfigRAW | None = None
                       ) -> bool | DownloadReport:
        await self.load_fields("title", "m3u8_base_url", "is_hls")
        if not self.m3u8_base_url:
            raise DownloadFailed(f"Download failed for {self.url}: No stream URL available")
        config = prepare_download_config(configuration, self.title)
        config_backup = (prepare_download_config(backup_configuration, self.title)
                         if backup_configuration is not None else None)
        logger.info(f"Starting download for video: {self.title or self.url}")
        config.m3u8_base_url = self.m3u8_base_url

        if not self.is_hls:
            assert isinstance(config_backup, DownloadConfigRAW), """
            The video you choose to download does not have an HLS stream. I tried falling back to raw video
            downloading over direct download links, but you did not provide a configuration for this case.

            Please supply a DownloadConfigRAW for the 'back_configuration' argument in this download function.
            Thanks :)
            """
            logger.info(f"Falling back to legacy download for video: {self.title or self.url}")
            return await self.core.legacy_download(configuration=config_backup, url=self.m3u8_base_url)

        return await self.core.download(configuration=config)

    async def author(self, load_html: bool = True) -> Pornstar | Channel:
        link = await self.get_field("author_link")
        if not isinstance(link, str):
            raise ValueError(f"No author link found for {self.url}")
        logger.info(f"Fetching author for video {self.title or self.url}: {link}")
        if "channel" in link:
            channel = Channel(url=link, core=self.core)
            if load_html:
                await channel.load_sources("html")
            return channel

        else:
            pornstar = Pornstar(url=link, core=self.core)
            if load_html:
                await pornstar.load_sources("html")
            return pornstar


class Client:
    def __init__(self, core: BaseCore | None = None):
        if core is None:
            core = BaseCore()
        self.core = core
        self.core.initialize_session()
        assert isinstance(self.core.session, AsyncSession)
        self.core.session.headers.update(headers)

    async def get_video(self, url: str, load_html: bool = True) -> Video:
        video = Video(url=url, core=self.core)
        if load_html:
            await video.load_sources("html")
        return video

    async def get_pornstar(self, url: str, load_html: bool = True) -> Pornstar:
        pornstar = Pornstar(url=url, core=self.core)
        if load_html:
            await pornstar.load_sources("html")
        return pornstar

    async def get_channel(self, url: str, load_html: bool = True) -> Channel:
        channel = Channel(url=url, core=self.core)
        if load_html:
            await channel.load_sources("html")
        return channel

    async def get_collection(self, url: str, load_html: bool = True) -> Collection:
        collection = Collection(url=url, core=self.core)
        if load_html:
            await collection.load_sources("html")
        return collection

    def search_videos(self, query: str, pages: int = 0,
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
                      iterator_config: IteratorConfig | None = None,
                      ) -> AsyncGenerator[ScrapeResult[Video], None]:
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

        if iterator_config is None:
            iterator_config = make_iterator_config()

        return scrape_stream(
            core=self.core,
            constructor=Video,
            target_page_urls=page_urls,
            item_extractor=extractor_html,
            iterator_config=iterator_config,
        )


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YouPorn API Command Line Interface")
    parser.add_argument("--download", metavar="URL", type=str, help="URL to download from")
    parser.add_argument("--quality", metavar="best|half|worst", type=str, default="best", help="The video quality (best, half, worst)")
    parser.add_argument("--file", metavar="FILE", type=str, help="(Optional) Specify a file with URLs (separated with new lines)")
    parser.add_argument("--output", metavar="DIR", type=str, required=True, help="The output path (with filename or directory)")
    parser.add_argument("--no-title", metavar="True,False", type=str, nargs="?", const="True", default="False",
                        help="Whether to apply video title automatically to output path or not")
    return parser


async def run_main(args_list: list[str] | None = None):
    parser = create_parser()
    args = parser.parse_args(args_list)
    no_title = str_to_bool(args.no_title) if isinstance(args.no_title, str) else bool(args.no_title)
    config = DownloadConfigHLS(quality=args.quality, path=args.output, no_title=no_title)
    raw_config = DownloadConfigRAW(quality=args.quality, path=args.output, no_title=no_title)

    urls: list[str] = []
    if args.download:
        urls.append(args.download)
    if args.file:
        with open(args.file, "r") as f:
            urls.extend([line.strip() for line in f if line.strip()])

    if not urls:
        parser.print_help()
        return

    client = Client()
    for url in urls:
        print(f"Fetching video information for: {url}")
        try:
            video = await client.get_video(url, load_html=True)
            title = getattr(video, "title", None) or url
            print(f"Starting download for: {title}")
            await video.download(configuration=config, backup_configuration=raw_config)
            print(f"Download complete: {title}")
        except Exception as e:
            logger.exception("CLI failed while processing %s", url)
            print(f"Error downloading {url}: {e}")


def main():
    configure_app_logging(level=logging.INFO)
    try:
        asyncio.run(run_main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")


if __name__ == "__main__":
    main()
