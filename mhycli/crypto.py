"""加密/签名工具 — 对应开源版 CryptoKit.cpp / MhyApi.hpp

包含:
- MD5 / HMAC-SHA256
- RSA PKCS#1 公钥加密 (Base64 输出)
- 米游社 DS 签名 (DataSignAlgorithmVersionGen2)
- makeSign (B站崩3 combo 签名, key=0ebc517adb1b62c6b408df153331f9aa)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

# 开源版 MhyApi.hpp 中内嵌的 RSA 公钥 (用于 CreateLoginCaptcha 的 area_code/mobile 加密)
MIHOYO_PUBLIC_KEY = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDDvekdPMHN3AYhm/vktJT+YJr7"
    "cI5DcsNKqdsx5DZX0gDuWFuIjzdwButrIYPNmRJ1G8ybDIF7oDW2eEpm5sMbL9zs"
    "9ExXCdvqrn51qELbqj0XxtMTIpaCHFSI50PfPpTFV9Xt/hmyVwokoOXFlAEgCn+Q"
    "CgGs52bFoYMtyi+xEQIDAQAB\n"
    "-----END PUBLIC KEY-----"
)

# 米游社 DS2 签名 salt (MhyApi.hpp mihoyobbs_salt_x6)
MHY_BBS_SALT_X6 = "t0qEgfub6cvueAPgR5m9aQWWVciEer7v"

# 米游社 game_record X4 salt (Snap.Hutao SaltType.X4)
MHY_BBS_SALT_X4 = "xV8v4Qu54lUKrEYFZkJhB8cuOh9Asafs"

# B站崩3 combo 签名 key (MhyApi.hpp makeSign)
COMBO_SIGN_KEY = "0ebc517adb1b62c6b408df153331f9aa"


def md5(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.md5(data).hexdigest()


def hmac_sha256_hex(message: str | bytes, key: str | bytes) -> str:
    if isinstance(message, str):
        message = message.encode("utf-8")
    if isinstance(key, str):
        key = key.encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def rsa_encrypt_base64(message: str | bytes, public_key_pem: str = MIHOYO_PUBLIC_KEY) -> str:
    """RSA PKCS#1 v1.5 加密并 Base64 编码 (对应 CryptoKit::rsaEncrypt)"""
    if isinstance(message, str):
        message = message.encode("utf-8")
    pub = serialization.load_pem_public_key(
        public_key_pem.encode("utf-8"), backend=default_backend()
    )
    encrypted = pub.encrypt(message, padding.PKCS1v15())
    return base64.b64encode(encrypted).decode("ascii")


def data_sign_gen2(body: str, query: str = "") -> str:
    """DataSignAlgorithmVersionGen2: 返回 't,r,md5' 组成的 DS 头值

    对应 MhyApi.hpp:
        m = "salt=" + salt_x6 + "&t=" + t + "&r=" + r + "&b=" + body + "&q=" + query
    """
    t = str(int(time.time()))
    r = str(secrets.randbelow(200000 - 100001) + 100001)
    m = f"salt={MHY_BBS_SALT_X6}&t={t}&r={r}&b={body}&q={query}"
    return f"{t},{r},{md5(m)}"


def data_sign_x4(query: str = "", salt: str = MHY_BBS_SALT_X4) -> str:
    """game_record DS2 签名 (X4 salt) — Snap.Hutao Gen2 + SaltType.X4

    用于 api-takumi-record.mihoyo.com 游戏记录接口
    """
    t = str(int(time.time()))
    r = str(secrets.randbelow(200000 - 100001) + 100001)
    m = f"salt={salt}&t={t}&r={r}&b=&q={query}"
    return f"{t},{r},{md5(m)}"


def data_sign_gen1_x4(salt: str = MHY_BBS_SALT_X4) -> str:
    """DS1 签名 (X4 salt) — 用于 getUserGameRolesByCookie

    对应 FufuLauncher GenerateDS: md5(salt&t&r)
    """
    t = str(int(time.time()))
    r = str(secrets.randbelow(200000 - 100001) + 100001)
    m = f"salt={salt}&t={t}&r={r}"
    return f"{t},{r},{md5(m)}"


def make_sign(data: dict) -> str:
    """B站崩3 combo 请求签名 — 对应 MhyApi.hpp::makeSign

    规则: 除 sign 外的所有键按出现顺序拼成 'k=v&k=v', 再去掉末尾 '&',
    然后 HMAC-SHA256(param, COMBO_SIGN_KEY)
    """
    parts: list[str] = []
    for key, value in data.items():
        if key == "sign":
            continue
        if isinstance(value, str):
            sv = value
        else:
            sv = __json_dump(value)
        parts.append(f"{key}={sv}")
    param = "&".join(parts)
    return hmac_sha256_hex(param, COMBO_SIGN_KEY)


def __json_dump(value) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
