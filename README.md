<div align="center">

# mhyscan

米哈游直播流抢码工具 · 基于 Python / PySide6

[![Build Windows](https://github.com/PolarisTime/mhyscan/actions/workflows/build.yml/badge.svg)](https://github.com/PolarisTime/mhyscan/actions/workflows/build.yml)
![Python](https://img.shields.io/badge/Python-3.12+-blue)
![License](https://img.shields.io/badge/License-MIT-green)

</div>

## 📖 简介

**mhyscan** 是一款用于从直播流中自动识别并抢占米哈游游戏登录二维码的工具。
它支持 B站 / 抖音直播流的实时拉取、二维码识别与自动扫码登录，并提供图形界面与命令行两种使用方式。

> ⚠️ 本项目仅用于个人学习与研究，请勿用于商业用途。

## ✨ 功能特性

- 🖥️ **PySide6 图形界面** + **命令行**双模式
- 📱 **米游社 App 扫码登录**（新一代 passport 接口）
- 🔐 **B站扫码登录**（TV 端接口，保存拉流凭证）
- 👥 **多账号管理**（Cookie / SToken 导入，`userinfo.json`）
- 🎮 **直播间抢码**：B站 / 抖音直播流 → 二维码识别 → 自动 `scanQRLogin` + `confirmQRLogin`
- 📊 **游戏角色信息显示**（7 天缓存）
- ⚡ **低延迟拉流**（ffmpeg 低延迟参数）
- 📜 **详细日志**（每 3 秒进度 + 上海时区时间戳）

## 📦 安装

### 环境要求
- Python 3.12+
- Windows / Linux / macOS

### 依赖安装
```bash
pip install -r requirements.txt
```

## 🚀 使用

### 图形界面（推荐）
```bash
python mhyscan_ui.py
```
或使用已打包的 Windows 版本（见 [Releases](https://github.com/PolarisTime/mhyscan/releases)）。

### 命令行
```bash
# 米游社 App 扫码登录，添加账号
mhyscan login

# B站扫码登录（保存拉流凭证，1080P + 抗限流）
mhyscan bili-login

# 注册用户（粘贴含 SToken 的 Cookie）
mhyscan add --cookie "stuid=..;stoken=..;mid=.."

# 列出账号
mhyscan accounts

# 监视 B站直播间抢码
mhyscan scan bili <RID>

# 监视抖音直播间抢码
mhyscan scan douyin <RID>

# 查看详细帮助
mhyscan help
```

### 抢码流程
1. 使用 `mhyscan login` 或 `mhyscan add` 注册账号
2. （可选）使用 `mhyscan bili-login` 登录 B站，提升拉流画质
3. 输入直播间 `RID`（纯数字），开始扫描
4. 识别到米哈游登录二维码后自动抢码登录

## ⚙️ 配置

| 文件 | 说明 |
|------|------|
| `Config/userinfo.json` | 账号信息（stoken/mid） |
| `Config/bili_cookie.json` | B站登录凭证（或环境变量 `BILIBILI_COOKIE`） |
| `Config/cache.json` | 游戏角色缓存（7 天） |

## 🔨 构建打包

### 本地打包
```bash
pip install pyinstaller
pyinstaller mhyscan_ui.spec --noconfirm
# 产物: dist/mhyscan_ui/
```

### CI/CD 自动构建（Windows）
推送 `v*` 标签即可触发 GitHub Actions 自动构建并发布 Release：
```bash
git tag v1.0.0
git push origin v1.0.0
```

## 🛡️ 隐私与安全

- 所有账号凭证仅保存在本地 `Config/` 目录，不会上传
- `Config/` 已通过 `.gitignore` 排除，避免敏感数据被提交
- 匿名 B站拉流为 720P；配置 B站 cookie 后为 1080P 原画

## 🙏 致谢

本项目参考并借鉴了以下优秀开源项目，在此表示衷心感谢：

| 项目 | 说明 |
|------|------|
| [MHY_Scanner](https://github.com/DSVVA/MHY_Scanner) | 原版米哈游扫码登录器，提供了整体功能与界面设计的参考 |
| [FufuLauncher](https://github.com/FufuLauncher/FufuLauncher) | 原神启动器，参考了米哈游登录接口封装与 B站拉流/登录逻辑 |
| [Snap.Hutao](https://github.com/DGP-Studio/Snap.Hutao) | 原神工具箱，参考了新一代米哈游扫码登录 API（passport 接口） |
| [biliup](https://github.com/biliup/biliup) | B站直播录制工具，参考了 B站直播流获取、二维码登录与 cookie 机制 |
| [mihoyo-api-collect](https://github.com/UIGF-org/mihoyo-api-collect) | 米哈游 API 收集文档，为接口调试提供了宝贵参考 |

## 📄 License

[MIT](LICENSE)
