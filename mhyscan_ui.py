#!/usr/bin/env python3
"""mhyscan UI — 米哈游直播流抢码图形界面 (PySide6)

评估方案:
  - 技术: PySide6 (Qt for Python), 直接复用 mhycli 全部业务模块
  - 打包: PyInstaller --onedir (PyAV/opencv 体积大, onedir 启动更快)
  - Windows 分发: 复制 dist/mhyscan_ui/ + 首次运行生成 Config/

界面布局:
  ┌─────────────────────────────────────────┐
  │ [账号管理区]                             │
  │   米游社扫码登录  添加Cookie  刷新        │
  │   B站凭证: [已登录/未登录] [B站登录][退出] │
  │   ─ 账号列表 ─────────────────────────   │
  │ [直播间抢码设置区]                       │
  │   平台[▾] RID[____] 超时[180]           │
  │   [开始扫描] [停止]  状态               │
  │ [日志区] (实时滚动)                     │
  └─────────────────────────────────────────┘
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap, QTextCursor, QTextCharFormat, QTextBlockFormat
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QComboBox, QListWidget,
    QPlainTextEdit, QDialog, QGridLayout, QFrame, QSplitter,
    QFormLayout, QSpinBox, QProgressBar, QCheckBox, QListWidgetItem,
)

sys.path.insert(0, str(Path(__file__).parent))

from mhycli.api_client import MhyClient
from mhycli.config import AccountStore, CacheStore
from mhycli.cookie_import import CookieParseError, extract_account_from_cookie
from mhycli.game_record import GameRecordClient, format_roles
from mhycli.live_link import LivePlatform
from mhycli.qr_login import app_qr_login
from mhycli.status_dot import StatusDot, COLORS as DOT_COLORS
from mhycli.stream_grab import LiveStreamGrabber
from mhycli.theme import QSS, LOG_COLORS

APP_DIR = Path(__file__).resolve().parent


# =====================================================================
# 工作线程: 扫码登录
# =====================================================================
class LoginWorker(QThread):
    qr_ready = Signal(str)              # 二维码 URL (用于弹窗展示)
    finished_ok = Signal(str, str, str)  # uid, stoken, mid
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stopped = False

    def stop(self):
        """协作式停止: 设置标志, 轮询循环中检查"""
        self._stopped = True

    def run(self):
        class _Stopped(Exception):
            pass

        def on_status(status):
            pass

        def on_qr(url, ticket):
            self.qr_ready.emit(url)

        try:
            client = MhyClient()
            # is_stopped 每轮轮询前检查, 停止即时生效 (不依赖 on_status 触发时机)
            session = app_qr_login(client, on_status=on_status, on_qr=on_qr,
                                   timeout=300, is_stopped=lambda: self._stopped)
            if self._stopped:
                return  # 用户主动停止
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
    qr_ready = Signal(str)   # 二维码 URL (用于弹窗展示)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stopped = False

    def stop(self):
        """协作式停止: 设置标志, 轮询循环中检查"""
        self._stopped = True

    def run(self):
        try:
            from mhycli import bili_login
            import requests

            session = requests.Session()
            qrcode_url, auth_code = bili_login.get_qrcode(session)
            self.qr_ready.emit(qrcode_url)
            try:
                resp = bili_login.poll_login(session, auth_code,
                                             on_status=None, timeout=180,
                                             is_stopped=lambda: self._stopped)
            except StopIteration:
                return  # 用户主动停止
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
    metrics = Signal(float, int, int, int)  # elapsed, bytes, rss_kb, frames
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
        self._stopped = False

    def run(self):
        try:
            grabber = LiveStreamGrabber(self.client, self.stoken, self.mid,
                                        frame_skip=2)
            self.grabber = grabber
            if self._stopped:
                self.finished.emit(False, "停止")
                return
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
        self.metrics.emit(elapsed, bytes_read, rss_kb, frame_count)

    def stop(self):
        self._stopped = True
        if self.grabber:
            self.grabber.stop()


# =====================================================================
# 二维码对话框
# =====================================================================
class QrCodeDialog(QDialog):
    def __init__(self, url: str, label: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("扫码登录")
        # 关键: 必须非模态。setModal(True)+show() 在 Windows 上不显示 (模态需 exec())
        self.setModal(False)
        self.setObjectName("card")
        self.resize(360, 440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        lbl = QLabel(label, objectName="cardTitle")
        lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl)
        # 内存中生成二维码图片 (不依赖写文件, 打包后目录只读也可用)
        from mhycli.qrcode_display import _build_matrix

        mat = _build_matrix(url)
        size = 300
        img = QPixmap(size, size)
        img.fill(Qt.white)
        painter = QPainter(img)
        painter.fillRect(img.rect(), Qt.white)
        painter.setBrush(Qt.black)
        painter.setPen(Qt.NoPen)
        n = len(mat)
        cell = size / n
        for y, row in enumerate(mat):
            for x, v in enumerate(row):
                if v:
                    painter.drawRect(int(x * cell), int(y * cell),
                                     int(cell) + 1, int(cell) + 1)
        painter.end()
        ql = QLabel()
        ql.setPixmap(img)
        ql.setAlignment(Qt.AlignCenter)
        layout.addWidget(ql)


# =====================================================================
# 主窗口
# =====================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        import mhycli

        self.setWindowTitle(f"mhyscan v{mhycli.__version__} — 米哈游直播流抢码")
        self.resize(980, 660)
        self.setMinimumSize(860, 600)
        self.store = AccountStore(None)
        self.login_worker = None
        self.bili_worker = None
        self.scan_worker = None
        self._build_ui()
        self.refresh_accounts()

    # ---- UI 构建 ----
    def _build_ui(self):
        central = QWidget(objectName="central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ===== 头部 =====
        header = QFrame(objectName="header")
        header.setFixedHeight(56)
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 8, 16, 8)
        h.setSpacing(10)

        logo = QLabel("M", objectName="logo")
        logo.setFixedSize(34, 34)
        logo.setAlignment(Qt.AlignCenter)
        h.addWidget(logo)

        title = QLabel("mhyscan · 米哈游直播流抢码", objectName="appTitle")
        h.addWidget(title)
        h.addStretch()

        # B站徽章
        self.badge = QFrame(objectName="badge")
        bh = QHBoxLayout(self.badge)
        bh.setContentsMargins(8, 3, 8, 3)
        bh.setSpacing(6)
        self.bili_dot = StatusDot("idle")
        self.bili_badge_text = QLabel("检测中", objectName="badgeText")
        bh.addWidget(self.bili_dot)
        bh.addWidget(self.bili_badge_text)
        h.addWidget(self.badge)

        self.btn_bili_login = QPushButton("登录", objectName="biliLogin")
        self.btn_bili_login.setProperty("ghost", True)
        self.btn_bili_logout = QPushButton("退出", objectName="biliLogout")
        self.btn_bili_logout.setProperty("ghost", True)
        h.addWidget(self.btn_bili_login)
        h.addWidget(self.btn_bili_logout)

        self.header_meta = QLabel("账号 0", objectName="headerMeta")
        h.addWidget(self.header_meta)

        version = QLabel(f"v{__import__('mhycli').__version__}", objectName="appVersion")
        h.addWidget(version)
        root.addWidget(header)

        # ===== 主体: 左卡片 + 右日志 =====
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        root.addWidget(splitter, 1)

        left = QWidget(objectName="leftPanel")
        left.setMinimumWidth(300)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 6, 12)
        ll.setSpacing(12)

        # -- 账号管理卡 --
        acc_card = QFrame(objectName="card")
        al = QVBoxLayout(acc_card)
        al.setContentsMargins(14, 14, 14, 14)
        al.setSpacing(10)

        acc_title = QLabel("账号管理", objectName="cardTitle")
        al.addWidget(acc_title)
        acc_sub = QLabel("管理多个账号", objectName="cardSub")
        al.addWidget(acc_sub)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_login = QPushButton("扫码登录")
        self.btn_login.setProperty("primary", True)
        self.btn_add = QPushButton("添加Cookie")
        btn_row.addWidget(self.btn_login)
        btn_row.addWidget(self.btn_add)
        btn_row.addStretch()
        al.addLayout(btn_row)

        self.account_list = QListWidget(objectName="accountList")
        self.account_list.setSizePolicy(self.account_list.sizePolicy().horizontalPolicy(),
                                        self.account_list.sizePolicy().verticalPolicy())
        al.addWidget(self.account_list, 1)

        acc_hint = QLabel("将使用选中账号进行抢码", objectName="cardSub")
        al.addWidget(acc_hint)
        ll.addWidget(acc_card, 1)

        # -- 抢码设置卡 --
        scan_card = QFrame(objectName="card")
        sl = QVBoxLayout(scan_card)
        sl.setContentsMargins(14, 14, 14, 14)
        sl.setSpacing(12)

        scan_title = QLabel("抢码设置", objectName="cardTitle")
        sl.addWidget(scan_title)

        form = QFormLayout()
        form.setSpacing(8)
        self.platform_combo = QComboBox()
        self.platform_combo.addItem("B站", LivePlatform.BiliBili)
        self.platform_combo.addItem("抖音", LivePlatform.Douyin)
        form.addRow("平台", self.platform_combo)
        self.rid_edit = QLineEdit()
        self.rid_edit.setPlaceholderText("直播间房间号 (纯数字)")
        form.addRow("房间RID", self.rid_edit)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(10, 3600)
        self.timeout_spin.setValue(180)
        self.timeout_spin.setSuffix(" s")
        form.addRow("超时", self.timeout_spin)
        sl.addLayout(form)

        self.btn_scan = QPushButton("开始扫描")
        self.btn_scan.setProperty("primary", True)
        self.btn_scan.setMinimumHeight(40)
        sl.addWidget(self.btn_scan)

        # 扫描进度条 (3px 无限循环, 默认隐藏)
        self.scan_progress = QProgressBar(objectName="scanProgress")
        self.scan_progress.setFixedHeight(3)
        self.scan_progress.setTextVisible(False)
        self.scan_progress.hide()
        sl.addWidget(self.scan_progress)

        # 扫描状态 (状态灯 + 文字 + 停止按钮)
        scan_status_row = QHBoxLayout()
        scan_status_row.setSpacing(6)
        self.scan_dot = StatusDot("idle")
        self.scan_status_label = QLabel("就绪")
        self.scan_status_label.setStyleSheet(f"color: {DOT_COLORS['idle']};")
        scan_status_row.addWidget(self.scan_dot)
        scan_status_row.addWidget(self.scan_status_label)
        scan_status_row.addStretch()
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setProperty("danger", True)
        self.btn_stop.setEnabled(False)
        scan_status_row.addWidget(self.btn_stop)
        sl.addLayout(scan_status_row)

        ll.addWidget(scan_card)
        splitter.addWidget(left)

        # -- 日志卡 --
        log_card = QFrame(objectName="card")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(14, 14, 14, 14)
        log_layout.setSpacing(8)

        log_top = QHBoxLayout()
        log_title = QLabel("运行日志", objectName="cardTitle")
        log_top.addWidget(log_title)
        log_top.addStretch()
        self.btn_clear = QPushButton("清空")
        self.btn_clear.setProperty("ghost", True)
        self.auto_scroll = QCheckBox("跟随滚动")
        self.auto_scroll.setChecked(True)
        self.auto_scroll.setStyleSheet(f"color: {DOT_COLORS['idle']};")
        log_top.addWidget(self.btn_clear)
        log_top.addWidget(self.auto_scroll)
        log_layout.addLayout(log_top)

        self.log_view = QPlainTextEdit(objectName="logView")
        self.log_view.setReadOnly(True)
        log_layout.addWidget(self.log_view, 1)
        splitter.addWidget(log_card)

        splitter.setSizes([340, 640])

        # ===== 底部状态栏 =====
        footer = QFrame(objectName="footer")
        footer.setFixedHeight(28)
        fh = QHBoxLayout(footer)
        fh.setContentsMargins(14, 0, 14, 0)
        fh.setSpacing(8)
        self.footer_dot = StatusDot("idle")
        self.footer_text = QLabel("就绪", objectName="footerText")
        fh.addWidget(self.footer_dot)
        fh.addWidget(self.footer_text)
        fh.addStretch()
        self.footer_metrics = QLabel("流量 0.0 MB · 帧 0 · 内存 0 MB · 已等待 0s", objectName="footerText")
        fh.addWidget(self.footer_metrics)
        root.addWidget(footer)

        # ---- 信号连接 ----
        self.btn_login.clicked.connect(self.on_login)
        self.btn_bili_login.clicked.connect(self.on_bili_login)
        self.btn_bili_logout.clicked.connect(self.on_bili_logout)
        self.btn_add.clicked.connect(self.on_add_cookie)
        self.btn_scan.clicked.connect(self.on_scan)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_clear.clicked.connect(self.log_view.clear)
        self.account_list.currentRowChanged.connect(lambda _: self.refresh_footer_account())

        # 初始刷新
        self.refresh_accounts()
        self.refresh_bili_status()

    # ---- 底部账号元信息 ----
    def refresh_footer_account(self):
        accs = self.store.list_accounts()
        self.header_meta.setText(f"账号 {len(accs)}")

    def _set_invalid(self, widget, invalid: bool):
        widget.setProperty("invalid", invalid)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    # ---- 日志 (分级上色) ----
    def log(self, msg: str = ""):
        # 上海时区; 打包环境缺 tzdata 时回退系统本地时间, 避免崩溃
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            ts = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H:%M:%S")
        except Exception:
            from datetime import datetime

            ts = datetime.now().strftime("%H:%M:%S")

        # 按前缀推断级别 (兼容现有所有 log() 调用)
        if msg.startswith("✔"):
            lvl = "success"
        elif msg.startswith("✘") or msg.startswith("⚠"):
            lvl = "error"
        elif msg.strip().startswith("[已等待") or msg.strip().startswith("[1/5]"):
            lvl = "progress"
        else:
            lvl = "info"

        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        # 时间戳 (弱色)
        tf = QTextCharFormat()
        tf.setForeground(QColor(LOG_COLORS["time"]))
        cursor.insertText(f"[{ts}] ", tf)
        # 消息 (按级别)
        mf = QTextCharFormat()
        mf.setForeground(QColor(LOG_COLORS[lvl]))
        cursor.insertText(msg, mf)
        # 行高 130%
        bf = QTextBlockFormat()
        bf.setLineHeight(130.0, QTextBlockFormat.ProportionalHeight.value)
        cursor.insertBlock(bf)
        if self.auto_scroll.isChecked():
            sb = self.log_view.verticalScrollBar()
            sb.setValue(sb.maximum())

    # ---- 账号 ----
    def refresh_accounts(self):
        self.account_list.clear()
        accs = self.store.list_accounts()
        for i, a in enumerate(accs):
            item = QListWidgetItem(
                f"{'◈' if i == self.store.data.get('last_account', 0) else '  '} "
                f"{a.get('name') or '?'}  uid={a.get('uid')}")
            item.setToolTip(f"stoken={str(a.get('access_key'))[:12]}...  type={a.get('type')}")
            self.account_list.addItem(item)
        self.refresh_footer_account()

    # ---- B站登录状态 (头部徽章) ----
    def refresh_bili_status(self):
        """检测 B站 cookie 状态并更新头部徽章 (强制刷新进程缓存)"""
        from mhycli.live_link import get_bili_cookie

        cookie = get_bili_cookie(force_refresh=True)
        if cookie:
            self.bili_dot.set_status("ok")
            self.bili_badge_text.setText("已登录")
            self.bili_badge_text.setStyleSheet(f"color: {DOT_COLORS['ok']};")
            self.btn_bili_login.hide()
            self.btn_bili_logout.show()
            self.log("B站凭证: 已登录")
        else:
            self.bili_dot.set_status("warn")
            self.bili_badge_text.setText("未登录")
            self.bili_badge_text.setStyleSheet(f"color: {DOT_COLORS['warn']};")
            self.btn_bili_login.show()
            self.btn_bili_logout.hide()
            self.log("B站凭证: 未登录 (拉流仅 720P)")

    def on_bili_logout(self):
        """退出 B站: 确认后删除 cookie 文件"""
        from PySide6.QtWidgets import QMessageBox

        ret = QMessageBox.question(self, "退出B站", "确定退出 B站登录并清除凭证？")
        if ret != QMessageBox.Yes:
            return
        from mhycli.live_link import _BILI_COOKIE_FILE

        try:
            if _BILI_COOKIE_FILE.exists():
                _BILI_COOKIE_FILE.unlink()
            self.log("✔ 已退出 B站登录, 凭证已清除")
        except Exception as e:
            self.log(f"✘ 退出 B站失败: {e}")
        self.refresh_bili_status()

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
        self.login_worker.qr_ready.connect(self._show_qr_dialog)
        self.login_worker.finished_ok.connect(self._on_login_ok)
        self.login_worker.failed.connect(self._on_worker_failed)
        self.login_worker.start()

    def _show_qr_dialog(self, url, label="请用米游社APP扫描二维码登录"):
        self.log(f"正在显示二维码窗口... url={url[:60]}")
        self._close_qr_dialogs()
        # 创建并显示新对话框 (非模态, 不阻塞扫码轮询)
        dialog = QrCodeDialog(url, label, self)
        dialog.show()
        dialog.raise_()   # 确保置顶
        dialog.activateWindow()
        self._qr_dialogs = [dialog]
        self.log(f"二维码窗口已显示")

    def _close_qr_dialogs(self):
        """关闭所有二维码对话框"""
        for d in getattr(self, "_qr_dialogs", []):
            if d.isVisible():
                d.close()
        self._qr_dialogs = []

    def _on_login_ok(self, uid, stoken, mid):
        self._close_qr_dialogs()
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
        self.bili_worker.qr_ready.connect(self._show_qr_dialog_bili)
        self.bili_worker.finished_ok.connect(self._on_bili_ok)
        self.bili_worker.failed.connect(self._on_worker_failed)
        self.bili_worker.start()

    def _show_qr_dialog_bili(self, url):
        self._show_qr_dialog(url, "请用B站APP扫描二维码登录")

    def _on_bili_ok(self, summary):
        self._close_qr_dialogs()
        self.log(f"✔ B站登录成功, cookie: {summary}")
        self.log(f"  已保存到 Config/bili_cookie.json, 后续拉流使用 (1080P + 抗限流)")
        self.refresh_bili_status()

    # ---- 抢码 ----
    def on_scan(self):
        # 防止重复启动 (按钮已禁用, 但双击/快速连点兜底)
        if self.scan_worker and self.scan_worker.isRunning():
            self.log("✘ 扫描已在运行中, 请先停止")
            return
        acc = self._get_selected_account()
        if acc is None:
            self.log("✘ 没有可用账号, 先扫码登录或添加 Cookie")
            self._set_scan_status("error", "没有可用账号")
            return
        stoken = acc.get("access_key", "")
        mid = acc.get("mid", "")
        if not stoken or not mid:
            self.log(f"✘ 账号 {acc.get('uid')} 缺少 stoken/mid")
            self._set_scan_status("error", "账号缺少凭证")
            return

        rid = self.rid_edit.text().strip()
        if not rid.isdigit():
            self.log("✘ RID 必须是纯数字")
            self._set_invalid(self.rid_edit, True)
            self._set_scan_status("error", "请输入纯数字房间号")
            return
        self._set_invalid(self.rid_edit, False)

        platform = self.platform_combo.currentData()
        timeout = float(self.timeout_spin.value())
        self.log(f"使用账号 {acc.get('name')} (uid={acc.get('uid')}) 监视直播间 RID={rid}")
        self.log(f"平台: {'B站' if platform == LivePlatform.BiliBili else '抖音'}  超时: {int(timeout)}s")

        client = MhyClient()
        self.scan_worker = ScanWorker(client, stoken, mid, platform, rid, timeout, self)
        self.scan_worker.log.connect(self.log)
        self.scan_worker.metrics.connect(self._on_scan_metrics)
        self.scan_worker.finished.connect(self._on_scan_done)
        self.scan_worker.start()
        self.btn_scan.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_scan.setText("扫描中...")
        self.scan_progress.setRange(0, 0)  # 无限循环动画
        self.scan_progress.show()
        self._set_scan_status("busy", "扫描中", pulse=True)
        # 角色信息通过独立 QThread 获取 (信号回传, 线程安全)
        self.roles_worker = RolesWorker(acc, self)
        self.roles_worker.result.connect(self._on_roles_result)
        self.roles_worker.start()

    def _set_scan_status(self, status: str, text: str, pulse: bool = False):
        """设置扫描状态灯 + 文字 + 底部状态"""
        self.scan_dot.set_status(status, pulse=pulse)
        self.scan_status_label.setText(text)
        self.scan_status_label.setStyleSheet(f"color: {DOT_COLORS[status]};")
        self.footer_dot.set_status(status)
        self.footer_text.setText(text)

    def _on_scan_metrics(self, elapsed, bytes_read, rss_kb, frame_count):
        mb = bytes_read / 1024 / 1024
        self.footer_metrics.setText(
            f"流量 {mb:.2f} MB · 帧 {frame_count} · 内存 {rss_kb/1024:.1f} MB · 已等待 {elapsed:.0f}s")

    def _on_roles_result(self, text):
        if text:
            self.log(f"  [角色] {text}")

    def on_stop(self):
        if self.scan_worker and self.scan_worker.isRunning():
            self.scan_worker.stop()
            self.log("正在停止...")
            self._set_scan_status("warn", "正在停止...")
        else:
            self.log("当前没有正在运行的扫描")

    def _on_scan_done(self, ok, ticket):
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_scan.setText("开始扫描")
        self.scan_progress.hide()
        if ok:
            self._set_scan_status("ok", f"✔ 抢码成功 ticket={ticket}")
            self.log(f"✔ 抢码成功! ticket={ticket}")
        elif ticket == "停止":
            self._set_scan_status("idle", "已停止")
            self.log("已停止")
        else:
            self._set_scan_status("error", "✘ 抢码失败")
            self.log(f"✘ 抢码失败: {ticket}")

    # ---- 通用 ----
    def _on_worker_failed(self, msg):
        self._close_qr_dialogs()
        self.log(f"✘ {msg}")

    def closeEvent(self, event):
        # 协作式停止所有工作线程, 再等待; 超时兜底 terminate
        for w in (self.scan_worker, self.login_worker, self.bili_worker, getattr(self, "roles_worker", None)):
            if w and w.isRunning():
                if hasattr(w, "stop"):
                    w.stop()
                else:
                    w.terminate()
                w.wait(3000)
        self._close_qr_dialogs()
        event.accept()


def main():
    # 磁盘日志: noconsole 打包下 print 不可见, 所有错误写日志文件便于诊断
    import logging
    import traceback

    log_file = Path(__file__).resolve().parent.parent / "Config" / "mhyscan.log"
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            filename=str(log_file),
            filemode="a",
            format="%(asctime)s [%(levelname)s] %(message)s",
        )
    except Exception:
        pass
    logging.info("=== mhyscan 启动 ===")

    # 全局异常钩子: 未捕获异常写入日志 (而非静默消失)
    def excepthook(exc_type, exc_value, exc_tb):
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.error("未捕获异常:\n%s", detail)
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(None, "错误", f"程序发生异常:\n{exc_value}\n\n详见 {log_file}")
        except Exception:
            pass

    sys.excepthook = excepthook

    app = QApplication(sys.argv)
    # 深色主题: Fusion 样式基座 (跨平台渲染一致) + 全局调色板 + QSS
    from PySide6.QtGui import QPalette, QColor
    from mhycli.theme import BG, SURFACE, SURFACE2, SURFACE3, INPUT_BG, TEXT1, TEXT2, TEXT3, ACCENT, ACCENT_ON

    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(SURFACE))
    pal.setColor(QPalette.WindowText, QColor(TEXT1))
    pal.setColor(QPalette.Base, QColor(INPUT_BG))
    pal.setColor(QPalette.AlternateBase, QColor(SURFACE3))
    pal.setColor(QPalette.Text, QColor(TEXT1))
    pal.setColor(QPalette.Button, QColor(SURFACE2))
    pal.setColor(QPalette.ButtonText, QColor(TEXT2))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor(ACCENT_ON))
    pal.setColor(QPalette.PlaceholderText, QColor(TEXT3))
    pal.setColor(QPalette.ToolTipBase, QColor(SURFACE3))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT1))
    app.setPalette(pal)
    app.setStyleSheet(QSS)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
