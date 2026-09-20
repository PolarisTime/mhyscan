use anyhow::Result;
use openh264::decoder::Decoder;
use openh264::formats::YUVSource;

use crate::flv::VideoUnit;

/// 基于 openh264 的 H.264 解码器，输出灰度（luma）帧
pub struct VideoDecoder {
    dec: Decoder,
    config: Option<Vec<u8>>,
}

impl VideoDecoder {
    pub fn new() -> Result<Self> {
        Ok(Self {
            dec: Decoder::new()?,
            config: None,
        })
    }

    /// 喂入一个视频单元，若解出图像则返回 (luma, width, height)
    pub fn feed(&mut self, unit: &VideoUnit) -> Result<Option<(Vec<u8>, u32, u32)>> {
        let nalu = match unit {
            VideoUnit::Config(cfg) => {
                self.config = Some(cfg.clone());
                let _ = self.dec.decode(cfg)?;
                return Ok(None);
            }
            VideoUnit::Nalu(n) => n,
        };

        // 关键帧前补上 SPS/PPS，兼容中途接入直播流的情况
        let combined = if is_idr(nalu) {
            self.config.as_ref().map(|cfg| {
                let mut b = Vec::with_capacity(cfg.len() + nalu.len());
                b.extend_from_slice(cfg);
                b.extend_from_slice(nalu);
                b
            })
        } else {
            None
        };
        let packet: &[u8] = combined.as_deref().unwrap_or(nalu);

        let Some(yuv) = self.dec.decode(packet)? else {
            return Ok(None);
        };
        let (w, h) = yuv.dimensions();
        let stride = yuv.strides().0;
        let y = yuv.y();

        let luma = if stride == w {
            y[..w * h].to_vec()
        } else {
            let mut out = Vec::with_capacity(w * h);
            for row in 0..h {
                out.extend_from_slice(&y[row * stride..row * stride + w]);
            }
            out
        };
        Ok(Some((luma, w as u32, h as u32)))
    }
}

/// 判断 Annex-B 访问单元的第一个 NAL 是否为 IDR（类型 5）
fn is_idr(annexb: &[u8]) -> bool {
    if annexb.len() >= 5 && annexb[0] == 0 && annexb[1] == 0 && annexb[2] == 0 && annexb[3] == 1 {
        return annexb[4] & 0x1f == 5;
    }
    false
}
