use anyhow::{Context, Result};
use reqwest::header::{HeaderMap, HeaderValue};
use serde_json::json;

use crate::crypto::{
    APP_ID_GAME, APP_ID_PASSPORT, SALT_MIYAKO_APP, generate_device_fingerprint, generate_ds,
    now_secs,
};

const UA_CAPTURE: &str = "Mozilla/5.0 miHoYoBBS/2.90.1 Capture/2.2.0";

const EP_APP_CREATE_QR: &str =
    "https://passport-api.mihoyo.com/account/ma-cn-passport/app/createQRLogin";
const EP_APP_QUERY_STATUS: &str =
    "https://passport-api.mihoyo.com/account/ma-cn-passport/app/queryQRLoginStatus";
const EP_PASSPORT_SCAN_QR: &str =
    "https://passport-api.mihoyo.com/account/ma-cn-passport/app/scanQRLogin";
const EP_PASSPORT_CONFIRM_QR: &str =
    "https://passport-api.mihoyo.com/account/ma-cn-passport/app/confirmQRLogin";

pub struct MhyClient {
    http: reqwest::Client,
    pub device_id: String,
    pub device_fp: String,
}

impl MhyClient {
    pub fn new(device_id: Option<String>) -> Self {
        let device_id = device_id.unwrap_or_else(|| {
            fastrand::u64(..)
                .to_be_bytes()
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>()[..16]
                .to_uppercase()
        });
        let device_fp = generate_device_fingerprint(&device_id);
        Self {
            http: reqwest::Client::new(),
            device_id,
            device_fp,
        }
    }

    /// 连接预热：提前完成到米哈游各接口的 DNS + TLS 握手，
    /// 抢码时首包不再付建连成本（返回 404 也算建连成功）。
    pub async fn warmup(&self) {
        for url in [
            "https://passport-api.mihoyo.com/",
            "https://api-sdk.mihoyo.com/",
        ] {
            let _ = self.http.get(url).send().await;
        }
    }

    fn common_headers(
        &self,
        body: &str,
        client_type: &str,
        app_id: &str,
        cookie: &str,
    ) -> HeaderMap {
        fn add(h: &mut HeaderMap, k: &str, v: &str) {
            if let Ok(name) = reqwest::header::HeaderName::from_bytes(k.as_bytes()) {
                if let Ok(val) = HeaderValue::from_str(v) {
                    h.insert(name, val);
                }
            }
        }
        let mut h = HeaderMap::new();
        add(&mut h, "User-Agent", UA_CAPTURE);
        add(&mut h, "Accept", "*/*");
        add(&mut h, "Accept-Language", "zh-cn");
        add(&mut h, "x-rpc-client_type", client_type);
        add(&mut h, "x-rpc-app_version", "2.90.1");
        add(&mut h, "x-rpc-device_id", &self.device_id);
        add(&mut h, "x-rpc-device_fp", &self.device_fp);
        add(&mut h, "x-rpc-game_biz", "bbs_cn");
        add(&mut h, "x-rpc-app_id", app_id);
        add(&mut h, "x-rpc-sdk_version", "2.90.1");
        add(&mut h, "x-rpc-account_version", "2.90.1");
        add(&mut h, "x-rpc-device_model", "Mi 14");
        add(&mut h, "x-rpc-device_name", "Mihoyo Capture");
        add(&mut h, "DS", &generate_ds(body, "", SALT_MIYAKO_APP));
        add(&mut h, "Content-Type", "application/json");
        if !cookie.is_empty() {
            add(&mut h, "Cookie", cookie);
        }
        h
    }

    // ---- App 扫码登录 (用于新增账号) ----

    pub async fn app_create_qr(&self) -> Result<(String, String)> {
        let body = "{}";
        let headers = self.common_headers(body, "3", APP_ID_GAME, "");
        let resp: serde_json::Value = self
            .http
            .post(EP_APP_CREATE_QR)
            .headers(headers)
            .body(body.to_string())
            .send()
            .await?
            .json()
            .await?;
        if resp.get("retcode").and_then(|v| v.as_i64()) == Some(0) {
            let data = resp.get("data").cloned().unwrap_or_default();
            let url = data
                .get("url")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let ticket = data
                .get("ticket")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            Ok((url, ticket))
        } else {
            anyhow::bail!(
                "创建二维码失败: {}",
                resp.get("message").and_then(|v| v.as_str()).unwrap_or("")
            )
        }
    }

    /// 查询 App 扫码状态，返回 (retcode, status, data)
    pub async fn app_query_status(&self, ticket: &str) -> Result<(i64, String, serde_json::Value)> {
        let body = serde_json::to_string(&json!({ "ticket": ticket }))?;
        let headers = self.common_headers(&body, "3", APP_ID_GAME, "");
        let resp: serde_json::Value = self
            .http
            .post(EP_APP_QUERY_STATUS)
            .headers(headers)
            .body(body)
            .send()
            .await?
            .json()
            .await?;
        let retcode = resp.get("retcode").and_then(|v| v.as_i64()).unwrap_or(-1);
        if retcode == -3501 || retcode == -106 {
            return Ok((retcode, "Expired".into(), serde_json::Value::Null));
        }
        if retcode == 0 {
            let data = resp.get("data").cloned().unwrap_or_default();
            let status = data
                .get("status")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            return Ok((0, status, data));
        }
        Ok((retcode, String::new(), serde_json::Value::Null))
    }

    // ---- 抢码 ----

    /// 从二维码 URL 模拟手机扫码：passport 登录码直接 scan+confirm，
    /// 游戏内码先 panda_scan 换 passport_qr_url 再 scan+confirm
    pub async fn steal_qr_login(&self, qr_url: &str, stoken: &str, mid: &str) -> Result<bool> {
        if qr_url.contains("login-platform") {
            let (rc, msg) = self.passport_qr_scan(qr_url, stoken, mid, false).await?;
            println!(
                "      [scanQRLogin] 结果: {}",
                if rc == 0 {
                    "成功".into()
                } else {
                    format!("失败 ({msg})")
                }
            );
            if rc != 0 {
                return Ok(false);
            }
            tokio::time::sleep(confirm_delay()).await;
            let (rc, msg) = self.passport_qr_scan(qr_url, stoken, mid, true).await?;
            println!(
                "      [confirmQRLogin] 结果: {}",
                if rc == 0 {
                    "成功".into()
                } else {
                    format!("失败 ({msg})")
                }
            );
            return Ok(rc == 0);
        }

        let parsed = url::Url::parse(qr_url);
        let q = |k: &str| -> String {
            parsed
                .as_ref()
                .ok()
                .and_then(|u| {
                    u.query_pairs()
                        .find(|(key, _)| key == k)
                        .map(|(_, v)| v.into_owned())
                })
                .unwrap_or_default()
        };
        let ticket = q("ticket");
        let app_id: i64 = q("app_id").parse().unwrap_or(0);
        let biz = q("biz_key");

        println!(
            "      [panda_scan] 提交扫码 ticket={}... (app_id={app_id})",
            &ticket[..ticket.len().min(20)]
        );
        let (rc, pqr, msg) = self.panda_scan_qrcode(&ticket, app_id, &biz).await?;
        println!(
            "      [panda_scan] 结果: {}",
            if rc == 0 {
                "成功".into()
            } else {
                format!("失败 ({msg})")
            }
        );
        if rc != 0 || pqr.is_empty() {
            return Ok(false);
        }
        let (rc, msg) = self.passport_qr_scan(&pqr, stoken, mid, false).await?;
        println!(
            "      [scanQRLogin] 结果: {}",
            if rc == 0 {
                "成功".into()
            } else {
                format!("失败 ({msg})")
            }
        );
        if rc != 0 {
            return Ok(false);
        }
        tokio::time::sleep(std::time::Duration::from_secs(1)).await;
        let (rc, msg) = self.passport_qr_scan(&pqr, stoken, mid, true).await?;
        println!(
            "      [confirmQRLogin] 结果: {}",
            if rc == 0 {
                "成功".into()
            } else {
                format!("失败 ({msg})")
            }
        );
        Ok(rc == 0)
    }

    /// B服崩坏3 抢码：使用 B站 access_key + uid 走 Combo proto + OA 链路
    pub async fn steal_qr_login_bili(
        &self,
        qr_url: &str,
        uid: &str,
        access_key: &str,
    ) -> Result<bool> {
        let ticket = crate::bh3_bili::ticket_of(qr_url);
        if ticket.is_empty() {
            anyhow::bail!("B服二维码 URL 中未找到 ticket");
        }
        println!(
            "      [bh3_scan] 扫码校验 ticket={}...",
            &ticket[..ticket.len().min(20)]
        );
        let _ = crate::bh3_bili::scan_check(&self.http, &ticket).await;
        let ok = crate::bh3_bili::scan_confirm(&self.http, qr_url, uid, access_key).await?;
        println!(
            "      [bh3_confirm] 结果: {}",
            if ok { "成功" } else { "失败" }
        );
        Ok(ok)
    }

    pub async fn panda_scan_qrcode(
        &self,
        ticket: &str,
        app_id: i64,
        biz_key: &str,
    ) -> Result<(i64, String, String)> {
        let scan_url = match app_id {
            1 => "https://api-sdk.mihoyo.com/bh3_cn/combo/panda/qrcode/scan",
            4 => "https://api-sdk.mihoyo.com/hk4e_cn/combo/panda/qrcode/scan",
            8 => "https://api-sdk.mihoyo.com/hkrpg_cn/combo/panda/qrcode/scan",
            12 => "https://api-sdk.mihoyo.com/nap_cn/combo/panda/qrcode/scan",
            _ if !biz_key.is_empty() => {
                return self
                    .panda_scan_url(
                        &format!("https://api-sdk.mihoyo.com/{biz_key}/combo/panda/qrcode/scan"),
                        ticket,
                        app_id,
                    )
                    .await;
            }
            _ => return Ok((-1, String::new(), format!("未知 app_id={app_id}"))),
        };
        self.panda_scan_url(scan_url, ticket, app_id).await
    }

    async fn panda_scan_url(
        &self,
        url: &str,
        ticket: &str,
        app_id: i64,
    ) -> Result<(i64, String, String)> {
        let body = serde_json::to_string(&json!({
            "passport_app_id": APP_ID_PASSPORT,
            "ticket": ticket,
            "app_id": app_id,
            "device": self.device_id.to_lowercase(),
            "ts": now_secs(),
        }))?;
        let mut headers = HeaderMap::new();
        headers.insert("Content-Type", HeaderValue::from_static("application/json"));
        headers.insert("x-rpc-app_id", HeaderValue::from_static(APP_ID_PASSPORT));
        if let Ok(v) = HeaderValue::from_str(&self.device_id) {
            headers.insert("x-rpc-device_id", v);
        }
        let resp: serde_json::Value = self
            .http
            .post(url)
            .headers(headers)
            .body(body)
            .send()
            .await
            .context("panda scan 请求失败")?
            .json()
            .await?;
        let rc = resp.get("retcode").and_then(|v| v.as_i64()).unwrap_or(-1);
        if rc == 0 {
            let pqr = resp
                .pointer("/data/passport_qr_url")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            Ok((0, pqr, String::new()))
        } else {
            Ok((
                rc,
                String::new(),
                resp.get("message")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
            ))
        }
    }

    pub async fn passport_qr_scan(
        &self,
        passport_qr_url: &str,
        stoken: &str,
        mid: &str,
        confirm: bool,
    ) -> Result<(i64, String)> {
        let ticket = extract_param(passport_qr_url, "tk", "&")
            .or_else(|| extract_param(passport_qr_url, "ticket", "&"))
            .unwrap_or_default();
        let token_types = extract_param(passport_qr_url, "token_types", "#").unwrap_or_default();
        if ticket.is_empty() || token_types.is_empty() {
            return Ok((
                -1,
                format!("缺少 tk({ticket:?}) 或 token_types({token_types:?})"),
            ));
        }
        let body = serde_json::to_string(&json!({
            "ticket": ticket,
            "token_types": [token_types],
        }))?;
        let url = if confirm {
            EP_PASSPORT_CONFIRM_QR
        } else {
            EP_PASSPORT_SCAN_QR
        };
        let mut headers = HeaderMap::new();
        headers.insert("Content-Type", HeaderValue::from_static("application/json"));
        headers.insert("x-rpc-app_id", HeaderValue::from_static(APP_ID_PASSPORT));
        if let Ok(v) = HeaderValue::from_str(&self.device_id) {
            headers.insert("x-rpc-device_id", v);
        }
        if let Ok(v) = HeaderValue::from_str(&format!("stoken={stoken}; mid={mid}")) {
            headers.insert("Cookie", v);
        }
        let resp: serde_json::Value = self
            .http
            .post(url)
            .headers(headers)
            .body(body)
            .send()
            .await
            .context("passport scan 请求失败")?
            .json()
            .await?;
        Ok((
            resp.get("retcode").and_then(|v| v.as_i64()).unwrap_or(-1),
            resp.get("message")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
        ))
    }
}

/// scan 与 confirm 之间的等待，默认 250ms（可用 MHYSCAN_CONFIRM_DELAY_MS 调整）
fn confirm_delay() -> std::time::Duration {
    let ms = std::env::var("MHYSCAN_CONFIRM_DELAY_MS")
        .ok()
        .and_then(|v| v.parse::<u64>().ok())
        .unwrap_or(250);
    std::time::Duration::from_millis(ms)
}

/// 对齐 C++ getPassportQRParam：取 key= 后到 terminator 的值
fn extract_param(url: &str, key: &str, terminator: &str) -> Option<String> {
    let needle = format!("{key}=");
    let begin = url.find(&needle)? + needle.len();
    let rest = &url[begin..];
    let end = rest.find(terminator).unwrap_or(rest.len());
    Some(rest[..end].to_string())
}
