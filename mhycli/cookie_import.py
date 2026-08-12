"""账号导入 — 对应 MHY_Scanner WindowLogin.cpp Tab2 (粘贴 Cookie 登录)

支持:
  - 粘贴完整 Cookie 串 (含 stoken / mid / stuid|ltuid|account_id)
  - 直接提供 stoken + uid + mid
"""
from __future__ import annotations

import re


class CookieParseError(ValueError):
    pass


def parse_cookie(cookie_str: str) -> dict[str, str]:
    """解析 Cookie 串为 {key: value} (对应 CookieParser.hpp)"""
    result = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k:
            result[k] = v
    return result


def extract_account_from_cookie(cookie_str: str) -> dict[str, str]:
    """从 Cookie 提取 {stoken, uid, mid, name}

    对应 WindowLogin.cpp pBtofficialLogin 点击逻辑:
      uid 从 stuid/ltuid/account_id 三者取其一
      stoken 必须存在; mid 必须存在
    """
    cookies = parse_cookie(cookie_str)
    if not cookies:
        raise CookieParseError("Cookie 为空或格式错误")

    uid = None
    for key in ("stuid", "ltuid", "account_id"):
        if key in cookies and cookies[key]:
            uid = cookies[key]
            break
    if uid is None:
        raise CookieParseError("Cookie 缺少 stuid/ltuid/account_id")

    stoken = cookies.get("stoken")
    if not stoken:
        raise CookieParseError("Cookie 缺少 stoken")

    mid = cookies.get("mid")
    if not mid:
        raise CookieParseError("Cookie 缺少 mid")

    return {"stoken": stoken, "uid": uid, "mid": mid}


def is_stoken_cookie(cookie_str: str) -> bool:
    """粗略判断是否为含 SToken 的 Cookie"""
    return bool(re.search(r"(^|;\s*)stoken=", cookie_str))
