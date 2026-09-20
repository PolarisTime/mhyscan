#![recursion_limit = "512"]

pub mod accounts;
pub mod bh3_bili;
pub mod bili;
pub mod bili_login;
pub mod bili_sdk;
pub mod bili_sdk_v3;
pub mod crypto;
pub mod decode;
pub mod douyin;
pub mod flv;
pub mod mihoyo;
pub mod qr;
pub mod telemetry;

use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use anyhow::{Context, Result};
use bytes::BytesMut;
use futures_util::StreamExt;

use crate::accounts::AccountStore;
use crate::decode::VideoDecoder;
use crate::flv::{FlvParser, VideoUnit};
use crate::mihoyo::MhyClient;
use crate::telemetry::Telemetry;

const UA: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";
const FRAME_SKIP: usize = 3;
const PROGRESS_INTERVAL: Duration = Duration::from_secs(1);

pub type Logger<'a> = &'a (dyn Fn(String) + Send + Sync);

#[derive(Debug, Clone)]
pub enum ScanOutcome {
    /// 抢码成功
    Success { ticket: String, account: String },
    /// 识别到二维码但没有可用账号
    Detected { ticket: String },
    /// 用户主动停止
    Stopped,
    /// 超时
    Timeout,
}

/// 获取按延迟排序的直播流候选地址（FLV 优先，多 CDN）
pub async fn resolve_stream(platform: &str, rid: &str) -> Result<Vec<String>> {
    match platform {
        "bili" | "bilibili" => bili::get_candidates(rid).await,
        "douyin" | "dy" => Ok(vec![douyin::get_flv_url(rid).await?]),
        other => anyhow::bail!("不支持的平台: {other}"),
    }
}

/// 监视直播间：拉流 → 解码 → 识别 → 用账号库抢码
pub async fn run_scan(
    platform: &str,
    rid: &str,
    timeout: Duration,
    stop: &AtomicBool,
    log: Logger<'_>,
    telemetry: &Option<Telemetry>,
) -> Result<ScanOutcome> {
    let candidates = resolve_stream(platform, rid).await?;
    log(format!("[1/3] 获取到 {} 个直播流候选", candidates.len()));

    let store = AccountStore::load(AccountStore::default_path())?;
    if store.account.is_empty() {
        log("警告: 没有已登录账号，只能识别二维码无法抢码 (先运行 login)".into());
    } else {
        log(format!("已加载 {} 个账号用于抢码", store.account.len()));
    }
    let client = MhyClient::new(None);
    log("  → 预热米哈游接口连接...".into());
    client.warmup().await; // 预热到米哈游接口的连接，降低抢码首包延迟

    // 依次尝试候选（多 CDN 容灾）；HLS 暂不支持解码，跳过
    let http = reqwest::Client::new();
    let mut opened = None;
    for url in &candidates {
        if url.contains(".m3u8") {
            log("  → 跳过 HLS(m3u8) 候选：当前仅支持 HTTP-FLV".into());
            continue;
        }
        log(format!("  → 尝试: {}...", &url[..url.len().min(88)]));
        match http
            .get(url)
            .header("User-Agent", UA)
            .header("Referer", "https://live.bilibili.com")
            .send()
            .await
        {
            Ok(r) if r.status().is_success() => {
                opened = Some(r);
                break;
            }
            Ok(r) => log(format!("     打开失败: HTTP {}", r.status())),
            Err(e) => log(format!(
                "     打开失败: {}",
                e.to_string().chars().take(60).collect::<String>()
            )),
        }
    }
    let resp = opened
        .ok_or_else(|| anyhow::anyhow!("没有可用直播流（HLS 暂不支持，或候选全部打开失败）"))?;
    log("[2/3] 直播流已连接".into());
    log("[3/3] 开始识别二维码...".into());

    let mut stream = resp.bytes_stream();
    let mut buf = BytesMut::with_capacity(1 << 20);
    let mut parser = FlvParser::new();
    let mut decoder = VideoDecoder::new()?;
    let mut units = Vec::new();

    let start = Instant::now();
    let mut last_progress = Instant::now();
    let mut bytes_read: u64 = 0;
    let mut frames: u64 = 0;
    let mut attempts: u64 = 0;
    let mut got_config = false;
    let mut result = ScanOutcome::Timeout;

    'outer: while let Some(chunk) = stream.next().await {
        if stop.load(Ordering::Relaxed) {
            log("已停止".into());
            result = ScanOutcome::Stopped;
            break;
        }
        let chunk = chunk.context("读取直播流失败")?;
        bytes_read += chunk.len() as u64;
        buf.extend_from_slice(&chunk);

        units.clear();
        parser.push(&mut buf, &mut units)?;

        for unit in &units {
            if let VideoUnit::Config(_) = unit {
                got_config = true;
            }
            let Ok(Some((luma, w, h))) = decoder.feed(unit) else {
                continue;
            };
            frames += 1;
            if frames as usize % FRAME_SKIP != 0 {
                continue;
            }
            attempts += 1;
            let Some(text) = qr::detect_qr(luma, w, h) else {
                continue;
            };
            if !qr::is_login_qr_url(&text) {
                continue;
            }
            let elapsed = start.elapsed();
            log(format!("\n识别到登录二维码! {text}"));
            log(format!(
                "  耗时 {:.1}s | 帧 {frames} | 识别 {attempts}",
                elapsed.as_secs_f64()
            ));

            if store.account.is_empty() {
                if let Some(t) = telemetry {
                    t.record_scan_result(
                        platform,
                        false,
                        attempts as u32,
                        elapsed.as_millis() as u64,
                    );
                }
                result = ScanOutcome::Detected {
                    ticket: qr::extract_ticket(&text).unwrap_or_default(),
                };
                break 'outer;
            }

            // 单账号抢码：优先上次使用的账号，否则第一个
            let acc = store
                .account
                .get(store.last_account)
                .or_else(|| store.account.first())
                .expect("账号列表非空");
            log(format!(
                "  → 使用账号 {} (uid={}, {})",
                acc.name, acc.uid, acc.type_
            ));
            let is_bili = acc.type_.contains("B服");
            let res = if is_bili {
                client
                    .steal_qr_login_bili(&text, &acc.uid, &acc.access_key)
                    .await
            } else {
                client
                    .steal_qr_login(&text, &acc.access_key, &acc.mid)
                    .await
            };
            let mut success_account = None;
            match res {
                Ok(true) => success_account = Some(acc.name.clone()),
                Ok(false) => {}
                Err(e) => log(format!("  → 账号 {} 出错: {e}", acc.name)),
            }
            if let Some(t) = telemetry {
                t.record_scan_result(
                    platform,
                    success_account.is_some(),
                    attempts as u32,
                    elapsed.as_millis() as u64,
                );
            }
            if let Some(account) = success_account {
                result = ScanOutcome::Success {
                    ticket: qr::extract_ticket(&text).unwrap_or_default(),
                    account,
                };
                break 'outer;
            }
            log("  抢码失败，继续监视...".into());
        }

        let now = Instant::now();
        if now.duration_since(last_progress) >= PROGRESS_INTERVAL {
            let elapsed = now.duration_since(start);
            let mib = bytes_read as f64 / 1024.0 / 1024.0;
            log(format!(
                "等待 {:.0}s · 流量 {mib:.1}MB · 帧 {frames} · 识别 {attempts} · 内存 {:.0}MB",
                elapsed.as_secs_f64(),
                rss_mb()
            ));
            last_progress = now;
            if elapsed > timeout {
                log("超时未识别到二维码".into());
                result = ScanOutcome::Timeout;
                break;
            }
        }
    }

    Ok(result)
}

pub fn rss_mb() -> f64 {
    memory_stats::memory_stats()
        .map(|s| s.physical_mem as f64 / 1024.0 / 1024.0)
        .unwrap_or(0.0)
}

/// 把文本渲染成二维码 PNG（灰度），供 GUI 展示登录二维码
pub fn qr_png(text: &str) -> anyhow::Result<Vec<u8>> {
    use std::io::Write;

    let code = qrcode::QrCode::new(text.as_bytes())?;
    let colors = code.to_colors();
    let modules = code.width() as usize;
    let scale = 6usize;
    let quiet = 4usize;
    let size = (modules + quiet * 2) * scale;

    let mut raw = vec![0u8; (size + 1) * size];
    for y in 0..size {
        raw[y * (size + 1)] = 0; // filter type
        for x in 0..size {
            let mx = x / scale;
            let my = y / scale;
            let dark = if mx < quiet || my < quiet || mx >= quiet + modules || my >= quiet + modules {
                false
            } else {
                matches!(
                    colors[(my - quiet) * modules + (mx - quiet)],
                    qrcode::types::Color::Dark
                )
            };
            raw[y * (size + 1) + 1 + x] = if dark { 0 } else { 255 };
        }
    }

    let mut enc = flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default());
    enc.write_all(&raw)?;
    let idat = enc.finish()?;

    let mut out = Vec::new();
    out.extend_from_slice(&[0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a]);
    let mut ihdr = Vec::new();
    ihdr.extend_from_slice(&(size as u32).to_be_bytes());
    ihdr.extend_from_slice(&(size as u32).to_be_bytes());
    ihdr.extend_from_slice(&[8, 0, 0, 0, 0]); // 8-bit 灰度
    chunk(&mut out, b"IHDR", &ihdr);
    chunk(&mut out, b"IDAT", &idat);
    chunk(&mut out, b"IEND", &[]);
    Ok(out)
}

fn chunk(out: &mut Vec<u8>, tag: &[u8; 4], data: &[u8]) {
    out.extend_from_slice(&(data.len() as u32).to_be_bytes());
    out.extend_from_slice(tag);
    out.extend_from_slice(data);
    let mut crc_input = Vec::with_capacity(4 + data.len());
    crc_input.extend_from_slice(tag);
    crc_input.extend_from_slice(data);
    out.extend_from_slice(&crc32fast::hash(&crc_input).to_be_bytes());
}

/// 离线识别二维码图片
pub fn detect_qr_file(path: &str) -> Result<String> {
    let result = rxing::helpers::detect_in_file(path, Some(rxing::BarcodeFormat::QR_CODE))
        .map_err(|e| anyhow::anyhow!("{e}"))?;
    Ok(result.getText().to_string())
}
