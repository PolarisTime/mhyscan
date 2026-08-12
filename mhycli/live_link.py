"""直播流地址获取 — 对应开源版 LiveStreamLink.cpp

支持 B站 (bilibili) 和抖音 (douyin) 两种直播平台。
根据 RID 获取直播间真实播放流地址。

B站 cookie 支持 (复用 biliup 逻辑):
  - 匿名: 720P 超清 (请求 qn=10000 但被降为 qn=250)
  - 带登录 cookie: 可拿 1080P 原画 + 抗限流
  cookie 来源 (优先级):
    1. 环境变量 BILIBILI_COOKIE (直接 Cookie 字符串)
    2. Config/bili_cookie.json (biliup 格式: {"cookie_info":{"cookies":[{"name":..,"value":..}]}})
"""
from __future__ import annotations

import json
import os
from enum import IntEnum
from pathlib import Path

import requests

# B站
BILI_ROOM_INIT = "https://api.live.bilibili.com/room/v1/Room/room_init"
BILI_ROOM_INFO = "https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom"
BILI_PLAY_INFO = "https://api.live.bilibili.com/xlive/web-room/v2/index/getRoomPlayInfo"
# 抖音
DOUYIN_ENTER = "https://live.douyin.com/webcast/room/web/enter/?"

# biliup 项目的 UA 与 Referer (防风控)
BILI_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
BILI_REFERER = "https://live.bilibili.com"
BILI_HEADERS = {"User-Agent": BILI_UA, "Referer": BILI_REFERER}

# 默认 cookie 文件路径 (biliup 格式)
_BILI_COOKIE_FILE = Path(__file__).resolve().parent.parent / "Config" / "bili_cookie.json"

# 缓存已加载的 cookie (进程内只读一次)
_bili_cookie_cache: str | None = None
_bili_cookie_loaded = False


def get_bili_cookie(force_refresh: bool = False) -> str:
    """获取 B站 cookie (复用 biliup 逻辑)

    优先级:
      1. 环境变量 BILIBILI_COOKIE (直接 Cookie 字符串)
      2. Config/bili_cookie.json (biliup 导出格式)
    返回 Cookie 字符串; 无则返回空串
    force_refresh=True: 忽略进程缓存, 重新读取 (B站登录/退出后需调用)
    """
    global _bili_cookie_cache, _bili_cookie_loaded
    if _bili_cookie_loaded and not force_refresh:
        return _bili_cookie_cache or ""

    # 1. 环境变量
    env = os.environ.get("BILIBILI_COOKIE", "").strip()
    if env:
        _bili_cookie_cache = env
        _bili_cookie_loaded = True
        return env

    # 2. biliup 格式 cookie 文件
    try:
        if _BILI_COOKIE_FILE.exists():
            data = json.loads(_BILI_COOKIE_FILE.read_text(encoding="utf-8"))
            cookies = (data.get("cookie_info") or {}).get("cookies") or []
            parts = []
            for c in cookies:
                name = c.get("name")
                value = c.get("value")
                if name and value:
                    parts.append(f"{name}={value}")
            _bili_cookie_cache = ";".join(parts) if parts else None
        else:
            # 文件不存在 (含 force_refresh 后删除的情况): 清缓存
            _bili_cookie_cache = None
    except Exception:
        _bili_cookie_cache = None

    _bili_cookie_loaded = True
    return _bili_cookie_cache or ""


def bili_headers() -> dict:
    """B站请求头 (含 cookie 时附加)"""
    headers = dict(BILI_HEADERS)
    cookie = get_bili_cookie()
    if cookie:
        headers["Cookie"] = cookie
    return headers

# 抖音请求用到的固定 cookie (开源版写死)
DOUYIN_COOKIE = (
    "enter_pc_once=1; UIFID_TEMP=29a1f63ec682dc0a0df227dd163e2b46e3a6390e403335fa4c2c6d1dc0ec5ffa7a288170e8828ecb8b2f0f16b3219daa18ad5d7faf7fb5fbb64df454c3b471cc1db9c0b5eb2cbc8e0cb1e690f5c1fbd6; "
    "stream_recommend_feed_params=%22%7B%5C%22cookie_enabled%5C%22%3Atrue%2C%5C%22screen_width%5C%22%3A2560%2C%5C%22screen_height%5C%22%3A1440%2C%5C%22browser_online%5C%22%3Atrue%2C%5C%22cpu_core_num%5C%22%3A16%2C%5C%22device_memory%5C%22%3A8%2C%5C%22downlink%5C%22%3A10%2C%5C%22effective_type%5C%22%3A%5C%224g%5C%22%2C%5C%22round_trip_time%5C%22%3A50%7D%22; "
    "hevc_supported=true; odin_tt=363047b47492a2e153d67e7022684ffd83726a0c57322991e6650da1dbe2fc0adb471e8be38efa85bf0ab9788a8e237d481c8fc488ef859f4476fc6ffd50dd31a258add2954b3fcf03cd546357df6a53; "
    "strategyABtestKey=%221772897157.15%22; passport_csrf_token=d71952d93315e4df5cc8373e4cdc2447; passport_csrf_token_default=d71952d93315e4df5cc8373e4cdc2447; "
    "home_can_add_dy_2_desktop=%221%22; biz_trace_id=fab9d888; "
    "ttwid=1%7CP0feYUzzIsbXr2aaLLBWHYtwVD4-6CV2voO9bAUQ7PU%7C1772897161%7Cd72bed8f6f576a1dfb7b8d1032c76706ce93b3ba3ac5b21e79501db1c2f17c9f; "
    "__security_mc_1_s_sdk_crypt_sdk=0ef27763-40a0-b3c3; "
    "is_dash_user=1; x-web-secsdk-uid=17063330-58d4-4719-9971-dba52fc661ab; "
    "__live_version__=%221.1.4.9549%22; has_avx2=null; device_web_cpu_core=16; device_web_memory_size=8; "
    "webcast_local_quality=null; live_use_vvc=%22false%22; csrf_session_id=5fe8f9d1180e55817920dae0808993ba; "
    "h265ErrorNum=-1; IsDouyinActive=false; live_can_add_dy_2_desktop=%220%22"
)


class LiveStreamStatus(IntEnum):
    Normal = 0
    Absent = 1
    NotLive = 2
    Error = 3


class LivePlatform(IntEnum):
    Douyin = 0
    BiliBili = 1


class LiveStreamInfo:
    def __init__(self, status: LiveStreamStatus, link: str = ""):
        self.status = status
        self.link = link


class LiveBili:
    """B站直播间 — 参考 biliup 项目封装 (带 UA/Referer/Cookie, 多协议候选回退)

    biliup 关键点:
      - Chrome UA + Referer: https://live.bilibili.com (无 UA 会被反爬拦截)
      - 可选 Cookie (登录后拿 1080P 原画 + 抗限流)
      - 房间信息用 getInfoByRoom, 播放信息用 getRoomPlayInfo
      - 多协议候选: flv 优先, hls 回退
    """

    def __init__(self, room_id: str):
        self.room_id = room_id
        self.real_room_id = room_id
        self.cookie = get_bili_cookie()

    def get_live_stream_info(self) -> LiveStreamInfo:
        headers = bili_headers()
        # 1. 获取房间信息
        resp = requests.get(BILI_ROOM_INIT, params={"id": self.room_id},
                            headers=headers, timeout=10)
        if resp.status_code != 200 or not resp.text:
            return LiveStreamInfo(LiveStreamStatus.Error)
        try:
            info = resp.json()
        except json.JSONDecodeError:
            return LiveStreamInfo(LiveStreamStatus.Error)

        code = info.get("code", -1)
        if code == 60004:
            return LiveStreamInfo(LiveStreamStatus.Absent)
        if code != 0:
            return LiveStreamInfo(LiveStreamStatus.Error)
        data = info.get("data", {})
        if data.get("live_status") != 1:
            return LiveStreamInfo(LiveStreamStatus.NotLive)
        if "room_id" in data:
            self.real_room_id = str(data["room_id"])

        # 2. 获取播放流 (flv 优先, hls 回退 — biliup 多协议候选)
        link = self._get_stream_url("0")       # flv
        if not link:
            link = self._get_stream_url("1")   # hls
        if not link:
            return LiveStreamInfo(LiveStreamStatus.Error)
        return LiveStreamInfo(LiveStreamStatus.Normal, link)

    def _get_stream_url(self, protocol: str = "0") -> str:
        """按协议获取播放流地址 (biliup request_play_info + parse_play_info)

        protocol: "0"=flv, "1"=hls
        qn: 有 cookie 用 10000(原画1080P), 匿名请求也传 10000 (服务端可能降 720P)
        """
        params = {
            "room_id": self.real_room_id,
            "qn": "10000",
            "platform": "html5",
            "protocol": protocol,
            "format": "0,1,2",
            "codec": "0",
            "dolby": "5",
        }
        try:
            resp = requests.get(BILI_PLAY_INFO, params=params,
                                headers=bili_headers(), timeout=10)
            if resp.status_code != 200 or not resp.text:
                return ""
            j = resp.json()
        except (json.JSONDecodeError, requests.RequestException):
            return ""
        if j.get("code") != 0:
            return ""

        # 解析 stream 候选 (参考 biliup parse_play_info)
        try:
            playurl = j["data"]["playurl_info"]["playurl"]
            streams = playurl.get("stream", [])
            for stream in streams:
                for fmt in stream.get("format", []):
                    for codec in fmt.get("codec", []):
                        url_info = codec.get("url_info", [])
                        if not url_info:
                            continue
                        base_url = codec.get("base_url", "")
                        extra = url_info[0].get("extra", "")
                        host = url_info[0].get("host", "")
                        if base_url:
                            return host + base_url + extra
        except (KeyError, IndexError, TypeError):
            pass
        return ""


class LiveDouyin:
    """抖音直播间 — 对应 LiveDouyin::GetLiveStreamInfo"""
    def __init__(self, room_id: str):
        self.room_id = room_id

    def get_live_stream_info(self) -> LiveStreamInfo:
        user_agent = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36")
        headers = {
            "User-Agent": user_agent,
            "referer": "https://live.douyin.com/",
            "cookie": DOUYIN_COOKIE,
        }
        params = (
            "aid=6383&app_name=douyin_web&live_id=1&device_platform=web&"
            "browser_language=zh-CN&browser_platform=Win32&browser_name=Edge&"
            "browser_version=139.0.0.0&is_need_double_stream=false&web_rid=" + self.room_id
        )
        url = DOUYIN_ENTER + params
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200 or not resp.text:
                return LiveStreamInfo(LiveStreamStatus.Error)
            info = resp.json()
            if info.get("status_code") != 0:
                return LiveStreamInfo(LiveStreamStatus.Absent)
            data = info["data"]["data"][0]
            status = data.get("status")
            if status == 2:  # 开播
                link = self._get_stream_link_from_response(data)
                if not link:
                    return LiveStreamInfo(LiveStreamStatus.Error)
                return LiveStreamInfo(LiveStreamStatus.Normal, link)
            elif status == 4:  # 未开播
                return LiveStreamInfo(LiveStreamStatus.NotLive)
            return LiveStreamInfo(LiveStreamStatus.Error)
        except (json.JSONDecodeError, KeyError, IndexError, requests.RequestException):
            return LiveStreamInfo(LiveStreamStatus.Error)

    def _get_stream_link_from_response(self, data: dict) -> str:
        try:
            stream_url = data["stream_url"]
            if "pull_datas" in stream_url and stream_url["pull_datas"]:
                pull_datas = stream_url["pull_datas"]
                double_screen = next(iter(pull_datas.values()))
                stream_data_str = double_screen["stream_data"]
                stream_data = json.loads(stream_data_str)
                return stream_data["data"]["origin"]["main"]["flv"]
            if "live_core_sdk_data" in stream_url:
                stream_data_str = stream_url["live_core_sdk_data"]["pull_data"]["stream_data"]
                stream_data = json.loads(stream_data_str)
                return stream_data["data"]["origin"]["main"]["flv"]
            return ""
        except (json.JSONDecodeError, KeyError, TypeError):
            return ""


def get_live_info(platform: LivePlatform, room_id: str) -> LiveStreamInfo:
    if platform == LivePlatform.Douyin:
        return LiveDouyin(room_id).get_live_stream_info()
    elif platform == LivePlatform.BiliBili:
        return LiveBili(room_id).get_live_stream_info()
    return LiveStreamInfo(LiveStreamStatus.Error)
