#!/usr/bin/env python3
"""mhyscan UI — 米哈游直播流抢码图形界面 (PySide6)

评估方案:
  - 技术: PySide6 (Qt for Python), 直接复用 mhycli 全部业务模块
  - 打包: PyInstaller --onedir (PyAV/opencv 体积大, onedir 启动更快)
  - Windows 分发: 复制 dist/mhyscan_ui/ + 首次运行生成 Config/

界面布局:
  ┌─────────────────────────────────────────┐
  │ [账号管理区]                             │
  │   登录  B站登录  添加Cookie  刷新  列表    │
  │ [直播间抢码区]                           │
  │   平台[▾] RID[____] [开始扫描] [停止]     │
  │ [日志区] (实时滚动)                      │
  └─────────────────────────────────────────┘
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QComboBox, QListWidget,
    QPlainTextEdit, QDialog, QGridLayout, QFrame,
)

sys.path.insert(0, str(Path(__file__).parent))

from mhycli.api_client import MhyClient
from mhycli.config import AccountStore, CacheStore
from mhycli.cookie_import import CookieParseError, extract_account_from_cookie
from mhycli.game_record import GameRecordClient, format_roles
from mhycli.live_link import LivePlatform
from mhycli.qr_login import app_qr_login
from mhycli.stream_grab import LiveStreamGrabber

APP_DIR = Path(__file__).resolve().parent


# =====================================================================
# 工作线程: 扫码登录
# =====================================================================
class LoginWorker(QThread):
    finished_ok = Signal(str, str, str)   # uid, stoken, mid
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session = None

    def run(self):
        try:
            client = MhyClient()

            def on_status(status):
                pass

            session = app_qr_login(client, on_status=on_status, timeout=300)
            if not session.stoken:
                self.failed.emit("扫码登录失败或超时")
                return
            self.finished_ok.emit(session.uid, session.stoken, session.mid)
        except Exception as e:
            self.failed.emit(f"扫码登录异常: {e}")


# =====================================================================
# 工作线程: B站扫码登录 (保存拉流凭证)
# =====================================================================
class BiliLoginWorker(QThread):
    finished_ok = Signal(str)
    failed = Signal(str)

    def run(self):
        try:
            from mhycli import bili_login
            import requests

            session = requests.Session()
            qrcode_url, auth_code = bili_login.get_qrcode(session)
            resp = bili_login.poll_login(session, auth_code, timeout=180)
            cookies = bili_login.extract_cookies(resp)
            if not cookies:
                self.failed.emit("登录成功但未获取到 cookie")
                return
            bili_login.save_cookies_to_file(cookies)
            self.finished_ok.emit(bili_login.cookie_summary(cookies))
        except TimeoutError:
            self.failed.emit("扫码登录超时")
        except Exception as e:
            self.failed.emit(f"B站登录异常: {e}")


# =====================================================================
# 工作线程: 获取游戏角色信息
# =====================================================================
class RolesWorker(QThread):
    result = Signal(str)  # 角色格式化文本 (空串表示失败/无角色)

    def __init__(self, acc: dict, parent=None):
        super().__init__(parent)
        self.acc = acc

    def run(self):
        try:
            client = MhyClient()
            stoken = self.acc.get("access_key", "")
            uid = self.acc.get("uid", "")
            mid = self.acc.get("mid", "")
            ct = client.get_cookie_account_info_by_stoken(stoken, mid, uid)
            lt = client.get_ltoken_by_stoken(stoken, mid, uid)
            cookie = f"ltoken={lt}; ltuid={uid}; cookie_token={ct}; account_id={uid}"
            gr = GameRecordClient(cookie, cache=CacheStore())
            roles = gr.get_roles()
            self.result.emit(format_roles(roles))
        except Exception:
            self.result.emit("")


# =====================================================================
# 工作线程: 直播流抢码
# =====================================================================
class ScanWorker(QThread):
    log = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, client, stoken, mid, platform, rid, timeout, parent=None):
        super().__init__(parent)
        self.client = client
        self.stoken = stoken
        self.mid = mid
        self.platform = platform
        self.rid = rid
        self.timeout = timeout
        self.grabber = None

    def run(self):
        try:
            grabber = LiveStreamGrabber(self.client, self.stoken, self.mid,
                                        frame_skip=2)
            self.grabber = grabber
            ok, ticket = grabber.grab_once(
                self.platform, self.rid, timeout=self.timeout,
                progress_cb=self._progress, log_cb=self.log.emit)
            self.finished.emit(ok, ticket)
        except Exception as e:
            self.finished.emit(False, str(e))

    def _progress(self, elapsed, bytes_read, rss_kb, frame_count):
        mb = bytes_read / 1024 / 1024
        self.log.emit(f"  [已等待 {elapsed:6.1f}s] 流量 {mb:6.2f} MB | "
                      f"帧 {frame_count:5d} | 内存 {rss_kb/1024:.1f} MB")

    def stop(self):
        if self.grabber:
            self.grabber.stop()


# =====================================================================
# 二维码对话框
# =====================================================================
class QrCodeDialog(QDialog):
    def __init__(self, url: str, label: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("扫码登录")
        self.setModal(True)
        layout = QVBoxLayout(self)
        lbl = QLabel(label)
        lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl)
        # 用终端字符画二维码兜底 + 保存 PNG
        from mhycli.qrcode_display import save_qr_png
        from io import BytesIO
        import qrcode as qrcode_lib

        png_path = APP_DIR / "qr_login.png"
        try:
            save_qr_png(url, str(png_path))
            pixmap = QPixmap(str(png_path))
            img = QLabel()
            img.setPixmap(pixmap.scaled(280, 280, Qt.KeepAspectRatio,
                                        Qt.SmoothTransformation))
            img.setAlignment(Qt.AlignCenter)
            layout.addWidget(img)
        except Exception:
            text = QPlainTextEdit()
            text.setReadOnly(True)
            text.setFixedHeight(300)
            layout.addWidget(text)


# =====================================================================
# 主窗口
# =====================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("mhyscan — 米哈游直播流抢码")
        self.resize(760, 640)
        self.store = AccountStore(None)
        self.login_worker = None
        self.bili_worker = None
        self.scan_worker = None
        self._build_ui()
        self.refresh_accounts()

    # ---- UI 构建 ----
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # ===== 账号区 =====
        acc_frame = QFrame()
        acc_frame.setFrameShape(QFrame.StyledPanel)
        acc_layout = QVBoxLayout(acc_frame)
        root.addWidget(acc_frame)

        acc_title = QLabel("账号管理")
        acc_title.setStyleSheet("font-weight: bold; font-size: 14px;")
        acc_layout.addWidget(acc_title)

        btn_row = QHBoxLayout()
        self.btn_login = QPushButton("扫码登录")
        self.btn_bili = QPushButton("B站扫码登录")
        self.btn_add = QPushButton("添加Cookie")
        self.btn_refresh = QPushButton("刷新")
        for b in (self.btn_login, self.btn_bili, self.btn_add, self.btn_refresh):
            btn_row.addWidget(b)
        btn_row.addStretch()
        acc_layout.addLayout(btn_row)

        self.account_list = QListWidget()
        self.account_list.setFixedHeight(120)
        acc_layout.addWidget(self.account_list)

        # ===== 直播间区 =====
        scan_frame = QFrame()
        scan_frame.setFrameShape(QFrame.StyledPanel)
        scan_layout = QGridLayout(scan_frame)
        root.addWidget(scan_frame)

        scan_title = QLabel("直播间抢码")
        scan_title.setStyleSheet("font-weight: bold; font-size: 14px;")
        scan_layout.addWidget(scan_title, 0, 0, 1, 4)

        scan_layout.addWidget(QLabel("平台:"), 1, 0)
        self.platform_combo = QComboBox()
        self.platform_combo.addItem("B站", LivePlatform.BiliBili)
        self.platform_combo.addItem("抖音", LivePlatform.Douyin)
        scan_layout.addWidget(self.platform_combo, 1, 1)

        scan_layout.addWidget(QLabel("RID:"), 1, 2)
        self.rid_edit = QLineEdit()
        self.rid_edit.setPlaceholderText("直播间房间号 (纯数字)")
        scan_layout.addWidget(self.rid_edit, 1, 3)

        self.btn_scan = QPushButton("开始扫描")
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setEnabled(False)
        scan_layout.addWidget(self.btn_scan, 2, 0)
        scan_layout.addWidget(self.btn_stop, 2, 1)
        scan_layout.setColumnStretch(2, 1)

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #666;")
        scan_layout.addWidget(self.status_label, 2, 3)

        # ===== 日志区 =====
        log_frame = QFrame()
        log_frame.setFrameShape(QFrame.StyledPanel)
        log_layout = QVBoxLayout(log_frame)
        root.addWidget(log_frame)

        log_title = QLabel("日志")
        log_title.setStyleSheet("font-weight: bold; font-size: 14px;")
        log_layout.addWidget(log_title)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 10))
        log_layout.addWidget(self.log_view)

        # ---- 信号连接 ----
        self.btn_login.clicked.connect(self.on_login)
        self.btn_bili.clicked.connect(self.on_bili_login)
        self.btn_add.clicked.connect(self.on_add_cookie)
        self.btn_refresh.clicked.connect(self.refresh_accounts)
        self.btn_scan.clicked.connect(self.on_scan)
        self.btn_stop.clicked.connect(self.on_stop)

    # ---- 日志 ----
    def log(self, msg: str = ""):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        ts = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y年%m月%d日 %H:%M:%S")
        self.log_view.appendPlainText(f"[{ts}] {msg}")
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum())

    # ---- 账号 ----
    def refresh_accounts(self):
        self.account_list.clear()
        accs = self.store.list_accounts()
        for i, a in enumerate(accs):
            self.account_list.addItem(
                f"[{i}] {a.get('name') or '?'}  uid={a.get('uid')}  "
                f"stoken={str(a.get('access_key'))[:8]}...")

    def _get_selected_account(self):
        accs = self.store.list_accounts()
        row = self.account_list.currentRow()
        if 0 <= row < len(accs):
            return accs[row]
        return self.store.get_last_account()

    def on_login(self):
        if self.login_worker and self.login_worker.isRunning():
            return
        self.log("正在创建 App 登录二维码...")
        self.login_worker = LoginWorker(self)
        self.login_worker.finished_ok.connect(self._on_login_ok)
        self.login_worker.failed.connect(self._on_worker_failed)
        self.login_worker.start()

    def _on_login_ok(self, uid, stoken, mid):
        ok = self.store.add_account(f"账号{uid}", stoken, uid, mid, "官服")
        if ok:
            self.log(f"✔ 登录成功并保存账号 uid={uid}")
        else:
            self.log(f"账号 uid={uid} 已存在")
        self.refresh_accounts()

    def on_add_cookie(self):
        from PySide6.QtWidgets import QInputDialog

        cookie, ok = QInputDialog.getText(self, "添加Cookie",
                                          "粘贴含 SToken 的完整 Cookie:")
        if not ok or not cookie.strip():
            return
        try:
            acc = extract_account_from_cookie(cookie)
        except CookieParseError as e:
            self.log(f"✘ Cookie 解析失败: {e}")
            return
        saved = self.store.add_account(f"账号{acc['uid']}",
                                       acc["stoken"], acc["uid"], acc["mid"], "官服")
        self.log(f"✔ 已添加账号 uid={acc['uid']}" if saved else f"账号 {acc['uid']} 已存在")
        self.refresh_accounts()

    # ---- B站登录 ----
    def on_bili_login(self):
        if self.bili_worker and self.bili_worker.isRunning():
            return
        self.log("正在获取 B站登录二维码 (TV端接口)...")
        self.bili_worker = BiliLoginWorker(self)
        self.bili_worker.finished_ok.connect(self._on_bili_ok)
        self.bili_worker.failed.connect(self._on_worker_failed)
        self.bili_worker.start()

    def _on_bili_ok(self, summary):
        self.log(f"✔ B站登录成功, cookie: {summary}")
        self.log(f"  已保存到 Config/bili_cookie.json, 后续拉流使用 (1080P + 抗限流)")

    # ---- 抢码 ----
    def on_scan(self):
        acc = self._get_selected_account()
        if acc is None:
            self.log("✘ 没有可用账号, 先扫码登录或添加 Cookie")
            return
        stoken = acc.get("access_key", "")
        mid = acc.get("mid", "")
        if not stoken or not mid:
            self.log(f"✘ 账号 {acc.get('uid')} 缺少 stoken/mid")
            return

        rid = self.rid_edit.text().strip()
        if not rid.isdigit():
            self.log("✘ RID 必须是纯数字")
            return

        platform = self.platform_combo.currentData()
        self.log(f"使用账号 {acc.get('name')} (uid={acc.get('uid')}) 监视直播间 RID={rid}")
        self.log(f"平台: {'B站' if platform == LivePlatform.BiliBili else '抖音'}")

        client = MhyClient()
        self.scan_worker = ScanWorker(client, stoken, mid, platform, rid, 180.0, self)
        self.scan_worker.log.connect(self.log)
        self.scan_worker.finished.connect(self._on_scan_done)
        self.scan_worker.start()
        self.btn_scan.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_label.setText("扫描中...")
        # 角色信息通过独立 QThread 获取 (信号回传, 线程安全)
        self.roles_worker = RolesWorker(acc, self)
        self.roles_worker.result.connect(self._on_roles_result)
        self.roles_worker.start()

    def _on_roles_result(self, text):
        if text:
            self.log(f"  [角色] {text}")

    def on_stop(self):
        if self.scan_worker and self.scan_worker.isRunning():
            self.scan_worker.stop()
            self.log("正在停止...")

    def _on_scan_done(self, ok, ticket):
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if ok:
            self.status_label.setText(f"✔ 抢码成功 ticket={ticket}")
            self.log(f"✔ 抢码成功! ticket={ticket}")
        else:
            self.status_label.setText("✘ 抢码失败")
            self.log(f"✘ 抢码失败: {ticket}")

    # ---- 通用 ----
    def _on_worker_failed(self, msg):
        self.log(f"✘ {msg}")

    def closeEvent(self, event):
        if self.scan_worker and self.scan_worker.isRunning():
            self.scan_worker.stop()
            self.scan_worker.wait(3000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
