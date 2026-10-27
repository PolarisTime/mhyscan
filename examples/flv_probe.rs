//! 诊断：拉抖音 FLV，逐候选统计解码成功/失败（调试用）
use std::time::Duration;
use bytes::BytesMut;
use futures_util::StreamExt;
use mhyscan_rs::decode::VideoDecoder;
use mhyscan_rs::flv::{FlvParser, VideoUnit};

#[tokio::main]
async fn main() {
    let rid = std::env::args().nth(1).unwrap_or_else(|| "douyin:971429369656".into());
    let idx: usize = std::env::args().nth(2).and_then(|v| v.parse().ok()).unwrap_or(0);
    let urls = if let Some(b) = rid.strip_prefix("bili:") {
        mhyscan_rs::bili::get_candidates(b).await.expect("resolve bili")
    } else {
        let d = rid.strip_prefix("douyin:").unwrap_or(&rid);
        mhyscan_rs::douyin::get_candidates(d).await.expect("resolve douyin")
    };
    println!("candidates: {}", urls.len());
    let http = reqwest::Client::new();

    let is_bili = rid.starts_with("bili:");
    let mut resp = None;
    if let Some(u) = urls.get(idx) {
        let req = if is_bili {
            http.get(u).header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36").header("Referer", "https://live.bilibili.com")
        } else {
            http.get(u).header("User-Agent", mhyscan_rs::douyin::UA).header("Referer", mhyscan_rs::douyin::REFERER)
        };
        if let Ok(r) = req.send().await {
            if r.status().is_success() {
                println!("open[{idx}]: {}", &u[..u.len().min(100)]);
                resp = Some(r);
            }
        }
    }
    let mut stream = resp.expect("no stream").bytes_stream();
    let mut parser = FlvParser::new();
    let mut dec = VideoDecoder::new().unwrap();
    let mut buf = BytesMut::with_capacity(1 << 20);
    let mut units = Vec::new();
    let (mut ok, mut none, mut err) = (0u64, 0u64, 0u64);
    let mut first_err = String::new();
    let deadline = tokio::time::Instant::now() + Duration::from_secs(12);
    while tokio::time::Instant::now() < deadline {
        let Some(Ok(chunk)) = tokio::time::timeout(Duration::from_secs(3), stream.next()).await.ok().flatten() else { break };
        buf.extend_from_slice(&chunk);
        units.clear();
        if parser.push(&mut buf, &mut units).is_err() { println!("parse error"); break; }
        for u in &units {
            if let VideoUnit::Nalu(n) = u {
                // 提取 Annex-B 起始码后的 NAL 类型序列
                let types: Vec<u8> = n
                    .windows(4)
                    .enumerate()
                    .filter(|(_, w)| w == &[0, 0, 0, 1])
                    .filter_map(|(i, _)| n.get(i + 4).map(|b| b & 0x1f))
                    .collect();
                let show = ok + err + none < 40;
                let r = match dec.feed(u) {
                    Ok(Some((luma, w, h))) => { ok += 1; if show { println!("  unit#{:<4} nals={:?} len={} -> frame {w}x{h} luma={}", ok+err+none, types, n.len(), luma.len()); } format!("ok") }
                    Ok(None) => { none += 1; if show { println!("  unit#{:<4} nals={:?} len={} -> none", ok+err+none, types, n.len()); } "none".into() }
                    Err(e) => { err += 1; if first_err.is_empty() { first_err = format!("{e}"); } if show { println!("  unit#{:<4} nals={:?} len={} -> ERR", ok+err+none, types, n.len()); } "err".into() }
                };
                let _ = r;
                continue;
            }
            match dec.feed(u) {
                Ok(Some((luma, w, h))) => { ok += 1; if ok <= 3 { println!("frame {ok}: {w}x{h} luma={}", luma.len()); } }
                Ok(None) => none += 1,
                Err(e) => { err += 1; if first_err.is_empty() { first_err = format!("{e}"); } }
            }
        }
    }
    println!("units_decoded_ok={ok} none={none} err={err}");
    if !first_err.is_empty() { println!("first_err={first_err}"); }
}
