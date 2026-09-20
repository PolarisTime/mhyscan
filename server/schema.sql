-- mhyscan 遥测 D1 schema
-- 新库: wrangler d1 execute mhyscan_telemetry --file=./schema.sql
-- 老库升级见 migrations/0002_event_id.sql

CREATE TABLE IF NOT EXISTS events (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id       TEXT,                            -- 幂等键（去重）
  schema_version INTEGER,
  ts             INTEGER NOT NULL,
  install_id     TEXT    NOT NULL,
  session_id     TEXT,
  event          TEXT    NOT NULL,
  app_version    TEXT,
  props          TEXT,
  ip_prefix      TEXT,
  created_at     INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_event_id ON events (event_id);
CREATE INDEX IF NOT EXISTS idx_events_install ON events (install_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_event   ON events (event, ts);

-- 抢码成功记录（核心指标）
CREATE TABLE IF NOT EXISTS scan_success (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id   TEXT,
  ts         INTEGER,
  install_id TEXT,
  platform   TEXT,
  rid        TEXT,
  uid_hash   TEXT,
  latency_ms INTEGER,
  attempts   INTEGER,
  ip_prefix  TEXT,
  created_at INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_success_event_id ON scan_success (event_id);
CREATE INDEX IF NOT EXISTS idx_success_platform ON scan_success (platform, ts);

-- 每日聚合
CREATE TABLE IF NOT EXISTS daily_stats (
  day       TEXT    NOT NULL,
  event     TEXT    NOT NULL,
  installs  INTEGER NOT NULL DEFAULT 0,
  total     INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, event)
);
