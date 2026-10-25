"""用参考实现产生的请求轨迹验证视频协议行为。"""

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from chaoxing.client import ChaoxingClient
from chaoxing.config import AccountConfig
from chaoxing.models import Chapter, Course, Task
from chaoxing.study import Study

FIXTURE = Path(__file__).parent / "fixtures" / "video_protocol.json"
COURSE = Course("course", "class", "cpi", "课程")


def make_http(scenario: dict[str, Any], trace: list[dict[str, Any]]) -> httpx.Client:
    report_count = 0
    status_count = 0
    denied = False

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal report_count, status_count, denied
        trace.append(
            {
                "at": round(time.time(), 6),
                "path": request.url.path,
                "params": dict(request.url.params),
                "referer": request.headers.get("referer"),
            }
        )
        if "/status/" in request.url.path:
            status_count += 1
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "duration": scenario["duration"],
                    "dtoken": "refreshed"
                    if status_count > 1
                    and scenario["mode"] in {"refresh_403", "forbidden_exhausted"}
                    else "token",
                    "crc": "",
                    "key": "",
                    "playTime": 20 if status_count > 1 else 99,
                },
            )
        report_count += 1
        params = request.url.params
        if scenario["mode"] == "rt_fallback" and params["rt"] == "0.9":
            return httpx.Response(403)
        if scenario["mode"] == "refresh_403" and params["isdrag"] == "3" and not denied:
            denied = True
            return httpx.Response(403)
        if scenario["mode"] == "forbidden_exhausted":
            if params["dtype"] == "Audio":
                return httpx.Response(200, json={"isPassed": True})
            if params["isdrag"] == "3":
                return httpx.Response(403)
            return httpx.Response(200, json={"isPassed": False})
        if scenario["mode"] == "instant":
            passed = True
        elif scenario["mode"] == "delayed_end":
            passed = report_count >= 8
        elif scenario["mode"] == "audio_after_failure":
            if params["dtype"] == "Video":
                return httpx.Response(500)
            passed = True
        else:
            passed = params["isdrag"] == "3" and int(params["playingTime"]) >= scenario["duration"]
        return httpx.Response(200, json={"isPassed": passed})

    return httpx.Client(transport=httpx.MockTransport(handle))


def cases() -> list[dict[str, Any]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", cases(), ids=lambda case: case["name"])
def test_requests_match_reference_trace(
    case: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("random.uniform", lambda lower, upper: (lower + upper) / 2)
    trace: list[dict[str, Any]] = []
    http = make_http(case, trace)
    client = ChaoxingClient(AccountConfig(cookies_file=tmp_path / "cookies.txt"), http)
    # 两边都模拟 OCR 的三次失败及其耗时，隔离识别器实现来对照媒体恢复协议。
    monkeypatch.setattr(client.captcha, "solve", lambda _: time.sleep(6) or False)
    monkeypatch.setattr(client, "reload_cookies", lambda: None)
    http.cookies.set("_uid", "42", domain=".chaoxing.com")
    study = Study(client, case["speed"])
    study.execute(
        COURSE,
        Chapter("chapter", "章节"),
        Task(
            "video",
            "job",
            "视频",
            object_id="object",
            played_seconds=case["played"],
            rt=case.get("rt", ""),
            other_info=case.get("other_info", "nodeId_chapter-"),
            extra={
                "attDuration": "120",
                "attDurationEnc": "duration-enc",
                "videoFaceCaptureEnc": "face-enc",
            },
        ),
    )
    assert trace == case["trace"]
    client.close()
