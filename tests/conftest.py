import time

import httpx
import pytest


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0
        self.now += seconds


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(time, "time", lambda: clock.now)
    monkeypatch.setattr(time, "sleep", clock.sleep)
    return clock


@pytest.fixture(autouse=True)
def prohibit_real_http(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: object, **kwargs: object) -> httpx.Response:
        pytest.fail("测试禁止真实网络请求，请使用 HTTPX MockTransport")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", reject)
