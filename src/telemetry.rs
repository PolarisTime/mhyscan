use std::collections::HashSet;
use std::io::Write;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use aes_gcm::aead::{Aead, KeyInit};
use aes_gcm::{Aes256Gcm, Nonce};
use flate2::Compression;
use flate2::write::GzEncoder;
use hmac::{Hmac, Mac};
use serde_json::{Value, json};
use sha2::Sha256;

use crate::crypto::now_secs;

const SCHEMA_VERSION: u32 = 1;
const MAX_QUEUE: usize = 512;
/// 单次上报批量上限（服务端限制 256，留余量）
const MAX_BATCH: usize = 200;
const MAX_SPOOL: usize = 2048;

/// 匿名遥测客户端（自建 API，批量上报）
///
/// 设计要点：
///   - 上报时机：启动后 + 定时 + 关闭前
///   - 幂等：每条带 `event_id`，服务端去重
///   - 可靠性：发送失败重入队；退出时剩余落盘 spool，下次启动补发
///   - 不阻塞：启动上报异步；HTTP 有超时
///
/// 关闭：`MHYSCAN_TELEMETRY=0` 或 `DO_NOT_TRACK=1`
/// 启用：`MHYSCAN_TELEMETRY_URL`
/// 可选：`MHYSCAN_TELEMETRY_AUTH`、`MHYSCAN_TELEMETRY_KEY`、
///       `MHYSCAN_TELEMETRY_INTERVAL`(默认 300s)、`MHYSCAN_TELEMETRY_SPOOL`
#[derive(Clone)]
pub struct Telemetry {
    inner: Arc<Inner>,
    interval: Duration,
}

struct Inner {
    http: reqwest::Client,
    url: String,
    session_url: String,
    auth: Option<String>,
    enc_key: Option<Vec<u8>>,
    install_id: String,
    session_id: String,
    queue: Mutex<Vec<Value>>,
    /// 串行化 flush，避免启动/退出/定时并发重复上报
    flush_lock: tokio::sync::Mutex<()>,
    /// 会话 token 缓存：(token, 过期时间戳)
    token: Mutex<Option<(String, u64)>>,
}

impl Telemetry {
    pub fn from_env() -> Option<Self> {
        if std::env::var("MHYSCAN_TELEMETRY").ok().as_deref() == Some("0")
            || std::env::var("DO_NOT_TRACK").ok().as_deref() == Some("1")
        {
            return None;
        }
        let url = std::env::var("MHYSCAN_TELEMETRY_URL").ok()?;
        let auth = std::env::var("MHYSCAN_TELEMETRY_AUTH").ok();
        let enc_key = std::env::var("MHYSCAN_TELEMETRY_KEY")
            .ok()
            .and_then(|k| hex::decode(k).ok())
            .filter(|k| k.len() == 32);
        let interval = std::env::var("MHYSCAN_TELEMETRY_INTERVAL")
            .ok()
            .and_then(|v| v.parse::<u64>().ok())
            .unwrap_or(300)
            .max(10);
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs(5))
            .connect_timeout(Duration::from_secs(3))
            .build()
            .ok()?;
        Some(Self {
            inner: Arc::new(Inner {
                http,
                session_url: session_url_from(&url),
                url,
                auth,
                enc_key,
                install_id: load_or_create_install_id(),
                session_id: random_hex(16),
                queue: Mutex::new(Vec::new()),
                flush_lock: tokio::sync::Mutex::new(()),
                token: Mutex::new(None),
            }),
            interval: Duration::from_secs(interval),
        })
    }

    /// 取会话 token（缓存优先，过期前 30s 刷新）
    pub async fn ensure_token(&self) -> anyhow::Result<String> {
        if let Some((token, exp)) = self.inner.token.lock().unwrap().clone() {
            if exp > now_secs() + 30 {
                return Ok(token);
            }
        }
        let body = serde_json::to_vec(&json!({ "install_id": self.inner.install_id }))?;
        let mut req = self
            .inner
            .http
            .post(&self.inner.session_url)
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")
            .body(body.clone());
        if let Some((ts, sig)) = sign_headers(self.inner.auth.as_deref(), &body) {
            req = req.header("X-Ts", ts).header("X-Sign", sig);
        }
        let resp = req.send().await?;
        if !resp.status().is_success() {
            anyhow::bail!("会话申请失败: HTTP {}", resp.status());
        }
        let v: Value = resp.json().await?;
        let token = v
            .get("token")
            .and_then(Value::as_str)
            .ok_or_else(|| anyhow::anyhow!("会话响应缺少 token"))?
            .to_string();
        let ttl = v.get("expires_in").and_then(Value::as_u64).unwrap_or(1800);
        *self.inner.token.lock().unwrap() = Some((token.clone(), now_secs() + ttl));
        Ok(token)
    }

    /// 入队一个事件（不发送）
    pub fn record(&self, event: &str, props: Value) {
        let payload = self.envelope(event, props);
        let mut q = self.inner.queue.lock().unwrap();
        q.push(payload);
        if q.len() > MAX_QUEUE {
            let excess = q.len() - MAX_QUEUE;
            q.drain(0..excess); // 超限丢最旧
        }
    }

    pub fn record_env(&self, ui_mode: &str) {
        self.record(
            "app_start",
            json!({
                "ui_mode": ui_mode,
                "os": std::env::consts::OS,
                "arch": std::env::consts::ARCH,
                "channel": channel(),
            }),
        );
    }

    pub fn record_scan_result(&self, platform: &str, ok: bool, attempts: u32, latency_ms: u64) {
        self.record(
            if ok { "scan_success" } else { "scan_result" },
            json!({
                "platform": platform,
                "success": ok,
                "attempt_count": attempts,
                "detect_latency_ms": latency_ms,
            }),
        );
    }

    pub fn record_error(&self, exc_type: &str) {
        self.record("error", json!({ "exc_type": exc_type }));
    }

    /// 启动定时上报（tokio runtime 内）
    pub fn start_auto_flush(&self) {
        let me = self.clone();
        tokio::spawn(async move {
            loop {
                tokio::time::sleep(me.interval).await;
                if let Err(e) = me.flush().await {
                    debug(&format!("定时上报失败(已重入队): {e}"));
                }
            }
        });
    }

    /// 立即上报队列。
    ///
    /// 取消安全：发送前只克隆快照，发送成功后按 `event_id` 移除；
    /// 若中途失败或被取消，事件仍留在队列，稍后/退出时重发（服务端按
    /// `event_id` 去重，故重复发送无副作用）。
    pub async fn flush(&self) -> anyhow::Result<()> {
        let _guard = self.inner.flush_lock.lock().await;
        loop {
            let snapshot: Vec<Value> = {
                let q = self.inner.queue.lock().unwrap();
                if q.is_empty() {
                    return Ok(());
                }
                q.iter().take(MAX_BATCH).cloned().collect()
            };
            let count = snapshot.len();
            let token = self.ensure_token().await?;
            let payload = Value::Array(snapshot.clone());
            match send(
                &self.inner.http,
                &self.inner.url,
                self.inner.auth.as_deref(),
                self.inner.enc_key.as_deref(),
                Some(&token),
                payload.clone(),
            )
            .await
            {
                Ok(()) => {}
                Err(e) if e.to_string().contains("HTTP 401") => {
                    // token 过期/被吊销：清缓存后重取一次
                    *self.inner.token.lock().unwrap() = None;
                    let token = self.ensure_token().await?;
                    send(
                        &self.inner.http,
                        &self.inner.url,
                        self.inner.auth.as_deref(),
                        self.inner.enc_key.as_deref(),
                        Some(&token),
                        payload,
                    )
                    .await?;
                }
                Err(e) => return Err(e),
            }

            let sent: HashSet<String> = snapshot
                .iter()
                .filter_map(|e| {
                    e.get("event_id")
                        .and_then(Value::as_str)
                        .map(str::to_string)
                })
                .collect();
            let removed = {
                let mut q = self.inner.queue.lock().unwrap();
                let before = q.len();
                q.retain(|e| match e.get("event_id").and_then(Value::as_str) {
                    Some(id) => !sent.contains(id),
                    None => true,
                });
                before - q.len()
            };
            // 防御：整批都没被移除时避免死循环
            if removed == 0 {
                anyhow::bail!("批量事件去重失败（缺少 event_id）");
            }
            if count < MAX_BATCH {
                return Ok(());
            }
        }
    }

    /// 退出时使用：尽力上报，失败的落盘 spool 等下次启动补发
    pub async fn flush_or_spool(&self) {
        if self.flush().await.is_err() {
            self.spool_remaining();
        }
    }

    /// 把当前队列剩余事件追加到 spool 文件（有界）
    pub fn spool_remaining(&self) {
        self.spool_remaining_to(&spool_path());
    }

    fn spool_remaining_to(&self, path: &std::path::Path) {
        let events = {
            let mut q = self.inner.queue.lock().unwrap();
            std::mem::take(&mut *q)
        };
        if events.is_empty() {
            return;
        }
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let mut lines: Vec<String> = std::fs::read_to_string(&path)
            .map(|t| t.lines().map(str::to_string).collect())
            .unwrap_or_default();
        for ev in &events {
            if let Ok(s) = serde_json::to_string(ev) {
                lines.push(s);
            }
        }
        if lines.len() > MAX_SPOOL {
            let excess = lines.len() - MAX_SPOOL;
            lines.drain(0..excess);
        }
        let _ = std::fs::write(path, lines.join("\n"));
        debug(&format!("已 spool {} 条待补发事件", events.len()));
    }

    /// 启动时调用：读取 spool 并重新入队，然后清空文件
    pub fn load_spool(&self) {
        self.load_spool_from(&spool_path());
    }

    fn load_spool_from(&self, path: &std::path::Path) {
        let Ok(text) = std::fs::read_to_string(path) else {
            return;
        };
        let events: Vec<Value> = text
            .lines()
            .filter(|l| !l.trim().is_empty())
            .filter_map(|l| serde_json::from_str::<Value>(l).ok())
            .collect();
        if !events.is_empty() {
            debug(&format!("从 spool 补入 {} 条事件", events.len()));
            let mut q = self.inner.queue.lock().unwrap();
            q.extend(events);
            if q.len() > MAX_QUEUE {
                let excess = q.len() - MAX_QUEUE;
                q.drain(0..excess);
            }
        }
        let _ = std::fs::remove_file(path);
    }

    fn envelope(&self, event: &str, props: Value) -> Value {
        json!({
            "schema_version": SCHEMA_VERSION,
            "event_id": uuid_v4(),
            "install_id": self.inner.install_id,
            "session_id": self.inner.session_id,
            "event": event,
            "ts": now_secs(),
            "app_version": env!("CARGO_PKG_VERSION"),
            "props": props,
        })
    }
}

async fn send(
    http: &reqwest::Client,
    url: &str,
    auth: Option<&str>,
    key: Option<&[u8]>,
    token: Option<&str>,
    payload: Value,
) -> anyhow::Result<()> {
    let raw = serde_json::to_vec(&payload)?;

    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(&raw)?;
    let mut body = encoder.finish()?;

    if let Some(key) = key {
        let nonce_bytes = {
            let mut n = [0u8; 12];
            for b in &mut n {
                *b = fastrand::u8(..);
            }
            n
        };
        let cipher = Aes256Gcm::new_from_slice(key)?;
        let nonce: Nonce<_> = nonce_bytes.into();
        let ct = cipher
            .encrypt(&nonce, body.as_slice())
            .map_err(|e| anyhow::anyhow!("加密失败: {e}"))?;
        let mut framed = nonce_bytes.to_vec();
        framed.extend_from_slice(&ct);
        body = framed;
    }

    let install = payload
        .as_array()
        .and_then(|a| a.first())
        .or(Some(&payload))
        .and_then(|v| v.get("install_id"))
        .and_then(Value::as_str)
        .unwrap_or_default();

    let mut req = http
        .post(url)
        .header("Content-Type", "application/octet-stream")
        .header("Accept", "application/json")
        .header("X-Install-Id", install);

    if let Some(token) = token {
        req = req.header("Authorization", format!("Bearer {token}"));
    }
    if let Some((ts, sig)) = sign_headers(auth, &body) {
        req = req.header("X-Ts", ts).header("X-Sign", sig);
    }

    let resp = req.body(body).send().await?;
    if !resp.status().is_success() {
        anyhow::bail!("HTTP {}", resp.status());
    }
    Ok(())
}

/// HMAC 请求签名头：`X-Ts` + `X-Sign = HMAC-SHA256(X-Ts || body)`
fn sign_headers(auth: Option<&str>, body: &[u8]) -> Option<(String, String)> {
    let auth = auth?;
    let ts = now_secs().to_string();
    let mut mac = Hmac::<Sha256>::new_from_slice(auth.as_bytes()).ok()?;
    mac.update(ts.as_bytes());
    mac.update(body);
    Some((ts, hex::encode(mac.finalize().into_bytes())))
}

/// 由事件上报 URL 推导会话申请 URL（可用 MHYSCAN_TELEMETRY_SESSION_URL 覆盖）
fn session_url_from(events_url: &str) -> String {
    if let Ok(url) = std::env::var("MHYSCAN_TELEMETRY_SESSION_URL") {
        let url = url.trim();
        if !url.is_empty() {
            return url.to_string();
        }
    }
    let base = events_url.trim_end_matches('/');
    match base.strip_suffix("/events") {
        Some(prefix) => format!("{prefix}/sessions"),
        None => format!("{base}/sessions"),
    }
}

fn spool_path() -> PathBuf {
    std::env::var("MHYSCAN_TELEMETRY_SPOOL")
        .map(PathBuf::from)
        .unwrap_or_else(|_| config_dir().join("telemetry_spool.jsonl"))
}

fn telemetry_path() -> PathBuf {
    std::env::var("MHYSCAN_TELEMETRY_FILE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| config_dir().join("telemetry.json"))
}

/// 配置目录：`MHYSCAN_CONFIG_DIR` > 平台标准目录 > 当前目录下的 `Config`
fn config_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("MHYSCAN_CONFIG_DIR") {
        if !dir.trim().is_empty() {
            return PathBuf::from(dir);
        }
    }
    if cfg!(target_os = "windows") {
        if let Ok(appdata) = std::env::var("APPDATA") {
            return PathBuf::from(appdata).join("mhyscan");
        }
    } else if cfg!(target_os = "macos") {
        if let Ok(home) = std::env::var("HOME") {
            return PathBuf::from(home).join("Library/Application Support/mhyscan");
        }
    } else {
        if let Ok(xdg) = std::env::var("XDG_CONFIG_HOME") {
            return PathBuf::from(xdg).join("mhyscan");
        }
        if let Ok(home) = std::env::var("HOME") {
            return PathBuf::from(home).join(".config/mhyscan");
        }
    }
    PathBuf::from("Config")
}

fn load_or_create_install_id() -> String {
    let path = telemetry_path();
    if let Ok(text) = std::fs::read_to_string(&path) {
        if let Ok(v) = serde_json::from_str::<Value>(&text) {
            if let Some(id) = v.get("install_id").and_then(Value::as_str) {
                return id.to_string();
            }
        }
    }
    let id = random_hex(16);
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let _ = std::fs::write(
        &path,
        serde_json::to_string_pretty(&json!({ "install_id": id })).unwrap_or_default(),
    );
    id
}

fn random_hex(len: usize) -> String {
    (0..len)
        .map(|_| format!("{:02x}", fastrand::u8(..)))
        .collect()
}

fn uuid_v4() -> String {
    let h = random_hex(16);
    format!(
        "{}-{}-{}-{}-{}",
        &h[0..8],
        &h[8..12],
        &h[12..16],
        &h[16..20],
        &h[20..32]
    )
}

fn channel() -> &'static str {
    if cfg!(debug_assertions) {
        "source"
    } else {
        "exe"
    }
}

fn debug(msg: &str) {
    if std::env::var("MHYSCAN_DEBUG").is_ok() {
        eprintln!("[telemetry] {msg}");
    }
}

#[cfg(test)]
impl Telemetry {
    fn for_test() -> Self {
        let http = reqwest::Client::builder()
            .timeout(Duration::from_millis(50))
            .build()
            .unwrap();
        Self {
            inner: Arc::new(Inner {
                http,
                url: "http://127.0.0.1:9/collect".to_string(),
                session_url: "http://127.0.0.1:9/sessions".to_string(),
                auth: None,
                enc_key: None,
                install_id: "test-install".to_string(),
                session_id: "test-session".to_string(),
                queue: Mutex::new(Vec::new()),
                flush_lock: tokio::sync::Mutex::new(()),
                token: Mutex::new(None),
            }),
            interval: Duration::from_secs(10),
        }
    }

    fn queue_len(&self) -> usize {
        self.inner.queue.lock().unwrap().len()
    }

    fn set_token_for_test(&self, token: &str, exp: u64) {
        *self.inner.token.lock().unwrap() = Some((token.to_string(), exp));
    }

    fn snapshot(&self) -> Vec<Value> {
        self.inner.queue.lock().unwrap().clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn envelope_has_required_fields_and_no_pii() {
        let t = Telemetry::for_test();
        t.record_scan_result("bili", true, 12, 3456);
        let env = t.snapshot().pop().expect("event");
        assert_eq!(env["event"], "scan_success");
        assert_eq!(env["props"]["platform"], "bili");
        assert!(env["event_id"].as_str().is_some_and(|s| s.len() == 36));
        assert_eq!(env["install_id"], "test-install");
        assert_eq!(env["schema_version"], 1);
        // 隐私：不得出现敏感字段名/值
        let text = env.to_string();
        for forbidden in ["ticket", "stoken", "cookie", "qrcode", "access_key"] {
            assert!(!text.contains(forbidden), "信封不应包含 {forbidden}: {text}");
        }
    }

    #[test]
    fn queue_is_bounded() {
        let t = Telemetry::for_test();
        for i in 0..600 {
            t.record("test_event", json!({ "i": i }));
        }
        assert_eq!(t.queue_len(), MAX_QUEUE);
    }

    #[test]
    fn spool_roundtrip() {
        let dir = std::env::temp_dir().join(format!("mhyscan-telemetry-{}", fastrand::u64(..)));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("spool.jsonl");

        let t = Telemetry::for_test();
        t.record("a", json!({}));
        t.record("b", json!({}));
        t.spool_remaining_to(&path);
        assert_eq!(t.queue_len(), 0, "spool 后队列应清空");

        t.load_spool_from(&path);
        assert_eq!(t.queue_len(), 2, "补发应恢复两条事件");
        assert!(!path.exists(), "读取后应删除 spool 文件");

        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn session_url_derivation() {
        assert_eq!(
            session_url_from("https://api.example.com/v1/events"),
            "https://api.example.com/v1/sessions"
        );
        assert_eq!(
            session_url_from("https://api.example.com/v1/events/"),
            "https://api.example.com/v1/sessions"
        );
        assert_eq!(
            session_url_from("https://api.example.com/collect"),
            "https://api.example.com/collect/sessions"
        );
    }

    #[tokio::test]
    async fn token_cache_hit_avoids_network() {
        let t = Telemetry::for_test();
        t.set_token_for_test("cached-token", now_secs() + 600);
        assert_eq!(t.ensure_token().await.unwrap(), "cached-token");
    }

    #[test]
    fn batch_limit_within_server_capacity() {
        // 服务端拒绝 >256 条/批，客户端必须留余量
        assert!(MAX_BATCH > 0 && MAX_BATCH <= 256);
    }
}
