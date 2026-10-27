//! 诊断：HLS(TS) 分片拉流 + 解码验证
use std::time::Duration;
use mhyscan_rs::decode::VideoDecoder;
use mhyscan_rs::hls::HlsSession;

#[tokio::main]
async fn main() {
    let url = std::env::args().nth(1).expect("m3u8 url");
    let mut s = HlsSession::new(&url, "Mozilla/5.0", "https://example.com/");
    let mut dec = VideoDecoder::new().unwrap();
    let (mut frames, mut units, mut printed) = (0u64, 0u64, 0u64);
    let deadline = tokio::time::Instant::now() + Duration::from_secs(10);
    while tokio::time::Instant::now() < deadline {
        match s.next_units().await {
            Ok(u) => {
                units += u.len() as u64;
                for unit in &u {
                    if printed < 12 {
                        printed += 1;
                        if let mhyscan_rs::flv::VideoUnit::Nalu(n) = unit {
                            let types: Vec<u8> = n.windows(4).enumerate()
                                .filter(|(_, w)| w == &[0, 0, 0, 1])
                                .filter_map(|(i, _)| n.get(i + 4).map(|b| b & 0x1f))
                                .collect();
                            println!("unit nals={types:?} len={}", n.len());
                        } else {
                            println!("unit CONFIG len={}", match unit { mhyscan_rs::flv::VideoUnit::Config(c) => c.len(), _ => 0 });
                        }
                    }
                    if let Ok(Some(_)) = dec.feed(unit) {
                        frames += 1;
                    }
                }
            }
            Err(e) => { println!("ERR {e}"); break; }
        }
    }
    println!("bytes={} units={units} frames={frames}", s.bytes_read());
}
