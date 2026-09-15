from base_api.modules.errors import (
    ScraperException,
    RegionBlocked,
    NotFound,
    NetworkError,
    BotDetection,
    ProxyError,
    UnknownNetworkError,
    DownloadFailed,
    VideoUnavailable,
)




class DataNotLoadedError(ScraperException):
    def __init__(self, msg):
        super().__init__(msg)
        self.msg = msg


__all__ = [
    "VideoUnavailable",
    "RegionBlocked",
    "NotFound",
    "NetworkError",
    "BotDetection",
    "ProxyError",
    "UnknownNetworkError",
    "DownloadFailed",
    "DataNotLoadedError",
]
