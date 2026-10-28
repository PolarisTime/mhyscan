-- 每分钟配额计数（按 install_id / 资源分桶）
CREATE TABLE IF NOT EXISTS rate_limits (
  bucket       TEXT    NOT NULL,
  window_start INTEGER NOT NULL,
  count        INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (bucket, window_start)
);
