<div align="center">

# mhyscan

米哈游直播流抢码工具 · 基于 **Rust**（openh264 + rxing）

[![Auto Release](https://github.com/PolarisTime/mhyscan/actions/workflows/auto-release.yml/badge.svg)](https://github.com/PolarisTime/mhyscan/actions/workflows/auto-release.yml)
![Rust](https://img.shields.io/badge/Rust-1.85+-orange)
![License](https://img.shields.io/badge/License-MIT-green)

</div>

## 简介

**mhyscan** 从 B站 / 抖音直播流中实时识别米哈游登录二维码，并用已登录账号自动抢码。

纯 Rust 实现：HTTP-FLV 拉流 → FLV 解复用 → H.264 硬解（openh264）→ ZXing 识别（rxing）→ `scanQRLogin`/`confirmQRLogin` 抢码。发布二进制约 **4–5 MB**，内存 ~15–35 MB。

> ⚠️ 仅用于个人学习与研究，请勿用于商业用途。

## 功能

- HTTP-FLV 低延迟拉流（FLV + AVC + 原画，多 CDN 候选容灾）
- 二维码识别（rxing / ZXing）
- 官服扫码登录 + 抢码（passport `scan/confirm`）
- B站扫码登录（保存拉流凭证 cookie）
- 抖音直播流
- 多账号/单账号抢码、连接预热
- 匿名遥测（可关闭，自建 Cloudflare Worker + D1）
- 可选 Tauri 桌面端（`tauri-app/`，HTML 设计稿）

## 安装 / 构建

```bash
cargo build --release
# 产物: target/release/mhyscan-rs
```

Windows 交叉编译（本机 Linux）：
```bash
rustup target add x86_64-pc-windows-gnu
cargo install cargo-zigbuild            # 配合 zig 提供 mingw 工具链
cargo zigbuild --release --target x86_64-pc-windows-gnu
```

## 命令

```text
mhyscan scan <RID> [--platform bili|douyin] [--timeout 秒]   监视直播间抢码
mhyscan accounts                                             列出已登录账号
mhyscan login                                                米游社 App 扫码登录 (官服)
mhyscan login bili                                           B站扫码登录, 保存拉流凭证
mhyscan login bili-game <账号> <密码>                         B服崩坏3 账号密码登录
mhyscan qr <图片>                                            离线识别二维码
mhyscan help
```

示例：
```bash
mhyscan scan 6                       # B站 RID=6，默认 180s
mhyscan scan 6 --platform douyin     # 抖音
mhyscan scan 6 --timeout 600
```

## 配置（环境变量）

| 变量 | 作用 | 默认 |
|---|---|---|
| `MHYSCAN_CONFIG` | 账号库路径 | `Config/userinfo.json` |
| `MHYSCAN_CONFIRM_DELAY_MS` | scan→confirm 等待 | `250` |
| `MHYSCAN_TELEMETRY_URL` | 遥测端点（不设=关闭） | — |
| `MHYSCAN_TELEMETRY_AUTH` / `_KEY` | HMAC / AES 密钥 | — |
| `MHYSCAN_TELEMETRY_INTERVAL` | 定时上报间隔(s) | `300` |
| `MHYSCAN_TELEMETRY=0` / `DO_NOT_TRACK=1` | 关闭遥测 | — |
| `MHYSCAN_DEBUG` | 调试日志 | 关 |

## 遥测后端（自建）

`server/` 为 Cloudflare Worker + D1：`/collect` 接收（HMAC + AES-256-GCM + gzip）、每日 Cron 聚合与 90 天清理。见 `docs/telemetry-events.md`。

部署：
```bash
cd server && npm install
npx wrangler d1 create mhyscan_telemetry     # 填入 database_id
npx wrangler d1 execute mhyscan_telemetry --remote --file=./schema.sql
npx wrangler secret put TELEMETRY_AUTH
npx wrangler secret put TELEMETRY_KEY
npx wrangler deploy
```

## CI/CD

- `auto-release.yml`：push 到 main 自动构建 Windows / Linux / macOS 并发布 Release（tag = 版本号 + 构建号）
- `deploy-telemetry.yml`：`server/**` 变更时部署 Worker
- `pages.yml`：发布 UI 设计稿到 GitHub Pages

## 桌面端（可选）

`tauri-app/` 为 Tauri v2 工程（HTML 设计稿，需 WebView 环境构建）：
```bash
cd tauri-app/src-tauri
cargo tauri icon ../../app-icon.png
cargo tauri dev
```

## 隐私

所有账号凭证仅保存在本地 `Config/`（已 gitignore）。游戏 UID 等敏感信息不参与遥测；遥测仅上报低敏环境与扫描事件，可随时关闭。

## License

[MIT](LICENSE)
