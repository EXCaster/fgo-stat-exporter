"""仅从公开图片源读取有界内容，不携带账号信息或继承代理。"""

import asyncio
import re
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from fgo_stat_core.contracts.models import CaptureError

__all__ = ["ImageDownloader", "PublicImageDownloader"]


class ImageDownloader(Protocol):
    async def fetch(self, url: str) -> bytes: ...


class PublicImageDownloader:
    def __init__(self, *, limit: int = 4 * 1024 * 1024, timeout: float = 25):
        self.limit, self.timeout = limit, timeout

    async def fetch(self, url: str) -> bytes:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "static.atlasacademy.io"
            or parsed.query
            or parsed.fragment
            or ".." in parsed.path
            or not re.fullmatch(r"/(?:CN|JP)/[A-Za-z]+/[A-Za-z0-9_/@.-]+\.png", parsed.path)
        ):
            raise CaptureError("REPORT_IMAGE_SOURCE_REJECTED")
        try:
            async with asyncio.timeout(self.timeout):
                async with httpx.AsyncClient(
                    trust_env=False,
                    follow_redirects=False,
                    timeout=self.timeout,
                ) as client:
                    async with client.stream(
                        "GET",
                        url,
                        headers={
                            "Accept-Encoding": "identity",
                            "User-Agent": "FGOStatDesktop/0.3",
                        },
                    ) as response:
                        if response.status_code != 200:
                            raise CaptureError("REPORT_IMAGE_DOWNLOAD_FAILED")
                        length = response.headers.get("Content-Length")
                        if length is not None and (
                            not length.isdigit() or int(length) > self.limit
                        ):
                            raise CaptureError("REPORT_IMAGE_TOO_LARGE")
                        chunks, count = [], 0
                        async for chunk in response.aiter_bytes(64 * 1024):
                            count += len(chunk)
                            if count > self.limit:
                                raise CaptureError("REPORT_IMAGE_TOO_LARGE")
                            chunks.append(chunk)
                        if length is not None and count != int(length):
                            raise CaptureError("REPORT_IMAGE_DOWNLOAD_FAILED")
                        return b"".join(chunks)
        except (httpx.HTTPError, OSError, TimeoutError):
            raise CaptureError("REPORT_IMAGE_DOWNLOAD_FAILED") from None
