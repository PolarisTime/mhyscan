//! 抖音直播拉流地址解析。
//!
//! 抖音没有公开的「取流」接口，网页端 `live.douyin.com/webcast/room/web/enter/`
//! 需要登录态 cookie。cookie 为易失凭证：内置值过期后请求会返回非 0 的
//! `status_code`，此时可用环境变量 `MHYSCAN_DOUYIN_COOKIE` 或文件
//! `Config/douyin_cookie.txt` 覆盖（内容就是浏览器里复制出来的 Cookie 头）。
use anyhow::{Result, bail};
use reqwest::Client;
use serde_json::Value;

pub const UA: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
(KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36";
pub const REFERER: &str = "https://live.douyin.com/";

const DEFAULT_COOKIE: &str = "enter_pc_once=1; UIFID_TEMP=29a1f63ec682dc0a0df227dd163e2b46e3a6390e403335fa4c2c6d1dc0ec5ffa7a288170e8828ecb8b2f0f16b3219daa18ad5d7faf7fb5fbb64df454c3b471cc1db9c0b5eb2cbc8e0cb1e690f5c1fbd6; \
stream_recommend_feed_params=%22%7B%5C%22cookie_enabled%5C%22%3Atrue%2C%5C%22screen_width%5C%22%3A2560%2C%5C%22screen_height%5C%22%3A1440%2C%5C%22browser_online%5C%22%3Atrue%2C%5C%22cpu_core_num%5C%22%3A16%2C%5C%22device_memory%5C%22%3A8%2C%5C%22downlink%5C%22%3A10%2C%5C%22effective_type%5C%22%3A%5C%224g%5C%22%2C%5C%22round_trip_time%5C%22%3A50%7D%22; \
hevc_supported=true; odin_tt=363047b47492a2e153d67e7022684ffd83726a0c57322991e6650da1dbe2fc0adb471e8be38efa85bf0ab9788a8e237d481c8fc488ef859f4476fc6ffd50dd31a258add2954b3fcf03cd546357df6a53; \
strategyABtestKey=%221772897157.15%22; passport_csrf_token=d71952d93315e4df5cc8373e4cdc2447; passport_csrf_token_default=d71952d93315e4df5cc8373e4cdc2447; \
home_can_add_dy_2_desktop=%221%22; biz_trace_id=fab9d888; \
ttwid=1%7CP0feYUzzIsbXr2aaLLBWHYtwVD4-6CV2voO9bAUQ7PU%7C1772897161%7Cd72bed8f6f576a1dfb7b8d1032c76706ce93b3ba3ac5b21e79501db1c2f17c9f; \
__security_mc_1_s_sdk_crypt_sdk=0ef27763-40a0-b3c3; \
is_dash_user=1; x-web-secsdk-uid=17063330-58d4-4719-9971-dba52fc661ab; \
__live_version__=%221.1.4.9549%22; has_avx2=null; device_web_cpu_core=16; device_web_memory_size=8; \
webcast_local_quality=null; live_use_vvc=%22false%22; csrf_session_id=5fe8f9d1180e55817920dae0808993ba; \
h265ErrorNum=-1; IsDouyinActive=false; live_can_add_dy_2_desktop=%220%22";

/// cookie 优先级：环境变量 > Config/douyin_cookie.txt > 内置快照
fn cookie() -> String {
    if let Ok(c) = std::env::var("MHYSCAN_DOUYIN_COOKIE") {
        if !c.trim().is_empty() {
            return c.trim().to_string();
        }
    }
    if let Ok(c) = std::fs::read_to_string(cookie_path()) {
        let c = c.trim();
        if !c.is_empty() {
            return c.to_string();
        }
    }
    DEFAULT_COOKIE.to_string()
}

/// 自定义 cookie 文件路径
pub fn cookie_path() -> std::path::PathBuf {
    std::path::PathBuf::from("Config/douyin_cookie.txt")
}

fn count_pairs(text: &str) -> usize {
    text.split(';')
        .filter(|p| p.trim().contains('='))
        .count()
}

/// 当前生效的 cookie 来源与条数
pub fn cookie_info() -> (String, usize) {
    if let Ok(c) = std::env::var("MHYSCAN_DOUYIN_COOKIE") {
        let c = c.trim();
        if !c.is_empty() {
            return ("环境变量".to_string(), count_pairs(c));
        }
    }
    if let Ok(c) = std::fs::read_to_string(cookie_path()) {
        let c = c.trim();
        if !c.is_empty() {
            return ("自定义".to_string(), count_pairs(c));
        }
    }
    ("内置快照".to_string(), count_pairs(DEFAULT_COOKIE))
}

/// 保存用户粘贴的 cookie（形如 `a=1; b=2`）
pub fn save_cookie(text: &str) -> Result<usize> {
    let text = text.trim();
    if text.is_empty() {
        bail!("cookie 不能为空");
    }
    if !text.contains('=') {
        bail!("格式不对：应形如 `name=value; name2=value2`");
    }
    let n = count_pairs(text);
    if n == 0 {
        bail!("没有解析到任何 cookie 项");
    }
    let path = cookie_path();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(&path, text)?;
    Ok(n)
}

/// 删除自定义 cookie，回退到内置快照
pub fn clear_cookie() -> Result<()> {
    let path = cookie_path();
    if path.exists() {
        std::fs::remove_file(&path)?;
    }
    Ok(())
}

/// 抖音直播间 FLV 候选（按「原画优先 + 多 CDN 容灾」排序）。
///
/// 入参是 `web_rid`（`live.douyin.com/<web_rid>` 里的那串），不是 B 站式房间号。
pub async fn get_candidates(room_id: &str) -> Result<Vec<String>> {
    match api_candidates(room_id).await {
        Ok(urls) if !urls.is_empty() => Ok(urls),
        Ok(_) => page_candidates(room_id).await,
        Err(api_err) => match page_candidates(room_id).await {
            Ok(urls) if !urls.is_empty() => Ok(urls),
            Ok(_) => Err(api_err),
            Err(_) => Err(api_err),
        },
    }
}

/// 页面兜底：直播间 HTML 里内嵌了 `stream_url.flv_pull_url`，无需签名/cookie
pub async fn page_candidates(room_id: &str) -> Result<Vec<String>> {
    let client = Client::new();
    let url = format!("https://live.douyin.com/{room_id}");
    let html = client
        .get(&url)
        .header("User-Agent", UA)
        .header("referer", REFERER)
        .send()
        .await?
        .text()
        .await?;
    let urls = extract_page_urls(&html);
    if urls.is_empty() {
        bail!("页面兜底未找到直播流地址（可能未开播或页面改版）");
    }
    Ok(urls)
}

/// 从直播间页面 HTML 提取 flv/hls 地址（优先原画）
fn extract_page_urls(html: &str) -> Vec<String> {
    // 页面里的 JSON 被转义过：\" 和 \u0026
    let normalized = html
        .replace("\\u0026", "&")
        .replace("\\/", "/")
        .replace("\\\"", "\"");

    let mut out: Vec<String> = Vec::new();
    for key in ["flv_pull_url", "hls_pull_url_map"] {
        let Some(pos) = normalized.find(&format!("\"{key}\"")) else {
            continue;
        };
        let rest = &normalized[pos..];
        let Some(open) = rest.find('{') else { continue };
        let Some(close) = rest[open..].find('}') else { continue };
        let body = &rest[open + 1..open + close];
        // 形如 "FULL_HD1":"http://...","HD1":"http://..."
        for ent in body.split("\",\"") {
            let ent = ent.trim_matches('"');
            if let Some((_k, v)) = ent.split_once("\":\"") {
                let v = v.trim_end_matches('"').trim();
                if v.starts_with("http") && !out.iter().any(|u| u == v) {
                    out.push(v.to_string());
                }
            }
        }
        if !out.is_empty() {
            break;
        }
    }
    out
}

async fn api_candidates(room_id: &str) -> Result<Vec<String>> {
    let client = Client::new();
    let params = format!(
        "aid=6383&app_name=douyin_web&live_id=1&device_platform=web&\
         browser_language=zh-CN&browser_platform=Win32&browser_name=Edge&\
         browser_version=139.0.0.0&is_need_double_stream=false&web_rid={room_id}&cookie_enabled=true"
    );
    // 抖音 web 接口需要 a_bogus 签名（未签名时返回 200 空 body）
    let fp = crate::douyin_abogus::BrowserFingerprintGenerator::generate_fingerprint("Edge");
    let mut signer = crate::douyin_abogus::ABogus::new(Some(&fp), Some(UA), None);
    let (signed_params, _a_bogus, _ua, _body) = signer.generate_abogus(&params, "");
    let url = format!("https://live.douyin.com/webcast/room/web/enter/?{signed_params}");
    let resp: Value = client
        .get(&url)
        .header("User-Agent", UA)
        .header("referer", REFERER)
        .header("cookie", cookie())
        .send()
        .await?
        .json()
        .await?;

    let status_code = resp.get("status_code").and_then(Value::as_i64);
    if status_code != Some(0) {
        bail!(
            "抖音接口返回错误: status_code={status_code:?}；若持续失败，cookie 可能已失效，\
             可用环境变量 MHYSCAN_DOUYIN_COOKIE 或 Config/douyin_cookie.txt 覆盖"
        );
    }
    let data = room_data(&resp).ok_or_else(|| anyhow::anyhow!("缺少直播间数据"))?;
    let status = data.get("status").and_then(Value::as_i64).unwrap_or(-1);
    match status {
        2 => {}
        4 => bail!("直播间未开播"),
        _ => bail!("直播间状态异常: status={status}"),
    }

    let urls = extract_stream_urls(data);
    if urls.is_empty() {
        bail!("未找到抖音可用的 FLV/HLS 流地址（可能未开播、cookie 失效或被风控拦截）");
    }
    Ok(urls)
}

/// 兼容旧调用：返回第一个（原画）地址
pub async fn get_flv_url(room_id: &str) -> Result<String> {
    let mut urls = get_candidates(room_id).await?;
    Ok(urls.remove(0))
}

/// 从直播间数据里收集全部 FLV 地址：优先 `origin/main/flv`，再收其它 CDN/清晰度。
/// 兼容 webcast/room/web/enter（data.data[0]）与 reflow（data.room）两种返回
fn room_data(resp: &Value) -> Option<&Value> {
    resp.pointer("/data/data/0")
        .or_else(|| resp.pointer("/data/room"))
}

fn extract_stream_urls(data: &Value) -> Vec<String> {
    let mut out = Vec::new();
    let Some(stream_url) = data.get("stream_url") else {
        return out;
    };

    // 主流形状：flv_pull_url / hls_pull_url_map（清晰度 → 地址）
    if let Some(map) = stream_url.get("flv_pull_url").and_then(Value::as_object) {
        let default = stream_url
            .get("default_resolution")
            .and_then(Value::as_str)
            .unwrap_or("FULL_HD1");
        for quality in quality_order(default) {
            if let Some(Value::String(u)) = map.get(quality) {
                push_unique(&mut out, u);
            }
        }
        for v in map.values() {
            if let Some(u) = v.as_str() {
                push_unique(&mut out, u);
            }
        }
    }
    // HLS 回退（引擎已支持 HLS(TS) 分片）
    if out.is_empty() {
        if let Some(map) = stream_url.get("hls_pull_url_map").and_then(Value::as_object) {
            let default = stream_url
                .get("default_resolution")
                .and_then(Value::as_str)
                .unwrap_or("FULL_HD1");
            for quality in quality_order(default) {
                if let Some(Value::String(u)) = map.get(quality) {
                    push_unique(&mut out, u);
                }
            }
            for v in map.values() {
                if let Some(u) = v.as_str() {
                    push_unique(&mut out, u);
                }
            }
        }
    }

    // 新版：pull_datas.<quality>.stream_data（JSON 字符串）
    if let Some(map) = stream_url.get("pull_datas").and_then(Value::as_object) {
        if let Some(origin) = map.get("origin").and_then(|v| v.get("stream_data")).and_then(Value::as_str) {
            if let Ok(parsed) = serde_json::from_str::<Value>(origin) {
                push_main_flv(&parsed, &mut out);
                collect_flv(&parsed, &mut out);
            }
        }
        for v in map.values() {
            if let Some(sd) = v.get("stream_data").and_then(Value::as_str) {
                if let Ok(parsed) = serde_json::from_str::<Value>(sd) {
                    collect_flv(&parsed, &mut out);
                }
            }
        }
    }

    // 旧版：live_core_sdk_data.pull_data.stream_data
    if let Some(sd) = stream_url
        .pointer("/live_core_sdk_data/pull_data/stream_data")
        .and_then(Value::as_str)
    {
        if let Ok(parsed) = serde_json::from_str::<Value>(sd) {
            push_main_flv(&parsed, &mut out);
            collect_flv(&parsed, &mut out);
        }
    }

    out
}

/// 原画优先，其次高清/标清（default_resolution 最优先）
fn quality_order(default: &str) -> Vec<&str> {
    let mut order = vec![default, "FULL_HD1", "HD1", "SD2", "SD1", "LD1", "LD2"];
    order.dedup();
    order
}

fn push_main_flv(parsed: &Value, out: &mut Vec<String>) {
    if let Some(u) = parsed.pointer("/data/origin/main/flv").and_then(Value::as_str) {
        push_unique(out, u);
    }
}

fn collect_flv(node: &Value, out: &mut Vec<String>) {
    match node {
        Value::Object(map) => {
            if let Some(Value::String(s)) = map.get("flv") {
                push_unique(out, s);
            }
            for v in map.values() {
                collect_flv(v, out);
            }
        }
        Value::Array(arr) => {
            for v in arr {
                collect_flv(v, out);
            }
        }
        _ => {}
    }
}

fn push_unique(out: &mut Vec<String>, url: &str) {
    if (url.starts_with("http://") || url.starts_with("https://")) && !out.iter().any(|u| u == url) {
        out.push(url.to_string());
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn wrap(stream_data: Value) -> Value {
        json!({ "stream_url": {
            "pull_datas": { "origin": { "stream_data": stream_data.to_string() } }
        }})
    }

    #[test]
    fn prefers_origin_main_flv_then_other_cdns() {
        let data = wrap(json!({ "data": { "origin": {
            "main": { "flv": "https://pull-flv.douyin.com/origin/main.flv?a=1" },
            "hd":   { "flv": "https://pull-flv.douyin.com/origin/hd.flv?a=2" },
            "backup": { "flv": "https://pull-flv2.douyin.com/backup.flv?a=3" }
        }}}));
        let urls = extract_stream_urls(&data);
        assert_eq!(urls[0], "https://pull-flv.douyin.com/origin/main.flv?a=1");
        assert!(urls.contains(&"https://pull-flv.douyin.com/origin/hd.flv?a=2".to_string()));
        assert!(urls.contains(&"https://pull-flv2.douyin.com/backup.flv?a=3".to_string()));
        assert_eq!(urls.len(), 3, "应去重且只收 http 地址");
    }

    #[test]
    fn supports_legacy_live_core_sdk_data() {
        let payload = json!({ "data": { "origin": {
            "main": { "flv": "https://pull-flv.douyin.com/legacy.flv" }
        }}});
        let data = json!({ "stream_url": {
            "live_core_sdk_data": { "pull_data": { "stream_data": payload.to_string() } }
        }});
        let urls = extract_stream_urls(&data);
        assert_eq!(urls, vec!["https://pull-flv.douyin.com/legacy.flv".to_string()]);
    }

    #[test]
    fn ignores_non_flv_only_streams() {
        let data = wrap(json!({ "data": { "origin": {
            "main": { "hls": "https://pull-hls.douyin.com/main.m3u8" }
        }}}));
        assert!(extract_stream_urls(&data).is_empty());
    }

    #[test]
    fn missing_stream_url_yields_empty() {
        assert!(extract_stream_urls(&json!({ "status": 2 })).is_empty());
    }

    #[test]
    fn parses_flv_pull_url_map_with_default_resolution_first() {
        let data = json!({
            "status": 2,
            "stream_url": {
                "default_resolution": "FULL_HD1",
                "flv_pull_url": {
                    "SD1": "https://pull-flv.example.com/ld.flv",
                    "FULL_HD1": "https://pull-flv.example.com/or4.flv",
                    "HD1": "https://pull-flv.example.com/hd.flv"
                }
            }
        });
        let urls = extract_stream_urls(&data);
        assert_eq!(urls[0], "https://pull-flv.example.com/or4.flv");
        assert_eq!(urls.len(), 3);
    }

    #[test]
    fn falls_back_to_hls_when_no_flv() {
        let data = json!({
            "status": 2,
            "stream_url": {
                "default_resolution": "FULL_HD1",
                "hls_pull_url_map": {
                    "FULL_HD1": "https://pull-hls.example.com/or4.m3u8",
                    "SD1": "https://pull-hls.example.com/ld.m3u8"
                }
            }
        });
        let urls = extract_stream_urls(&data);
        assert_eq!(urls[0], "https://pull-hls.example.com/or4.m3u8");
    }

    #[test]
    fn accepts_reflow_shape() {
        let resp = json!({ "status_code": 0, "data": { "room": {
            "status": 2,
            "stream_url": { "flv_pull_url": { "FULL_HD1": "https://pull-flv.example.com/reflow.flv" } }
        }}});
        let room = room_data(&resp).expect("应能取到 room");
        let urls = extract_stream_urls(room);
        assert_eq!(urls, vec!["https://pull-flv.example.com/reflow.flv".to_string()]);
    }

    #[test]
    fn accepts_enter_shape() {
        let resp = json!({ "status_code": 0, "data": { "data": [{
            "status": 2,
            "stream_url": { "flv_pull_url": { "FULL_HD1": "https://pull-flv.example.com/enter.flv" } }
        }]}});
        let room = room_data(&resp).expect("应能取到 room");
        assert_eq!(extract_stream_urls(room).len(), 1);
    }

    #[test]
    fn extracts_stream_urls_from_page_html() {
        // 页面里 JSON 被转义：\" 与 \u0026
        let html = r#"<script>self.__pace_f.push([1,"{\"stream_url\":{\"flv_pull_url\":{\"FULL_HD1\":\"http://pull-flv.example.com/or4.flv?expire=1\u0026sign=abc\",\"HD1\":\"http://pull-flv.example.com/hd.flv\"}}}"])</script>"#;
        let urls = extract_page_urls(html);
        assert!(urls.iter().any(|u| u.contains("or4.flv")), "urls={urls:?}");
        assert!(urls[0].contains("&sign=abc"), "应还原 \\u0026: {urls:?}");
    }

    #[test]
    fn counts_cookie_pairs() {
        assert_eq!(count_pairs("ttwid=a; odin_tt=b; junk"), 2);
        assert_eq!(count_pairs(""), 0);
        assert!(save_cookie("").is_err(), "空 cookie 应报错");
        assert!(save_cookie("no-equals-sign").is_err(), "格式错误应报错");
    }
}
