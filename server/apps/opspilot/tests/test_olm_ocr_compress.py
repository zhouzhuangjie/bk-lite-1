"""OlmOcr._compress_image_from_bytes：小于阈值原样返回，超限 JPEG 压缩到上限内。"""
import io

import pytest
from PIL import Image

from apps.opspilot.metis.ocr.olm_ocr import OlmOcr

pytestmark = pytest.mark.unit


def _jpeg_bytes(width=800, height=600, color=(12, 34, 56)):
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def test_compress_returns_original_when_under_limit():
    data = b"tiny-image"
    assert OlmOcr._compress_image_from_bytes(data, max_size_kb=1) is data


def test_compress_shrinks_large_jpeg_below_limit():
    data = _jpeg_bytes(1600, 1200)
    assert len(data) > 20 * 1024
    compressed = OlmOcr._compress_image_from_bytes(data, max_size_kb=20)
    assert compressed != data
    assert len(compressed) <= 20 * 1024
    roundtrip = Image.open(io.BytesIO(compressed))
    assert roundtrip.format in {"JPEG", "PNG"}
    assert roundtrip.size[0] <= 1600
