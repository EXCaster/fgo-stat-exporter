"""公开图片下载的地址限制、错误处理和缓存行为。"""

import asyncio

import httpx
import pytest

from fgo_stat_core.contracts.models import CaptureError
from fgo_stat_core.infrastructure.public_download import PublicImageDownloader


@pytest.mark.parametrize(
    "url",
    [
        "https://unapproved.invalid/CN/Items/a.png",
        "https://static.atlasacademy.io/CN/Items/a.png?account=synthetic",
        "https://static.atlasacademy.io/CN/Items/../a.png",
        "http://static.atlasacademy.io/CN/Items/a.png",
    ],
)
def test_only_plain_public_image_urls_are_accepted(url):
    with pytest.raises(CaptureError, match="REPORT_IMAGE_SOURCE_REJECTED"):
        asyncio.run(PublicImageDownloader().fetch(url))


@pytest.mark.parametrize(
    "status,body,limit,expected",
    [
        (200, b"synthetic-public-image", 32, None),
        (302, b"", 32, "REPORT_IMAGE_DOWNLOAD_FAILED"),
        (200, b"larger-than-limit", 4, "REPORT_IMAGE_TOO_LARGE"),
    ],
)
def test_download_is_bounded_and_does_not_follow_redirects(
    monkeypatch,
    status,
    body,
    limit,
    expected,
):
    import fgo_stat_core.infrastructure.public_download as module

    original = httpx.AsyncClient
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, content=body, headers={"Location": "https://other.invalid/"})

    def client(**options):
        assert options["trust_env"] is False
        assert options["follow_redirects"] is False
        return original(transport=httpx.MockTransport(handle), **options)

    monkeypatch.setattr(module.httpx, "AsyncClient", client)
    task = PublicImageDownloader(limit=limit).fetch("https://static.atlasacademy.io/CN/Items/a.png")
    if expected:
        with pytest.raises(CaptureError, match=expected):
            asyncio.run(task)
    else:
        assert asyncio.run(task) == body
    assert len(requests) == 1
    assert "Cookie" not in requests[0].headers
    assert "Authorization" not in requests[0].headers
