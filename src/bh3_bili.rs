//! 崩坏3 B服（BiliBili 服）抢码链路，参考 MR-LIYA/MHY_Scanner `_scan_confirm_bh3`。
//!
//! 需要 B服账号的 B站 `access_key` + `uid`：
//!   1. `granter/login/v2/login` 换取 `open_id` / `combo_token` / `combo_id`
//!   2. 取 OA 调度串
//!   3. `combo/panda/qrcode/confirm` 提交 Combo proto（raw + ext）
use anyhow::Result;
use hmac::{Hmac, KeyInit, Mac};
use serde_json::{Value, json};
use sha2::Sha256;

use crate::crypto::now_secs;

const BH3_V2_LOGIN: &str = "https://api-sdk.mihoyo.com/bh3_cn/combo/granter/login/v2/login";
const BH3_SCAN: &str = "https://api-sdk.mihoyo.com/bh3_cn/combo/panda/qrcode/scan";
const BH3_CONFIRM: &str = "https://api-sdk.mihoyo.com/bh3_cn/combo/panda/qrcode/confirm";
const BH3_OA: &str = "https://api.v6qbb.cloud/get_bh3_bilibili_oa";
const BH3_APP_KEY: &str = "0ebc517adb1b62c6b408df153331f9aa";

fn hmac_hex(key: &str, msg: &str) -> String {
    let mut mac = Hmac::<Sha256>::new_from_slice(key.as_bytes()).expect("hmac key");
    mac.update(msg.as_bytes());
    hex::encode(mac.finalize().into_bytes())
}

/// 从二维码 URL 提取 ticket
pub fn ticket_of(qr_url: &str) -> String {
    url::Url::parse(qr_url)
        .ok()
        .and_then(|u| {
            u.query_pairs()
                .find(|(k, _)| k == "ticket")
                .map(|(_, v)| v.into_owned())
        })
        .unwrap_or_default()
}

/// 换取 B服外部登录信息：(open_id, combo_token, combo_id)
pub async fn external_login(
    http: &reqwest::Client,
    uid: &str,
    access_key: &str,
) -> Result<(String, String, String)> {
    let uid_num: i64 = uid.parse().unwrap_or(0);
    let body_data = serde_json::to_string(&json!({ "access_key": access_key, "uid": uid_num }))?;
    let sign = hmac_hex(BH3_APP_KEY, &body_data);
    let body = json!({
        "device": "0000000000000000",
        "app_id": 1,
        "channel_id": 14,
        "data": body_data,
        "sign": sign,
    });
    let resp: Value = http
        .post(BH3_V2_LOGIN)
        .header("Content-Type", "application/json")
        .json(&body)
        .send()
        .await?
        .json()
        .await?;
    let retcode = resp.get("retcode").and_then(Value::as_i64).unwrap_or(-1);
    if retcode != 0 {
        anyhow::bail!("granter/login/v2 失败: {resp}");
    }
    let d = resp.get("data").cloned().unwrap_or_default();
    Ok((
        d.get("open_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        d.get("combo_token")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
        d.get("combo_id").map(scalar).unwrap_or_default(),
    ))
}

/// 崩坏3 B服 OA 调度串
pub async fn oa_string(http: &reqwest::Client) -> String {
    match http.get(BH3_OA).send().await {
        Ok(r) => r.text().await.unwrap_or_default().trim().to_string(),
        Err(_) => String::new(),
    }
}

/// 扫码校验（对齐 scanCheck）
pub async fn scan_check(http: &reqwest::Client, ticket: &str) -> bool {
    let body = json!({
        "app_id": "1",
        "device": "0000000000000000",
        "ticket": ticket,
        "ts": now_secs(),
    });
    match http
        .post(BH3_SCAN)
        .header("Content-Type", "application/json")
        .json(&body)
        .send()
        .await
    {
        Ok(r) => r.status().is_success(),
        Err(_) => false,
    }
}

/// B服扫码确认：Combo proto + OA
pub async fn scan_confirm(
    http: &reqwest::Client,
    qr_url: &str,
    uid: &str,
    access_key: &str,
) -> Result<bool> {
    let ticket = ticket_of(qr_url);
    if ticket.is_empty() {
        anyhow::bail!("二维码 URL 中未找到 ticket");
    }

    let (open_id, combo_token, combo_id) = external_login(http, uid, access_key).await?;
    let oa = oa_string(http).await;

    let raw = json!({
        "heartbeat": false,
        "open_id": open_id,
        "device_id": "0000000000000000",
        "app_id": "1",
        "channel_id": "14",
        "combo_token": combo_token,
        "asterisk_name": "",
        "combo_id": combo_id,
        "account_type": "2",
    });
    let ext = json!({
        "data": {
            "accountType": "2",
            "accountID": "",
            "c": open_id,
            "accountToken": combo_token,
            "dispatch": oa,
        }
    });
    let body = json!({
        "device": "0000000000000000",
        "app_id": 1,
        "ts": now_secs(),
        "ticket": ticket,
        "payload": {
            "proto": "Combo",
            "raw": raw.to_string(),
            "ext": ext.to_string(),
        }
    });

    let resp: Value = http
        .post(BH3_CONFIRM)
        .header("Content-Type", "application/json")
        .json(&body)
        .send()
        .await?
        .json()
        .await?;
    let retcode = resp.get("retcode").and_then(Value::as_i64).unwrap_or(-1);
    if retcode != 0 {
        println!("      [bh3_combo] confirm 返回: {resp}");
    }
    Ok(retcode == 0)
}

fn scalar(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}
