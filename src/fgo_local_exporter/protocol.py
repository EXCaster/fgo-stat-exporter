"""仅实现用户授权的游戏登录和统计读取，无奖励领取或游戏操作接口。"""

import hashlib
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from fgo_local_exporter.errors import ExportError
from fgo_local_exporter.game_profile import GameProfile
from fgo_local_exporter.statistics import decode_response, export_statistics

__all__ = ["SERVERS", "GameClient"]
_SDK = "https://line3-sdk-center-login-sh.biligame.net"
# 原版 2.129.0 的网络清单分别列出安卓和 iOS 区服。
# 角色区服与授权所用 SDK 及本工具所在操作系统无关。
SERVERS = {
    "android": ("安卓服务器", "https://line3-s2-bili-fate.bilibiligame.net"),
    "ios": ("iOS 服务器", "https://line3-s2-ios-fate.bilibiligame.net"),
}
_LIMIT = 16 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ExportError("REMOTE_REDIRECT_REJECTED")


class GameClient:
    def __init__(self, profile: GameProfile, server: str):
        if server not in SERVERS:
            raise ExportError("SERVER_SELECTION_REQUIRED")
        self.profile = profile
        self.server = server
        self.game_url = SERVERS[server][1]
        # 不继承系统代理；凭据仅通过经过证书校验的官方 TLS 连接发送。
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def _request(self, url: str, fields: dict) -> bytes:
        if not url.startswith((_SDK + "/", self.game_url + "/")):
            raise ExportError("REMOTE_DESTINATION_REJECTED")
        request = urllib.request.Request(
            url,
            urllib.parse.urlencode(fields).encode(),
            headers={
                "User-Agent": "Mozilla/5.0 BSGameSDK"
                if url.startswith(_SDK)
                else "Dalvik/2.1.0 (Linux; U; Android 9)",
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Unity-Version": "2019.4.40f1",
            },
        )
        try:
            with self._opener.open(request, timeout=20) as response:
                body = response.read(_LIMIT + 1)
            if len(body) > _LIMIT:
                raise ExportError("RESPONSE_LIMIT")
            return body
        except ExportError:
            raise
        except urllib.error.HTTPError as error:
            raise ExportError(f"REMOTE_HTTP_{int(error.code)}") from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, ssl.SSLCertVerificationError):
                code = "REMOTE_TLS_VERIFY_FAILED"
            elif isinstance(error.reason, TimeoutError):
                code = "REMOTE_TIMEOUT"
            else:
                code = "REMOTE_REQUEST_FAILED"
            raise ExportError(code) from None
        except TimeoutError:
            raise ExportError("REMOTE_TIMEOUT") from None
        except Exception:
            raise ExportError("REMOTE_REQUEST_FAILED") from None

    def _sdk(self, action: str, extra: dict | None = None) -> dict:
        params = dict(self.profile.sdk_base, timestamp=str(int(time.time() * 1000)))
        params.update(extra or {})
        params["sign"] = hashlib.md5(
            ("".join(params[k] for k in sorted(params)) + self.profile.sdk_key).encode()
        ).hexdigest()
        try:
            result = json.loads(
                self._request(_SDK + "/api/external/qrcode.login/" + action + "/v3", params)
            )
            if not isinstance(result, dict):
                raise ExportError("SDK_RESPONSE_INVALID")
            return result
        except (ValueError, UnicodeError):
            raise ExportError("SDK_RESPONSE_INVALID") from None

    def generate(self) -> tuple[str, str]:
        root = self._sdk("generate")
        data = root.get("data")
        if str(root.get("code")) != "0" or not isinstance(data, dict):
            raise ExportError("SDK_QR_GENERATE_FAILED")
        ticket = data.get("ticket")
        if not isinstance(ticket, str) or not 1 <= len(ticket) <= 1024:
            raise ExportError("SDK_RESPONSE_INVALID")
        redirect = data.get("redirect_url")
        if redirect:
            parsed = urllib.parse.urlsplit(redirect)
            if (
                parsed.scheme != "https"
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or not parsed.hostname
                or parsed.port not in (None, 443)
                or not parsed.hostname.endswith(
                    (".biligame.com", ".biligame.net", ".bilibili.com", ".bilibiligame.net")
                )
            ):
                raise ExportError("SDK_QR_REDIRECT_REJECTED")
            value = (
                redirect
                + "?"
                + urllib.parse.urlencode(
                    {
                        "ticket": ticket,
                        "fromNative": "biligame://portal/auth/login/qrcode",
                        "id": str(data.get("game_base_id", "")),
                        "st": "0",
                    }
                )
            )
        else:
            value = "biligame://portal/auth/login/qrcode?" + ticket
        return ticket, value

    def poll(self, ticket: str) -> tuple[str, dict]:
        root = self._sdk("status", {"ticket": ticket})
        code = str(root.get("code"))
        if code == "0":
            data = root.get("data")
            if not isinstance(data, dict) or not data.get("access_key"):
                raise ExportError("SDK_CREDENTIAL_FIELDS_MISSING")
            return "authorized", {
                k: data[k] for k in ("uid", "access_key", "uname", "username") if k in data
            }
        state = {"710000": "waiting_scan", "710002": "waiting_confirm", "710001": "expired"}
        if code not in state:
            raise ExportError("SDK_QR_POLL_FAILED")
        return state[code], {}

    def _game(self, path: str, params: dict) -> tuple[dict, dict]:
        root = decode_response(self._request(self.game_url + path, params))
        responses = root.get("response")
        if not isinstance(responses, list) or len(responses) != 1:
            raise ExportError("GAME_RESPONSE_INVALID")
        row = responses[0]
        code = str(row.get("resCode"))
        if code not in ("0", "00") or row.get("fail"):
            raise ExportError(
                "GAME_REJECTED_" + code if re.fullmatch(r"[0-9]{1,5}", code) else "GAME_REJECTED"
            )
        if not isinstance(row.get("success"), dict):
            raise ExportError("GAME_RESPONSE_INVALID")
        return root, row["success"]

    def statistics(self, user: dict, progress, cancelled) -> tuple[bytes, dict]:
        """所有凭据只在此调用的内存中存活，调用结束后清除会话引用。"""
        member = params = info = login = None
        try:
            uid, access = str(user.get("uid", "")), user.get("access_key")
            if not uid.isdigit() or not isinstance(access, str) or not access:
                raise ExportError("SDK_CREDENTIAL_FIELDS_MISSING")
            common = {
                "deviceid": uuid.uuid4().hex,
                "os": "Android OS 9 / API-28",
                "ptype": "Android",
                "appVer": self.profile.version,
                "dateVer": "0",
                "lastAccessTime": str(int(time.time())),
                "try": "",
                "dataVer": "0",
                "developmentAuthCode": self.profile.development_code,
            }

            def stage(name):
                if cancelled():
                    raise ExportError("CANCELLED")
                progress(name)

            stage("game_handoff")
            member = dict(
                common,
                t="22360",
                v="1.0.1",
                s="1",
                mac="0",
                imei="",
                bundleid=_PACKAGE_NAME,
                username=str(user.get("uname", user.get("username", ""))),
                type="token",
                rkuid=uid,
                access_token=access,
                rksdkid="1",
                rkchannel="24",
                version="0",
            )
            _, info = self._game("/rongame_beta/rgfate/60_member/logintomembercenter.php", member)
            member.clear()
            access = None
            for name in ("dateVer", "dataVer"):
                value = info.get(name)
                if type(value) not in (int, str) or not re.fullmatch(r"[0-9]{1,12}", str(value)):
                    raise ExportError("GAME_RESPONSE_INVALID")
                common[name] = str(value)
            stage("game_initialization")
            params = dict(
                common,
                rgsid="1001",
                rguid=info["rguid"],
                rgusk=info["rgusk"],
                idfa="",
                v="1.0.1",
                mac="0",
                imei="",
                type="login",
                nickname=str(info["rgusk"])[:10],
                rkchannel="24",
                assetbundleFolder="",
                userAgent="1",
                t="20399",
                s="1",
                rksdkid="1",
            )
            _, login = self._game("/rongame_beta/rgfate/60_1001/login.php", params)
            params.clear()
            info.clear()
            stage("fetching_statistics")
            params = dict(
                common,
                ac="action",
                key="toplogin",
                userId=str(login["sguid"]),
                usk=hashlib.md5(
                    (self.profile.session_prefix + str(login["sgusk"])).encode()
                ).hexdigest(),
                umk="",
                rgsid="1001",
                rkchannel="24",
                userAgent="1",
                lastAccessTime="0",
                nickname=str(login.get("nickname", "")),
                sgtype=str(login.get("sgtype", "")),
                sgtag=str(login.get("sgtag", "")),
            )
            query = urllib.parse.urlencode({"_userId": str(login["sguid"]), "_key": "toplogin"})
            root, _ = self._game("/rongame_beta/rgfate/60_1001/ac.php?" + query, params)
            params.clear()
            login.clear()
            stage("filtering_statistics")
            return export_statistics(root)
        except ExportError:
            raise
        except (KeyError, TypeError, ValueError):
            raise ExportError("GAME_RESPONSE_INVALID") from None
        finally:
            user.clear()
            for value in (member, params, info, login):
                if isinstance(value, dict):
                    value.clear()


_PACKAGE_NAME = "com.bilibili.fatego"
