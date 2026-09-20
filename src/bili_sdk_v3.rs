//! B站游戏登录 SDK v3（对应 `Ko-Koa/bilibili-game-sdk-reverse` 的 `external_*_v3`）。
//!
//! 流程：
//!   1. `client_activate`           → 注册设备，取得 `bd_id`
//!   2. `external/issue/cipher/v3`  → 取 `hash` + RSA 公钥
//!   3. `external/login/v3`         → RSA(hash+pwd) → 登录，返回 access_key/uid
//!
//! 崩坏3 参数：app_id=180 / merchant_id=590 / server_id=378（可按需覆盖）。
use std::path::PathBuf;

use aes::cipher::{BlockEncrypt, KeyInit};
use anyhow::{Result, bail};
use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use md5::{Digest, Md5};
use reqwest::header::{CONTENT_TYPE, USER_AGENT};
use rsa::pkcs8::DecodePublicKey;
use rsa::{Pkcs1v15Encrypt, RsaPublicKey};
use serde_json::{Value, json};

use crate::crypto::now_millis;

const UA: &str = "Mozilla/5.0 BSGameSDK";
const ISSUE_CIPHER: &str =
    "https://line1-sdk-center-login-sh.biligame.net/api/external/issue/cipher/v3";
const LOGIN_V3: &str = "https://line1-sdk-center-login-sh.biligame.net/api/external/login/v3";
const ACTIVATE: &str = "https://p.biligame.com/api/client/activate";
const BD_INFO_KEY: &[u8; 16] = b"68b9f18eac8f4e3b";

#[derive(Clone)]
pub struct Bh3BiliConfig {
    pub app_id: String,
    pub merchant_id: String,
    pub server_id: String,
    pub app_key: String,
}

impl Default for Bh3BiliConfig {
    fn default() -> Self {
        let env = |k: &str, d: &str| std::env::var(k).unwrap_or_else(|_| d.to_string());
        Self {
            app_id: env("MHYSCAN_BH3_GAME_ID", "180"),
            merchant_id: env("MHYSCAN_BH3_MERCHANT_ID", "590"),
            server_id: env("MHYSCAN_BH3_SERVER_ID", "378"),
            app_key: env("MHYSCAN_BH3_APP_KEY", "0ebc517adb1b62c6b408df153331f9aa"),
        }
    }
}

/// 对应 sdkUtils.generate_sign：按 key 排序拼接值（排除过滤键）+ APP_Key，取 md5
fn generate_sign(pairs: &[(String, String)], app_key: &str) -> String {
    let mut items: Vec<&(String, String)> = pairs.iter().collect();
    items.sort_by(|a, b| a.0.cmp(&b.0));
    let mut plain = String::new();
    for (k, v) in items {
        if ["item_name", "item_desc", "feign_sign", "token", "sign"].contains(&k.as_str()) {
            continue;
        }
        plain.push_str(v);
    }
    plain.push_str(app_key);
    md5_hex(&plain)
}

pub struct LoginV3Result {
    pub code: i64,
    pub message: String,
    pub uid: String,
    pub access_key: String,
    pub uname: String,
}

fn md5_hex(s: &str) -> String {
    hex::encode(Md5::digest(s.as_bytes()))
}

/// 设备 MAC（可用 MHYSCAN_MAC 覆盖，默认固定值以保证 bd_id 稳定）
fn device_mac() -> String {
    std::env::var("MHYSCAN_MAC")
        .unwrap_or_else(|_| "08:00:27:53:DD:12".to_string())
        .to_uppercase()
}

fn get_buvid(mac: &str) -> String {
    let h = md5_hex(&mac.to_uppercase());
    let b = h.as_bytes();
    let salt = format!("{}{}{}", b[2] as char, b[12] as char, b[22] as char);
    format!("XY{salt}{h}").to_uppercase()
}

fn get_hwid(mac: &str) -> String {
    format!("EA{}", md5_hex(&mac.to_uppercase()))
}

fn get_udid(mac: &str) -> String {
    let norm: String = mac
        .chars()
        .filter(|c| c.is_ascii_hexdigit())
        .collect::<String>()
        .to_lowercase();
    let plaintext = format!("{norm}|||");
    let mut bytes = plaintext.into_bytes();
    let len = bytes.len();
    bytes[0] ^= (len & 0xff) as u8;
    for i in 1..len {
        bytes[i] = (bytes[i - 1] ^ bytes[i]) & 0xff;
    }
    STANDARD.encode(bytes)
}

fn uuid_v4() -> String {
    let h: String = (0..16)
        .map(|_| format!("{:02x}", fastrand::u8(..)))
        .collect();
    format!(
        "{}-{}-{}-{}-{}",
        &h[0..8],
        &h[8..12],
        &h[12..16],
        &h[16..20],
        &h[20..32]
    )
}

fn bd_id_path() -> PathBuf {
    std::env::var("MHYSCAN_BD_ID")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("Config/bili_bd_id.txt"))
}

fn load_or_create_bd_id(mac: &str) -> String {
    let path = bd_id_path();
    if let Ok(s) = std::fs::read_to_string(&path) {
        let s = s.trim().to_string();
        if !s.is_empty() {
            return s;
        }
    }
    let buvid = get_buvid(mac);
    let raw = format!("{}-{}", uuid_v4(), buvid.to_lowercase());
    let bd_id: String = raw.chars().take(64).collect();
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let _ = std::fs::write(&path, &bd_id);
    bd_id
}

/// AES-128-ECB + PKCS7，前缀 `_v2_`
fn bd_info(device_info: &Value) -> String {
    let text = serde_json::to_string(device_info)
        .unwrap_or_default()
        .replace('/', "\\/");
    let mut data = text.into_bytes();
    let pad = 16 - (data.len() % 16);
    data.extend(std::iter::repeat_n(pad as u8, pad));

    let cipher = aes::Aes128::new(BD_INFO_KEY.into());
    let mut out = Vec::with_capacity(data.len());
    for chunk in data.chunks(16) {
        let mut block = aes::cipher::generic_array::GenericArray::clone_from_slice(chunk);
        cipher.encrypt_block(&mut block);
        out.extend_from_slice(&block);
    }
    format!("_v2_{}", STANDARD.encode(out))
}

pub struct BiliV3Client {
    pub http: reqwest::Client,
    pub cfg: Bh3BiliConfig,
}

impl BiliV3Client {
    pub fn new(cfg: Bh3BiliConfig) -> Self {
        Self {
            http: reqwest::Client::new(),
            cfg,
        }
    }

    /// 注册设备，返回 bd_id
    pub async fn client_activate(&self) -> Result<String> {
        let mac = device_mac();
        let buvid = get_buvid(&mac);
        let bd_id = load_or_create_bd_id(&mac);
        let ts = now_millis().to_string();

        let device_info = json!({
            "cur_buvid": buvid, "old_buvid": buvid,
            "udid": get_udid(&mac), "bd_id": bd_id,
            "imei": "", "mac": mac,
            "android_id": "a33db2dab3a0ec80", "oaid": "aafc70c5cc148b40",
            "model": "MIX 3", "brand": "Xiaomi", "dp": "2030,1080,440", "net": "1",
            "operators": "中国移动", "supportedAbis": "[arm64-v8a, armeabi-v7a, armeabi]",
            "is_root": "0", "pf_ver": "9", "platform_type": "Android", "ver": "1.0.55",
            "version_code": "110", "sdk_ver": "5.9.0", "app_id": self.cfg.app_id,
            "fts": 0, "first": 0, "files": "", "pkg_name": "", "app_name": "",
            "finger_print": "Xiaomi/chiron/chiron:9/PKQ1.190118.001/9.9.3:user/release-keys",
            "serial": "unknown", "band": "AT20-0827_0009_2705804,AT20-0827_0009_2705804",
            "cpu_count": 8, "cpu_model": "AArch64 Processor rev 1 (aarch64)",
            "cpu_freq": 1900800, "cpu_verdor": "Qualcomm",
            "camcnt": 2, "campx": "4000x3000", "camzoom": "4.5",
            "bat_level": "100", "bat_state": "2", "ts": ts, "brightness": 1040,
            "boot": 347487608, "total_ram": 6002499584u64, "total_rom": 117990408192u64,
            "is_debug": "1", "is_emu": "000000",
            "time_zone": "GMT+08:00 TimeZone id :Asia/Shanghai", "lang": "ZH",
            "os": "android", "hwId": get_hwid(&mac), "kernel_ver": "4.4.153-perf+"
        });

        let mut fields: Vec<(String, String)> = vec![
            ("merchant_id".into(), self.cfg.merchant_id.clone()),
            ("game_id".into(), self.cfg.app_id.clone()),
            ("timestamp".into(), ts.clone()),
            ("bd_id".into(), bd_id.clone()),
            ("server_id".into(), self.cfg.server_id.clone()),
            ("version".into(), "1".into()),
            ("bd_info".into(), bd_info(&device_info)),
            ("channel_id".into(), "1".into()),
        ];
        let sign = generate_sign(&fields, &self.cfg.app_key);
        fields.push(("sign".into(), sign));

        let resp: Value = self
            .http
            .post(ACTIVATE)
            .header(USER_AGENT, "okhttp/3.12.1")
            .header("cversion", "1")
            .header("one-sdk-ver", "null")
            .header(CONTENT_TYPE, "application/x-www-form-urlencoded")
            .form(&fields)
            .send()
            .await?
            .json()
            .await?;

        let code = resp.get("code").and_then(Value::as_i64).unwrap_or(-1);
        if code != 0 {
            bail!("activate 失败: {resp}");
        }
        Ok(bd_id)
    }

    async fn issue_cipher(&self) -> Result<(String, String)> {
        let mut fields: Vec<(String, String)> = vec![
            ("merchant_id".into(), self.cfg.merchant_id.clone()),
            ("game_id".into(), self.cfg.app_id.clone()),
            ("timestamp".into(), now_millis().to_string()),
            ("cipher_type".into(), "bili_login_rsa".into()),
            ("server_id".into(), self.cfg.server_id.clone()),
            ("version".into(), "3".into()),
        ];
        let sign = generate_sign(&fields, &self.cfg.app_key);
        fields.push(("sign".into(), sign));

        let resp: Value = self
            .http
            .post(ISSUE_CIPHER)
            .header(USER_AGENT, UA)
            .header(CONTENT_TYPE, "application/x-www-form-urlencoded")
            .form(&fields)
            .send()
            .await?
            .json()
            .await?;
        if resp.get("code").and_then(Value::as_i64) != Some(0) {
            bail!("issue/cipher/v3 失败: {resp}");
        }
        Ok((
            resp.get("hash")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string(),
            resp.get("cipher_key")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string(),
        ))
    }

    /// 账号密码登录
    pub async fn login(&self, user_id: &str, password: &str) -> Result<LoginV3Result> {
        let bd_id = self.client_activate().await?;
        let (hash, rsa_key) = self.issue_cipher().await?;

        // RSA PKCS#1 v1.5 (hash + password) → base64
        let key = RsaPublicKey::from_public_key_pem(&rsa_key)
            .map_err(|e| anyhow::anyhow!("解析 cipher_key 失败: {e}"))?;
        let mut rng = rand::thread_rng();
        let enc = key
            .encrypt(
                &mut rng,
                Pkcs1v15Encrypt,
                format!("{hash}{password}").as_bytes(),
            )
            .map_err(|e| anyhow::anyhow!("RSA 加密失败: {e}"))?;
        let pwd = STANDARD.encode(enc);

        let mut fields: Vec<(String, String)> = vec![
            ("merchant_id".into(), self.cfg.merchant_id.clone()),
            ("game_id".into(), self.cfg.app_id.clone()),
            ("timestamp".into(), now_millis().to_string()),
            ("bd_id".into(), bd_id),
            ("server_id".into(), self.cfg.server_id.clone()),
            ("version".into(), "3".into()),
            ("user_id".into(), user_id.to_string()),
            ("pwd".into(), pwd),
        ];
        let sign = generate_sign(&fields, &self.cfg.app_key);
        fields.push(("sign".into(), sign));

        let resp: Value = self
            .http
            .post(LOGIN_V3)
            .header(USER_AGENT, UA)
            .header(CONTENT_TYPE, "application/x-www-form-urlencoded")
            .form(&fields)
            .send()
            .await?
            .json()
            .await?;

        let code = resp.get("code").and_then(Value::as_i64).unwrap_or(-1);
        Ok(LoginV3Result {
            code,
            message: resp
                .get("message")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string(),
            uid: resp.get("uid").map(scalar).unwrap_or_default(),
            access_key: resp
                .get("access_key")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string(),
            uname: resp
                .get("uname")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string(),
        })
    }
}

fn scalar(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}
