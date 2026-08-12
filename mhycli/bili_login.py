"""B站 TV 端二维码登录 — 复用 biliup credential.rs 逻辑

流程 (biliup get_qrcode + login_by_qrcode):
  1. POST /x/passport-tv-login/qrcode/auth_code → 获取 auth_code + 二维码 URL
  2. 用 qrcode_url 生成二维码, 手机 B 站 APP 扫码
  3. 轮询 POST /x/passport-tv-login/qrcode/poll:
     - code=0     → 登录成功, 返回 cookie_info (含 SESSDATA 等)
     - code=86039 → 尚未确认, 继续轮询
  登录成功后可保存 cookie 到 Config/bili_cookie.json (get_bili_cookie 读取格式)
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path

import requests

# BiliTV app_key/appsec (biliup AppKeyStore::BiliTV)
BILI_TV_APPKEY = "4409e2ce8ffd12b8"
BILI_TV_APPSEC = "59b43e04ad6965f34319062b478f83dd"

# TV 端登录 API
API_AUTH_CODE = "https://passport.bilibili.com/x/passport-tv-login/qrcode/auth_code"
API_POLL = "https://passport.bilibili.com/x/passport-tv-login/qrcode/poll"

# BiliApp UA (biliup login_by_web_qrcode 使用; 缺 UA 会返回 412)
BILI_UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:38.0) Gecko/20100101 "
           "Firefox/38.0 Iceweasel/38.2.1 BiliApp")

# cookie 保存路径 (与 get_bili_cookie 一致)
COOKIE_FILE = Path(__file__).resolve().parent.parent / "Config" / "bili_cookie.json"


def _sign(urlencoded: str, app_sec: str = BILI_TV_APPSEC) -> str:
    """MD5(urlencoded_params + appsec) — 对应 biliup sign()"""
    return hashlib.md5((urlencoded + app_sec).encode("utf-8")).hexdigest()


def _build_auth_code_form() -> dict:
    """构造 auth_code 请求 form (appkey + local_id + ts + sign)"""
    from urllib.parse import urlencode

    form = {
        "appkey": BILI_TV_APPKEY,
        "local_id": "0",
        "ts": str(int(time.time())),
    }
    form["sign"] = _sign(urlencode(form))
    return form


def _tv_headers() -> dict:
    """TV 端请求头 (BiliApp UA 必须, 否则 412)"""
    return {"User-Agent": BILI_UA}


def get_qrcode(session: requests.Session | None = None) -> tuple[str, str]:
    """获取登录二维码, 返回 (qrcode_url, auth_code)

    对应 biliup get_qrcode
    """
    s = session or requests.Session()
    resp = s.post(API_AUTH_CODE, data=_build_auth_code_form(),
                  headers=_tv_headers(), timeout=15)
    resp.raise_for_status()
    j = resp.json()
    if j.get("code") != 0:
        raise RuntimeError(f"获取二维码失败: {j.get('code')} {j.get('message')}")
    data = j.get("data", {})
    qrcode_url = data.get("url") or data.get("qrcode_url") or ""
    auth_code = data.get("auth_code") or ""
    if not qrcode_url or not auth_code:
        raise RuntimeError(f"二维码数据不完整: {data}")
    return qrcode_url, auth_code


def poll_login(session: requests.Session | None, auth_code: str,
               on_status=None, timeout: float = 180.0) -> dict:
    """轮询扫码状态, 登录成功返回完整响应 (含 data.cookie_info)

    对应 biliup login_by_qrcode
    on_status(code): 状态回调 (86039=等待确认, -4=未扫, -5=已扫, 0=成功)
    """
    from urllib.parse import urlencode

    s = session or requests.Session()
    deadline = time.time() + timeout
    while time.time() < deadline:
        form = {
            "appkey": BILI_TV_APPKEY,
            "auth_code": auth_code,
            "local_id": "0",
            "ts": str(int(time.time())),
        }
        form["sign"] = _sign(urlencode(form))
        try:
            resp = s.post(API_POLL, data=form, headers=_tv_headers(), timeout=15)
            resp.raise_for_status()
            j = resp.json()
        except (requests.RequestException, ValueError) as e:
            if on_status:
                on_status("network_error")
            time.sleep(2)
            continue

        code = j.get("code")
        if on_status:
            on_status(code)

        if code == 0 and j.get("data", {}).get("cookie_info"):
            return j  # 登录成功
        if code == -4:
            continue  # 二维码未扫描
        time.sleep(1.5)
    raise TimeoutError("扫码登录超时")


def extract_cookies(login_response: dict) -> list[dict]:
    """从登录响应提取 cookie 列表 [{name, value}]"""
    cookie_info = (login_response.get("data") or {}).get("cookie_info") or {}
    return list(cookie_info.get("cookies") or [])


def save_cookies_to_file(cookies: list[dict], path: Path | None = None):
    """保存 cookie 到 biliup 格式文件 (get_bili_cookie 读取格式)"""
    target = path or COOKIE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {"cookie_info": {"cookies": cookies}}
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cookie_summary(cookies: list[dict]) -> str:
    """返回 cookie 概要 (列出关键字段名)"""
    names = [c.get("name") for c in cookies if c.get("name")]
    return ", ".join(names) if names else "(空)"
