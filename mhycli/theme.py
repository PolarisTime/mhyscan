"""mhyscan 明亮主题 — QSS 样式常量 + 配色令牌

设计: 清爽明亮风格 (白底 + 翡翠绿主色)
主色翡翠绿传达"GO/成功"语义, 与直播开播/抢码成功认知一致。
"""

# 色彩令牌 (明亮)
BG = "#F4F5F7"           # 窗口/全局背景 (淡灰)
SURFACE = "#FFFFFF"      # 卡片背景 (白)
SURFACE2 = "#F0F2F5"     # 按钮/嵌套区
SURFACE3 = "#FFFFFF"     # 弹出层/下拉/徽章
INPUT_BG = "#FFFFFF"     # 输入框/日志底色
BORDER = "#E0E3E8"       # 默认边框
BORDER2 = "#C7CBD4"      # hover 边框
TEXT1 = "#1F2328"        # 主文字
TEXT2 = "#4A5568"        # 次要文字
TEXT3 = "#8A94A6"        # 弱化/占位/时间戳
ACCENT = "#10B981"       # 主色 (翡翠绿)
ACCENT_HOVER = "#0EA370"
ACCENT_ACTIVE = "#0B8F62"
ACCENT_ON = "#FFFFFF"    # 主按钮文字
SUCCESS = "#10B981"
WARNING = "#D97706"
DANGER = "#DC2626"
INFO = "#3B82F6"

# 日志分级颜色
LOG_COLORS = {
    "time": "#9AA3B2",
    "info": "#4A5568",
    "success": "#0B8F62",
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
QFrame#header {{ background-color: #FFFFFF; border-bottom: 1px solid {BORDER}; }}
QLabel#logo {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {ACCENT}, stop:1 {INFO});
    color: #FFFFFF; border-radius: 8px;
    font-size: 14px; font-weight: 800;
}}
QLabel#appTitle {{ font-size: 15px; font-weight: 700; }}
QLabel#appVersion, QLabel#headerMeta {{ color: {TEXT3}; font-size: 12px; }}

/* ============ 徽章 ============ */
QFrame#badge {{
    background-color: {SURFACE}; border: 1px solid {BORDER};
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
    color: {TEXT2}; font-weight: 600;
}}
QPushButton:hover {{ background-color: #E6E9EE; border-color: {BORDER2}; }}
QPushButton:pressed {{ background-color: #DCE0E6; }}
QPushButton:disabled {{ color: #B0B6C0; background-color: #F0F1F3; border-color: #E8EAED; }}
QPushButton:focus {{ border-color: {ACCENT}; }}

QPushButton[primary="true"] {{
    background-color: {ACCENT}; border: none; color: {ACCENT_ON};
}}
QPushButton[primary="true"]:hover  {{ background-color: {ACCENT_HOVER}; }}
QPushButton[primary="true"]:pressed{{ background-color: {ACCENT_ACTIVE}; }}
QPushButton[primary="true"]:disabled{{ background-color: #B8E6D5; color: #FFFFFF; }}

QPushButton[ghost="true"] {{ background-color: transparent; border-color: transparent; color: {TEXT2}; }}
QPushButton[ghost="true"]:hover {{ background-color: #EEF0F3; color: {TEXT1}; }}

QPushButton[danger="true"] {{
    background-color: transparent; border: 1px solid #F0C9C9; color: {DANGER};
}}
QPushButton[danger="true"]:hover {{ background-color: #FDECEC; border-color: {DANGER}; }}
QPushButton[danger="true"]:disabled {{ color: #D9A5A5; border-color: #F0DBDB; }}

/* ============ 输入类 ============ */
QLineEdit, QSpinBox, QComboBox {{
    background-color: {INPUT_BG};
    border: 1px solid {BORDER}; border-radius: 6px;
    padding: 5px 10px; color: {TEXT1};
    selection-background-color: {ACCENT}; selection-color: #FFFFFF;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit[invalid="true"] {{ border-color: {DANGER}; }}
QLineEdit::placeholder {{ color: {TEXT3}; }}
QSpinBox::up-button, QSpinBox::down-button {{ background: transparent; border: none; width: 18px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background-color: {SURFACE}; border: 1px solid {BORDER2};
    border-radius: 8px; padding: 4px;
    selection-background-color: #EAF6F1; selection-color: {ACCENT_ACTIVE};
}}

/* ============ 账号列表 ============ */
QListWidget#accountList {{ background-color: transparent; border: none; }}
QListWidget#accountList::item {{
    padding: 8px 10px; border-radius: 6px; margin: 1px 0;
    color: {TEXT2};
}}
QListWidget#accountList::item:hover {{ background-color: #EEF0F3; color: {TEXT1}; }}
QListWidget#accountList::item:selected {{ background-color: #EAF6F1; color: {ACCENT_ACTIVE}; }}

/* ============ 日志 ============ */
QPlainTextEdit#logView {{
    background-color: #FAFBFC; border: none; border-radius: 8px;
    font-family: "JetBrains Mono", "Cascadia Mono", "Consolas", monospace;
    font-size: 12px; color: {TEXT2};
}}

/* ============ 扫描进度条 ============ */
QProgressBar#scanProgress {{ background: transparent; border: none; }}
QProgressBar#scanProgress::chunk {{ background-color: {ACCENT}; border-radius: 1px; }}

/* ============ 细滚动条 ============ */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER2}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #AEB4C0; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER2}; border-radius: 4px; min-width: 30px; }}

/* ============ 其他 ============ */
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {ACCENT}; }}
QToolTip {{
    background-color: {SURFACE}; color: {TEXT1};
    border: 1px solid {BORDER2}; border-radius: 6px; padding: 5px 8px;
}}
QFrame#footer {{ background-color: #FFFFFF; border-top: 1px solid {BORDER}; }}
QLabel#footerText {{ color: #6B7280; font-size: 12px; }}
"""
