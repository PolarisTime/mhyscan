use md5::{Digest, Md5};

pub const SALT_MIYAKO_APP: &str = "dDIQHbKOdaPaLuvQKVzUzqdeCaxjtaPV";
#[allow(dead_code)]
pub const SALT_MOBILE: &str = "t0qEgfub6cvueAPgR5m9aQWWVciEer7v";
#[allow(dead_code)]
pub const SALT_PROD: &str = "JwYDpKvLj6MrMqqYU6jTKF17KNO2PXoS";

pub const APP_ID_PASSPORT: &str = "bll8iq97cem8";
pub const APP_ID_GAME: &str = "ddxf5dufpuyo";

pub fn md5_hex(data: &str) -> String {
    hex::encode(Md5::digest(data.as_bytes()))
}

pub fn now_secs() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

pub fn now_millis() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}

fn rand_chars(len: usize, chars: &[u8]) -> String {
    (0..len)
        .map(|_| chars[fastrand::usize(..chars.len())] as char)
        .collect()
}

/// 对应 FufuLauncher GenerateDS: md5(salt&t&r&b&q) → "t,r,sign"
pub fn generate_ds(body: &str, query: &str, salt: &str) -> String {
    let t = now_secs();
    let r = rand_chars(6, b"abcdefghijklmnopqrstuvwxyz0123456789");
    let sign_str = format!("salt={salt}&t={t}&r={r}&b={body}&q={query}");
    format!("{t},{r},{}", md5_hex(&sign_str))
}

/// 对应 FufuLauncher GenerateDeviceFingerprint
pub fn generate_device_fingerprint(device_id: &str) -> String {
    let seed_id = rand_chars(16, b"0123456789abcdef");
    let payload = format!(
        r#"{{"device_id":"{device_id}","seed_id":"{seed_id}","seed_time":{},"platform":"2","device_fp":"","app_name":"bbs_cn"}}"#,
        now_secs()
    );
    md5_hex(&payload)
}
