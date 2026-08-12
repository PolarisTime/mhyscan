"""二维码识别 — 对应开源版 QRScanner.cpp (OpenCV) / 16.0 (ZXing)

实测结论 (zxingcpp 5.x):
  - zxingcpp: 原图/缩放/模糊/灰度/水印遮挡 全部识别成功
  - opencv QRCodeDetector: 同场景全部失败
16.0 闭源版用的就是 ZXing, 因此默认使用 zxingcpp。

注意: zxingcpp.read_barcodes 不支持 try_harder 参数 (会 TypeError),
      应使用其实际支持的 try_rotate/try_downscale/try_invert 等。
"""
from __future__ import annotations

import numpy as np
import zxingcpp


class QRScanner:
    """ZXing 二维码解码器 (对应 16.0 的 ZXing::ReadBarcode)"""

    def __init__(self, try_rotate: bool = True, try_downscale: bool = True,
                 try_invert: bool = True):
        self.try_rotate = try_rotate
        self.try_downscale = try_downscale
        self.try_invert = try_invert

    def decode_single(self, img: np.ndarray) -> str:
        """解码单帧图像, 返回第一个二维码文本 (空串表示未识别)"""
        if img is None or img.size == 0:
            return ""
        try:
            results = zxingcpp.read_barcodes(
                img,
                try_rotate=self.try_rotate,
                try_downscale=self.try_downscale,
                try_invert=self.try_invert,
            )
        except Exception:
            # 个别平台参数不兼容时回退默认
            try:
                results = zxingcpp.read_barcodes(img)
            except Exception:
                return ""
        if not results:
            return ""
        return results[0].text or ""


class OpenCVQRScanner:
    """备选: OpenCV QRCodeDetector (识别率远低于 zxing, 不建议用于直播流)"""

    def __init__(self):
        import cv2

        self._detector = cv2.QRCodeDetector()

    def decode_single(self, img: np.ndarray) -> str:
        try:
            text, _points, _ = self._detector.detectAndDecode(img)
        except Exception:
            return ""
        return text or ""
