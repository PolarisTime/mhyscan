# mhyscan 遥测事件数据字典

- `schema_version`: **1**（只增字段不改语义；破坏性变更才升版本）
- 上报格式：`nonce(12B) || AES-256-GCM( gzip( JSON ) )`，body 为单个事件对象或事件数组
- 鉴权：`X-Ts` + `X-Sign = HMAC-SHA256(X-Ts || body)`
- 传输：`application/octet-stream`

## 信封字段（每个事件都带）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `schema_version` | int | ✅ | 事件结构版本，当前 `1` |
| `event_id` | string(uuid) | ✅ | 幂等键，服务端唯一索引去重 |
| `install_id` | string(32 hex) | ✅ | 匿名装机 ID，本地生成、可删 |
| `session_id` | string(32 hex) | ✅ | 每次运行生成 |
| `event` | string | ✅ | 事件名（见下表） |
| `ts` | int | ✅ | 客户端 Unix 秒 |
| `app_version` | string | ✅ | 如 `0.1.0` |
| `props` | object | ✅ | 事件属性（可为空对象） |

## 事件清单

| event | props 字段 | 类型 | 说明 |
|---|---|---|---|
| `app_start` | `ui_mode` | string | `cli` / `gui` |
| | `os` | string | `linux` / `windows` / `macos` |
| | `arch` | string | `x86_64` / `aarch64` |
| | `channel` | string | `exe` / `pip` / `source` |
| `scan_result` | `platform` | string | `bili` / `douyin` |
| | `success` | bool | 是否抢码成功（失败时记此事件） |
| | `attempt_count` | int | 本次识别尝试次数 |
| | `detect_latency_ms` | int | 从启动到识别耗时(ms) |
| `scan_success` | `platform` | string | `bili` / `douyin` |
| | `rid` | string | 直播间号（公开数据） |
| | `uid_hash` | string | 游戏 UID 的服务端/客户端 HMAC（可空） |
| | `game_biz` / `region` | string | 如 `hk4e_cn` / `cn_gf01` |
| | `attempt_count` / `detect_latency_ms` | int | 同上 |
| `error` | `exc_type` | string | 异常类型名（**不含堆栈明文**） |

## 服务端表

| 表 | 说明 | 保留 |
|---|---|---|
| `events` | 原始事件（含 `props`、`ip_prefix`） | 90 天（Cron 清理） |
| `scan_success` | 抢码成功/尝试记录（便于聚合） | 长期 |
| `daily_stats` | 按天 × 事件聚合（`installs`,`total`） | 长期 |

## 隐私约束（禁止上报）

`stoken` / `cookie` / `mid` / 明文游戏 UID / 二维码内容 / ticket / token / MAC / MachineGuid / 序列号。
`ip` 仅由服务端截断为 `/24`(v4) 或 `/48`(v6) 前缀。
