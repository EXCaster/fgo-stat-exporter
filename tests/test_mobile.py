import io
import threading
from types import SimpleNamespace

import pytest
from PIL import Image

from fgo_local_exporter.errors import ExportError
from fgo_local_exporter.mobile import MobileRuntime, bounded_import


def test_mobile_import_rejects_oversized_input():
    with pytest.raises(ExportError, match="INPUT_TOO_LARGE"):
        bounded_import(b"x" * (16 * 1024 * 1024 + 1))


def runtime_with_report():
    runtime = MobileRuntime.__new__(MobileRuntime)
    session = SimpleNamespace(
        lock=threading.RLock(),
        document=object(),
        report_version="current",
        export=b'{"synthetic":true}',
        state=lambda: None,
    )
    runtime._session = session
    return runtime, session


def test_mobile_export_requires_current_memory_data():
    runtime, session = runtime_with_report()
    assert runtime.export_json() == b'{"synthetic":true}'
    session.export = b""
    with pytest.raises(ExportError, match="STATISTICS_NOT_READY"):
        runtime.export_json()


def test_mobile_image_rejects_expired_report_before_decoding():
    runtime, _ = runtime_with_report()
    with pytest.raises(ExportError, match="REPORT_EXPIRED"):
        runtime.image_bytes("data:image/jpeg;base64,not-a-jpeg", "old")


def test_mobile_image_requires_jpeg_dimensions():
    import base64

    runtime, _ = runtime_with_report()
    for width, expected in ((600, True), (10, False)):
        output = io.BytesIO()
        Image.new("RGB", (width, 400)).save(output, "JPEG")
        url = "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode()
        if expected:
            assert runtime.image_bytes(url, "current") == output.getvalue()
        else:
            with pytest.raises(ExportError, match="IMAGE_DATA_INVALID"):
                runtime.image_bytes(url, "current")
