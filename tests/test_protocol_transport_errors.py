import ssl
import urllib.error

import pytest

from fgo_local_exporter.errors import ExportError
from fgo_local_exporter.game_profile import GameProfile
from fgo_local_exporter.protocol import GameClient


@pytest.mark.parametrize(
    "exception,code",
    [
        (
            urllib.error.URLError(ssl.SSLCertVerificationError(1, "synthetic-private-detail")),
            "REMOTE_TLS_VERIFY_FAILED",
        ),
        (urllib.error.URLError(TimeoutError("synthetic-private-detail")), "REMOTE_TIMEOUT"),
        (TimeoutError("synthetic-private-detail"), "REMOTE_TIMEOUT"),
        (
            urllib.error.HTTPError(
                "https://example.invalid/?token=synthetic-private-detail",
                403,
                "synthetic-private-detail",
                {},
                None,
            ),
            "REMOTE_HTTP_403",
        ),
    ],
)
def test_transport_errors_expose_only_safe_category(exception, code):
    class Opener:
        def open(self, *args, **kwargs):
            raise exception

    client = GameClient(GameProfile("2.129.0", {}, "x" * 32, "y" * 50, "z" * 32), "ios")
    client._opener = Opener()
    with pytest.raises(ExportError) as result:
        client._request(
            "https://line3-sdk-center-login-sh.biligame.net/test",
            {"token": "synthetic-private-detail"},
        )
    assert result.value.code == code
    assert "synthetic-private-detail" not in str(result.value)
