"""终端二维码渲染 — 用 qrcode 生成, ANSI 半块字符在终端显示 + 保存 PNG"""
from __future__ import annotations

import qrcode


def _build_matrix(url: str, border: int = 2) -> list[list[bool]]:
    qr = qrcode.QRCode(border=border, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.get_matrix()


def print_qr_terminal(url: str, label: str = "请用米游社APP扫描上方二维码") -> None:
    """在终端打印二维码 (半块字符, 双倍密度)"""
    mat = _build_matrix(url)
    # ANSI: 黑底白块在上/下半块
    for y in range(0, len(mat), 2):
        line = ""
        for x in range(len(mat[y])):
            top = mat[y][x]
            bot = mat[y + 1][x] if y + 1 < len(mat) else False
            if top and bot:
                line += "█"      # 全块
            elif top:
                line += "▀"      # 上半块
            elif bot:
                line += "▄"      # 下半块
            else:
                line += " "
        print(line)
    print(label)


def save_qr_png(url: str, path: str) -> None:
    """保存二维码为 PNG 文件"""
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(path)
