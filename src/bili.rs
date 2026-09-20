use anyhow::{Context, Result, bail};
use reqwest::Client;
use serde_json::Value;

const UA: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";
const REFERER: &str = "https://live.bilibili.com";

/// 按「延迟最低」排序返回候选直播流地址：
///   1. HTTP-FLV + AVC（长连接逐帧，延迟最低，匹配 openh264）
///   2. HLS（ts/fmp4，仅回退；当前 Rust 侧不解码）
/// 同一档位返回多个 CDN 候选（url_info），供上层择优/容灾。
pub async fn get_candidates(room_id: &str) -> Result<Vec<String>> {
    let client = Client::new();

    let init: Value = client
        .get("https://api.live.bilibili.com/room/v1/Room/room_init")
        .query(&[("id", room_id)])
        .header("User-Agent", UA)
        .header("Referer", REFERER)
        .send()
        .await
        .context("room_init 请求失败")?
        .json()
        .await
        .context("room_init 解析失败")?;

    if init.get("code").and_then(Value::as_i64) != Some(0) {
        bail!("room_init 返回错误: {}", init);
    }
    let data = init.get("data").context("room_init 缺少 data")?;
    let live_status = data.get("live_status").and_then(Value::as_i64).unwrap_or(0);
    if live_status != 1 {
        bail!("直播间未开播 (live_status={live_status})");
    }
    let real_room = data
        .get("room_id")
        .and_then(Value::as_i64)
        .map(|v| v.to_string())
        .unwrap_or_else(|| room_id.to_string());

    let mut candidates = Vec::new();

    // HTTP-FLV + AVC (protocol=0, format=0, codec=0) —— 延迟最低
    candidates.extend(fetch_variants(&client, &real_room, "0", "0", "0").await);

    // HLS 回退 (protocol=1): fmp4 优先于 ts
    if candidates.is_empty() {
        candidates.extend(fetch_variants(&client, &real_room, "1", "2", "0").await);
        candidates.extend(fetch_variants(&client, &real_room, "1", "1", "0").await);
    }

    if candidates.is_empty() {
        bail!("未找到可用的 H.264 直播流 (可能仅 HEVC/AV1 或房间受限)");
    }
    Ok(candidates)
}

/// 单次 getRoomPlayInfo，收集指定 protocol/format/codec 下的全部 CDN 候选
async fn fetch_variants(
    client: &Client,
    room_id: &str,
    protocol: &str,
    format: &str,
    codec: &str,
) -> Vec<String> {
    let resp: Value = match client
        .get("https://api.live.bilibili.com/xlive/web-room/v2/index/getRoomPlayInfo")
        .query(&[
            ("room_id", room_id),
            ("qn", "10000"), // 原画，避免二压延迟
            ("platform", "web"),
            ("ptype", "8"),
            ("protocol", protocol),
            ("format", format),
            ("codec", codec),
            ("dolby", "5"),
        ])
        .header("User-Agent", UA)
        .header("Referer", REFERER)
        .send()
        .await
    {
        Ok(r) => match r.json().await {
            Ok(j) => j,
            Err(_) => return Vec::new(),
        },
        Err(_) => return Vec::new(),
    };

    if resp.get("code").and_then(Value::as_i64) != Some(0) {
        return Vec::new();
    }

    let mut urls = Vec::new();
    let Some(streams) = resp
        .pointer("/data/playurl_info/playurl/stream")
        .and_then(Value::as_array)
    else {
        return urls;
    };
    for stream in streams {
        let Some(formats) = stream.get("format").and_then(Value::as_array) else {
            continue;
        };
        for fmt in formats {
            let Some(codecs) = fmt.get("codec").and_then(Value::as_array) else {
                continue;
            };
            for codec in codecs {
                let base_url = codec.get("base_url").and_then(Value::as_str).unwrap_or("");
                let Some(url_info) = codec.get("url_info").and_then(Value::as_array) else {
                    continue;
                };
                for info in url_info {
                    let host = info.get("host").and_then(Value::as_str).unwrap_or("");
                    let extra = info.get("extra").and_then(Value::as_str).unwrap_or("");
                    if !base_url.is_empty() && !host.is_empty() {
                        urls.push(format!("{host}{base_url}{extra}"));
                    }
                }
            }
        }
    }
    urls
}
