import json

import pytest

from fgo_local_exporter.errors import ExportError
from fgo_local_exporter.game_profile import GameProfile
from fgo_local_exporter.protocol import GameClient


@pytest.mark.parametrize(
    ("server", "expected_host"),
    [
        ("ios", "https://line3-s2-ios-fate.bilibiligame.net"),
        ("android", "https://line3-s2-bili-fate.bilibiligame.net"),
    ],
)
def test_every_game_login_stage_uses_the_selected_role_server(server, expected_host, monkeypatch):
    client = GameClient(GameProfile("test", {}, "synthetic", "synthetic", "synthetic"), server)
    requests = []

    def response(url, fields):
        requests.append(url)
        assert url.startswith(expected_host + "/")
        if url.endswith("logintomembercenter.php"):
            success = {"dateVer": 1, "dataVer": 1, "rguid": "123", "rgusk": "synthetic"}
            nid, cache = "login_to_membercenter", {}
        elif url.endswith("login.php"):
            success = {"sguid": "123", "sgusk": "synthetic", "nickname": "synthetic"}
            nid, cache = "initialization", {}
        else:
            assert fields["userId"] == "123" and fields["lastAccessTime"] == "0"
            nid, success = "login", {}
            cache = {
                "serverTime": 1700000000,
                "replaced": {
                    "userGame": [{"userId": "123", "friendCode": "100000000123", "lv": 3}],
                    "userSvt": [],
                    "userSvtCollection": [],
                },
            }
        return json.dumps(
            {
                "response": [{"nid": nid, "resCode": "00", "success": success}],
                "cache": cache,
            }
        ).encode()

    monkeypatch.setattr(client, "_request", response)
    auth = {"uid": "123", "access_key": "synthetic"}
    raw, _ = client.statistics(auth, lambda _: None, lambda: False)
    assert len(requests) == 3 and json.loads(raw)["response"][0]["nid"] == "login"
    assert not auth


def test_client_rejects_unselected_server_and_other_server_destination():
    profile = GameProfile("test", {}, "synthetic", "synthetic", "synthetic")
    with pytest.raises(ExportError, match="SERVER_SELECTION_REQUIRED"):
        GameClient(profile, "")
    client = GameClient(profile, "ios")
    with pytest.raises(ExportError, match="REMOTE_DESTINATION_REJECTED"):
        client._request("https://line3-s2-bili-fate.bilibiligame.net/example", {})
