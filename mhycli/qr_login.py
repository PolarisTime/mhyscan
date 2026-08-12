"""扫码登录流程 — 基于 FufuLauncher LoginQrWindow 封装

两种模式:
  A. App 扫码登录: createQRLogin 生成二维码 → 用户手机扫 → 轮询 queryQRLoginStatus → Confirmed → 提取 SToken
  B. 直播流抢码: 识别直播间二维码 → 提取 ticket → 用账号库中已登录账号的 stoken/mid
     调 scanQRLogin + confirmQRLogin → 完成抢码登录
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .api_client import MhyClient


@dataclass
class QrSession:
    """一次扫码会话"""
    ticket: str = ""
    qr_url: str = ""
    status: str = ""
    stoken: str = ""
    uid: str = ""
    mid: str = ""


def app_qr_login(client: MhyClient, on_status=None, on_qr=None,
                 timeout: float = 300.0, is_stopped=None) -> QrSession:
    """App 扫码登录: 创建二维码 → on_qr(url, ticket) → 轮询到 Confirmed

    on_status(status): 状态变化回调 (Created/Scanned/Confirmed/Expired)
    on_qr(url, ticket): 二维码创建成功后立即调用 (用于展示二维码)
    is_stopped(): 可选, 每轮轮询前调用, 返回 True 则提前退出 (用于 UI 停止)
    """
    session = QrSession()
    ok, url, ticket, msg = client.app_create_qr()
    if not ok:
        raise RuntimeError(f"创建二维码失败: {msg}")
    session.qr_url, session.ticket = url, ticket

    if on_qr:
        on_qr(url, ticket)

    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        if is_stopped and is_stopped():
            break  # 用户停止
        rc, status, data = client.app_query_status(session.ticket)
        if status != last:
            if on_status:
                on_status(status)
            last = status
        if status.lower() == "confirmed":
            _extract_app_confirmed(session, data)
            return session
        if status.lower() == "expired":
            break
        time.sleep(3)
    return session


def _extract_app_confirmed(session: QrSession, data: dict):
    """从 App 扫码 Confirmed 响应中提取 SToken (token_type==1) 和 uid/mid"""
    tokens = data.get("tokens") or []
    for tok in tokens:
        if tok.get("token_type") == 1:
            session.stoken = tok.get("token", "")
            break
    ui = data.get("user_info") or {}
    session.uid = str(ui.get("aid") or "")
    session.mid = str(ui.get("mid") or "")


def steal_qr_login(client: MhyClient, qr_url: str, stoken: str, mid: str,
                   log_cb=print) -> bool:
    """直播流抢码: 识别到的二维码 → scan + confirm

    用已登录账号的 stoken/mid 模拟手机扫码, 两种二维码走不同链路:

    - 游戏内二维码 (qr_code_in_game, panda 体系, ticket 为 32 位 hex):
      两阶段抢码 —— panda_scan 用账号换取 passport_qr_url,
      再对 passport 二维码执行 scanQRLogin + confirmQRLogin。
      游戏 ticket 不能直接给 passport scanQRLogin (会返回 -3501 已失效)。

    - passport 登录二维码 (login-platform, ticket 为 uuid):
      直接 passport scanQRLogin + confirmQRLogin。
    """
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(qr_url).query)
    ticket = (qs.get("ticket") or [""])[0]

    if "login-platform" in qr_url:
        # passport 登录二维码: 直接 passport 扫码 (URL 自带 tk + token_types)
        rc, msg = client.passport_qr_scan(qr_url, stoken, mid, confirm=False)
        log_cb(f"      [scanQRLogin] 结果: {'成功' if rc == 0 else f'失败 ({msg})'}")
        if rc != 0:
            return False
        time.sleep(1)
        rc, msg = client.passport_qr_scan(qr_url, stoken, mid, confirm=True)
        log_cb(f"      [confirmQRLogin] 结果: {'成功' if rc == 0 else f'失败 ({msg})'}")
        return rc == 0

    # ---- 游戏内二维码: 两阶段抢码 ----
    app_id = int((qs.get("app_id") or ["0"])[0] or 0)
    biz = qs.get("biz_key", [""])[0]
    log_cb(f"      [panda_scan] 提交扫码 ticket={ticket[:20]}... (app_id={app_id})")
    rc, pqr, msg = client.panda_scan_qrcode(ticket, app_id, biz)
    log_cb(f"      [panda_scan] 结果: {'成功' if rc == 0 else f'失败 ({msg})'}")
    if rc != 0 or not pqr:
        return False

    log_cb("      → 已换取 passport 二维码, passport 扫码确认...")
    rc, msg = client.passport_qr_scan(pqr, stoken, mid, confirm=False)
    log_cb(f"      [scanQRLogin] 结果: {'成功' if rc == 0 else f'失败 ({msg})'}")
    if rc != 0:
        return False
    time.sleep(1)
    rc, msg = client.passport_qr_scan(pqr, stoken, mid, confirm=True)
    log_cb(f"      [confirmQRLogin] 结果: {'成功' if rc == 0 else f'失败 ({msg})'}")
    return rc == 0
