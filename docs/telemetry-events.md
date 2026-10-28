# mhyscan 遥测事件数据字典

- `schema_version`: **1**（只增字段不改语义；破坏性变更才升版本）
- 会话接口：`POST /v1/sessions`（HMAC 签名，body `{"install_id":"<32 hex>"}`）→ `201` `{token, token_type:"Bearer", expires_in}`
- 上报接口：`POST /v1/events`（必须带 `Authorization: Bearer <token>`）
- 上报格式：`nonce(12B) || AES-256-GCM( gzip( JSON ) )`，body 为单个事件对象或事件数组
- 鉴权：`X-Ts` + `X-Sign = HMAC-SHA256(X-Ts || body)`
- 请求头：`Content-Type: application/octet-stream`、`Accept: application/json`
- 成功响应：`202 Accepted`，body `{ "accepted": n, "rejected": n }`
- 错误响应：RFC 9457 `application/problem+json`（`type/title/status/detail/instance`）
- 状态码：401 签名/时钟/token、400 解密/解压/JSON、403 token 与 install_id 不匹配、413 体积、415 Content-Type、422 批量条数、429 超配额、503 依赖不可用
- 防刷：会话 token 有效期 `TOKEN_TTL`（默认 1800s）；每 install_id 每分钟配额
  `RATE_LIMIT_PER_MIN`（事件，默认 600）与 `RATE_LIMIT_SESSIONS_PER_MIN`（会话，默认 10）；
  超限返回 429 + `Retry-After`

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
| | `channel` | string | `exe` / `source` |
| `scan_result` | `platform` | string | `bili` / `douyin` |
| | `success` | bool | 是否抢码成功（失败时记此事件） |
| | `attempt_count` | int | 本次识别尝试次数 |
| | `detect_latency_ms` | int | 从启动到识别耗时(ms) |
| `scan_success` | `platform` | string | `bili` / `douyin` |
| | `success` | bool | 恒为 `true`（失败走 `scan_result`） |
| | `attempt_count` | int | 本次识别尝试次数 |
| | `detect_latency_ms` | int | 从启动到识别耗时(ms) |

> 说明：`rid` / `uid_hash` / `game_biz` / `region` **当前不采集**（隐私优先，仅保留平台与耗时）。
> 服务端 `scan_success` 表只为 `scan_success` 事件写入，`scan_result`（失败）只进 `events` 表。
| `error` | `exc_type` | string | 异常类型名（**不含堆栈明文**） |

## 服务端表

| 表 | 说明 | 保留 |
|---|---|---|
| `events` | 原始事件（含 `props`、`ip_prefix`） | 90 天（Cron 清理） |
| `scan_success` | 抢码成功/尝试记录（便于聚合） | 长期 |
| `daily_stats` | 按天 × 事件聚合（`installs`,`total`） | 长期 |
| `GET /v1/health` | 健康检查：`status/version/commit/time/checks.db/runtime.colo`，依赖异常返回 503 | — |
| `GET /v1/stats?days=1..365` | 实时聚合（直接查 `events`）：`totals{events,installs,latest_event_at}`、`by_event`、`by_day`、`success`、`rate_limit_buckets`；设置 `STATS_TOKEN` 后需 `?token=` 或 `Authorization: Bearer` | — |
| `daily_stats` | Cron 每天 03:15 UTC 写入的离线聚合，仅作历史留存；`/v1/stats` 不再依赖它 | 长期 |

## 隐私约束（禁止上报）

`stoken` / `cookie` / `mid` / 明文游戏 UID / 二维码内容 / ticket / token / MAC / MachineGuid / 序列号。
`ip` 仅由服务端截断为 `/24`(v4) 或 `/48`(v6) 前缀。
