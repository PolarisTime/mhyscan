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
    demux: TsDemuxer,
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
            demux: TsDemuxer::new(),
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
                self.demux.push(&data, &mut units);
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

/// TS 解复用器：跨 PES 包重组视频 elementary stream，按 NAL/AU 边界切分。
///
/// 关键点：H.264 的一帧可能跨多个 PES 包，不能按 PES 直接切；必须先拼成
/// 连续的 ES，再按起始码分 NAL，最后按「first_mb_in_slice == 0」或 AUD 分帧。
#[derive(Default)]
pub struct TsDemuxer {
    pmt_pid: Option<u16>,
    video_pid: Option<u16>,
    es: Vec<u8>,
    au: Vec<Vec<u8>>,
    /// 当前 PES 还剩多少 ES 字节（用于裁掉 TS 包尾 0xFF 填充）
    pes_remaining: Option<usize>,
}

impl TsDemuxer {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn push(&mut self, data: &[u8], out: &mut Vec<VideoUnit>) {
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
                self.pmt_pid = parse_pat(payload);
            } else if Some(pid) == self.pmt_pid && pusi {
                self.video_pid = parse_pmt(payload);
            } else if Some(pid) == self.video_pid {
                // 新 PES 起点：跳过 PES 头，把后续 ES 接到之前的 ES 缓冲上
                // （一帧可能横跨多个 PES 包）
                if pusi {
                    match pes_es_start(payload) {
                        Some(es_start) => {
                            let rest = &payload[es_start..];
                            let pes_len = pes_total_len(payload);
                            let take = match pes_len {
                                Some(total) => rest.len().min(total.saturating_sub(es_start)),
                                None => rest.len(),
                            };
                            self.es.extend_from_slice(&rest[..take]);
                            self.pes_remaining = pes_len.map(|t| t.saturating_sub(es_start + take));
                        }
                        None => {
                            self.es.extend_from_slice(payload);
                            self.pes_remaining = None;
                        }
                    }
                } else {
                    let take = match self.pes_remaining {
                        Some(rem) => payload.len().min(rem),
                        None => payload.len(),
                    };
                    self.es.extend_from_slice(&payload[..take]);
                    if let Some(rem) = self.pes_remaining.as_mut() {
                        *rem = rem.saturating_sub(take);
                    }
                }
                self.drain_nalus(out);
            }
        }
        self.drain_nalus(out);
    }

    /// 流结束时吐出最后一帧
    pub fn finish(&mut self, out: &mut Vec<VideoUnit>) {
        self.drain_nalus(out);
        // 末尾 NAL 后面没有起始码，单独取出
        if let Some((start, sc_len)) = find_start_code(&self.es, 0) {
            if start <= 3 && self.es.len() > sc_len {
                let nal = self.es[sc_len..].to_vec();
                self.push_nal(nal, out);
            }
        }
        if self.au.iter().any(|n| is_vcl(n)) {
            self.flush_au(out);
        }
        self.es.clear();
        self.pes_remaining = None;
    }

    /// 从 ES 缓冲里切出完整 NAL，并按 AU 分组
    fn drain_nalus(&mut self, out: &mut Vec<VideoUnit>) {
        loop {
            let Some((start, sc_len)) = find_start_code(&self.es, 0) else {
                if self.es.len() > 4 {
                    // 保留最多 3 字节可能的起始码前缀
                    let keep = self.es.len().min(3);
                    let cut = self.es.len() - keep;
                    self.es.drain(..cut);
                }
                return;
            };
            if start > 0 {
                self.es.drain(..start);
            }
            let Some((next, _)) = find_start_code(&self.es, sc_len) else {
                return; // 下一个 NAL 还没到齐
            };
            let nal: Vec<u8> = self.es[sc_len..next].to_vec();
            self.es.drain(..next);
            self.push_nal(nal, out);
        }
    }

    fn push_nal(&mut self, nal: Vec<u8>, out: &mut Vec<VideoUnit>) {
        let nal_type = nal.first().map(|b| b & 0x1f).unwrap_or(0);
        match nal_type {
            7 | 8 => {
                // 参数集属于下一个 AU
                if self.au.iter().any(|n| is_vcl(n)) {
                    self.flush_au(out);
                }
                self.au.push(nal);
            }
            9 => {
                if !self.au.is_empty() {
                    self.flush_au(out);
                }
                self.au.push(nal);
            }
            1 | 5 => {
                let first_mb_zero = first_mb_in_slice(&nal) == Some(0);
                if first_mb_zero && self.au.iter().any(|n| is_vcl(n)) {
                    self.flush_au(out);
                }
                self.au.push(nal);
            }
            _ => self.au.push(nal),
        }
    }

    fn flush_au(&mut self, out: &mut Vec<VideoUnit>) {
        if self.au.is_empty() {
            return;
        }
        let mut buf = Vec::with_capacity(self.au.iter().map(Vec::len).sum::<usize>() + 16);
        for nal in self.au.drain(..) {
            buf.extend_from_slice(&[0, 0, 0, 1]);
            buf.extend_from_slice(&nal);
        }
        out.push(VideoUnit::Nalu(buf));
    }
}

/// 兼容旧接口：一次性喂完并 flush
pub fn demux_ts(data: &[u8], out: &mut Vec<VideoUnit>) {
    let mut d = TsDemuxer::new();
    d.push(data, out);
    d.finish(out);
}

fn is_vcl(nal: &[u8]) -> bool {
    matches!(nal.first().map(|b| b & 0x1f), Some(1) | Some(5))
}

/// 找起始码，返回 (起始码位置, 长度)
fn find_start_code(buf: &[u8], from: usize) -> Option<(usize, usize)> {
    let mut i = from;
    while i + 3 <= buf.len() {
        if buf[i] == 0 && buf[i + 1] == 0 {
            if buf[i + 2] == 1 {
                return Some((i, 3));
            }
            if i + 4 <= buf.len() && buf[i + 2] == 0 && buf[i + 3] == 1 {
                return Some((i, 4));
            }
        }
        i += 1;
    }
    None
}

/// PES 总长度（6 + PES_packet_length；0 表示无界）
fn pes_total_len(buf: &[u8]) -> Option<usize> {
    if buf.len() < 8 {
        return None;
    }
    let len = ((buf[4] as usize) << 8) | buf[5] as usize;
    if len == 0 { None } else { Some(6 + len) }
}

/// PES 头长度（返回 ES 数据偏移）
fn pes_es_start(buf: &[u8]) -> Option<usize> {
    if buf.len() < 9 || buf[0] != 0 || buf[1] != 0 || buf[2] != 1 {
        return None;
    }
    Some(9 + buf[8] as usize)
}

fn parse_pat(payload: &[u8]) -> Option<u16> {
    let sec = section(payload)?;
    if sec.first() != Some(&0x00) || sec.len() < 12 {
        return None;
    }
    Some((((sec[10] & 0x1f) as u16) << 8) | sec[11] as u16)
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

/// 解析 slice header 的第一个 ue(v)：first_mb_in_slice
fn first_mb_in_slice(nal: &[u8]) -> Option<u32> {
    let bits = nal.get(1..)?;
    if bits.is_empty() {
        return None;
    }
    let bit = |i: usize| -> u32 { ((bits[i / 8] >> (7 - (i % 8))) & 1) as u32 };
    let mut pos = 0usize;
    let mut zeros = 0usize;
    while pos < bits.len() * 8 && bit(pos) == 0 {
        zeros += 1;
        pos += 1;
        if zeros > 24 {
            return None;
        }
    }
    if pos >= bits.len() * 8 {
        return None;
    }
    pos += 1;
    let mut v = 0u32;
    for _ in 0..zeros {
        if pos >= bits.len() * 8 {
            return None;
        }
        v = (v << 1) | bit(pos);
        pos += 1;
    }
    Some((1u32 << zeros) - 1 + v)
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
