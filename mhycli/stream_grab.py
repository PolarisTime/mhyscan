"""直播流抢码 — 对应 MHY_Scanner QRCodeForStream.cpp + 16.0 ZXing 识别

流程:
  1. 获取直播流地址 (B站/抖音) — live_link
  2. PyAV 拉流抽帧 (自带 ffmpeg, 支持自定义 Referer/UA 头, 比 opencv 稳定)
  3. ZXing (zxingcpp) 识别帧中的二维码
  4. 从二维码 URL 提取 ticket (新版格式: tk= 参数)
  5. 用账号库中已登录账号的 stoken/mid 调 scanQRLogin + confirmQRLogin 抢码

进度日志: 每 10 秒输出已等待时间 / 已使用流量 / 内存 RSS
"""
from __future__ import annotations

import logging
import os
import re
import time
from urllib.parse import parse_qs, urlparse

import av

from . import live_link
from .api_client import MhyClient
from .qr_login import steal_qr_login
from .qr_scanner import QRScanner

log = logging.getLogger(__name__)

# 二维码内容必须包含的片段 (米哈游登录平台 URL)
QR_URL_MARKERS = ("mihoyo.com", "hoyolab.com", "login-platform")
# 抽帧间隔: 每 N 帧识别一次
FRAME_SKIP = 2
# 进度日志间隔 (秒)
PROGRESS_INTERVAL = 3.0


def extract_ticket_from_url(url: str) -> str | None:
    """从二维码 URL 提取 ticket

    新版: https://user.mihoyo.com/login-platform/mobile.html?expire=..&tk=<uuid>&token_types=1#/login/qr
      → tk 参数
    旧版: https://webstatic.mihoyo.com/.../qrcode/...?ticket=.. 或 URL 末尾
    """
    if not url:
        return None
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for key in ("tk", "ticket", "t"):
        if key in qs and qs[key]:
            return qs[key][0]
    # 兜底: 若 query 里没有, 从 URL 中找 uuid 形式的 ticket
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", url)
    if m:
        return m.group(1)
    return None


def is_login_qr_url(url: str) -> bool:
    """判断是否为米哈游登录二维码"""
    return bool(url) and any(m in url for m in QR_URL_MARKERS)


def _rss_kb() -> int:
    """当前进程内存 RSS (KB), 用于泄露监控"""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return 0


def _stream_headers(platform: live_link.LivePlatform) -> dict:
    """构建拉流用 Referer/UA 头 (参考 biliup stream_headers)

    多数 CDN (如 B站) 需要 Referer 校验, 否则返回 403。
    B站拉流附带 cookie (登录后拿高清 + 抗限流, 复用 biliup 逻辑)。
    """
    if platform == live_link.LivePlatform.BiliBili:
        headers = {"Referer": live_link.BILI_REFERER, "User-Agent": live_link.BILI_UA}
        cookie = live_link.get_bili_cookie()
        if cookie:
            headers["Cookie"] = cookie
        return headers
    if platform == live_link.LivePlatform.Douyin:
        return {"Referer": "https://live.douyin.com/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    return {}


def _low_delay_options() -> dict:
    """低延迟拉流 options — B站 http-flv 默认延迟约 5-10 秒

    对齐 ffplay 低延迟参数:
      - fflags=nobuffer      禁用输入缓冲
      - probesize=1024       减少探测数据量
      - analyzeduration=0    跳过流分析
      - flags=low_delay      解码低延迟模式
    """
    return {
        "fflags": "nobuffer",
        "probesize": "1024",
        "analyzeduration": "0",
        "flags": "low_delay",
    }


# 直播流状态 → 友好提示
STREAM_STATUS_MESSAGE = {
    live_link.LiveStreamStatus.Normal: "",
    live_link.LiveStreamStatus.Absent: "直播间不存在",
    live_link.LiveStreamStatus.NotLive: "直播间未开播，请确认主播正在直播",
    live_link.LiveStreamStatus.Error: "直播流获取失败，请检查网络或 RID 是否正确",
}


class LiveStreamGrabber:
    """直播流抢码器 (对应 QRCodeForStream::LoginOfficial)"""

    def __init__(self, client: MhyClient, stoken: str, mid: str,
                 frame_skip: int = FRAME_SKIP):
        self.client = client
        self.stoken = stoken
        self.mid = mid
        self.frame_skip = frame_skip
        self.scanner = QRScanner()
        self._stop = False

    def stop(self):
        self._stop = True

    def grab_once(self, platform: live_link.LivePlatform, room_id: str,
                  timeout: float = 180.0, progress_cb=None, log_cb=print) -> tuple[bool, str]:
        """抢一次码: 拉流 → 识别 → 抢码, 成功返回 (True, ticket)

        Args:
            platform: LivePlatform.BiliBili / LivePlatform.Douyin
            room_id: 直播间 RID
            timeout: 最长时间秒
            progress_cb: 可选回调, 每 PROGRESS_INTERVAL 秒调用一次,
                         progress_cb(elapsed, bytes_read, rss_kb, frame_count)
            log_cb: 步骤日志回调, 默认 print
        """
        # [步骤1] 获取直播流地址
        log_cb(f"[1/5] 获取直播间 {room_id} 的直播流地址...")
        info = live_link.get_live_info(platform, room_id)
        if info.status != live_link.LiveStreamStatus.Normal:
            msg = STREAM_STATUS_MESSAGE.get(info.status, f"直播流获取失败: {info.status.name}")
            return False, msg
        stream_url = info.link
        log_cb(f"      → 获取成功: {stream_url[:90]}...")

        # [步骤2] 打开直播流 (低延迟)
        log_cb("[2/5] 打开直播流 (低延迟模式)...")
        headers = _stream_headers(platform)
        options = {}
        if headers:
            options["headers"] = "\r\n".join(f"{k}: {v}" for k, v in headers.items()) + "\r\n"
        options.update(_low_delay_options())
        try:
            container = av.open(stream_url, options=options, timeout=15)
            video = container.streams.video[0]
            w = video.codec_context.width
            h = video.codec_context.height
            log_cb(f"      → 已打开, 分辨率 {w}x{h}")
        except Exception as e:
            return False, f"无法打开直播流: {str(e)[:60]}"

        start = time.time()
        frame_idx = 0
        bytes_read = 0
        last_progress = start
        try:
            # [步骤3] 循环读取帧并识别
            log_cb("[3/5] 开始监视直播流, 识别登录二维码中...")
            for packet in container.demux(video):
                if self._stop:
                    break
                bytes_read += packet.size
                now = time.time()
                if now - start > timeout:
                    return False, "超时未识别到二维码"
                if progress_cb and now - last_progress >= PROGRESS_INTERVAL:
                    progress_cb(now - start, bytes_read, _rss_kb(), frame_idx)
                    last_progress = now

                for frame in packet.decode():
                    frame_idx += 1
                    if frame_idx % (self.frame_skip + 1) != 0:
                        continue

                    img = frame.to_ndarray(format="bgr24")
                    text = self.scanner.decode_single(img)
                    if not text or not is_login_qr_url(text):
                        continue

                    # [步骤4] 识别到二维码, 提取 ticket
                    ticket = extract_ticket_from_url(text)
                    if not ticket:
                        log_cb("      → 识别到二维码但无法提取 ticket, 跳过")
                        continue
                    log_cb(f"[4/5] 识别到登录二维码! ticket={ticket}")

                    # [步骤5] 抢码登录 (scan + confirm)
                    log_cb("[5/5] 调用 scanQRLogin + confirmQRLogin 抢码...")
                    ok = steal_qr_login(self.client, ticket, self.stoken, self.mid,
                                        log_cb=log_cb)
                    if ok:
                        log_cb("      → 抢码登录成功!")
                        return True, ticket
                    log_cb("      → 抢码失败, 继续监视")
        except KeyboardInterrupt:
            pass
        except Exception as e:
            return False, f"拉流异常: {str(e)[:60]}"
        finally:
            try:
                container.close()
            except Exception:
                pass
        return False, "停止"
