# -*- mode: python ; coding: utf-8 -*-
# mhyscan 1.0.0 — PyInstaller 打包配置
#
# 用法 (在目标平台执行):
#   pyinstaller mhyscan_ui.spec
#   → dist/mhyscan_ui/  (onedir, Windows 下为 mhyscan_ui.exe)
#
# 说明:
#   - --onedir: PyAV/opencv 体积大, onedir 启动更快
#   - --noconsole: Windows 下不弹出黑窗 (GUI 模式)
#   - mhycli 为内部包, 自动收集; 第三方依赖自动分析

import os

block_cipher = None

# 版本号
version = "1.0.0"

a = Analysis(
    ['mhyscan_ui.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # PyAV 的协议/解复用器/编解码器 (flv/hls/avc)
        'av',
        'av.protocol',
        'av.codec',
        # zxing 二维码识别
        'zxingcpp',
        # opencv 视频后端
        'cv2',
        # 二维码生成
        'qrcode',
        'qrcode.image.pil',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='mhyscan_ui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # Windows 无黑窗
    icon='',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='mhyscan_ui',
)
