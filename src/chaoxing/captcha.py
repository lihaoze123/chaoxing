"""可选 OCR，只有遇到拦截时才加载模型。"""

import importlib
import logging
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)


class OCR(Protocol):
    def classification(self, image: bytes) -> str: ...


class CaptchaSolver:
    def __init__(self) -> None:
        self._loaded = False
        self._ocr: OCR | None = None

    def solve(self, client: httpx.Client) -> bool:
        if not self._loaded:
            self._loaded = True
            try:
                self._ocr = importlib.import_module("ddddocr").DdddOcr(show_ad=False)
            except Exception:
                logger.warning(
                    "OCR 不可用，需要时请安装 uv sync --extra ocr，否则请在浏览器手动验证"
                )
        if self._ocr is None:
            return False
        for _ in range(3):
            try:
                image = client.get("https://mooc1.chaoxing.com/processVerifyPng.ac")
                image.raise_for_status()
                if "image/" not in image.headers.get("Content-Type", ""):
                    return False
                code = self._ocr.classification(image.content)
                result = client.get(
                    "https://mooc1.chaoxing.com/html/processVerify.ac",
                    params={"ucode": code, "app": 0},
                    follow_redirects=False,
                )
                if result.status_code == 302:
                    return True
            except Exception:
                logger.debug("OCR 识别或验证码提交失败")
        return False
