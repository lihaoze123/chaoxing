import json

import pytest

from chaoxing.models import ProtocolError
from chaoxing.parsing import parse_card, parse_chapters, parse_courses


def test_pending_quiz_and_live_retained_only_as_task_markers() -> None:
    html = (
        "var mArg = "
        + json.dumps(
            {
                "attachments": [
                    {"type": "workid", "jobid": "quiz", "job": True},
                    {"type": "video", "jobid": "live", "job": True, "property": {"liveId": 4}},
                    {"type": "video", "jobid": "done", "job": True, "isPassed": True},
                    {"type": "read", "property": {"read": True}},
                    {"type": "audio", "job": True, "mid": "m", "objectId": "o", "playTime": 3500},
                ]
            }
        )
        + ";"
    )
    tasks = parse_card(html).tasks
    assert [task.kind for task in tasks] == ["workid", "live", "video"]
    assert tasks[-1].media_type == "Audio"
    assert tasks[-1].played_seconds == 3.5


def test_json_with_spaces_and_embedded_braces_is_preserved() -> None:
    card = parse_card('var mArg = {"attachments":[{"type":"read","property":{"title":"a }; b"}}]};')
    assert card.tasks[0].title == "a }; b"


@pytest.mark.parametrize(
    "html",
    [
        "mArg = broken;",
        "mArg = [];",
        'mArg = {"attachments":false};',
        'mArg = {"attachments":[{"type":"video","job":true}]};',
    ],
)
def test_malformed_card_fails_instead_of_reporting_completion(html: str) -> None:
    with pytest.raises(ProtocolError):
        parse_card(html)


def test_missing_card_and_locked_card_are_distinct() -> None:
    assert not parse_card("<html></html>").recognized
    assert parse_card("章节未开放").locked


def test_chapter_completion_and_lock_status() -> None:
    chapters = parse_chapters("""<div class="chapter_unit"><ul>
      <li><div id="cur1"><a class="clicktitle">已学</a><span class="bntHoverTips">已完成</span></div></li>
      <li><div id="cur2"><a class="clicktitle">锁定</a><span class="bntHoverTips">需要解锁</span></div></li>
      <li><div id="cur3"><a class="clicktitle">空白</a><input class="knowledgeJobCount" value="0"></div></li>
    </ul></div>""")
    assert chapters[0].finished
    assert chapters[1].locked
    assert chapters[2].task_count == 0


def test_course_cpi_at_end_of_query() -> None:
    courses = parse_courses("""<div class="course"><a href="/course?cpi=9"></a>
        <input class="courseId" value="1"><input class="clazzId" value="2">
        <span class="course-name" title="课程"></span></div>""")
    assert courses[0].cpi == "9"
