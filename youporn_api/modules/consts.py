import re
from selectolax.lexbor import LexborHTMLParser


headers = {
    "Referer": "https://www.youporn.com/"
}

region_locked_pattern = re.compile(
    r'<div\s+class="geo-blocked-content">\s*This page is not available in your location\.\s*</div>',
    re.DOTALL | re.IGNORECASE)

# Map vertical "quality" to (width, height)
RES_BY_QUALITY = {
    1080: (1920, 1080),
    720:  (1280, 720),
    480:  (854, 480),
    360:  (640, 360),
    240:  (426, 240),
}

# Fallback average bandwidths (in bits per second) if none can be parsed from URL
BPS_FALLBACK = {
    1080: 5000_000,
    720:  3500_000,
    480:  2000_000,
    360:  1000_000,
    240:  500_000,
}

def extractor_html(content: str):
    results = []
    lexbor = LexborHTMLParser(content)
    selector = "article.video-box.pc.js_video-box.js-pop"
    try:
        main_container = lexbor.css_first("div.full-row-thumbs")
        videos_container = main_container.css(selector)

    except AttributeError:
        main_container = lexbor.css_first("div.three-thumbs-row")
        videos_container = main_container.css(selector)

    # Fetch content from HTML, if page = 0, to reduce one network request
    for video_object in videos_container:
        url = f'https://youporn.com{video_object.css_first("a").attributes.get("href")}'
        video_id = video_object.attributes.get("data-video-id")
        uploader_id = video_object.attributes.get("data-uploader-id")
        uploader_status = video_object.attributes.get("data-uploader-status")
        uploader_type = video_object.attributes.get("data-uploader-type")
        uploader_name = video_object.attributes.get("data-uploader-name")
        title = video_object.attributes.get("aria-label")
        author_link = f"https://www.youporn.com{video_object.css_first('a.author-title-text').attributes.get('href')}"
        pornstars_urls = [f"https://youporn.com{stuff.attributes.get('href')}" for stuff in video_object.css("a.channel-performer")]
        info_views = video_object.css("span.info-views")
        if len(info_views) >= 2:
            views = info_views[0].text(strip=True).replace("Views:", "").strip()
            rating = info_views[1].text(strip=True).replace("Rating:", "").strip()
        else:
            views, rating = None, None
        results.append({
            "url": url,
            "video_id": video_id,
            "uploader_id": uploader_id,
            "uploader_status": uploader_status,
            "uploader_type": uploader_type,
            "uploader_name": uploader_name,
            "title": title,
            "author_link": author_link,
            "pornstars_urls": pornstars_urls,
            "views": views,
            "rating": rating
        })

    return results

def parse_bitrate_from_url(url: str) -> int | None:
    """
    Try to pull something like 4000K or 2000k out of the URL and convert to bps.
    """
    m = re.search(r'(\d+)\s*[kK](?![a-zA-Z])', url)
    if m:
        return int(m.group(1)) * 1000
    return None


def variant_key(item: dict) -> tuple[int, int]:
    """
    Sort key: default first (False>True trick with tuple), then by quality descending.
    We invert defaultQuality so True sorts before False.
    """
    return 0 if item.get("defaultQuality") else 1, -(int(item.get("quality", 0)))


def build_master_playlist(variants: list[dict]) -> str:
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


def pick_best_mp4(variants: list[dict]) -> str | None:
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
