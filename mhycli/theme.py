"""mhyscan 明亮主题 v2 — QSS 样式常量 + 配色令牌

设计: 清爽明亮风格 (白底 + 翡翠绿主色)
v2 视觉焕新:
  - 更大圆角 (卡片 14 / 按钮 9 / 输入 9), 细腻分层边框
  - 主按钮翡翠绿渐变, hover/pressed 递进
  - 输入聚焦: 主色边框 + 淡绿底色 (无布局抖动)
  - 卡片标题带主色强调条; 徽章/版本号胶囊化
  - 日志区淡底色 + 等宽字体; 8px 细滚动条
主色翡翠绿传达"GO/成功"语义, 与直播开播/抢码成功认知一致。
"""

# 色彩令牌 (明亮)
BG = "#F6F7F9"           # 窗口/全局背景 (淡灰)
SURFACE = "#FFFFFF"      # 卡片背景 (白)
SURFACE2 = "#F1F3F6"     # 按钮/嵌套区
SURFACE3 = "#FFFFFF"     # 弹出层/下拉/徽章
INPUT_BG = "#FFFFFF"     # 输入框/日志底色
BORDER = "#E5E8EE"       # 默认边框
BORDER2 = "#CDD3DD"      # hover 边框
TEXT1 = "#181D26"        # 主文字
TEXT2 = "#4B5563"        # 次要文字
TEXT3 = "#98A1B0"        # 弱化/占位/时间戳
ACCENT = "#10B981"       # 主色 (翡翠绿)
ACCENT_HOVER = "#0DA271"
ACCENT_ACTIVE = "#0A8B61"
ACCENT_ON = "#FFFFFF"    # 主按钮文字
ACCENT_SOFT = "#E7F7F1"  # 主色浅底 (选中/聚焦 tint)
SUCCESS = "#10B981"
WARNING = "#D97706"
DANGER = "#DC2626"
INFO = "#3B82F6"

# 日志分级颜色
LOG_COLORS = {
    "time": "#A6AEBD",
    "info": "#4B5563",
    "success": "#0A8B61",
    "error": "#DC2626",
    "progress": "#6B7280",
}

QSS = f"""
/* ============ 全局 ============ */
* {{ outline: none; }}
QWidget {{
    background-color: {BG};
    color: {TEXT1};
    font-family: "Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC", sans-serif;
    font-size: 13px;
}}
QWidget#central, QWidget#leftPanel {{ background: transparent; }}

/* ============ 头部 ============ */
QFrame#header {{
    background-color: #FFFFFF;
    border-bottom: 1px solid {BORDER};
}}
QLabel#logo {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {ACCENT}, stop:1 {INFO});
    color: #FFFFFF; border-radius: 10px;
    font-size: 15px; font-weight: 800;
}}
QLabel#appTitle {{ font-size: 16px; font-weight: 800; letter-spacing: 0.5px; background: transparent; }}
QLabel#headerMeta {{ color: {TEXT3}; font-size: 12px; background: transparent; }}
QLabel#appVersion {{
    color: {TEXT3}; font-size: 11px; font-weight: 600;
    background-color: {SURFACE2};
    border: 1px solid {BORDER};
    border-radius: 10px; padding: 2px 9px;
}}

/* ============ 徽章 ============ */
QFrame#badge {{
    background-color: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 15px; padding: 3px 11px;
}}
QLabel#badgeText {{ color: {TEXT1}; font-size: 12px; font-weight: 600; background: transparent; }}

/* ============ 卡片 ============ */
QFrame#card {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QLabel#cardTitle {{
    font-size: 13px; font-weight: 700; color: {TEXT1};
    border-left: 3px solid {ACCENT};
    padding-left: 8px; background: transparent;
}}
QLabel#cardSub {{ color: {TEXT3}; font-size: 12px; background: transparent; }}

/* ============ 按钮四态 ============ */
QPushButton {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 9px; padding: 7px 16px;
    color: {TEXT2}; font-weight: 600;
}}
QPushButton:hover {{ background-color: #F6F8FA; border-color: {BORDER2}; color: {TEXT1}; }}
QPushButton:pressed {{ background-color: #EBEEF2; }}
QPushButton:disabled {{ color: #B4BAC4; background-color: #F2F3F5; border-color: #EAECF0; }}
QPushButton:focus {{ border-color: {ACCENT}; }}

QPushButton[primary="true"] {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {ACCENT}, stop:1 {ACCENT_HOVER});
    border: 1px solid {ACCENT_ACTIVE}; color: {ACCENT_ON};
}}
QPushButton[primary="true"]:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {ACCENT_HOVER}, stop:1 {ACCENT_ACTIVE});
}}
QPushButton[primary="true"]:pressed {{ background-color: {ACCENT_ACTIVE}; }}
QPushButton[primary="true"]:disabled {{
    background-color: #C2EBDC; color: #FFFFFF; border-color: #C2EBDC;
}}

QPushButton[ghost="true"] {{
    background-color: transparent; border-color: transparent; color: {TEXT2};
    padding: 5px 10px;
}}
QPushButton[ghost="true"]:hover {{ background-color: {SURFACE2}; color: {TEXT1}; }}

QPushButton[danger="true"] {{
    background-color: transparent; border: 1px solid #F3CBCB; color: {DANGER};
}}
QPushButton[danger="true"]:hover {{ background-color: #FDEFEF; border-color: {DANGER}; }}
QPushButton[danger="true"]:pressed {{ background-color: #FBE3E3; }}
QPushButton[danger="true"]:disabled {{ color: #E0B4B4; border-color: #F5E2E2; }}

/* ============ 输入类 ============ */
QLineEdit, QSpinBox, QComboBox {{
    background-color: {INPUT_BG};
    border: 1px solid {BORDER}; border-radius: 9px;
    padding: 6px 12px; color: {TEXT1};
    selection-background-color: {ACCENT}; selection-color: #FFFFFF;
}}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{ border-color: {BORDER2}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {ACCENT}; background-color: #F7FDFB;
}}
QLineEdit[invalid="true"] {{
    border-color: {DANGER}; background-color: #FEF6F6;
}}
QLineEdit::placeholder {{ color: {TEXT3}; }}
QSpinBox::up-button, QSpinBox::down-button {{
    background: transparent; border: none; width: 18px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ border-radius: 4px; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{
    background-color: {SURFACE}; border: 1px solid {BORDER2};
    border-radius: 10px; padding: 5px;
    selection-background-color: {ACCENT_SOFT}; selection-color: {ACCENT_ACTIVE};
}}

/* ============ 账号列表 ============ */
QListWidget#accountList {{
    background-color: transparent; border: none;
}}
QListWidget#accountList::item {{
    padding: 9px 12px; border-radius: 9px; margin: 2px 0;
    color: {TEXT2};
}}
QListWidget#accountList::item:hover {{ background-color: {SURFACE2}; color: {TEXT1}; }}
QListWidget#accountList::item:selected {{
    background-color: {ACCENT_SOFT}; color: {ACCENT_ACTIVE}; font-weight: 600;
}}

/* ============ 日志 ============ */
QPlainTextEdit#logView {{
    background-color: #F8FAF9; border: 1px solid {BORDER};
    border-radius: 10px; padding: 6px;
    font-family: "JetBrains Mono", "Cascadia Mono", "Consolas", monospace;
    font-size: 12px; color: {TEXT2};
    selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT1};
}}

/* ============ 复选框 ============ */
QCheckBox {{ color: {TEXT3}; font-size: 12px; spacing: 5px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {BORDER2}; border-radius: 4px; background: {SURFACE};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{
    background-color: {ACCENT}; border-color: {ACCENT};
    image: none;
}}

/* ============ 扫描进度条 ============ */
QProgressBar#scanProgress {{ background: transparent; border: none; }}
QProgressBar#scanProgress::chunk {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {ACCENT}, stop:1 {INFO});
    border-radius: 1px;
}}

/* ============ 细滚动条 ============ */
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER2}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #AEB4C0; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER2}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* ============ 其他 ============ */
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {ACCENT}; border-radius: 1px; }}
QToolTip {{
    background-color: {SURFACE}; color: {TEXT1};
    border: 1px solid {BORDER2}; border-radius: 8px; padding: 6px 10px;
}}
QMessageBox, QDialog {{ background-color: {SURFACE}; }}
QFrame#footer {{
    background-color: #FFFFFF;
    border-top: 1px solid {BORDER};
}}
QLabel#footerText {{ color: {TEXT2}; font-size: 12px; background: transparent; }}
"""
