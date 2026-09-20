use rxing::helpers::detect_in_luma_with_hints;
use rxing::{BarcodeFormat, DecodeHints};

/// 米哈游登录二维码 URL 必须包含的片段
const QR_URL_MARKERS: [&str; 3] = ["mihoyo.com", "hoyolab.com", "login-platform"];

/// 对灰度图做二维码识别，返回第一个结果文本
pub fn detect_qr(luma: Vec<u8>, width: u32, height: u32) -> Option<String> {
    let mut hints = DecodeHints::default();
    hints.TryHarder = Some(true);
    detect_in_luma_with_hints(
        luma,
        width,
        height,
        Some(BarcodeFormat::QR_CODE),
        &mut hints,
    )
    .ok()
    .map(|r| r.getText().to_string())
}

pub fn is_login_qr_url(url: &str) -> bool {
    !url.is_empty() && QR_URL_MARKERS.iter().any(|m| url.contains(m))
}

/// 从二维码 URL 提取 ticket（新版使用 tk= 参数）
pub fn extract_ticket(url: &str) -> Option<String> {
    if let Ok(parsed) = url::Url::parse(url) {
        for (key, value) in parsed.query_pairs() {
            if matches!(key.as_ref(), "tk" | "ticket" | "t") && !value.is_empty() {
                return Some(value.into_owned());
            }
        }
    }
    find_uuid(url)
}

/// 兜底：从字符串中提取 UUID 形式的 ticket
fn find_uuid(s: &str) -> Option<String> {
    let bytes = s.as_bytes();
    let is_hex = |b: u8| b.is_ascii_hexdigit();
    let mut i = 0usize;
    while i + 36 <= bytes.len() {
        let candidate = &bytes[i..i + 36];
        let ok = is_hex(candidate[0])
            && is_hex(candidate[1])
            && is_hex(candidate[2])
            && is_hex(candidate[3])
            && is_hex(candidate[4])
            && is_hex(candidate[5])
            && is_hex(candidate[6])
            && is_hex(candidate[7])
            && candidate[8] == b'-'
            && is_hex(candidate[9])
            && is_hex(candidate[10])
            && is_hex(candidate[11])
            && is_hex(candidate[12])
            && candidate[13] == b'-'
            && is_hex(candidate[14])
            && is_hex(candidate[15])
            && is_hex(candidate[16])
            && is_hex(candidate[17])
            && candidate[18] == b'-'
            && is_hex(candidate[19])
            && is_hex(candidate[20])
            && is_hex(candidate[21])
            && is_hex(candidate[22])
            && candidate[23] == b'-'
            && candidate[24..36].iter().all(|&b| is_hex(b));
        if ok {
            return Some(s[i..i + 36].to_string());
        }
        i += 1;
    }
    None
}
