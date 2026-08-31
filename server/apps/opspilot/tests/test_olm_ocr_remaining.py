"""OlmOcr：图片压缩降级、predict/base64 入口、OCR 空响应与异常。"""
import base64
import io
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from apps.opspilot.metis.ocr.olm_ocr import OlmOcr

pytestmark = pytest.mark.unit


def _jpeg_bytes(size, color=(10, 20, 30)):
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _png_rgba_bytes(size=(80, 80)):
    img = Image.new("RGBA", size, (255, 0, 0, 120))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_compress_returns_original_when_under_limit_and_compresses_large_rgb():
    small = _jpeg_bytes((20, 20))
    assert OlmOcr._compress_image_from_bytes(small, max_size_kb=600) == small

    large = _jpeg_bytes((1800, 1800))
    if len(large) <= 20 * 1024:
        large = large * 40
    compressed = OlmOcr._compress_image_from_bytes(large if len(large) > 20 * 1024 else _jpeg_bytes((2500, 2500)), max_size_kb=20)
    assert len(compressed) <= 20 * 1024
    Image.open(io.BytesIO(compressed)).verify()


def test_compress_png_keeps_alpha_and_palette_converts_to_jpeg():
    png = _png_rgba_bytes((400, 400))
    out = OlmOcr._compress_image_from_bytes(png, max_size_kb=5)
    img = Image.open(io.BytesIO(out))
    assert img.format in {"PNG", "JPEG"}

    pal = Image.new("P", (300, 300))
    pal.putpalette([i % 256 for i in range(768)])
    pal_buf = io.BytesIO()
    pal.save(pal_buf, format="PNG")
    converted = OlmOcr._compress_image_from_bytes(pal_buf.getvalue(), max_size_kb=8)
    Image.open(io.BytesIO(converted)).verify()

    gray = Image.new("L", (400, 400), 80)
    gray_buf = io.BytesIO()
    gray.save(gray_buf, format="PNG")
    gray_out = OlmOcr._compress_image_from_bytes(gray_buf.getvalue(), max_size_kb=8)
    Image.open(io.BytesIO(gray_out)).verify()


def test_predict_paths_and_perform_ocr_empty_or_error(tmp_path):
    with (
        patch("apps.opspilot.metis.ocr.olm_ocr.SSRFValidator.validate_llm_endpoint") as validate,
        patch("apps.opspilot.metis.ocr.olm_ocr.OpenAI") as openai_cls,
    ):
        client = MagicMock()
        openai_cls.return_value = client
        ocr = OlmOcr("http://127.0.0.1:8080/v1", "sk", model="ocr-x")
    validate.assert_called_once_with("http://127.0.0.1:8080/v1")

    small = _jpeg_bytes((10, 10))
    with patch.object(ocr, "_perform_ocr", return_value="from-b64") as perform:
        assert ocr.predict_from_base64(base64.b64encode(small).decode()) == "from-b64"
        perform.assert_called_once()

    img_path = tmp_path / "a.jpg"
    img_path.write_bytes(small)
    with patch.object(ocr, "_perform_ocr", return_value="from-file") as perform:
        assert ocr.predict(str(img_path)) == "from-file"
        perform.assert_called_once()

    client.chat.completions.create.return_value = SimpleChoices("hello")
    assert ocr._perform_ocr("abc") == "hello"

    client.chat.completions.create.return_value = MagicMock(choices=[])
    assert ocr._perform_ocr("abc") == "无法识别文本"

    client.chat.completions.create.side_effect = RuntimeError("quota")
    assert ocr._perform_ocr("abc") == "请求失败: quota"


class SimpleChoices:
    def __init__(self, text):
        self.choices = [MagicMock(message=MagicMock(content=text))]
