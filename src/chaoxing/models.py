"""在解析边界将外部数据转换为明确的内部类型。"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class ChaoxingError(Exception):
    """可以直接向用户展示的错误，不携带凭证或原始 HTTP 请求。"""


class AuthenticationError(ChaoxingError):
    pass


class CaptchaRequired(ChaoxingError):
    pass


class ProtocolError(ChaoxingError):
    pass


@dataclass(frozen=True)
class Course:
    id: str
    class_id: str
    cpi: str
    title: str


@dataclass(frozen=True)
class Chapter:
    id: str
    title: str
    finished: bool = False
    locked: bool = False
    task_count: int | None = None


@dataclass(frozen=True)
class Task:
    kind: str
    id: str = ""
    title: str = ""
    object_id: str = ""
    token: str = ""
    other_info: str = ""
    played_seconds: float = 0
    rt: str = ""
    media_type: Literal["Video", "Audio"] = "Video"
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Card:
    tasks: tuple[Task, ...] = ()
    locked: bool = False
    recognized: bool = False
    report_interval: float = 60


class Status(StrEnum):
    COMPLETED = "完成"
    SKIPPED = "跳过"
    FAILED = "失败"


@dataclass(frozen=True)
class Result:
    course: Course
    chapter: Chapter | None
    task: Task | None
    status: Status
    detail: str = ""

    @property
    def label(self) -> str:
        parts = [f"{self.course.title}（班级 {self.course.class_id}）"]
        if self.chapter:
            parts.append(self.chapter.title)
        if self.task:
            parts.append(f"{self.task.title or self.task.kind}（ID {self.task.id or '?'}）")
        return " / ".join(parts)


@dataclass
class Summary:
    results: list[Result] = field(default_factory=list)

    @property
    def incomplete(self) -> bool:
        return not self.results or any(item.status != Status.COMPLETED for item in self.results)

    def render(self) -> str:
        counts = {status: sum(item.status == status for item in self.results) for status in Status}
        lines = [
            "chaoxing：本轮处理结束",
            "，".join(f"{status.value} {counts[status]} 项" for status in Status),
        ]
        for item in self.results:
            if item.status != Status.COMPLETED:
                lines.append(f"[{item.status.value}] {item.label}：{item.detail}")
        if self.incomplete:
            lines.append("尚有未完成项。测验、解锁或验证码需手动处理，之后可重新运行。")
        else:
            lines.append("本轮所选课程的学习任务均已处理完成。")
        return "\n".join(lines)
