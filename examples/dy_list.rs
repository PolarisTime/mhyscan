//! 探针：用签名请求直播广场，列出在播房间（调试用）
#[tokio::main]
async fn main() {
    let params = "aid=6383&app_name=douyin_web&live_id=1&device_platform=web&browser_language=zh-CN&browser_platform=Win32&browser_name=Edge&browser_version=139.0.0.0&count=15&offset=0&partition=0&partition_type=0&req_from=2";
    let fp = mhyscan_rs::douyin_abogus::BrowserFingerprintGenerator::generate_fingerprint("Edge");
    let mut signer = mhyscan_rs::douyin_abogus::ABogus::new(Some(&fp), Some(mhyscan_rs::douyin::UA), None);
    let (signed, ..) = signer.generate_abogus(params, "");
    let url = format!("https://live.douyin.com/webcast/web/partition/detail/room/?{signed}");
    let client = reqwest::Client::new();
    let resp = client.get(&url)
        .header("User-Agent", mhyscan_rs::douyin::UA)
        .header("Referer", mhyscan_rs::douyin::REFERER)
        .send().await.unwrap();
    let status = resp.status();
    let text = resp.text().await.unwrap();
    println!("HTTP {status} len={}", text.len());
    println!("{}", &text[..text.len().min(600)]);
}
