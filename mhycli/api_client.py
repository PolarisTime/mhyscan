"""米哈游账号 API 客户端 — 基于 FufuLauncher (LoginQrWindow.xaml.cs) 封装

复用仍在维护的 FufuLauncher 项目的接口封装, 完整流程:
  1. App 扫码登录 (createQRLogin + queryQRLoginStatus) → 提取 SToken
  2. 用 SToken 换 V2 Cookie (getCookieAccountInfoBySToken / getLTokenBySToken)
  3. 游戏扫码抢码 (识别直播间二维码 → scanQRLogin + confirmQRLogin)
"""
from __future__ import annotations

import hashlib
import json
import random
import string
import time
import uuid

import requests

# ---- 常量 (来自 FufuLauncher HeaderSalts / HeaderConstants / ApiEndpoints) ----

# DS 签名 salt
SALT_MIYAKO_APP = "dDIQHbKOdaPaLuvQKVzUzqdeCaxjtaPV"  # App 扫码 (16.0.1+)
SALT_MOBILE = "t0qEgfub6cvueAPgR5m9aQWWVciEer7v"      # 米游社移动端 / 游戏扫码
SALT_PROD = "JwYDpKvLj6MrMqqYU6jTKF17KNO2PXoS"        # passport 账号体系

# app_id: 通行证 vs 游戏扫码
APP_ID_PASSPORT = "bll8iq97cem8"
APP_ID_GAME = "ddxf5dufpuyo"

# ---- Panda 游戏二维码抢码 (对齐 MHY_Scanner PandaScanQRCode) ----
# 游戏内二维码 ticket 属于 panda 体系, 需先用账号调 panda scan 换取
# passport_qr_url, 再走 passport scan/confirm 两阶段完成抢码。
GAME_SCAN_ENDPOINTS = {
    1: "https://api-sdk.mihoyo.com/bh3_cn/combo/panda/qrcode/scan",    # 崩坏3
    4: "https://api-sdk.mihoyo.com/hk4e_cn/combo/panda/qrcode/scan",   # 原神
    8: "https://api-sdk.mihoyo.com/hkrpg_cn/combo/panda/qrcode/scan",  # 星穹铁道
    12: "https://api-sdk.mihoyo.com/nap_cn/combo/panda/qrcode/scan",   # 绝区零
}
BIZ_KEY_TO_APP = {"bh3_cn": 1, "hk4e_cn": 4, "hkrpg_cn": 8, "nap_cn": 12}

# 端点 (来自 FufuLauncher ApiEndpoints)
EP_PASSPORT_CREATE_QR = "https://passport-api.mihoyo.com/account/ma-cn-passport/web/createQRLogin"
EP_PASSPORT_SCAN_QR = "https://passport-api.mihoyo.com/account/ma-cn-passport/app/scanQRLogin"
EP_PASSPORT_CONFIRM_QR = "https://passport-api.mihoyo.com/account/ma-cn-passport/app/confirmQRLogin"
EP_PASSPORT_QUERY_STATUS = "https://passport-api.mihoyo.com/account/ma-cn-passport/web/queryQRLoginStatus"
EP_APP_CREATE_QR = "https://passport-api.mihoyo.com/account/ma-cn-passport/app/createQRLogin"
EP_APP_QUERY_STATUS = "https://passport-api.mihoyo.com/account/ma-cn-passport/app/queryQRLoginStatus"
EP_HK4E_QR_FETCH = "https://hk4e-sdk.mihoyo.com/hk4e_cn/combo/panda/qrcode/fetch"
EP_HK4E_QR_QUERY = "https://hk4e-sdk.mihoyo.com/hk4e_cn/combo/panda/qrcode/query"
EP_GET_TOKEN_BY_GAME_TOKEN = "https://api-takumi.mihoyo.com/account/ma-cn-session/app/getTokenByGameToken"
EP_GET_COOKIE_BY_STOKEN = "https://passport-api.mihoyo.com/account/auth/api/getCookieAccountInfoBySToken"
EP_GET_LTOKEN_BY_STOKEN = "https://passport-api.mihoyo.com/account/auth/api/getLTokenBySToken"

UA_CAPTURE = "Mozilla/5.0 miHoYoBBS/2.90.1 Capture/2.2.0"
UA_BBS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) miHoYoBBS/2.90.1"


# ---- 工具函数 ----

def _md5(data: str) -> str:
    return hashlib.md5(data.encode("utf-8")).hexdigest()


def _rand_str(length: int, chars: str) -> str:
    return "".join(random.choice(chars) for _ in range(length))


def generate_ds(body: str, query: str = "", salt: str = SALT_MIYAKO_APP) -> str:
    """对应 FufuLauncher GenerateDS: md5(salt&t&r&b&q) → "t,r,sign" """
    t = str(int(time.time()))
    r = _rand_str(6, string.ascii_lowercase + string.digits)
    b = body or ""
    q = query or ""
    sign_str = f"salt={salt}&t={t}&r={r}&b={b}&q={q}"
    return f"{t},{r},{_md5(sign_str)}"


def generate_device_fingerprint(device_id: str) -> str:
    """对应 FufuLauncher GenerateDeviceFingerprint"""
    seed_id = _rand_str(16, "0123456789abcdef")
    payload = {
        "device_id": device_id,
        "seed_id": seed_id,
        "seed_time": int(time.time()),
        "platform": "2",
        "device_fp": "",
        "app_name": "bbs_cn",
    }
    return _md5(json.dumps(payload, separators=(",", ":")))


def make_client() -> "MhyClient":
    return MhyClient()


class MhyClient:
    """对应 FufuLauncher LoginQrWindow 的 HTTP 封装"""

    def __init__(self, device_id: str | None = None):
        self.device_id = (device_id or uuid.uuid4().hex[:16]).upper()
        self.device_fp = generate_device_fingerprint(self.device_id)
        self.session = requests.Session()
        self.session.verify = True

    # ---- 请求构造 ----

    def _common_headers(self, body: str, query: str = "", client_type: str = "2",
                        app_id: str = APP_ID_PASSPORT, sdk_version: str = "2.90.1",
                        cookie: str = "", referer: str = "") -> dict:
        """对应 FufuLauncher AddCommonHeaders"""
        headers = {
            "User-Agent": UA_CAPTURE,
            "Accept": "*/*",
            "Accept-Language": "zh-cn",
            "x-rpc-client_type": client_type,
            "x-rpc-app_version": "2.90.1",
            "x-rpc-device_id": self.device_id,
            "x-rpc-device_fp": self.device_fp,
            "x-rpc-game_biz": "bbs_cn",
            "x-rpc-app_id": app_id,
            "x-rpc-sdk_version": sdk_version,
            "x-rpc-account_version": "2.90.1",
            "x-rpc-device_model": "Mi 14",
            "x-rpc-device_name": "Mihoyo Capture",
            "DS": generate_ds(body, query, SALT_MIYAKO_APP),
            "Content-Type": "application/json",
        }
        if cookie:
            headers["Cookie"] = cookie
        if referer:
            headers["Referer"] = referer
        return headers

    def _passport_auth_headers(self, body: str, cookie: str, sign: bool = True) -> dict:
        """对应 FufuLauncher AddPassportAuthHeaders"""
        headers = {
            "User-Agent": UA_BBS,
            "Accept": "application/json",
            "Accept-Language": "zh-cn",
            "x-rpc-aigis": "",
            "x-rpc-app_id": APP_ID_PASSPORT,
            "x-rpc-app_version": "2.90.1",
            "x-rpc-client_type": "2",
            "x-rpc-device_id": self.device_id,
            "x-rpc-device_name": "",
            "x-rpc-game_biz": "bbs_cn",
            "x-rpc-sdk_version": "2.16.0",
        }
        if cookie:
            headers["Cookie"] = cookie
        if sign:
            headers["DS"] = generate_ds(body, "", SALT_PROD)
        return headers

    def _game_headers(self, body: str, query: str = "") -> dict:
        """对应 FufuLauncher AddGameHeaders (游戏扫码)"""
        return {
            "x-rpc-app_version": "2.71.1",
            "x-rpc-aigis": "",
            "Accept": "application/json",
            "x-rpc-game_biz": "bbs_cn",
            "x-rpc-sys_version": "12",
            "x-rpc-device_id": self.device_id,
            "x-rpc-device_name": "Xiaomi MI 6",
            "x-rpc-device_model": "MI 6",
            "x-rpc-client_type": "3",
            "User-Agent": "okhttp/4.9.3",
            "Content-Type": "application/json",
        }

    # ---- App 扫码登录 (对应 StartAppLoginFlowAsync) ----

    def app_create_qr(self) -> tuple[bool, str, str, str]:
        """CreateAppQrCodeAsync: 创建 App 登录二维码
        返回 (成功, qrUrl, ticket, message)
        """
        url = EP_APP_CREATE_QR
        body = {}
        body_str = json.dumps(body)
        headers = self._common_headers(body_str, "", "3", APP_ID_GAME, "2.90.1")
        try:
            r = self.session.post(url, data=body_str, headers=headers, timeout=15)
            result = r.json()
            if result.get("retcode") == 0:
                data = result.get("data", {})
                return True, data.get("url", ""), data.get("ticket", ""), "Success"
            return False, "", "", result.get("message", "")
        except Exception as e:
            return False, "", "", str(e)

    def app_query_status(self, ticket: str) -> tuple[int, str, dict]:
        """PollAppLoginStatusAsync 单次查询
        返回 (retcode, status, data); status ∈ Created/Scanned/Confirmed/Expired
        """
        url = EP_APP_QUERY_STATUS
        body = {"ticket": ticket}
        body_str = json.dumps(body)
        headers = self._common_headers(body_str, "", "3", APP_ID_GAME, "2.90.1")
        try:
            r = self.session.post(url, data=body_str, headers=headers, timeout=15)
            result = r.json()
            retcode = result.get("retcode", -1)
            if retcode == -3501 or retcode == -106:
                return retcode, "Expired", {}
            if retcode == 0:
                return 0, result.get("data", {}).get("status", ""), result.get("data", {})
            return retcode, "", {}
        except Exception:
            return -2, "", {}

    # ---- 游戏扫码登录 (对应 StartGameLoginFlowAsync, 旧 panda 接口) ----

    def game_qr_fetch(self, app_id: int) -> tuple[bool, str, str, str]:
        """CreateGameQrCodeAsync: fetch 游戏二维码
        返回 (成功, qrUrl, ticket, message)
        """
        url = EP_HK4E_QR_FETCH
        body = {"app_id": int(app_id), "device": self.device_id.lower()}
        body_str = json.dumps(body)
        headers = self._game_headers(body_str)
        try:
            r = self.session.post(url, data=body_str, headers=headers, timeout=15)
            result = r.json()
            if result.get("retcode") == 0:
                qr_url = result.get("data", {}).get("url", "")
                from urllib.parse import parse_qs, urlparse

                query = parse_qs(urlparse(qr_url).query)
                ticket = query.get("ticket", [""])[0]
                return True, qr_url, ticket, "Success"
            return False, "", "", result.get("message", "")
        except Exception as e:
            return False, "", "", str(e)

    def game_qr_query(self, app_id: int, ticket: str) -> tuple[int, str, str, str]:
        """PollGameLoginStatusAsync 单次查询
        返回 (retcode, stat, uid, game_token); stat ∈ Init/Scanned/Confirmed
        """
        url = EP_HK4E_QR_QUERY
        body = {"app_id": int(app_id), "device": self.device_id.lower(), "ticket": ticket}
        body_str = json.dumps(body)
        headers = self._game_headers(body_str)
        try:
            r = self.session.post(url, data=body_str, headers=headers, timeout=15)
            result = r.json()
            retcode = result.get("retcode", -1)
            if retcode != 0:
                return retcode, "", "", ""
            stat = result.get("data", {}).get("stat", "")
            if stat == "Confirmed":
                raw = result.get("data", {}).get("payload", {}).get("raw", "")
                try:
                    raw_node = json.loads(raw)
                    return 0, stat, raw_node.get("uid", ""), raw_node.get("token", "")
                except json.JSONDecodeError:
                    pass
            return 0, stat, "", ""
        except Exception:
            return -2, "", "", ""

    # ---- token 转换 ----

    def get_stoken_by_game_token(self, account_id: str, game_token: str) -> tuple[int, str, str]:
        """GetSTokenByGameTokenAsync: game_token → SToken
        返回 (retcode, stoken, mid)
        """
        url = EP_GET_TOKEN_BY_GAME_TOKEN
        body = {"account_id": int(account_id), "game_token": game_token}
        body_str = json.dumps(body)
        headers = {
            "x-rpc-app_version": "2.71.1",
            "x-rpc-game_biz": "bbs_cn",
            "x-rpc-sys_version": "12",
            "x-rpc-device_id": self.device_id,
            "x-rpc-device_name": "Xiaomi MI 6",
            "x-rpc-device_model": "MI 6",
            "x-rpc-app_id": APP_ID_PASSPORT,
            "x-rpc-client_type": "4",
            "User-Agent": "okhttp/4.9.3",
            "DS": generate_ds(body_str, "", SALT_MOBILE),
            "Content-Type": "application/json",
        }
        try:
            r = self.session.post(url, data=body_str, headers=headers, timeout=15)
            result = r.json()
            if result.get("retcode") == 0:
                token = result.get("data", {}).get("token", {}).get("token", "")
                mid = result.get("data", {}).get("user_info", {}).get("mid", "")
                return 0, token, mid
            return result.get("retcode", -1), "", ""
        except Exception:
            return -2, "", ""

    def get_cookie_account_info_by_stoken(self, stoken: str, mid: str, aid: str) -> str:
        """GetCookieAccountInfoBySTokenAsync: SToken → cookie_token"""
        url = EP_GET_COOKIE_BY_STOKEN
        cookie = f"mid={mid}; stoken={stoken}; stuid={aid}"
        headers = self._passport_auth_headers("", cookie, True)
        try:
            r = self.session.get(url, headers=headers, timeout=15)
            result = r.json()
            if result.get("retcode") == 0:
                return result.get("data", {}).get("cookie_token", "")
        except Exception:
            pass
        return ""

    def get_ltoken_by_stoken(self, stoken: str, mid: str, aid: str) -> str:
        """GetLTokenBySTokenAsync: SToken → ltoken"""
        url = EP_GET_LTOKEN_BY_STOKEN
        cookie = f"mid={mid}; stoken={stoken}; stuid={aid}"
        headers = self._passport_auth_headers("", cookie, True)
        try:
            r = self.session.get(url, headers=headers, timeout=15)
            result = r.json()
            if result.get("retcode") == 0:
                return result.get("data", {}).get("ltoken", "")
        except Exception:
            pass
        return ""

    # ---- V2 Cookie 换取 (对应 ExchangeV2TokensAsync) ----

    def create_web_qr(self) -> str:
        """CreateWebQrCodeAsync: 创建 web 二维码, 返回 ticket"""
        url = EP_PASSPORT_CREATE_QR
        body = {}
        body_str = json.dumps(body)
        headers = self._common_headers(body_str, "", "2", APP_ID_PASSPORT, "2.90.1")
        try:
            r = self.session.post(url, data=body_str, headers=headers, timeout=15)
            result = r.json()
            if result.get("retcode") == 0:
                return result.get("data", {}).get("ticket", "")
        except Exception:
            pass
        return ""

    def simulate_app_action(self, url: str, ticket: str, auth_cookie: str) -> tuple[int, str]:
        """SimulateAppActionAsync: scanQRLogin / confirmQRLogin
        body = {ticket, token_types:["4"]}, Cookie = stoken=..; mid=..
        返回 (retcode, message); retcode==0 成功
        常见错误码: -100 登录状态失效(stoken 无效), -3501 二维码已失效
        """
        body = {"ticket": ticket, "token_types": ["4"]}
        body_str = json.dumps(body)
        headers = self._common_headers(body_str, "", "2", APP_ID_PASSPORT, "2.90.1", auth_cookie)
        try:
            r = self.session.post(url, data=body_str, headers=headers, timeout=15)
            result = r.json()
            return result.get("retcode", -1), result.get("message", "")
        except Exception as e:
            return -2, str(e)[:50]

    @staticmethod
    def _passport_qr_param(qr_url: str, key: str, terminators: str = "&") -> str:
        """从 passport 二维码 URL 提取参数 (对齐 C++ getPassportQRParam)

        示例: ...mobile.html?app_id=..&tk=<uuid>&token_types=1#/login/qr
          tk 参数以 & 结尾, token_types 以 # 结尾
        """
        needle = key + "="
        begin = qr_url.find(needle)
        if begin == -1:
            return ""
        value_begin = begin + len(needle)
        value_end = len(qr_url)
        for t in terminators:
            idx = qr_url.find(t, value_begin)
            if idx != -1:
                value_end = idx
                break
        return qr_url[value_begin:value_end]

    def panda_scan_qrcode(self, ticket: str, app_id: int, biz_key: str = "") -> tuple[int, str, str]:
        """Panda 扫码 (抢码阶段一, 对齐 C++ PandaScanQRCode)

        游戏内二维码 ticket 属于 panda 体系, 不能直接给 passport scanQRLogin。
        需用已登录账号向游戏 scan 端点发扫码请求, 换取 passport_qr_url,
        供阶段二 (passport scan/confirm) 完成抢码。

        body: {passport_app_id, ticket, app_id, device, ts}
        headers: 必须带 x-rpc-app_id + x-rpc-device_id (对齐 C++)
        返回 (retcode, passport_qr_url, message)
        """
        scan_url = GAME_SCAN_ENDPOINTS.get(int(app_id))
        if not scan_url and biz_key:
            scan_url = f"https://api-sdk.mihoyo.com/{biz_key}/combo/panda/qrcode/scan"
        if not scan_url:
            return -1, "", f"未知 app_id={app_id}"
        device = self.device_id.lower()
        body = {
            "passport_app_id": APP_ID_PASSPORT,
            "ticket": ticket,
            "app_id": int(app_id),
            "device": device,
            "ts": int(time.time()),
        }
        headers = {
            "Content-Type": "application/json",
            "x-rpc-app_id": APP_ID_PASSPORT,
            "x-rpc-device_id": self.device_id,
        }
        try:
            r = self.session.post(scan_url, data=json.dumps(body), headers=headers, timeout=15)
            result = r.json()
            rc = result.get("retcode", -1)
            if rc == 0:
                pqr = result.get("data", {}).get("passport_qr_url", "")
                return 0, pqr, ""
            return rc, "", result.get("message", "")
        except Exception as e:
            return -2, "", str(e)[:50]

    def passport_qr_scan(self, passport_qr_url: str, stoken: str, mid: str,
                         confirm: bool = False) -> tuple[int, str]:
        """passport 扫码/确认 (抢码阶段二, 对齐 C++ PassportQRCodeLogin)

        从 passport_qr_url 提取 tk + token_types (动态), 用账号 stoken/mid
        Cookie 模拟手机扫码/确认。token_types 不能固定写死, 否则 retcode=-502。
        返回 (retcode, message)
        """
        ticket = (self._passport_qr_param(passport_qr_url, "tk", "&")
                  or self._passport_qr_param(passport_qr_url, "ticket", "&"))
        token_types = self._passport_qr_param(passport_qr_url, "token_types", "#")
        if not ticket or not token_types:
            return -1, f"缺少 tk({ticket!r}) 或 token_types({token_types!r})"
        body = {"ticket": ticket, "token_types": [token_types]}
        url = EP_PASSPORT_CONFIRM_QR if confirm else EP_PASSPORT_SCAN_QR
        headers = {
            "Content-Type": "application/json",
            "x-rpc-app_id": APP_ID_PASSPORT,
            "x-rpc-device_id": self.device_id,
            "Cookie": f"stoken={stoken}; mid={mid}",
        }
        try:
            r = self.session.post(url, data=json.dumps(body), headers=headers, timeout=15)
            result = r.json()
            return result.get("retcode", -1), result.get("message", "")
        except Exception as e:
            return -2, str(e)[:50]

    def get_web_qr_status_and_cookies(self, ticket: str) -> dict | None:
        """GetWebQrStatusAndExtractCookiesAsync: 查询状态并从 Set-Cookie 提取 cookie"""
        url = EP_PASSPORT_QUERY_STATUS
        body = {"ticket": ticket}
        body_str = json.dumps(body)
        for _ in range(3):
            headers = self._common_headers(body_str, "", "2", APP_ID_PASSPORT, "2.90.1")
            try:
                r = self.session.post(url, data=body_str, headers=headers, timeout=15)
                result = r.json()
                if result.get("retcode") == 0:
                    status = result.get("data", {}).get("status", "")
                    if status.lower() == "confirmed":
                        cookie_dict = {}
                        for set_cookie in r.headers.get("Set-Cookie", "").split(","):
                            main = set_cookie.split(";")[0].strip()
                            if "=" in main:
                                k, v = main.split("=", 1)
                                cookie_dict[k.strip()] = v.strip()
                        return cookie_dict or None
            except Exception:
                pass
            time.sleep(1)
        return None

    def exchange_v2_tokens(self, stoken: str, mid: str, aid: str) -> dict | None:
        """ExchangeV2TokensAsync 完整流程: SToken → V2 Cookie"""
        final_cookies = {"stoken": stoken, "mid": mid, "account_id": aid, "ltuid": aid}

        cookie_token = self.get_cookie_account_info_by_stoken(stoken, mid, aid)
        if cookie_token:
            final_cookies["cookie_token"] = cookie_token

        ltoken = self.get_ltoken_by_stoken(stoken, mid, aid)
        if ltoken:
            final_cookies["ltoken"] = ltoken

        web_ticket = self.create_web_qr()
        if not web_ticket:
            return None

        auth_cookie = f"stoken={stoken}; mid={mid}"
        rc, _ = self.simulate_app_action(EP_PASSPORT_SCAN_QR, web_ticket, auth_cookie)
        if rc != 0:
            return None
        time.sleep(1)
        rc, _ = self.simulate_app_action(EP_PASSPORT_CONFIRM_QR, web_ticket, auth_cookie)
        if rc != 0:
            return None

        v2 = self.get_web_qr_status_and_cookies(web_ticket)
        if v2:
            final_cookies.update(v2)
            if "stoken" not in v2 or not v2.get("stoken"):
                final_cookies["stoken"] = stoken
            return final_cookies
        return None
