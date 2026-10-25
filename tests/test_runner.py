import json
from pathlib import Path

import httpx
import pytest

from chaoxing.client import ChaoxingClient
from chaoxing.config import AccountConfig, StudyConfig
from chaoxing.models import (
    CaptchaRequired,
    Card,
    Chapter,
    Course,
    NoChapters,
    ProtocolError,
    Status,
    Task,
)
from chaoxing.runner import Runner, select_courses

COURSE = Course("course", "class", "cpi", "课程")
CHAPTER = Chapter("chapter", "章节")


def make_client(tmp_path: Path) -> ChaoxingClient:
    return ChaoxingClient(
        AccountConfig(cookies_file=tmp_path / "cookies.txt"),
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200)),
        ),
    )


def test_full_serial_flow_never_requests_quiz_endpoints(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    attachments = [
        {
            "type": "video",
            "job": True,
            "jobid": "v",
            "mid": "m",
            "objectId": "object",
            "property": {"name": "视频"},
        },
        {"type": "document", "job": True, "jobid": "d", "jtoken": "t"},
        {"type": "read", "jobid": "r", "jtoken": "t"},
        {"type": "workid", "job": True, "jobid": "quiz"},
        {"type": "video", "job": True, "jobid": "live", "property": {"liveId": "live"}},
        {"type": "unknown", "job": True, "jobid": "unknown"},
    ]

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        assert "/work/" not in path and "submit" not in path.lower()
        if path.endswith("studentcourse"):
            return httpx.Response(
                200,
                text="""<div class="chapter_unit"><ul>
              <li><div id="cur1"><a class="clicktitle">混合</a></div></li>
              <li><div id="cur2"><a class="clicktitle">空白</a><input class="knowledgeJobCount" value="0"></div></li>
              <li><div id="cur3"><a class="clicktitle">锁定</a></div></li>
              <li><div id="cur4"><a class="clicktitle">完成</a><span class="bntHoverTips">已完成</span></div></li>
            </ul></div>""",
            )
        if path.endswith("knowledge/cards"):
            if request.url.params["knowledgeid"] == "3":
                return httpx.Response(200, text="章节未开放")
            if request.url.params["num"] != "0":
                return httpx.Response(200, text="")
            items = attachments if request.url.params["knowledgeid"] == "1" else []
            return httpx.Response(200, text="mArg = " + json.dumps({"attachments": items}) + ";")
        if "/ananas/status/" in path:
            return httpx.Response(
                200, json={"status": "success", "duration": 0, "dtoken": "media-token"}
            )
        if "/multimedia/log/" in path:
            return httpx.Response(200, json={"isPassed": True})
        if "/ananas/job/" in path:
            return httpx.Response(200, json={"status": True})
        if path.endswith("studentstudyAjax"):
            return httpx.Response(200, text="<html>章节内容</html>")
        pytest.fail(f"意外请求：{path}")

    client = ChaoxingClient(
        AccountConfig(cookies_file=tmp_path / "cookies.txt"),
        httpx.Client(
            transport=httpx.MockTransport(handle),
        ),
    )
    client.http.cookies.set("_uid", "42", domain=".chaoxing.com")
    summary = Runner(client, StudyConfig(retry_interval=0)).run([COURSE])
    assert sum(result.status == Status.COMPLETED for result in summary.results) == 5
    assert sum(result.status == Status.SKIPPED for result in summary.results) == 4
    assert summary.incomplete
    assert "测验需手动完成" in summary.render()
    assert "均已处理完成" not in summary.render()
    learned_paths = [request.url.path for request in requests if "/job/" in request.url.path]
    assert learned_paths == ["/ananas/job/document", "/ananas/job/readv2"]
    client.close()


def test_retry_only_failed_task_and_continue_after_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client(tmp_path)
    monkeypatch.setattr(client, "chapters", lambda _: [CHAPTER])
    monkeypatch.setattr(
        client, "cards", lambda *_: [Card(tasks=(Task("document", "d"), Task("read", "r")))]
    )
    calls = []
    runner = Runner(client, StudyConfig(max_attempts=3, retry_interval=0))

    def execute(course: Course, chapter: Chapter, task: Task, interval: float) -> None:
        calls.append(task.id)
        if task.id == "d":
            raise ProtocolError("文档失败")

    monkeypatch.setattr(runner.study, "execute", execute)
    summary = runner.run([COURSE])
    assert calls == ["d", "d", "d", "r"]
    assert [item.status for item in summary.results] == [Status.FAILED, Status.COMPLETED]
    client.close()


def test_captcha_not_retried_and_later_task_still_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client(tmp_path)
    monkeypatch.setattr(client, "chapters", lambda _: [CHAPTER])
    monkeypatch.setattr(
        client, "cards", lambda *_: [Card(tasks=(Task("video", "v"), Task("read", "r")))]
    )
    runner = Runner(client, StudyConfig(max_attempts=3, retry_interval=0))
    calls = []

    def execute(course: Course, chapter: Chapter, task: Task, interval: float) -> None:
        calls.append(task.id)
        if task.id == "v":
            raise CaptchaRequired("请手动验证")

    monkeypatch.setattr(runner.study, "execute", execute)
    summary = runner.run([COURSE])
    assert calls == ["v", "r"]
    assert summary.incomplete
    client.close()


def test_chapter_list_failure_does_not_block_next_course(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client(tmp_path)
    other = Course("other", "class", "cpi", "其他课程")

    def chapters(course: Course) -> list[Chapter]:
        if course.id == COURSE.id:
            raise ProtocolError("章节获取失败")
        return [Chapter("done", "已学", finished=True)]

    monkeypatch.setattr(client, "chapters", chapters)
    summary = Runner(client, StudyConfig(max_attempts=1)).run([COURSE, other])
    assert [item.status for item in summary.results] == [Status.FAILED, Status.COMPLETED]
    client.close()


def test_missing_course_never_falls_back_to_all() -> None:
    with pytest.raises(Exception, match="找不到课程 ID"):
        select_courses([COURSE], ("typo",))
    same_id_other_class = Course(COURSE.id, "other-class", "cpi", "课程")
    assert len(select_courses([COURSE, COURSE, same_id_other_class], (COURSE.id,))) == 2


def test_empty_course_is_skipped_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client(tmp_path)
    calls = []

    def chapters(course: Course) -> list[Chapter]:
        calls.append(course.id)
        raise NoChapters("课程暂无章节内容")

    monkeypatch.setattr(client, "chapters", chapters)
    summary = Runner(client, StudyConfig(max_attempts=3)).run([COURSE])
    assert calls == [COURSE.id]
    assert summary.results[0].status == Status.SKIPPED
    client.close()
