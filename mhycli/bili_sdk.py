"""B站崩坏3 (B服) 登录 — 对应开源版 BSGameSDK.hpp

流程:
  1. 请求 /api/client/rsa 获取 RSA 公钥, 加密密码
  2. POST /api/client/login 登录 → access_key + uid
  3. POST /api/client/user.info 获取昵称
  (若需极验验证码: 先 /api/client/start_captcha 获取 gt/challenge)
"""
from __future__ import annotations

import json
import time

import requests

from .crypto import md5, rsa_encrypt_base64

BILI_BASE = "https://line1-sdk-center-login-sh.biligame.net"
BILI_RSA = f"{BILI_BASE}/api/client/rsa"
BILI_LOGIN = f"{BILI_BASE}/api/client/login"
BILI_USERINFO = f"{BILI_BASE}/api/client/user.info"
BILI_CAPTCHA = f"{BILI_BASE}/api/client/start_captcha"

HEADERS = {
    "User-Agent": "Mozilla/5.0 BSGameSDK",
    "Content-Type": "application/x-www-form-urlencoded",
    "Host": "line1-sdk-center-login-sh.biligame.net",
}

# BSGameSDK.hpp 中写死的设备参数 (MuMu 模拟器指纹)
BASE_PARAM = {
    "operators": "5", "merchant_id": "590", "isRoot": "0", "domain_switch_count": "0",
    "sdk_type": "1", "sdk_log_type": "1",
    "support_abis": "x86,armeabi-v7a,armeabi",
    "access_key": "", "sdk_ver": "3.4.2", "oaid": "", "dp": "1280*720",
    "original_domain": "", "imei": "",
    "version": "1", "udid": "KREhESMUIhUjFnJKNko2TDQFYlZkB3cdeQ==",
    "apk_sign": "4502a02a00395dec05a4134ad593224d", "platform_type": "3",
    "old_buvid": "XZA2FA4AC240F665E2F27F603ABF98C615C29",
    "android_id": "84567e2dda72d1d4", "fingerprint": "", "mac": "08:00:27:53:DD:12",
    "server_id": "378", "domain": "line1-sdk-center-login-sh.biligame.net",
    "app_id": "180", "version_code": "510", "net": "4", "pf_ver": "12",
    "cur_buvid": "XZA2FA4AC240F665E2F27F603ABF98C615C29", "c": "1",
    "brand": "Android", "channel_id": "1", "uid": "", "game_id": "180",
    "ver": "6.1.0", "model": "MuMu",
}


def _set_sign(data: dict) -> str:
    """对应 BSGameSDK::detail::SetSign
    除 pwd 外不 urlEncode, 生成 k=v& 串, 再加 sign=md5(所有值拼接+key)
    """
    data = dict(data)
    data["timestamp"] = str(int(time.time()))
    data["client_timestamp"] = str(int(time.time()))
    from urllib.parse import quote

    body_parts = []
    values = []
    for key, value in data.items():
        if isinstance(value, str):
            sv = value
        else:
            sv = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if key == "pwd":
            body_parts.append(f"{key}={quote(sv)}")
        else:
            body_parts.append(f"{key}={sv}")
        values.append(sv)
    sign_raw = "".join(values) + "dbf8f1b4496f430b8a3c0f436a35b931"
    body = "&".join(body_parts) + "&" + "sign=" + md5(sign_raw)
    return body


def _encrypted_pwd(password: str) -> str:
    """对应 BSGameSDK::detail::GetEncryptedPwd
    先请求 rsa 接口拿公钥+hash, 再对 hash+pwd 做 RSA 加密
    """
    rsa_param = {k: v for k, v in BASE_PARAM.items() if k not in ("access_key",)}
    rsa_param["access_key"] = ""
    rsa_param["timestamp"] = str(int(time.time()))
    rsa_param["client_timestamp"] = str(int(time.time()))
    body = _set_sign(rsa_param)
    resp = requests.post(BILI_RSA, data=body, headers=HEADERS)
    resp.raise_for_status()
    info = resp.json()
    public_key = info["rsa_key"]
    hash_ = info["hash"]
    return rsa_encrypt_base64(hash_ + password, public_key)


def login_by_password(account: str, password: str, gt_user: str = "",
                      challenge: str = "", validate: str = "") -> dict:
    """对应 BSGameSDK::LoginByPassWord
    返回 {code, message, uid, access_key, uname}
    """
    data = {k: v for k, v in BASE_PARAM.items()}
    data.update({
        "access_key": "", "gt_user_id": gt_user, "uid": "",
        "challenge": challenge, "user_id": account, "validate": validate,
    })
    if validate:
        data["seccode"] = validate + "|jordan"
    data["pwd"] = _encrypted_pwd(password)

    body = _set_sign(data)
    resp = requests.post(BILI_LOGIN, data=body, headers=HEADERS)
    resp.raise_for_status()
    info = resp.json()
    result = {"code": info.get("code", -1), "message": info.get("message", ""),
              "uid": "", "access_key": "", "uname": ""}
    if info.get("code") in (0,):
        result["uid"] = str(info.get("uid", ""))
        result["access_key"] = info.get("access_key", "")
        ui = get_user_info(result["uid"], result["access_key"])
        result["uname"] = ui["uname"]
    return result


def get_user_info(uid: str, access_key: str) -> dict:
    """对应 BSGameSDK::GetUserInfo"""
    data = {k: v for k, v in BASE_PARAM.items()}
    data.update({"uid": uid, "access_key": access_key})
    body = _set_sign(data)
    resp = requests.post(BILI_USERINFO, data=body, headers=HEADERS)
    resp.raise_for_status()
    info = resp.json()
    return {"code": info.get("code", -1), "uname": info.get("uname", "")}


def start_captcha() -> dict:
    """对应 BSGameSDK::CaptchaCaptcha — 返回 GeetestData"""
    data = {k: v for k, v in BASE_PARAM.items()}
    body = _set_sign(data)
    resp = requests.post(BILI_CAPTCHA, data=body, headers=HEADERS)
    resp.raise_for_status()
    cap = resp.json()
    return {"gt": cap.get("gt", ""), "challenge": cap.get("challenge", ""),
            "gt_user_id": cap.get("gt_user_id", "")}
