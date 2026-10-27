//! 极简 HLS（TS 分片）读取：拉 m3u8 → 下载新分片 → 解出 Annex-B H.264 单元。
//!
//! 只做「直播 FLV 拿不到时的回退」：不支持 fMP4 分片（#EXT-X-MAP），
//! 也不做解密（KEY 加密的流会明确报错）。
use std::collections::{HashSet, VecDeque};
use std::time::{Duration, Instant};

use anyhow::{Context, Result, bail};
use reqwest::Client;

use crate::flv::VideoUnit;

/// 直播播放列表的刷新间隔
pub const REFRESH_INTERVAL: Duration = Duration::from_secs(2);
/// 分片队列上限：落后太多时丢弃旧分片，避免延迟越滚越大
const MAX_QUEUE: usize = 8;

pub struct HlsSession {
    http: Client,
    playlist_url: String,
    media_url: String,
    ua: &'static str,
    referer: &'static str,
    seen: HashSet<String>,
    queue: VecDeque<String>,
    last_refresh: Option<Instant>,
    bytes_read: u64,
}

impl HlsSession {
    pub fn new(playlist_url: &str, ua: &'static str, referer: &'static str) -> Self {
        Self {
            http: Client::new(),
            playlist_url: playlist_url.to_string(),
            media_url: playlist_url.to_string(),
            ua,
            referer,
            seen: HashSet::new(),
            queue: VecDeque::new(),
            last_refresh: None,
            bytes_read: 0,
        }
    }

    pub fn bytes_read(&self) -> u64 {
        self.bytes_read
    }

    /// 取下一段分片解出的视频单元；暂时没有新分片时返回空 Vec（内部已 sleep）。
    pub async fn next_units(&mut self) -> Result<Vec<VideoUnit>> {
        for _ in 0..4 {
            self.maybe_refresh().await?;
            if let Some(seg) = self.queue.pop_front() {
                let data = self.fetch_bytes(&seg).await?;
                self.bytes_read += data.len() as u64;
                let mut units = Vec::new();
                demux_ts(&data, &mut units);
                if !units.is_empty() {
                    return Ok(units);
                }
                continue;
            }
            // 直播列表还没更新，等一会儿再看
            tokio::time::sleep(Duration::from_millis(800)).await;
        }
        Ok(Vec::new())
    }

    async fn maybe_refresh(&mut self) -> Result<()> {
        let due = match self.last_refresh {
            None => true,
            Some(t) => t.elapsed() >= REFRESH_INTERVAL,
        };
        if !due {
            return Ok(());
        }
        self.last_refresh = Some(Instant::now());

        let text = self.get_text(&self.playlist_url).await?;
        let (variant, _) = parse_playlist(&text, &self.playlist_url);
        if let Some(v) = variant {
            // 主播放列表：切到第一个码率的媒体列表
            if v != self.media_url {
                self.media_url = v;
                self.seen.clear();
                self.queue.clear();
            }
            let media = self.get_text(&self.media_url).await?;
            self.enqueue_segments(&media);
        } else {
            self.enqueue_segments(&text);
        }
        Ok(())
    }

    fn enqueue_segments(&mut self, text: &str) {
        let (_, segments) = parse_playlist(text, &self.media_url);
        for seg in segments {
            if self.seen.insert(seg.clone()) {
                self.queue.push_back(seg);
            }
        }
        while self.queue.len() > MAX_QUEUE {
            self.queue.pop_front();
        }
    }

    async fn get_text(&self, url: &str) -> Result<String> {
        let resp = self
            .http
            .get(url)
            .header("User-Agent", self.ua)
            .header("Referer", self.referer)
            .send()
            .await
            .with_context(|| format!("拉取播放列表失败: {url}"))?;
        if !resp.status().is_success() {
            bail!("播放列表 HTTP {}", resp.status());
        }
        Ok(resp.text().await?)
    }

    async fn fetch_bytes(&self, url: &str) -> Result<Vec<u8>> {
        let resp = self
            .http
            .get(url)
            .header("User-Agent", self.ua)
            .header("Referer", self.referer)
            .send()
            .await
            .with_context(|| format!("下载分片失败: {url}"))?;
        if !resp.status().is_success() {
            bail!("分片 HTTP {}", resp.status());
        }
        Ok(resp.bytes().await?.to_vec())
    }
}

/// 解析播放列表：返回 (第一个变体地址, 分片地址列表)
pub fn parse_playlist(text: &str, base: &str) -> (Option<String>, Vec<String>) {
    let mut variant = None;
    let mut segments = Vec::new();
    let mut want_variant = false;

    for raw in text.lines() {
        let line = raw.trim();
        if line.is_empty() {
            continue;
        }
        if line.starts_with("#EXT-X-STREAM-INF") {
            want_variant = true;
            continue;
        }
        if line.starts_with('#') {
            if line.starts_with("#EXT-X-KEY") && !line.contains("METHOD=NONE") {
                // 加密流暂不支持，交给上层报错
                return (None, Vec::new());
            }
            continue;
        }
        if want_variant && variant.is_none() {
            variant = Some(resolve_url(base, line));
            want_variant = false;
            continue;
        }
        segments.push(resolve_url(base, line));
    }
    (variant, segments)
}

/// 把播放列表里的相对地址解析成绝对地址
pub fn resolve_url(base: &str, rel: &str) -> String {
    if rel.starts_with("http://") || rel.starts_with("https://") {
        return rel.to_string();
    }
    if rel.starts_with("//") {
        let scheme = base.split(':').next().unwrap_or("https");
        return format!("{scheme}:{rel}");
    }
    let (origin, path) = match base.find("://") {
        Some(i) => {
            let after = &base[i + 3..];
            let host_end = after.find('/').map(|p| i + 3 + p).unwrap_or(base.len());
            (&base[..host_end], &base[host_end..])
        }
        None => ("", base),
    };
    if rel.starts_with('/') {
        return format!("{origin}{rel}");
    }
    let dir = match path.rfind('/') {
        Some(p) => &path[..p + 1],
        None => "/",
    };
    format!("{origin}{dir}{rel}")
}

/// 解 TS：PAT → PMT → 视频 PES → Annex-B H.264
pub fn demux_ts(data: &[u8], out: &mut Vec<VideoUnit>) {
    let mut pmt_pid: Option<u16> = None;
    let mut video_pid: Option<u16> = None;
    let mut pes: Vec<u8> = Vec::new();

    for packet in data.chunks_exact(188) {
        if packet[0] != 0x47 {
            continue;
        }
        let pusi = packet[1] & 0x40 != 0;
        let pid = (((packet[1] & 0x1f) as u16) << 8) | packet[2] as u16;
        let afc = (packet[3] >> 4) & 0x3;
        let mut off = 4usize;
        if afc & 0x2 != 0 {
            if off >= packet.len() {
                continue;
            }
            off = 5 + packet[off] as usize;
        }
        if afc & 0x1 == 0 || off >= packet.len() {
            continue;
        }
        let payload = &packet[off..];

        if pid == 0 && pusi {
            pmt_pid = parse_pat(payload);
        } else if Some(pid) == pmt_pid && pusi {
            video_pid = parse_pmt(payload);
        } else if Some(pid) == video_pid {
            if pusi && !pes.is_empty() {
                flush_pes(&mut pes, out);
            }
            pes.extend_from_slice(payload);
        }
    }
    flush_pes(&mut pes, out);
}

fn parse_pat(payload: &[u8]) -> Option<u16> {
    let sec = section(payload)?;
    if sec.first() != Some(&0x00) || sec.len() < 12 {
        return None;
    }
    // 跳过 5 字节表头，取第一个 program 的 PMT PID
    let pid = (((sec[10] & 0x1f) as u16) << 8) | sec[11] as u16;
    Some(pid)
}

fn parse_pmt(payload: &[u8]) -> Option<u16> {
    let sec = section(payload)?;
    if sec.first() != Some(&0x02) || sec.len() < 12 {
        return None;
    }
    let info_len = (((sec[10] & 0x0f) as usize) << 8) | sec[11] as usize;
    let mut i = 12 + info_len;
    while i + 5 <= sec.len() {
        let stream_type = sec[i];
        let pid = (((sec[i + 1] & 0x1f) as u16) << 8) | sec[i + 2] as u16;
        let es_len = (((sec[i + 3] & 0x0f) as usize) << 8) | sec[i + 4] as usize;
        if stream_type == 0x1b {
            return Some(pid);
        }
        i += 5 + es_len;
    }
    None
}

/// 去掉 pointer_field，返回 section（含 table_id）
fn section(payload: &[u8]) -> Option<&[u8]> {
    if payload.is_empty() {
        return None;
    }
    let start = 1 + payload[0] as usize;
    if start >= payload.len() {
        return None;
    }
    let sec = &payload[start..];
    if sec.len() < 8 {
        return None;
    }
    let len = (((sec[1] & 0x0f) as usize) << 8) | sec[2] as usize;
    let end = (3 + len).min(sec.len());
    Some(&sec[..end])
}

fn flush_pes(pes: &mut Vec<u8>, out: &mut Vec<VideoUnit>) {
    if pes.len() > 9 && pes[0] == 0 && pes[1] == 0 && pes[2] == 1 {
        let pes_len = ((pes[4] as usize) << 8) | pes[5] as usize;
        let total = 6 + pes_len;
        let buf: &[u8] = if pes_len > 0 && pes.len() >= total {
            &pes[..total]
        } else {
            &pes
        };
        let header_len = buf[8] as usize;
        let es_start = 9 + header_len;
        if es_start < buf.len() {
            let es = &buf[es_start..];
            if es.windows(3).any(|w| w == [0, 0, 1]) {
                out.push(VideoUnit::Nalu(es.to_vec()));
            }
        }
    }
    pes.clear();
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ts_packet(pid: u16, pusi: bool, payload: &[u8]) -> Vec<u8> {
        let mut p = vec![0xFFu8; 188];
        p[0] = 0x47;
        p[1] = (if pusi { 0x40 } else { 0 }) | ((pid >> 8) as u8 & 0x1f);
        p[2] = (pid & 0xff) as u8;
        p[3] = 0x10;
        let n = payload.len().min(184);
        p[4..4 + n].copy_from_slice(&payload[..n]);
        p
    }

    fn pat(pmt_pid: u16) -> Vec<u8> {
        vec![
            0x00, 0x00, 0xB0, 0x0D, 0x00, 0x01, 0xC1, 0x00, 0x00, 0x00, 0x01,
            0xE0 | ((pmt_pid >> 8) as u8 & 0x1f), (pmt_pid & 0xff) as u8,
            0x00, 0x00, 0x00, 0x00,
        ]
    }

    fn pmt(video_pid: u16) -> Vec<u8> {
        vec![
            0x00, 0x02, 0xB0, 0x12, 0x00, 0x01, 0xC1, 0x00, 0x00, 0xFF, 0xFF, 0xF0, 0x00,
            0x1B, 0xE0 | ((video_pid >> 8) as u8 & 0x1f), (video_pid & 0xff) as u8, 0xF0, 0x00,
            0x00, 0x00, 0x00, 0x00,
        ]
    }

    #[test]
    fn resolves_relative_segments() {
        assert_eq!(
            resolve_url("https://hls.example.com/live/stream.m3u8", "seg1.ts"),
            "https://hls.example.com/live/seg1.ts"
        );
        assert_eq!(
            resolve_url("https://hls.example.com/live/stream.m3u8", "/a/b.ts"),
            "https://hls.example.com/a/b.ts"
        );
        assert_eq!(
            resolve_url("https://hls.example.com/x.m3u8", "https://cdn/seg.ts"),
            "https://cdn/seg.ts"
        );
    }

    #[test]
    fn parses_master_playlist_variant() {
        let text = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\n720p/index.m3u8\n";
        let (variant, segs) = parse_playlist(text, "https://h.example/live/master.m3u8");
        assert_eq!(variant.as_deref(), Some("https://h.example/live/720p/index.m3u8"));
        assert!(segs.is_empty());
    }

    #[test]
    fn parses_media_playlist_segments() {
        let text = "#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:1.9,\nseg1.ts\n#EXTINF:1.9,\nseg2.ts\n";
        let (variant, segs) = parse_playlist(text, "https://h.example/live/index.m3u8");
        assert!(variant.is_none());
        assert_eq!(
            segs,
            vec![
                "https://h.example/live/seg1.ts".to_string(),
                "https://h.example/live/seg2.ts".to_string()
            ]
        );
    }

    #[test]
    fn demux_ts_extracts_annexb_h264() {
        let mut data = Vec::new();
        data.extend(ts_packet(0, true, &pat(0x1000)));
        data.extend(ts_packet(0x1000, true, &pmt(0x0101)));
        // PES: 00 00 01 E0, len, flags, header_len=0, ES= Annex-B IDR
        let es: Vec<u8> = vec![
            0x00, 0x00, 0x00, 0x01, 0x09, 0xF0, // AUD
            0x00, 0x00, 0x00, 0x01, 0x65, 0x88, 0x84, 0x00,
        ];
        let pes_len = 3 + es.len();
        let mut pes = vec![0x00, 0x00, 0x01, 0xE0, (pes_len >> 8) as u8, (pes_len & 0xff) as u8, 0x80, 0x00, 0x00];
        pes.extend_from_slice(&es);
        data.extend(ts_packet(0x0101, true, &pes));

        let mut units = Vec::new();
        demux_ts(&data, &mut units);
        assert_eq!(units.len(), 1, "应解出一个视频单元");
        match &units[0] {
            VideoUnit::Nalu(n) => {
                assert_eq!(&n[..4], &[0, 0, 0, 1]);
                assert!(n.contains(&0x65), "应包含 IDR NAL");
            }
            _ => panic!("应为 Nalu"),
        }
    }

    #[test]
    fn demux_ignores_garbage() {
        let mut units = Vec::new();
        demux_ts(&[0u8; 188 * 2], &mut units);
        assert!(units.is_empty());
    }
}
