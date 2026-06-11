import re

from bs4 import BeautifulSoup

try:
    import lxml
    parser = "lxml"

except (ModuleNotFoundError, ImportError):
    parser = "html.parser"

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
    video_urls = []
    soup = BeautifulSoup(content, parser)
    try:
        main_container = soup.find("div", class_="full-row-thumbs")
        videos_container = main_container.find_all("article", class_="video-box pc js_video-box js-pop")

    except AttributeError:
        main_container = soup.find("div", class_="three-thumbs-row")
        videos_container = main_container.find_all("article", class_="video-box pc js_video-box js-pop")

    # Fetch content from HTML, if page = 0, to reduce one network request
    for video_object in videos_container:
        video_urls.append(f'https://youporn.com{video_object.find("a")["href"]}')

    return video_urls