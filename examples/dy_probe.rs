//! 手动探针：验证抖音取流（真机调试用）
#[tokio::main]
async fn main() {
    let rid = std::env::args().nth(1).unwrap_or_else(|| "369324308707".to_string());
    match mhyscan_rs::douyin::get_candidates(&rid).await {
        Ok(urls) => {
            println!("OK {} 个候选", urls.len());
            for u in urls.iter().take(4) {
                println!("  {}", &u[..u.len().min(120)]);
            }
        }
        Err(e) => println!("ERR: {e}"),
    }
}
