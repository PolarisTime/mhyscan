"""mhyscan 深色主题 — QSS 样式常量 + 配色令牌

设计: 东京夜灵感 (冷灰蓝基底 + 翡翠绿主色)
主色翡翠绿传达"GO/成功"语义, 与直播开播/抢码成功认知一致。
"""

# 色彩令牌
BG = "#15171C"           # 窗口/全局背景
SURFACE = "#1B1E24"      # 卡片背景
SURFACE2 = "#21252D"     # 按钮/嵌套区
SURFACE3 = "#1F232B"     # 弹出层/下拉/徽章
INPUT_BG = "#12141A"     # 输入框/日志底色
BORDER = "#2B3038"       # 默认边框
BORDER2 = "#3A4050"      # hover 边框
TEXT1 = "#E8EAF0"        # 主文字
TEXT2 = "#A3A8B5"        # 次要文字
TEXT3 = "#6A7080"        # 弱化/占位/时间戳
ACCENT = "#34D399"       # 主色 (翡翠绿)
ACCENT_HOVER = "#2BC290"
ACCENT_ACTIVE = "#22A67C"
ACCENT_ON = "#0A2E23"    # 主按钮文字
SUCCESS = "#34D399"
WARNING = "#FBBF24"
DANGER = "#F87171"
INFO = "#7CB3FF"

# 日志分级颜色
LOG_COLORS = {
    "time": "#575D6E",
    "info": "#A3A8B5",
    "success": "#34D399",
    "error": "#F87171",
    "progress": "#8B92A3",
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
QFrame#header {{ background-color: #1A1D24; border-bottom: 1px solid {BORDER}; }}
QLabel#logo {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {ACCENT}, stop:1 {INFO});
    color: {ACCENT_ON}; border-radius: 8px;
    font-size: 14px; font-weight: 800;
}}
QLabel#appTitle {{ font-size: 15px; font-weight: 700; }}
QLabel#appVersion, QLabel#headerMeta {{ color: {TEXT3}; font-size: 12px; }}

/* ============ 徽章 ============ */
QFrame#badge {{
    background-color: {SURFACE3}; border: 1px solid {BORDER};
    border-radius: 14px; padding: 3px 10px;
}}
QLabel#badgeText {{ color: {TEXT1}; font-size: 12px; font-weight: 600; }}

/* ============ 卡片 ============ */
QFrame#card {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QLabel#cardTitle {{ font-size: 13px; font-weight: 700; color: {TEXT1}; }}
QLabel#cardSub {{ color: {TEXT3}; font-size: 12px; }}

/* ============ 按钮四态 ============ */
QPushButton {{
    background-color: {SURFACE2}; border: 1px solid {BORDER};
    border-radius: 7px; padding: 6px 14px;
    color: #D6DAE3; font-weight: 600;
}}
QPushButton:hover {{ background-color: #282D37; border-color: {BORDER2}; }}
QPushButton:pressed {{ background-color: #1C2027; }}
QPushButton:disabled {{ color: #5A5F6B; background-color: #1A1D24; border-color: #262A32; }}
QPushButton:focus {{ border-color: {ACCENT}; }}

QPushButton[primary="true"] {{
    background-color: {ACCENT}; border: none; color: {ACCENT_ON};
}}
QPushButton[primary="true"]:hover  {{ background-color: {ACCENT_HOVER}; }}
QPushButton[primary="true"]:pressed{{ background-color: {ACCENT_ACTIVE}; }}
QPushButton[primary="true"]:disabled{{ background-color: #14382E; color: #3E8A6F; }}

QPushButton[ghost="true"] {{ background-color: transparent; border-color: transparent; color: {TEXT2}; }}
QPushButton[ghost="true"]:hover {{ background-color: #262B34; color: {TEXT1}; }}

QPushButton[danger="true"] {{
    background-color: transparent; border: 1px solid #3A2A2E; color: {DANGER};
}}
QPushButton[danger="true"]:hover {{ background-color: rgba(248,113,113,0.10); border-color: {DANGER}; }}
QPushButton[danger="true"]:disabled {{ color: #5A3A3A; border-color: #2B1F22; }}

/* ============ 输入类 ============ */
QLineEdit, QSpinBox, QComboBox {{
    background-color: {INPUT_BG};
    border: 1px solid {BORDER}; border-radius: 6px;
    padding: 5px 10px; color: {TEXT1};
    selection-background-color: {ACCENT}; selection-color: {ACCENT_ON};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit[invalid="true"] {{ border-color: {DANGER}; }}
QLineEdit::placeholder {{ color: {TEXT3}; }}
QSpinBox::up-button, QSpinBox::down-button {{ background: transparent; border: none; width: 18px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background-color: {SURFACE3}; border: 1px solid {BORDER2};
    border-radius: 8px; padding: 4px;
    selection-background-color: #2A2F3A; selection-color: {ACCENT};
}}

/* ============ 账号列表 ============ */
QListWidget#accountList {{ background-color: transparent; border: none; }}
QListWidget#accountList::item {{
    padding: 8px 10px; border-radius: 6px; margin: 1px 0;
    color: {TEXT2};
}}
QListWidget#accountList::item:hover {{ background-color: #232830; color: {TEXT1}; }}
QListWidget#accountList::item:selected {{ background-color: rgba(52,211,153,0.12); color: {ACCENT}; }}

/* ============ 日志 ============ */
QPlainTextEdit#logView {{
    background-color: {INPUT_BG}; border: none; border-radius: 8px;
    font-family: "JetBrains Mono", "Cascadia Mono", "Consolas", monospace;
    font-size: 12px; color: {TEXT2};
}}

/* ============ 扫描进度条 ============ */
QProgressBar#scanProgress {{ background: transparent; border: none; }}
QProgressBar#scanProgress::chunk {{ background-color: {ACCENT}; border-radius: 1px; }}

/* ============ 细滚动条 ============ */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER2}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #4A5162; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER2}; border-radius: 4px; min-width: 30px; }}

/* ============ 其他 ============ */
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {ACCENT}; }}
QToolTip {{
    background-color: {SURFACE3}; color: {TEXT1};
    border: 1px solid {BORDER2}; border-radius: 6px; padding: 5px 8px;
}}
QFrame#footer {{ background-color: #1A1D24; border-top: 1px solid {BORDER}; }}
QLabel#footerText {{ color: #8B92A3; font-size: 12px; }}
"""
