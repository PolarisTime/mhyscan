"""账号存储管理 — 对应开源版 ConfigDate.cpp / WindowMain 的 userinfo.json

结构 (与开源版一致):
{
  "auto_exit": false, "auto_login": false, "auto_start": false,
  "account": [ {"access_key": SToken, "uid": "…", "name": "…", "type": "官服/崩坏3B服", "note": "", "mid": "…"} ],
  "last_account": 0, "num": 0
}
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# 默认配置固定指向项目根 (不受当前工作目录影响)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "Config" / "userinfo.json"
DEFAULT_CACHE_PATH = _PROJECT_ROOT / "Config" / "cache.json"

# 默认缓存时效: 7 天 (秒)
DEFAULT_TTL = 7 * 24 * 3600


class AccountStore:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path else DEFAULT_CONFIG_PATH
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return self.default()
        return self.default()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=4), encoding="utf-8")

    @staticmethod
    def default() -> dict:
        return {"auto_exit": False, "auto_login": False, "auto_start": False,
                "account": [], "last_account": 0, "num": 0}

    # ---- 账号 CRUD ----
    def list_accounts(self) -> list[dict]:
        return list(self.data.get("account", []))

    def add_account(self, name: str, token: str, uid: str, mid: str, type_: str) -> bool:
        """重复账号(同 uid)拒绝添加, 返回是否成功"""
        for acc in self.data["account"]:
            if acc.get("uid") == uid:
                return False
        self.data["account"].append({
            "access_key": token, "uid": uid, "name": name, "type": type_, "note": "", "mid": mid,
        })
        self.data["num"] = len(self.data["account"])
        self.save()
        return True

    def remove_account(self, uid: str) -> bool:
        before = len(self.data["account"])
        self.data["account"] = [a for a in self.data["account"] if a.get("uid") != uid]
        self.data["num"] = len(self.data["account"])
        if len(self.data["account"]) != before:
            self.save()
            return True
        return False

    def get_account(self, uid: str) -> dict | None:
        for a in self.data["account"]:
            if a.get("uid") == uid:
                return a
        return None

    def get_last_account(self) -> dict | None:
        idx = self.data.get("last_account", 0)
        accs = self.data["account"]
        if 0 <= idx < len(accs):
            return accs[idx]
        return accs[0] if accs else None

    def set_last_account(self, uid: str):
        for i, a in enumerate(self.data["account"]):
            if a.get("uid") == uid:
                self.data["last_account"] = i
                self.save()
                return

    # ---- 设置项 ----
    def get_bool(self, key: str) -> bool:
        return bool(self.data.get(key, False))

    def set_bool(self, key: str, value: bool):
        self.data[key] = bool(value)
        self.save()


class CacheStore:
    """通用缓存 (带 TTL 时效) — 用于角色/device_fp 等数据

    文件: Config/cache.json, 每项 {key: {"value": ..., "ts": <unix秒>}}
    """

    def __init__(self, path: str | os.PathLike | None = None, ttl: int = DEFAULT_TTL):
        self.path = Path(path) if path else DEFAULT_CACHE_PATH
        self.ttl = ttl
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, key: str):
        """读取缓存, 已过期返回 None"""
        entry = self.data.get(key)
        if not entry:
            return None
        import time

        if time.time() - entry.get("ts", 0) > self.ttl:
            return None
        return entry.get("value")

    def set(self, key: str, value):
        """写入缓存"""
        import time

        self.data[key] = {"value": value, "ts": int(time.time())}
        self.save()

    def clear(self, key: str | None = None):
        if key is None:
            self.data = {}
        else:
            self.data.pop(key, None)
        self.save()
