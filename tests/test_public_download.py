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
        (200, b"\x89PNG\r\n\x1a\nsynthetic-image", 32, None),
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
    assert len(requests) == (2 if expected else 1)
    assert {request.url.host for request in requests} <= {
        "static.atlasacademy.io",
        "static.atlas.chaldea.center",
    }
    assert all("Cookie" not in request.headers for request in requests)
    assert all("Authorization" not in request.headers for request in requests)


def test_domestic_fallback_reuses_connection_without_cookies(monkeypatch):
    import fgo_stat_core.infrastructure.public_download as module

    original = httpx.AsyncClient
    requests, clients = [], []
    payload = b"\x89PNG\r\n\x1a\nsynthetic-image"

    async def handle(request):
        requests.append(request)
        if request.url.host == "static.atlasacademy.io":
            raise httpx.ConnectTimeout("artificial network error")
        return httpx.Response(200, content=payload, headers={"Set-Cookie": "artificial=private"})

    def client(**options):
        clients.append(True)
        return original(transport=httpx.MockTransport(handle), **options)

    monkeypatch.setattr(module.httpx, "AsyncClient", client)

    async def run():
        async with PublicImageDownloader(timeout=4) as downloader:
            assert (
                await downloader.fetch("https://static.atlasacademy.io/CN/Items/a.png") == payload
            )
            assert (
                await downloader.fetch("https://static.atlasacademy.io/CN/Items/b.png") == payload
            )

    asyncio.run(run())
    assert len(clients) == 1 and len(requests) == 3
    assert requests[-1].url.host == "static.atlas.chaldea.center"
    assert all("Cookie" not in request.headers for request in requests)


def test_report_batch_timeout_cancels_downloads(monkeypatch, tmp_path):
    import threading

    from fgo_local_exporter.errors import ExportError
    from fgo_local_exporter.reports import _prepare_images
    from fgo_stat_core.infrastructure.report_assets import AssetSpec

    active = set()

    async def blocked(_self, url):
        active.add(url)
        try:
            await asyncio.sleep(100)
        finally:
            active.discard(url)

    monkeypatch.setattr(PublicImageDownloader, "fetch", blocked)
    specs = tuple(
        AssetSpec(f"image-{i}.png", f"https://static.atlasacademy.io/CN/Items/{i}.png")
        for i in range(12)
    )
    with pytest.raises(ExportError, match="REPORT_IMAGE_TIMEOUT"):
        asyncio.run(
            _prepare_images(specs, tmp_path, threading.Event(), lambda *_: None, timeout=0.03)
        )
    assert not active
    assert not list(tmp_path.iterdir())


def test_clearing_report_cancels_active_image_downloads(monkeypatch, tmp_path):
    import threading

    from fgo_local_exporter.errors import ExportError
    from fgo_local_exporter.reports import _prepare_images
    from fgo_stat_core.infrastructure.report_assets import AssetSpec

    cancel = threading.Event()
    active = []

    async def blocked(_self, _url):
        active.append(True)
        cancel.set()
        try:
            await asyncio.sleep(100)
        finally:
            active.clear()

    monkeypatch.setattr(PublicImageDownloader, "fetch", blocked)
    specs = (AssetSpec("image-1.png", "https://static.atlasacademy.io/CN/Items/1.png"),)
    with pytest.raises(ExportError, match="CANCELLED"):
        asyncio.run(_prepare_images(specs, tmp_path, cancel, lambda *_: None, timeout=1))
    assert not active


def test_image_progress_counts_existing_and_downloaded_images(monkeypatch, tmp_path):
    import hashlib
    import io
    import threading

    from PIL import Image

    from fgo_local_exporter.reports import _prepare_images
    from fgo_stat_core.infrastructure.report_assets import AssetSpec

    output = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, "PNG")
    image = output.getvalue()
    specs = tuple(
        AssetSpec(f"image-{i}.png", f"https://static.atlasacademy.io/CN/Items/{i}.png")
        for i in range(2)
    )
    (tmp_path / "image-0.png").write_bytes(image)
    (tmp_path / "image-0.png.sha256").write_text(
        hashlib.sha256(specs[0].url.encode()).hexdigest() + ":" + hashlib.sha256(image).hexdigest()
    )
    requests, progress = [], []

    async def fetch(_self, url):
        requests.append(url)
        return image

    monkeypatch.setattr(PublicImageDownloader, "fetch", fetch)
    result = asyncio.run(
        _prepare_images(specs, tmp_path, threading.Event(), lambda *value: progress.append(value))
    )
    assert requests == [specs[1].url]
    assert result == {"available": 2, "missing": 0, "downloaded": 1}
    assert progress == [("images", 1, 2), ("images", 2, 2)]
