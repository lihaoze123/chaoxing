"""HTML/JSON 的动态数据只在此模块转换为课程模型。"""

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

from chaoxing.models import Card, Chapter, Course, ProtocolError, Task


def _attr(tag: Tag, name: str) -> str:
    value = tag.get(name, "")
    return " ".join(value) if isinstance(value, list) else str(value)


def _required(tag: Tag | BeautifulSoup, selector: str) -> Tag:
    result = tag.select_one(selector)
    if result is None:
        raise ProtocolError(f"课程页面缺少必要字段：{selector}")
    return result


def parse_courses(html: str) -> list[Course]:
    courses = []
    for course in BeautifulSoup(html, "html.parser").select("div.course"):
        if course.select_one(".not-open-tip"):
            continue
        query = parse_qs(urlparse(_attr(_required(course, "a"), "href")).query)
        if not query.get("cpi"):
            raise ProtocolError("课程链接缺少 cpi")
        courses.append(
            Course(
                id=_attr(_required(course, "input.courseId"), "value"),
                class_id=_attr(_required(course, "input.clazzId"), "value"),
                cpi=query["cpi"][0],
                title=_attr(_required(course, "span.course-name"), "title"),
            )
        )
    return courses


def parse_folders(html: str) -> list[str]:
    return [
        _attr(folder, "fileid")
        for folder in BeautifulSoup(html, "html.parser").select("ul.file-list>li[fileid]")
        if _attr(folder, "fileid")
    ]


def parse_chapters(html: str) -> list[Chapter]:
    chapters = []
    for point in BeautifulSoup(html, "html.parser").select("div.chapter_unit li div[id]"):
        match = re.fullmatch(r"cur(\d{1,20})", _attr(point, "id"))
        if match is None:
            continue
        tip = point.select_one("span.bntHoverTips")
        status = tip.get_text() if tip else ""
        count = point.select_one("input.knowledgeJobCount")
        try:
            task_count = int(_attr(count, "value")) if count is not None else None
        except ValueError as exc:
            raise ProtocolError("章节任务数量无效") from exc
        chapters.append(
            Chapter(
                id=match.group(1),
                title=_required(point, "a.clicktitle").get_text(strip=True),
                finished="已完成" in status,
                locked="解锁" in status,
                task_count=task_count,
            )
        )
    return chapters


def _parse_task(card: dict[str, Any]) -> Task | None:
    if card.get("isPassed", False):
        return None
    kind = str(card.get("type", "unknown")).lower()
    prop = card.get("property", {})
    if not isinstance(prop, dict):
        raise ProtocolError("任务属性格式无效")
    live = any(
        "live" in str(value).lower()
        for value in (kind, prop.get("type", ""), prop.get("resourceType", ""))
    ) or any(prop.get(key) is not None for key in ("liveId", "streamName", "vdoid"))
    if live:
        kind = "live"
    if kind == "read" and prop.get("read", False):
        return None
    if card.get("job") is None and kind not in {"read", "workid", "live"}:
        return None
    if kind in {"video", "audio"} and not card.get("mid"):
        raise ProtocolError("视频/音频缺少 mid，可能尚未转码完成")
    return Task(
        kind="video" if kind == "audio" else kind,
        id=str(card.get("jobid", card.get("id", ""))),
        title=str(prop.get("name", prop.get("title", kind))),
        object_id=str(card.get("objectId", "")),
        token=str(card.get("jtoken", "")),
        other_info=str(card.get("otherInfo", "")).split("&")[0],
        played_seconds=max(0.0, float(card.get("playTime", 0)) / 1000),
        rt=str(prop.get("rt", "")),
        media_type="Audio" if kind == "audio" else "Video",
        extra={
            key: str(card.get(key, ""))
            for key in ("attDuration", "attDurationEnc", "videoFaceCaptureEnc")
            if card.get(key)
        },
    )


def parse_card(html: str) -> Card:
    if "章节未开放" in html:
        return Card(locked=True, recognized=True)
    # 使用 JSONDecoder 读取对象，避免嵌套对象或字符串中的 }; 提前截断。
    match = re.search(r"\bmArg\s*=\s*", html)
    if match is None:
        return Card()
    try:
        data, _ = json.JSONDecoder().raw_decode(html[match.end() :].lstrip())
        if not isinstance(data, dict):
            raise ValueError
        defaults = data.get("defaults", {})
        attachments = data.get("attachments", [])
        if not isinstance(defaults, dict) or not isinstance(attachments, list):
            raise ValueError
        interval = float(defaults.get("reportTimeInterval", 60))
        if not 1 <= interval <= 300:
            raise ValueError
        if any(not isinstance(item, dict) for item in attachments):
            raise ValueError
        tasks = tuple(task for item in attachments if (task := _parse_task(item)) is not None)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ProtocolError("无法解析章节任务卡片") from exc
    return Card(tasks, bool(defaults.get("notOpen", False)), True, interval)
