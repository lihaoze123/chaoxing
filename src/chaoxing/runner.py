"""按课程、章节、任务依次执行；重试有上限，跳过项不会视为完成。"""

import logging
import time
from collections.abc import Callable
from functools import partial
from typing import TypeVar

import httpx

from chaoxing.client import ChaoxingClient
from chaoxing.config import StudyConfig
from chaoxing.models import (
    AuthenticationError,
    CaptchaRequired,
    ChaoxingError,
    Chapter,
    Course,
    NoChapters,
    Result,
    Status,
    Summary,
    Task,
)
from chaoxing.study import Study

logger = logging.getLogger(__name__)
T = TypeVar("T")


def error_detail(exc: Exception) -> str:
    # 原始 HTTP 异常可能包含播放令牌，不直接输出 URL、请求体或 Cookie。
    if isinstance(exc, ChaoxingError):
        return str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}，请检查服务状态"
    if isinstance(exc, httpx.HTTPError):
        return "网络请求失败，请检查网络或代理"
    return f"处理异常（{type(exc).__name__}）"


def select_courses(courses: list[Course], ids: tuple[str, ...]) -> list[Course]:
    if ids:
        missing = set(ids) - {course.id for course in courses}
        if missing:
            raise ChaoxingError(f"找不到课程 ID：{', '.join(sorted(missing))}")
    selected = {}
    for course in courses:
        if not ids or course.id in ids:
            selected[(course.id, course.class_id)] = course
    if not selected:
        raise ChaoxingError("没有找到可处理的课程")
    return list(selected.values())


class Runner:
    def __init__(self, client: ChaoxingClient, config: StudyConfig) -> None:
        self.client = client
        self.config = config
        self.study = Study(client, config.speed)

    def _retry(self, operation: Callable[[], T]) -> T:
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                return operation()
            except (AuthenticationError, CaptchaRequired, NoChapters):
                # 需要手动介入的情况不重复请求。
                raise
            except Exception as exc:
                if attempt == self.config.max_attempts:
                    raise
                logger.warning("%s；准备第 %s 次尝试", error_detail(exc), attempt + 1)
                time.sleep(self.config.retry_interval)
        raise AssertionError("max_attempts 必须大于零")

    def _record(
        self,
        summary: Summary,
        course: Course,
        chapter: Chapter | None,
        task: Task | None,
        operation: Callable[[], object],
    ) -> None:
        try:
            self._retry(operation)
        except Exception as exc:
            result = Result(course, chapter, task, Status.FAILED, error_detail(exc))
            logger.warning("%s：%s", result.label, result.detail)
            summary.results.append(result)
        else:
            summary.results.append(Result(course, chapter, task, Status.COMPLETED))

    def run(self, courses: list[Course]) -> Summary:
        summary = Summary()
        for course in courses:
            logger.info("课程：%s（班级 %s）", course.title, course.class_id)
            try:
                chapters = self._retry(partial(self.client.chapters, course))
            except NoChapters as exc:
                logger.info("跳过 %s：%s", course.title, exc)
                summary.results.append(Result(course, None, None, Status.SKIPPED, str(exc)))
                continue
            except Exception as exc:
                summary.results.append(Result(course, None, None, Status.FAILED, error_detail(exc)))
                continue
            for chapter in chapters:
                self._chapter(summary, course, chapter)
        return summary

    def _chapter(self, summary: Summary, course: Course, chapter: Chapter) -> None:
        if chapter.finished:
            summary.results.append(Result(course, chapter, None, Status.COMPLETED, "此前已完成"))
            return
        # 即使章节列表显示需要解锁，也读取卡片；前一章节完成后可能已经开放。
        try:
            cards = self._retry(lambda: self.client.cards(course, chapter))
        except Exception as exc:
            summary.results.append(Result(course, chapter, None, Status.FAILED, error_detail(exc)))
            return
        if any(card.locked for card in cards):
            summary.results.append(
                Result(
                    course,
                    chapter,
                    None,
                    Status.SKIPPED,
                    "章节未开放，或需要先手动完成测验解锁",
                )
            )
            return
        seen: set[tuple[str, str, str]] = set()
        pending = False
        for card in cards:
            for task in card.tasks:
                key = (task.kind, task.id, task.object_id)
                if task.id and key in seen:
                    continue
                seen.add(key)
                pending = True
                if task.kind not in {"video", "document", "read"}:
                    detail = (
                        "测验需手动完成"
                        if task.kind == "workid"
                        else f"不支持的任务类型：{task.kind}"
                    )
                    summary.results.append(Result(course, chapter, task, Status.SKIPPED, detail))
                    continue
                self._record(
                    summary,
                    course,
                    chapter,
                    task,
                    partial(self.study.execute, course, chapter, task, card.report_interval),
                )
        if not pending:
            self._record(
                summary, course, chapter, None, lambda: self.client.visit_empty(course, chapter)
            )
