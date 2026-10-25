from pathlib import Path

import httpx
import pytest

from chaoxing.client import ChaoxingClient
from chaoxing.config import AccountConfig
from chaoxing.models import Chapter, Course, ProtocolError, Task
from chaoxing.study import Study

COURSE = Course("course", "class", "cpi", "课程")
CHAPTER = Chapter("chapter", "章节")


def test_media_resumes_and_advances_with_elapsed_time(tmp_path: Path) -> None:
    positions: list[int] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if "/status/" in request.url.path:
            return httpx.Response(
                200, json={"status": "success", "duration": 10, "dtoken": "t", "playTime": 4}
            )
        position = int(request.url.params["playingTime"])
        positions.append(position)
        return httpx.Response(200, json={"isPassed": position == 10})

    client = ChaoxingClient(
        AccountConfig(cookies_file=tmp_path / "cookie"),
        httpx.Client(
            transport=httpx.MockTransport(handle),
        ),
    )
    client.http.cookies.set("_uid", "42", domain=".chaoxing.com")
    Study(client, speed=2).execute(COURSE, CHAPTER, Task("video", "v", object_id="o"), interval=3)
    assert positions[0] == 4
    assert positions[-1] == 10
    assert all(left <= right for left, right in zip(positions, positions[1:], strict=False))
    assert len(positions) >= 2
    client.close()


def test_unconfirmed_media_end_is_bounded(tmp_path: Path) -> None:
    reports = []

    def handle(request: httpx.Request) -> httpx.Response:
        if "/status/" in request.url.path:
            return httpx.Response(200, json={"status": "success", "duration": 0, "dtoken": "t"})
        reports.append(request)
        return httpx.Response(200, json={"isPassed": False})

    client = ChaoxingClient(
        AccountConfig(cookies_file=tmp_path / "cookie"),
        httpx.Client(
            transport=httpx.MockTransport(handle),
        ),
    )
    client.http.cookies.set("_uid", "42", domain=".chaoxing.com")
    with pytest.raises(ProtocolError, match="五次"):
        Study(client, speed=1).execute(COURSE, CHAPTER, Task("video", "v", object_id="o"), 60)
    assert len(reports) == 5
    client.close()


@pytest.mark.parametrize("kind", ["document", "read"])
def test_http_200_business_failure_is_not_success(tmp_path: Path, kind: str) -> None:
    client = ChaoxingClient(
        AccountConfig(cookies_file=tmp_path / "cookie"),
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"status": False})),
        ),
    )
    with pytest.raises(ProtocolError, match="未得到成功确认"):
        Study(client, speed=1).execute(COURSE, CHAPTER, Task(kind, "task"), 60)
    client.close()


def test_audio_fallback_uses_audio_referer(tmp_path: Path) -> None:
    referers = []

    def handle(request: httpx.Request) -> httpx.Response:
        referer = request.headers["referer"]
        referers.append(referer)
        if "/status/" in request.url.path:
            if "video/" in referer:
                return httpx.Response(200, json={"status": "failed"})
            return httpx.Response(200, json={"status": "success", "duration": 0, "dtoken": "t"})
        assert request.url.params["dtype"] == "Audio"
        return httpx.Response(200, json={"isPassed": True})

    client = ChaoxingClient(
        AccountConfig(cookies_file=tmp_path / "cookie"),
        httpx.Client(
            transport=httpx.MockTransport(handle),
        ),
    )
    client.http.cookies.set("_uid", "42", domain=".chaoxing.com")
    Study(client, speed=1).execute(COURSE, CHAPTER, Task("video", "v", object_id="o"), 60)
    assert "video/" in referers[0]
    assert "audio/" in referers[1]
    client.close()
