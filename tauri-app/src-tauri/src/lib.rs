use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use mhyscan_rs::accounts::AccountStore;
use mhyscan_rs::mihoyo::MhyClient;
use mhyscan_rs::telemetry::Telemetry;
use mhyscan_rs::{ScanOutcome, run_scan};
use serde::Serialize;
use tauri::{AppHandle, Emitter, State};

#[derive(Default)]
struct AppState {
    scanning: Mutex<Option<Arc<AtomicBool>>>,
}

#[derive(Serialize)]
struct AccountView {
    name: String,
    uid: String,
    mid: String,
    r#type: String,
}

#[tauri::command]
fn list_accounts() -> Result<Vec<AccountView>, String> {
    let store = AccountStore::load(AccountStore::default_path()).map_err(|e| e.to_string())?;
    Ok(store
        .account
        .into_iter()
        .map(|a| AccountView {
            name: a.name,
            uid: a.uid,
            mid: a.mid,
            r#type: a.type_,
        })
        .collect())
}

#[tauri::command]
async fn start_login(app: AppHandle) -> Result<String, String> {
    let client = MhyClient::new(None);
    let (url, ticket) = client.app_create_qr().await.map_err(|e| e.to_string())?;

    // 生成二维码 PNG，返回 data URL 供界面 <img> 显示
    let png = mhyscan_rs::qr_png(&url).map_err(|e| e.to_string())?;
    use base64::Engine as _;
    let b64 = base64::engine::general_purpose::STANDARD.encode(&png);
    let data_url = format!("data:image/png;base64,{b64}");
    let _ = app.emit("login-qr", &data_url);
    let _ = app.emit("login-qr-text", &url);

    let deadline = Instant::now() + Duration::from_secs(300);
    let mut last = String::new();
    while Instant::now() < deadline {
        let (_, status, data) = client
            .app_query_status(&ticket)
            .await
            .map_err(|e| e.to_string())?;
        if status != last && !status.is_empty() {
            let _ = app.emit("login-status", &status);
            last = status.clone();
        }
        let lower = status.to_lowercase();
        if lower == "confirmed" {
            let stoken = data
                .get("tokens")
                .and_then(|v| v.as_array())
                .and_then(|arr| {
                    arr.iter()
                        .find(|t| t.get("token_type").and_then(|v| v.as_i64()) == Some(1))
                })
                .and_then(|t| t.get("token"))
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let ui = data.get("user_info").cloned().unwrap_or_default();
            let uid = scalar(&ui, "aid");
            let mid = scalar(&ui, "mid");
            if stoken.is_empty() {
                return Err("未取到 SToken".into());
            }
            let path = AccountStore::default_path();
            let mut store = AccountStore::load(&path).map_err(|e| e.to_string())?;
            let name = format!("账号{uid}");
            let added = store.add_account(&name, &stoken, &uid, &mid, "官服");
            store.save(&path).map_err(|e| e.to_string())?;
            let _ = app.emit("login-done", &name);
            return Ok(if added { name } else { format!("{name} (已存在)") });
        }
        if lower == "expired" {
            return Err("二维码已过期".into());
        }
        tokio::time::sleep(Duration::from_secs(3)).await;
    }
    Err("登录超时".into())
}

/// B站扫码登录，保存拉流凭证（返回二维码 PNG data URL）
#[tauri::command]
async fn start_bili_login(app: AppHandle) -> Result<String, String> {
    let http = reqwest::Client::new();
    let (url, auth_code) = mhyscan_rs::bili_login::get_qrcode(&http)
        .await
        .map_err(|e| e.to_string())?;

    let png = mhyscan_rs::qr_png(&url).map_err(|e| e.to_string())?;
    use base64::Engine as _;
    let b64 = base64::engine::general_purpose::STANDARD.encode(&png);
    let data_url = format!("data:image/png;base64,{b64}");
    let _ = app.emit("login-qr", &data_url);
    let _ = app.emit("login-qr-text", &url);

    let app_for_log = app.clone();
    let log = move |s: String| {
        let _ = app_for_log.emit("login-status", s);
    };
    let resp = mhyscan_rs::bili_login::poll_login(&http, &auth_code, Duration::from_secs(180), &log)
        .await
        .map_err(|e| e.to_string())?;
    let cookies = mhyscan_rs::bili_login::extract_cookies(&resp);
    if cookies.is_empty() {
        return Err("未取到 cookie".into());
    }
    let path = mhyscan_rs::bili_login::save_cookies(&cookies).map_err(|e| e.to_string())?;
    let msg = format!("已保存 {} 个 cookie", cookies.len());
    let _ = app.emit("login-done", &msg);
    let _ = path;
    Ok(msg)
}

fn scalar(v: &serde_json::Value, key: &str) -> String {
    match v.get(key) {
        Some(serde_json::Value::String(s)) => s.clone(),
        Some(other) => other.to_string(),
        None => String::new(),
    }
}

#[tauri::command]
async fn scan(
    app: AppHandle,
    state: State<'_, AppState>,
    platform: String,
    rid: String,
    timeout: u64,
) -> Result<String, String> {
    let stop = Arc::new(AtomicBool::new(false));
    *state.scanning.lock().unwrap() = Some(stop.clone());

    let telemetry = Telemetry::from_env();
    let app_for_log = app.clone();
    let log = move |s: String| {
        let _ = app_for_log.emit("scan-log", s);
    };

    let outcome = run_scan(
        &platform,
        &rid,
        Duration::from_secs(timeout),
        &stop,
        &log,
        &telemetry,
    )
    .await
    .map_err(|e| e.to_string());

    *state.scanning.lock().unwrap() = None;

    let result = match outcome? {
        ScanOutcome::Success { ticket, account } => format!("抢码成功: {account} ({ticket})"),
        ScanOutcome::Detected { ticket } => format!("识别到二维码但无账号: {ticket}"),
        ScanOutcome::Stopped => "已停止".to_string(),
        ScanOutcome::Timeout => "超时结束".to_string(),
    };
    let _ = app.emit("scan-done", &result);
    Ok(result)
}

#[tauri::command]
fn stop_scan(state: State<'_, AppState>) {
    if let Some(flag) = state.scanning.lock().unwrap().as_ref() {
        flag.store(true, Ordering::Relaxed);
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![
            list_accounts,
            start_login,
            start_bili_login,
            scan,
            stop_scan
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
