"""米游社游戏角色信息 (game_record)

仅保留角色列表获取:
  GET api-takumi.mihoyo.com/binding/api/getUserGameRolesByCookie (DS1 X4)

注: 深渊/剧诗查询已移除 (受 device_fp 风控影响不稳定, 详见历史实现)。
"""
from __future__ import annotations

import json
import random
import time

import requests

from .config import CacheStore
from .crypto import data_sign_gen1_x4

API_TAKUMI = "https://api-takumi.mihoyo.com"

ROLE_TTL = 7 * 24 * 3600  # 角色信息 7 天


def _rand_lower_hex(n: int) -> str:
    return "".join(random.choice("0123456789abcdef") for _ in range(n))


class GameRecordClient:
    """游戏角色信息客户端"""

    def __init__(self, cookie: str, cache: CacheStore | None = None,
                 log_cb=print):
        self.cookie = cookie
        self.cache = cache or CacheStore()
        self.log_cb = log_cb
        self.device_id = _rand_lower_hex(16)

    # ---- 角色列表 (7 天缓存) ----

    def get_roles(self, force_refresh: bool = False) -> list[dict]:
        """获取游戏角色列表, 带 7 天缓存"""
        if not force_refresh:
            cached = self.cache.get("roles")
            if cached:
                return cached

        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 12; Unspecified Device) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/103.0.5060.129 Mobile Safari/537.36 miHoYoBBS/2.93.1",
            "Accept": "application/json",
            "Cookie": self.cookie,
            "Referer": "https://act.mihoyo.com/",
            "Origin": "https://act.mihoyo.com",
            "x-rpc-device_id": self.device_id,
            "x-rpc-client_type": "5",
            "DS": data_sign_gen1_x4(),
        }
        url = f"{API_TAKUMI}/binding/api/getUserGameRolesByCookie?game_biz=hk4e_cn"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            j = r.json()
            if j.get("retcode") != 0:
                self.log_cb(f"      [角色] 获取失败: {j.get('message')}")
                return []
            roles = (j.get("data") or {}).get("list", [])
            self.cache.set("roles", roles)
            return roles
        except Exception as e:
            self.log_cb(f"      [角色] 获取异常: {e}")
            return []


def format_roles(roles: list[dict]) -> str:
    """格式化角色列表"""
    if not roles:
        return "无角色"
    parts = []
    for role in roles:
        parts.append(f"{role.get('game_uid')}({role.get('region_name')}) Lv{role.get('level')} {role.get('nickname')}")
    return " | ".join(parts)
