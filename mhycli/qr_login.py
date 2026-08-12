"""扫码登录流程 — 基于 FufuLauncher LoginQrWindow 封装

两种模式:
  A. App 扫码登录: createQRLogin 生成二维码 → 用户手机扫 → 轮询 queryQRLoginStatus → Confirmed → 提取 SToken
  B. 直播流抢码: 识别直播间二维码 → 提取 ticket → 用账号库中已登录账号的 stoken/mid
     调 scanQRLogin + confirmQRLogin → 完成抢码登录
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .api_client import (
    MhyClient,
    EP_PASSPORT_SCAN_QR,
    EP_PASSPORT_CONFIRM_QR,
)


@dataclass
class QrSession:
    """一次扫码会话"""
    ticket: str = ""
    qr_url: str = ""
    status: str = ""
    stoken: str = ""
    uid: str = ""
    mid: str = ""


def app_qr_login(client: MhyClient, on_status=None, on_qr=None, timeout: float = 300.0) -> QrSession:
    """App 扫码登录: 创建二维码 → on_qr(url, ticket) → 轮询到 Confirmed

    on_status(status): 状态变化回调 (Created/Scanned/Confirmed/Expired)
    on_qr(url, ticket): 二维码创建成功后立即调用 (用于展示二维码)
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


def steal_qr_login(client: MhyClient, ticket: str, stoken: str, mid: str,
                   log_cb=print) -> bool:
    """直播流抢码: 对识别到的二维码执行 scan + confirm

    用已登录账号的 stoken/mid 作为 Cookie 模拟手机扫码动作
    """
    auth_cookie = f"stoken={stoken}; mid={mid}"
    log_cb(f"      [scanQRLogin] 提交扫码 ticket={ticket[:20]}...")
    ok = client.simulate_app_action(EP_PASSPORT_SCAN_QR, ticket, auth_cookie)
    log_cb(f"      [scanQRLogin] 结果: {'成功' if ok else '失败'}")
    if not ok:
        return False
    time.sleep(1)
    log_cb("      [confirmQRLogin] 提交确认...")
    ok2 = client.simulate_app_action(EP_PASSPORT_CONFIRM_QR, ticket, auth_cookie)
    log_cb(f"      [confirmQRLogin] 结果: {'成功' if ok2 else '失败'}")
    return ok2
