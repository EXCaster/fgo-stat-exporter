"""仅从公开图片源读取有界内容，不携带账号信息或继承代理。"""

import asyncio
import re
from contextlib import asynccontextmanager
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
        self._client = None
        self._source = ""
        self._choice = asyncio.Lock()

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            trust_env=False, follow_redirects=False, timeout=self.timeout
        )
        return self

    async def __aexit__(self, *_args):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @asynccontextmanager
    async def _connection(self):
        if self._client is not None:
            yield self._client
        else:
            async with httpx.AsyncClient(
                trust_env=False, follow_redirects=False, timeout=self.timeout
            ) as client:
                yield client

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
                if not self._source:
                    async with self._choice:
                        if not self._source:
                            return await self._choose(parsed.path)
                for host in (self._source, next(h for h in _SOURCES if h != self._source)):
                    try:
                        async with asyncio.timeout(self.timeout / 2):
                            raw = await self._read(host + parsed.path)
                        self._source = host
                        return raw
                    except (CaptureError, httpx.HTTPError, OSError, TimeoutError):
                        continue
                raise CaptureError("REPORT_IMAGE_DOWNLOAD_FAILED")
        except (httpx.HTTPError, OSError, TimeoutError):
            raise CaptureError("REPORT_IMAGE_DOWNLOAD_FAILED") from None

    async def _choose(self, path):
        async def read(host, delay):
            if delay:
                await asyncio.sleep(delay)
            return await self._read(host + path)

        # 原站正常时不请求镜像；连接较慢时再启用 Chaldea 官方国内线路。
        tasks = {
            asyncio.create_task(read(host, delay)): host
            for host, delay in zip(_SOURCES, (0, 1), strict=True)
        }
        pending = set(tasks)
        oversized = False
        try:
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    try:
                        raw = task.result()
                    except CaptureError as error:
                        oversized = oversized or error.code == "REPORT_IMAGE_TOO_LARGE"
                        continue
                    except (httpx.HTTPError, OSError, TimeoutError):
                        continue
                    self._source = tasks[task]
                    return raw
            raise CaptureError(
                "REPORT_IMAGE_TOO_LARGE" if oversized else "REPORT_IMAGE_DOWNLOAD_FAILED"
            )
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _read(self, url):
        async with self._connection() as client:
            request = client.build_request(
                "GET",
                url,
                headers={"Accept-Encoding": "identity", "User-Agent": "FGOStatDesktop/0.4"},
            )
            # 公共资源连接复用时仍不发送服务器设置的 Cookie 或认证头。
            for name in ("Cookie", "Authorization"):
                request.headers.pop(name, None)
            response = await client.send(request, stream=True)
            try:
                if response.status_code != 200:
                    raise CaptureError("REPORT_IMAGE_DOWNLOAD_FAILED")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isdigit() or int(length) > self.limit):
                    raise CaptureError("REPORT_IMAGE_TOO_LARGE")
                chunks, count = [], 0
                async for chunk in response.aiter_bytes(64 * 1024):
                    count += len(chunk)
                    if count > self.limit:
                        raise CaptureError("REPORT_IMAGE_TOO_LARGE")
                    chunks.append(chunk)
                if length is not None and count != int(length):
                    raise CaptureError("REPORT_IMAGE_DOWNLOAD_FAILED")
                raw = b"".join(chunks)
                if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise CaptureError("REPORT_IMAGE_DOWNLOAD_FAILED")
                return raw
            finally:
                await response.aclose()


_SOURCES = ("https://static.atlasacademy.io", "https://static.atlas.chaldea.center")
