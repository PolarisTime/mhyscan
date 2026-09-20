//! B站崩坏3（B服）账号密码登录，对应 Python `bili_sdk.py` / BSGameSDK.hpp。
//!
//! 流程：`/api/client/rsa` 取公钥 → RSA 加密 `hash+pwd` → `/api/client/login`
//! → `/api/client/user.info` 取昵称；需要极验时先 `/api/client/start_captcha`。
use anyhow::{Result, bail};
use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use percent_encoding::{NON_ALPHANUMERIC, utf8_percent_encode};
use reqwest::header::{CONTENT_TYPE, USER_AGENT};
use rsa::pkcs8::DecodePublicKey;
use rsa::{Pkcs1v15Encrypt, RsaPublicKey};
use serde_json::Value;

use crate::crypto::md5_hex;

const BILI_BASE: &str = "https://line1-sdk-center-login-sh.biligame.net";
const BILI_RSA: &str = "https://line1-sdk-center-login-sh.biligame.net/api/client/rsa";
const BILI_LOGIN: &str = "https://line1-sdk-center-login-sh.biligame.net/api/client/login";
const BILI_USERINFO: &str = "https://line1-sdk-center-login-sh.biligame.net/api/client/user.info";
const BILI_CAPTCHA: &str =
    "https://line1-sdk-center-login-sh.biligame.net/api/client/start_captcha";

const UA: &str = "Mozilla/5.0 BSGameSDK";
const BILI_APP_KEY: &str = "dbf8f1b4496f430b8a3c0f436a35b931";

/// 有序参数表（保持插入顺序，更新已存在键不改变位置）
#[derive(Clone)]
struct Params(Vec<(String, String)>);

impl Params {
    fn base() -> Self {
        let pairs: &[(&str, &str)] = &[
            ("operators", "5"),
            ("merchant_id", "590"),
            ("isRoot", "0"),
            ("domain_switch_count", "0"),
            ("sdk_type", "1"),
            ("sdk_log_type", "1"),
            ("support_abis", "x86,armeabi-v7a,armeabi"),
            ("access_key", ""),
            ("sdk_ver", "3.4.2"),
            ("oaid", ""),
            ("dp", "1280 * 720"),
            ("original_domain", ""),
            ("imei", ""),
            ("version", "1"),
            ("udid", "XXA31CBAB6CBA63E432E087B58411A213BFB7"),
            ("apk_sign", "4502a02a00395dec05a4134ad593224d"),
            ("platform_type", "3"),
            ("old_buvid", "XZA2FA4AC240F665E2F27F603ABF98C615C29"),
            ("android_id", "84567e2dda72d1d4"),
            ("fingerprint", ""),
            ("mac", "08:00:27:53:DD:12"),
            ("server_id", "378"),
            ("domain", "line1-sdk-center-login-sh.biligame.net"),
            ("app_id", "180"),
            ("version_code", "510"),
            ("net", "4"),
            ("pf_ver", "12"),
            ("cur_buvid", "XZA2FA4AC240F665E2F27F603ABF98C615C29"),
            ("c", "1"),
            ("brand", "Android"),
            ("channel_id", "1"),
            ("uid", ""),
            ("game_id", "180"),
            ("ver", "6.1.0"),
            ("model", "MuMu"),
        ];
        Params(
            pairs
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect(),
        )
    }

    fn set(&mut self, k: &str, v: impl Into<String>) {
        let v = v.into();
        if let Some(slot) = self.0.iter_mut().find(|(key, _)| key == k) {
            slot.1 = v;
        } else {
            self.0.push((k.to_string(), v));
        }
    }

    fn remove(&mut self, k: &str) {
        self.0.retain(|(key, _)| key != k);
    }
}

/// 对应 BSGameSDK::detail::SetSign（时间戳为毫秒）
fn set_sign(mut data: Params) -> String {
    let ts = crate::crypto::now_millis().to_string();
    data.set("timestamp", ts.clone());
    data.set("client_timestamp", ts);

    let mut values = String::new();
    let mut parts = Vec::new();
    for (k, v) in &data.0 {
        values.push_str(v);
        if k == "pwd" {
            parts.push(format!("{k}={}", utf8_percent_encode(v, NON_ALPHANUMERIC)));
        } else {
            parts.push(format!("{k}={v}"));
        }
    }
    let sign = md5_hex(&format!("{values}{BILI_APP_KEY}"));
    format!("{}&sign={sign}", parts.join("&"))
}

async fn post(http: &reqwest::Client, url: &str, body: String) -> Result<Value> {
    let resp = http
        .post(url)
        .header(USER_AGENT, UA)
        .header(CONTENT_TYPE, "application/x-www-form-urlencoded")
        .body(body)
        .send()
        .await?;
    Ok(resp.json().await?)
}

/// RSA PKCS#1 v1.5 加密 + Base64
fn rsa_encrypt_base64(message: &str, public_key_pem: &str) -> Result<String> {
    let key = RsaPublicKey::from_public_key_pem(public_key_pem)
        .map_err(|e| anyhow::anyhow!("解析公钥失败: {e}"))?;
    let mut rng = rand::thread_rng();
    let enc = key
        .encrypt(&mut rng, Pkcs1v15Encrypt, message.as_bytes())
        .map_err(|e| anyhow::anyhow!("RSA 加密失败: {e}"))?;
    Ok(STANDARD.encode(enc))
}

/// 对应 BSGameSDK::detail::GetEncryptedPwd
async fn encrypted_pwd(http: &reqwest::Client, password: &str) -> Result<String> {
    let mut rsa_param = Params::base();
    for k in [
        "uid",
        "pwd",
        "challenge",
        "validate",
        "seccode",
        "gt_user_id",
        "user_id",
        "captcha_type",
    ] {
        rsa_param.remove(k);
    }
    let body = set_sign(rsa_param);
    let info = post(http, BILI_RSA, body).await?;
    let public_key = info.get("rsa_key").and_then(Value::as_str).unwrap_or("");
    let hash = info.get("hash").and_then(Value::as_str).unwrap_or("");
    if public_key.is_empty() || hash.is_empty() {
        bail!("rsa 接口返回异常: {info}");
    }
    rsa_encrypt_base64(&format!("{hash}{password}"), public_key)
}

pub struct BiliLoginResult {
    pub code: i64,
    pub message: String,
    pub uid: String,
    pub access_key: String,
    pub uname: String,
}

/// 账号密码登录（可带极验 challenge/validate/gt_user_id）
pub async fn login_by_password(
    http: &reqwest::Client,
    account: &str,
    password: &str,
    gt_user: &str,
    challenge: &str,
    validate: &str,
) -> Result<BiliLoginResult> {
    let mut data = Params::base();
    data.set("access_key", "");
    data.set("gt_user_id", gt_user);
    data.set("uid", "");
    data.set("challenge", challenge);
    data.set("user_id", account);
    data.set("validate", validate);
    data.set(
        "seccode",
        if validate.is_empty() {
            String::new()
        } else {
            format!("{validate}|jordan")
        },
    );
    let pwd = encrypted_pwd(http, password).await?;
    data.set("pwd", pwd);
    data.set("captcha_type", "1");

    let info = post(http, BILI_LOGIN, set_sign(data)).await?;
    let code = info.get("code").and_then(Value::as_i64).unwrap_or(-1);
    let mut result = BiliLoginResult {
        code,
        message: info
            .get("message")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        uid: String::new(),
        access_key: String::new(),
        uname: String::new(),
    };
    if code == 0 {
        result.uid = info.get("uid").map(scalar).unwrap_or_default();
        result.access_key = info
            .get("access_key")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        if let Ok(ui) = get_user_info(http, &result.uid, &result.access_key).await {
            result.uname = ui;
        }
    }
    Ok(result)
}

/// 对应 BSGameSDK::GetUserInfo，返回昵称
pub async fn get_user_info(http: &reqwest::Client, _uid: &str, access_key: &str) -> Result<String> {
    let mut data = Params::base();
    data.set("uid", "");
    data.set("access_key", access_key);
    let info = post(http, BILI_USERINFO, set_sign(data)).await?;
    Ok(info
        .get("uname")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string())
}

/// 对应 BSGameSDK::CaptchaCaptcha，返回 (gt, challenge, gt_user_id)
pub async fn start_captcha(http: &reqwest::Client) -> Result<(String, String, String)> {
    let info = post(http, BILI_CAPTCHA, set_sign(Params::base())).await?;
    Ok((
        info.get("gt")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        info.get("challenge")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        info.get("gt_user_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
    ))
}

fn scalar(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

/// 基础域名（供上层日志展示）
pub fn base_url() -> &'static str {
    BILI_BASE
}
