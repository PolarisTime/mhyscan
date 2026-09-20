-- 老库升级: 增加 event_id 幂等键（可重复执行会报错，属于正常）
ALTER TABLE events ADD COLUMN event_id TEXT;
ALTER TABLE events ADD COLUMN schema_version INTEGER;
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_event_id ON events (event_id);

ALTER TABLE scan_success ADD COLUMN event_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_success_event_id ON scan_success (event_id);
