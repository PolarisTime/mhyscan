"""二维码识别 — 对应开源版 QRScanner.cpp (OpenCV) / 16.0 (ZXing)

实测结论 (本机 zxingcpp 5.0 / opencv 5.0):
  - zxingcpp: 原图/缩放/模糊/灰度/水印遮挡 全部识别成功
  - opencv QRCodeDetector: 同场景全部失败
16.0 闭源版用的就是 ZXing, 因此默认使用 zxingcpp。
"""
from __future__ import annotations

import numpy as np
import zxingcpp


class QRScanner:
    """ZXing 二维码解码器 (对应 16.0 的 ZXing::ReadBarcode)"""

    def __init__(self, try_harder: bool = True):
        self.try_harder = try_harder

    def decode_single(self, img: np.ndarray) -> str:
        """解码单帧图像, 返回第一个二维码文本 (空串表示未识别)"""
        if img is None or img.size == 0:
            return ""
        kwargs = {}
        if self.try_harder:
            kwargs["try_harder"] = True
        try:
            results = zxingcpp.read_barcodes(img, **kwargs)
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
