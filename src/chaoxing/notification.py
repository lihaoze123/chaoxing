"""仅通过 Telegram 发送本轮结果；消息使用纯文本，长消息分段发送。"""

import logging

import httpx

from chaoxing.config import TelegramConfig

logger = logging.getLogger(__name__)


class Telegram:
    def __init__(self, config: TelegramConfig) -> None:
        self.config = config

    def send(self, message: str) -> bool:
        if not self.config.bot_token.get_secret_value() or not self.config.chat_id:
            return False
        token = self.config.bot_token.get_secret_value()
        url = f"{self.config.api_base}/bot{token}/sendMessage"
        try:
            with httpx.Client(timeout=15) as http:
                # 每段最多 4000 个 UTF-16 单元，包含 emoji 时也不会超限。
                for start in range(0, len(message), 2000):
                    response = http.post(
                        url,
                        json={
                            "chat_id": self.config.chat_id,
                            "text": message[start : start + 2000],
                        },
                    )
                    response.raise_for_status()
                    if response.json().get("ok") is not True:
                        logger.warning("Telegram 拒绝了通知请求")
                        return False
        except (httpx.HTTPError, ValueError, AttributeError):
            # httpx 异常可能包含 Bot Token，不输出异常原文。
            logger.warning("Telegram 发送失败，请检查配置、代理和网络")
            return False
        return True
