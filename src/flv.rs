use std::io::Cursor;

use anyhow::Result;
use bytes::{Buf, Bytes, BytesMut};
use scuffle_flv::video::VideoData;
use scuffle_flv::video::body::VideoTagBody;
use scuffle_flv::video::body::legacy::LegacyVideoTagBody;
use scuffle_flv::video::header::VideoTagHeaderData;
use scuffle_flv::video::header::legacy::{LegacyVideoTagHeader, LegacyVideoTagHeaderAvcPacket};

/// 一个从 FLV 视频标签解析出的 H.264 单元
pub enum VideoUnit {
    /// AVCDecoderConfigurationRecord 转换出的 Annex-B SPS/PPS
    Config(Vec<u8>),
    /// AVCC 长度前缀 NALU 转换出的 Annex-B 访问单元
    Nalu(Vec<u8>),
}

/// 增量式 FLV 解复用器：喂入字节缓冲，产出 H.264 视频单元
pub struct FlvParser {
    started: bool,
    tags_seen: u64,
}

impl FlvParser {
    pub fn new() -> Self {
        Self {
            started: false,
            tags_seen: 0,
        }
    }

    pub fn push(&mut self, buf: &mut BytesMut, out: &mut Vec<VideoUnit>) -> Result<()> {
        if !self.started {
            if buf.len() < 13 {
                return Ok(());
            }
            if !buf.starts_with(b"FLV") {
                anyhow::bail!("不是有效的 FLV 流");
            }
            let data_offset = u32::from_be_bytes([buf[5], buf[6], buf[7], buf[8]]) as usize;
            let skip = data_offset + 4;
            if buf.len() < skip {
                return Ok(());
            }
            buf.advance(skip);
            self.started = true;
        }

        loop {
            if buf.len() < 11 {
                break;
            }
            let tag_type = buf[0];
            let data_size =
                ((buf[1] as usize) << 16) | ((buf[2] as usize) << 8) | (buf[3] as usize);
            let total = 11 + data_size;
            if buf.len() < total + 4 {
                break;
            }
            let tag_bytes = buf.split_to(total).freeze();
            buf.advance(4);
            self.tags_seen += 1;
            if self.tags_seen <= 10 && std::env::var("MHYSCAN_DEBUG").is_ok() {
                eprintln!(
                    "[flv] tag#{} type={} size={} first={:02x?}",
                    self.tags_seen,
                    tag_type,
                    data_size,
                    &tag_bytes[..tag_bytes.len().min(6)]
                );
            }
            if tag_type == 9
                && let Some(unit) = parse_video_tag(tag_bytes)
            {
                out.push(unit);
            }
        }
        Ok(())
    }
}

fn parse_video_tag(tag_bytes: Bytes) -> Option<VideoUnit> {
    let debug = std::env::var("MHYSCAN_DEBUG").is_ok();
    if debug {
        let n = tag_bytes.len().min(12);
        eprintln!(
            "[flv] video tag len={} head={:02x?}",
            tag_bytes.len(),
            &tag_bytes[..n]
        );
    }
    let mut cur = Cursor::new(tag_bytes.slice(11..));
    let video = match VideoData::demux(&mut cur) {
        Ok(v) => v,
        Err(e) => {
            if debug {
                eprintln!("[flv] VideoData::demux 失败: {e:?}");
            }
            return None;
        }
    };
    if debug {
        eprintln!(
            "[flv] header.frame_type={:?} header.data={:?}",
            video.header.frame_type, video.header.data
        );
    }

    let is_nalu = matches!(
        &video.header.data,
        VideoTagHeaderData::Legacy(LegacyVideoTagHeader::AvcPacket(
            LegacyVideoTagHeaderAvcPacket::Nalu { .. }
        ))
    );
    if is_nalu && let VideoTagBody::Legacy(LegacyVideoTagBody::Other { data }) = video.body {
        return Some(VideoUnit::Nalu(avcc_to_annexb(&data, 4)));
    }

    let is_seq = matches!(
        &video.header.data,
        VideoTagHeaderData::Legacy(LegacyVideoTagHeader::AvcPacket(
            LegacyVideoTagHeaderAvcPacket::SequenceHeader
        ))
    );
    if is_seq
        && let VideoTagBody::Legacy(LegacyVideoTagBody::AvcVideoPacketSeqHdr(cfg)) = video.body
    {
        let mut out = Vec::with_capacity(64);
        for sps in &cfg.sps {
            out.extend_from_slice(&[0, 0, 0, 1]);
            out.extend_from_slice(sps);
        }
        for pps in &cfg.pps {
            out.extend_from_slice(&[0, 0, 0, 1]);
            out.extend_from_slice(pps);
        }
        return Some(VideoUnit::Config(out));
    }

    None
}

/// 将 AVCC 长度前缀 NALU 转换为 Annex-B（4 字节起始码）
fn avcc_to_annexb(data: &[u8], len_size: usize) -> Vec<u8> {
    let mut out = Vec::with_capacity(data.len() + 32);
    let mut i = 0usize;
    while i + len_size <= data.len() {
        let mut n = 0usize;
        for j in 0..len_size {
            n = (n << 8) | data[i + j] as usize;
        }
        i += len_size;
        if i + n > data.len() {
            break;
        }
        out.extend_from_slice(&[0, 0, 0, 1]);
        out.extend_from_slice(&data[i..i + n]);
        i += n;
    }
    out
}
