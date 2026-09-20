use std::sync::atomic::AtomicBool;
use std::time::{Duration, Instant};

use anyhow::Result;

use mhyscan_rs::accounts::AccountStore;
use mhyscan_rs::mihoyo::MhyClient;
use mhyscan_rs::telemetry::Telemetry;
use mhyscan_rs::{ScanOutcome, detect_qr_file, run_scan};

#[tokio::main]
async fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let telemetry = Telemetry::from_env();

    // [启动后上报] 补发 spool → 记录 app_start → 异步上报一次；同时启动 [定时上报]
    if let Some(t) = &telemetry {
        t.load_spool();
        t.record_env("cli");
        t.start_auto_flush();
        let startup = t.clone();
        tokio::spawn(async move {
            let _ = startup.flush().await;
        });
    }

    // [关闭前上报] Ctrl-C 时尽力上报，剩余落盘
    if let Some(t) = telemetry.clone() {
        tokio::spawn(async move {
            if tokio::signal::ctrl_c().await.is_ok() {
                t.flush_or_spool().await;
                std::process::exit(0);
            }
        });
    }

    let result = dispatch(&args, &telemetry).await;

    // [关闭前上报] 正常退出兜底
    if let Some(t) = &telemetry {
        t.flush_or_spool().await;
    }
    result
}

async fn dispatch(args: &[String], telemetry: &Option<Telemetry>) -> Result<()> {
    let Some(cmd) = args.get(1).map(String::as_str) else {
        usage();
        return Ok(());
    };

    match cmd {
        "scan" => {
            let Some(rid) = args.get(2) else {
                eprintln!("用法: mhyscan scan <RID> [--platform bili|douyin] [--timeout 秒]");
                return Ok(());
            };
            let platform = opt_value(args, "--platform").unwrap_or_else(|| "bili".into());
            let timeout = opt_value(args, "--timeout")
                .and_then(|s| s.parse().ok())
                .unwrap_or(180);
            do_scan(&platform, rid, timeout, telemetry).await
        }
        "accounts" => cmd_accounts(),
        "login" => match args.get(2).map(String::as_str) {
            None => cmd_login().await,
            Some("bili") => cmd_bili_login().await,
            Some("bili-game") => {
                let (Some(account), Some(password)) = (args.get(3), args.get(4)) else {
                    eprintln!("用法: mhyscan login bili-game <B站账号> <密码>");
                    return Ok(());
                };
                cmd_bili_game_login(account, password).await
            }
            Some(other) => {
                eprintln!("未知登录方式: {other}");
                usage();
                Ok(())
            }
        },
        "qr" => {
            let Some(path) = args.get(2) else {
                eprintln!("用法: mhyscan qr <图片路径>");
                return Ok(());
            };
            let text = detect_qr_file(path)?;
            println!("离线识别结果: {text}");
            if mhyscan_rs::qr::is_login_qr_url(&text) {
                println!(
                    "是米哈游登录二维码, ticket = {:?}",
                    mhyscan_rs::qr::extract_ticket(&text)
                );
            }
            Ok(())
        }
        "help" | "--help" | "-h" => {
            usage();
            Ok(())
        }
        other => {
            eprintln!("未知命令: {other}");
            usage();
            Ok(())
        }
    }
}

/// 取 `--flag value` 形式的值
fn opt_value(args: &[String], name: &str) -> Option<String> {
    args.iter()
        .position(|a| a == name)
        .and_then(|i| args.get(i + 1).cloned())
}

async fn do_scan(
    platform: &str,
    rid: &str,
    timeout: u64,
    telemetry: &Option<Telemetry>,
) -> Result<()> {
    let log = |s: String| println!("{s}");
    let stop = AtomicBool::new(false);
    let outcome = run_scan(
        platform,
        rid,
        Duration::from_secs(timeout),
        &stop,
        &log,
        telemetry,
    )
    .await?;
    match outcome {
        ScanOutcome::Success { ticket, account } => {
            println!("抢码成功! ticket={ticket} 账号={account}");
        }
        ScanOutcome::Detected { ticket } => {
            println!("识别到二维码但无账号可抢码, ticket={ticket}");
        }
        ScanOutcome::Stopped => println!("已停止"),
        ScanOutcome::Timeout => {
            println!("超时结束");
        }
    }
    Ok(())
}

fn usage() {
    println!(
        "mhyscan — 米哈游直播流抢码 (Rust)\n\
         \n\
         用法:\n\
           mhyscan scan <RID> [--platform bili|douyin] [--timeout 秒]\n\
               监视直播间，识别二维码并抢码\n\
         \n\
           mhyscan accounts                      列出已登录账号\n\
           mhyscan login                         米游社 App 扫码登录 (官服)\n\
           mhyscan login bili                    B站扫码登录, 保存拉流凭证\n\
           mhyscan login bili-game <账号> <密码>  B服崩坏3 账号密码登录\n\
           mhyscan qr <图片>                     离线识别二维码\n\
           mhyscan help                          显示本帮助"
    );
}

fn cmd_accounts() -> Result<()> {
    let store = AccountStore::load(AccountStore::default_path())?;
    if store.account.is_empty() {
        println!("暂无账号，请先运行 `mhyscan login`");
        return Ok(());
    }
    println!("共 {} 个账号:", store.account.len());
    for (i, a) in store.account.iter().enumerate() {
        println!(
            "  [{}] {}  uid={} mid={} 类型={}",
            i, a.name, a.uid, a.mid, a.type_
        );
    }
    Ok(())
}

async fn cmd_login() -> Result<()> {
    let client = MhyClient::new(None);
    let (url, ticket) = client.app_create_qr().await?;
    println!("请用米游社 App 扫描以下二维码链接：");
    println!("  {url}");
    println!("(ticket={ticket}) 等待扫码...");

    let deadline = Instant::now() + Duration::from_secs(300);
    let mut last = String::new();
    while Instant::now() < deadline {
        let (_, status, data) = client.app_query_status(&ticket).await?;
        if status != last && !status.is_empty() {
            println!("  状态: {status}");
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
            let uid = ui.get("aid").map(scalar_to_string).unwrap_or_default();
            let mid = ui.get("mid").map(scalar_to_string).unwrap_or_default();
            if stoken.is_empty() {
                anyhow::bail!("未取到 SToken");
            }
            let path = AccountStore::default_path();
            let mut store = AccountStore::load(&path)?;
            let name = format!("账号{uid}");
            if store.add_account(&name, &stoken, &uid, &mid, "官服") {
                store.save(&path)?;
                println!("登录成功，已保存: {name} (uid={uid})");
            } else {
                println!("账号已存在: uid={uid}");
            }
            return Ok(());
        }
        if lower == "expired" {
            anyhow::bail!("二维码已过期，请重试");
        }
        tokio::time::sleep(Duration::from_secs(3)).await;
    }
    anyhow::bail!("登录超时")
}

async fn cmd_bili_login() -> Result<()> {
    let http = reqwest::Client::new();
    let (url, auth_code) = mhyscan_rs::bili_login::get_qrcode(&http).await?;
    println!("请用 B站 App 扫描二维码登录：");
    println!("  {url}");
    println!("(auth_code={auth_code}) 等待扫码...");
    let log = |s: String| println!("{s}");
    let resp =
        mhyscan_rs::bili_login::poll_login(&http, &auth_code, Duration::from_secs(180), &log)
            .await?;
    let cookies = mhyscan_rs::bili_login::extract_cookies(&resp);
    if cookies.is_empty() {
        anyhow::bail!("未取到 cookie");
    }
    let path = mhyscan_rs::bili_login::save_cookies(&cookies)?;
    println!(
        "B站登录成功，已保存 {} 个 cookie: {}",
        cookies.len(),
        mhyscan_rs::bili_login::cookie_summary(&cookies)
    );
    println!("  文件: {}", path.display());
    Ok(())
}

async fn cmd_bili_game_login(account: &str, password: &str) -> Result<()> {
    let client = mhyscan_rs::bili_sdk_v3::BiliV3Client::new(Default::default());
    println!(
        "B服崩坏3 登录 (SDK v3)  game_id={} merchant_id={}",
        client.cfg.app_id, client.cfg.merchant_id
    );
    let r = client.login(account, password).await?;
    if r.code == 0 {
        println!("登录成功: {} uid={}", r.uname, r.uid);
        let path = AccountStore::default_path();
        let mut store = AccountStore::load(&path)?;
        let name = if r.uname.is_empty() {
            format!("B服{}", r.uid)
        } else {
            r.uname.clone()
        };
        if store.add_account(&name, &r.access_key, &r.uid, "", "B服") {
            store.save(&path)?;
            println!("已保存账号: {name} (uid={})", r.uid);
        } else {
            println!("账号已存在: uid={}", r.uid);
        }
    } else {
        println!("登录失败: code={} message={}", r.code, r.message);
    }
    Ok(())
}

fn scalar_to_string(v: &serde_json::Value) -> String {
    match v {
        serde_json::Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}
