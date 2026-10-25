"""Typer 命令行入口。"""

import logging
import sys
from getpass import getpass
from pathlib import Path
from typing import Annotated

import typer
from pydantic import SecretStr

from chaoxing.client import ChaoxingClient
from chaoxing.config import AccountConfig, load_config
from chaoxing.models import ChaoxingError
from chaoxing.notification import Telegram
from chaoxing.output import configure_logging, show_courses, show_summary
from chaoxing.runner import Runner, error_detail, select_courses

logger = logging.getLogger(__name__)
app = typer.Typer(
    add_completion=False,
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="chaoxing：超星课程学习工具。",
)


def _credentials(account: AccountConfig) -> AccountConfig:
    if account.use_cookies or (account.username and account.password.get_secret_value()):
        return account
    if not sys.stdin.isatty():
        raise ChaoxingError("非交互运行需要配置账号密码，或启用 use_cookies")
    username = account.username or input("手机号：").strip()
    password = account.password.get_secret_value() or getpass("密码：")
    if not username or not password:
        raise ChaoxingError("账号密码不能为空")
    return account.model_copy(update={"username": username, "password": SecretStr(password)})


def run(
    config_path: Path | None = None,
    *,
    course_ids: str | None = None,
    list_courses: bool = False,
    use_cookies: bool | None = None,
    speed: float | None = None,
    max_attempts: int | None = None,
    retry_interval: float | None = None,
    verbose: bool = False,
) -> int:
    configure_logging(verbose)
    notification: Telegram | None = None
    client: ChaoxingClient | None = None
    try:
        config = load_config(
            config_path,
            {
                "course_ids": course_ids,
                "use_cookies": use_cookies,
                "speed": speed,
                "max_attempts": max_attempts,
                "retry_interval": retry_interval,
            },
        )
        notification = Telegram(config.telegram)
        client = ChaoxingClient(_credentials(config.account))
        client.login()
        courses = client.courses()
        if list_courses:
            show_courses(courses)
            return 0
        summary = Runner(client, config.study).run(select_courses(courses, config.study.course_ids))
        show_summary(summary)
        notification.send(summary.render())
        return 2 if summary.incomplete else 0
    except KeyboardInterrupt:
        logger.warning("运行已中断")
        if notification:
            notification.send("chaoxing：运行被手动中断，任务尚未全部完成。")
        return 130
    except Exception as exc:
        message = f"chaoxing：运行失败，{error_detail(exc)}"
        logger.error("%s", message)
        if notification:
            notification.send(message)
        return 1
    finally:
        if client:
            client.close()


@app.command(help="超星课程学习工具，支持媒体、文档和阅读任务。")
def command(
    config: Annotated[Path | None, typer.Option("--config", "-c", help="TOML 配置路径")] = None,
    courses: Annotated[str | None, typer.Option(help="课程 ID，逗号分隔；留空处理所有课程")] = None,
    list_courses: Annotated[bool, typer.Option("--list-courses", help="只显示课程列表")] = False,
    use_cookies: Annotated[bool | None, typer.Option("--use-cookies/--no-use-cookies")] = None,
    speed: Annotated[float | None, typer.Option(min=1, max=2, help="播放倍速，默认 1")] = None,
    max_attempts: Annotated[
        int | None, typer.Option(min=1, help="失败操作最多尝试次数，默认 3")
    ] = None,
    retry_interval: Annotated[
        float | None, typer.Option(min=0, help="失败重试间隔秒数，默认 3")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="调试日志")] = False,
) -> None:
    raise typer.Exit(
        run(
            config,
            course_ids=courses,
            list_courses=list_courses,
            use_cookies=use_cookies,
            speed=speed,
            max_attempts=max_attempts,
            retry_interval=retry_interval,
            verbose=verbose,
        )
    )


def main() -> None:
    app()
