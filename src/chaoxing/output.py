"""Rich 终端展示；非交互输出保持普通文本。"""

import logging
from collections.abc import Callable, Generator
from contextlib import contextmanager

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeRemainingColumn
from rich.table import Table
from rich.text import Text

from chaoxing.models import Course, Status, Summary

console = Console(stderr=True)


def configure_logging(verbose: bool) -> None:
    handler: logging.Handler = (
        RichHandler(console=console, markup=False, show_path=False)
        if console.is_terminal
        else logging.StreamHandler()
    )
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s" if console.is_terminal else "%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[handler],
        force=True,
    )
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def show_courses(courses: list[Course]) -> None:
    out = Console()
    if not out.is_terminal:
        for course in courses:
            print(f"{course.id}\t班级 {course.class_id}\t{course.title}")
        return
    table = Table("课程 ID", "班级 ID", "课程", title="课程列表")
    for course in courses:
        table.add_row(Text(course.id), Text(course.class_id), Text(course.title))
    out.print(table)


def show_summary(summary: Summary) -> None:
    if not console.is_terminal:
        logging.getLogger(__name__).info("\n%s", summary.render())
        return
    table = Table("状态", "课程 / 章节 / 任务", "说明", title="本轮结果")
    for result in summary.results:
        color = (
            "green"
            if result.status == Status.COMPLETED
            else ("yellow" if result.status == Status.SKIPPED else "red")
        )
        table.add_row(
            Text(result.status.value, style=color), Text(result.label), Text(result.detail)
        )
    console.print(table)
    console.print(Text(summary.render().splitlines()[-1]))


@contextmanager
def media_progress(title: str, duration: int, initial: float) -> Generator[Callable[[float], None]]:
    if not console.is_terminal:
        yield lambda _: None
        return
    with Progress(
        TextColumn("{task.description}", markup=False),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=True,
        auto_refresh=False,
    ) as progress:
        task_id = progress.add_task(title, total=max(1, duration), completed=int(initial))
        yield lambda position: progress.update(task_id, completed=position, refresh=True)
