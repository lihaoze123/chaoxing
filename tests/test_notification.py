import json
import logging
from unittest.mock import patch

import httpx
import pytest
from pydantic import SecretStr

from chaoxing.config import TelegramConfig
from chaoxing.notification import Telegram


def test_disabled_telegram_makes_no_network_request() -> None:
    assert not Telegram(TelegramConfig()).send("message")


def test_plaintext_chunking_keeps_emoji_and_angle_brackets() -> None:
    chunks = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "parse_mode" not in body
        assert body["chat_id"] == "123"
        assert len(body["text"].encode("utf-16-le")) // 2 <= 4096
        chunks.append(body["text"])
        return httpx.Response(200, json={"ok": True})

    http = httpx.Client(transport=httpx.MockTransport(handle))
    message = "<课程&章节>" + "😀" * 4200
    with patch("chaoxing.notification.httpx.Client", return_value=http):
        assert Telegram(TelegramConfig(bot_token=SecretStr("private-token"), chat_id="123")).send(
            message
        )
    assert "".join(chunks) == message
    assert len(chunks) == 3


def test_send_failure_does_not_leak_token(caplog: pytest.LogCaptureFixture) -> None:
    http = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    with (
        caplog.at_level(logging.WARNING),
        patch("chaoxing.notification.httpx.Client", return_value=http),
    ):
        assert not Telegram(
            TelegramConfig(bot_token=SecretStr("private-token"), chat_id="123")
        ).send("text")
    assert "private-token" not in caplog.text
    assert "发送失败" in caplog.text
