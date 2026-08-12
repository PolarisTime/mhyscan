# -*- mode: python ; coding: utf-8 -*-
# mhyscan — PyInstaller 打包配置
#
# 用法 (在目标平台执行):
#   pyinstaller mhyscan_ui.spec
#   → dist/mhyscan_ui/  (onedir, Windows 下为 mhyscan_ui.exe)
#
# 说明:
#   - --onedir: PyAV/opencv 体积大, onedir 启动更快
#   - --noconsole: Windows 下不弹出黑窗 (GUI 模式)
#   - upx=False: 关键! UPX 压缩 Qt DLL 已知会导致 DLL 损坏/无法加载
#   - PySide6 插件由 PyInstaller hook 自动收集, 不写无效 hiddenimport

import os

block_cipher = None

a = Analysis(
    ['mhyscan_ui.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # tzdata: Windows 打包必需 (zoneinfo 时区数据, 缺则 ZoneInfo 崩溃)
        'tzdata',
        # PyAV (整包收集, 协议/编解码器由内部自动加载)
        'av',
        'av.codec',
        # zxing 二维码识别
        'zxingcpp',
        # opencv 视频后端
        'cv2',
        # numpy (cv2/PyAV 传递依赖, 需显式收集)
        'numpy',
        'numpy._core',
        'numpy._core._multiarray_umath',
        # psutil (Windows/macOS 内存监控)
        'psutil',
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
    upx=False,          # 禁用 UPX, 避免 Qt DLL 损坏
    console=False,      # Windows 无黑窗
    icon='',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,          # 禁用 UPX
    upx_exclude=[],
    name='mhyscan_ui',
)
