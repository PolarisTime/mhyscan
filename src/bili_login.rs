//! B站 TV 端二维码登录（保存拉流 cookie），对应 Python `bili_login.py` / biliup。
use std::path::PathBuf;

use anyhow::{Result, bail};
use reqwest::header::{CONTENT_TYPE, USER_AGENT};
use serde_json::Value;

use crate::crypto::{md5_hex, now_secs};

const APPKEY: &str = "4409e2ce8ffd12b8";
const APPSEC: &str = "59b43e04ad6965f34319062b478f83dd";
const UA: &str =
    "Mozilla/5.0 (X11; Linux x86_64; rv:38.0) Gecko/20100101 Firefox/38.0 Iceweasel/38.2.1 BiliApp";
const API_AUTH_CODE: &str = "https://passport.bilibili.com/x/passport-tv-login/qrcode/auth_code";
const API_POLL: &str = "https://passport.bilibili.com/x/passport-tv-login/qrcode/poll";

fn form_encode(pairs: &[(&str, &str)]) -> String {
    let mut s = url::form_urlencoded::Serializer::new(String::new());
    for (k, v) in pairs {
        s.append_pair(k, v);
    }
    s.finish()
}

/// MD5(urlencoded_params + appsec)
fn sign(form: &str) -> String {
    md5_hex(&format!("{form}{APPSEC}"))
}

/// 获取登录二维码，返回 (qrcode_url, auth_code)
pub async fn get_qrcode(http: &reqwest::Client) -> Result<(String, String)> {
    let ts = now_secs().to_string();
    let base = form_encode(&[("appkey", APPKEY), ("local_id", "0"), ("ts", &ts)]);
    let body = format!("{base}&sign={}", sign(&base));

    let resp: Value = http
        .post(API_AUTH_CODE)
        .header(USER_AGENT, UA)
        .header(CONTENT_TYPE, "application/x-www-form-urlencoded")
        .body(body)
        .send()
        .await?
        .json()
        .await?;

    if resp.get("code").and_then(Value::as_i64) != Some(0) {
        bail!(
            "获取二维码失败: {} {}",
            resp.get("code").and_then(Value::as_i64).unwrap_or(-1),
            resp.get("message").and_then(Value::as_str).unwrap_or("")
        );
    }
    let data = resp.get("data").cloned().unwrap_or_default();
    let url = data
        .get("url")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let auth_code = data
        .get("auth_code")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    if url.is_empty() || auth_code.is_empty() {
        bail!("二维码数据不完整: {data}");
    }
    Ok((url, auth_code))
}

/// 轮询扫码状态，成功返回完整响应（含 data.cookie_info）
pub async fn poll_login(
    http: &reqwest::Client,
    auth_code: &str,
    timeout: std::time::Duration,
    log: &(dyn Fn(String) + Send + Sync),
) -> Result<Value> {
    let deadline = std::time::Instant::now() + timeout;
    let mut last_code: i64 = -999;
    while std::time::Instant::now() < deadline {
        let ts = now_secs().to_string();
        let base = form_encode(&[
            ("appkey", APPKEY),
            ("auth_code", auth_code),
            ("local_id", "0"),
            ("ts", &ts),
        ]);
        let body = format!("{base}&sign={}", sign(&base));
        let resp = http
            .post(API_POLL)
            .header(USER_AGENT, UA)
            .header(CONTENT_TYPE, "application/x-www-form-urlencoded")
            .body(body)
            .send()
            .await;
        let j: Value = match resp {
            Ok(r) => match r.json().await {
                Ok(v) => v,
                Err(_) => {
                    tokio::time::sleep(std::time::Duration::from_secs(2)).await;
                    continue;
                }
            },
            Err(_) => {
                tokio::time::sleep(std::time::Duration::from_secs(2)).await;
                continue;
            }
        };
        let code = j.get("code").and_then(Value::as_i64).unwrap_or(-1);
        if code != last_code {
            let msg = match code {
                -4 => "二维码未扫描",
                -5 => "已扫描，等待确认",
                86039 => "已扫描，等待确认",
                86038 => "二维码已失效",
                0 => "登录成功",
                _ => "",
            };
            if !msg.is_empty() {
                log(format!("  扫码状态: {msg} (code={code})"));
            }
            last_code = code;
        }
        if code == 0 && j.get("data").and_then(|d| d.get("cookie_info")).is_some() {
            return Ok(j);
        }
        if code == 86038 {
            bail!("二维码已失效，请重试");
        }
        tokio::time::sleep(std::time::Duration::from_millis(1500)).await;
    }
    bail!("扫码登录超时")
}

/// 从登录响应提取 cookie 列表 [{name,value}]
pub fn extract_cookies(login_response: &Value) -> Vec<Value> {
    login_response
        .get("data")
        .and_then(|d| d.get("cookie_info"))
        .and_then(|c| c.get("cookies"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
}

fn cookie_path() -> PathBuf {
    if let Ok(p) = std::env::var("MHYSCAN_CONFIG") {
        if let Some(dir) = PathBuf::from(p).parent() {
            return dir.join("bili_cookie.json");
        }
    }
    PathBuf::from("Config/bili_cookie.json")
}

/// 保存 cookie（biliup 格式，供拉流复用）
pub fn save_cookies(cookies: &[Value]) -> Result<PathBuf> {
    let path = cookie_path();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let data = serde_json::json!({ "cookie_info": { "cookies": cookies } });
    std::fs::write(&path, serde_json::to_string_pretty(&data)?)?;
    Ok(path)
}

pub fn cookie_summary(cookies: &[Value]) -> String {
    let names: Vec<&str> = cookies
        .iter()
        .filter_map(|c| c.get("name").and_then(Value::as_str))
        .collect();
    if names.is_empty() {
        "(空)".into()
    } else {
        names.join(", ")
    }
}
