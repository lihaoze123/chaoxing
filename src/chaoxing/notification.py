"""仅通过 Telegram 发送本轮结果；消息使用纯文本，长消息分段发送。"""

import logging

import httpx

from chaoxing.config import TelegramConfig

logger = logging.getLogger(__name__)


class Telegram:
    def __init__(self, config: TelegramConfig) -> None:
        self.config = config

    @property
    def enabled(self) -> bool:
        return bool(self.config.bot_token.get_secret_value() and self.config.chat_id)

    def send(self, message: str) -> bool:
        if not self.enabled:
            logger.info("Telegram 未配置，已跳过通知")
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
                    try:
                        data = response.json()
                    except ValueError:
                        data = {}
                    if not isinstance(data, dict):
                        data = {}
                    if not response.is_success or data.get("ok") is not True:
                        description = str(data.get("description", "未返回有效的成功确认"))
                        description = description.replace(token, "[已隐藏]")
                        logger.warning(
                            "Telegram 通知发送失败：HTTP %s，%s",
                            response.status_code,
                            description,
                        )
                        return False
        except httpx.HTTPError as exc:
            # httpx 异常可能包含 Bot Token，不输出异常原文。
            logger.warning("Telegram 发送失败：%s，请检查网络或代理", type(exc).__name__)
            return False
        logger.info("Telegram 通知已发送（%s 段）", (len(message) + 1999) // 2000)
        return True
