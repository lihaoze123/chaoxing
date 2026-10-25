from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from chaoxing.cli import app
from chaoxing.config import Config
from chaoxing.models import Chapter, Course, Result, Status, Summary, Task

cli = CliRunner()
COURSE = Course("1", "class", "cpi", "课程")


def config_file(path: Path) -> Path:
    path.write_text('[account]\nusername="user"\npassword="private-password"\n', encoding="utf-8")
    return path


def test_help_without_initializing_client() -> None:
    with patch("chaoxing.cli.ChaoxingClient") as client:
        result = cli.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "超星课程学习工具" in result.output
    client.assert_not_called()


def test_config_failure_has_no_traceback_or_secret(tmp_path: Path) -> None:
    path = config_file(tmp_path / "config.toml")
    with path.open("a", encoding="utf-8") as target:
        target.write('[telegram]\nbot_token="private-token"\n')
    result = cli.invoke(app, ["--config", str(path)])
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "private-password" not in result.output
    assert "private-token" not in result.output


def test_course_listing_does_not_start_study(tmp_path: Path) -> None:
    client = MagicMock()
    client.courses.return_value = [COURSE]
    with (
        patch("chaoxing.cli.ChaoxingClient", return_value=client),
        patch("chaoxing.cli.Runner") as runner,
    ):
        result = cli.invoke(
            app, ["-c", str(config_file(tmp_path / "config.toml")), "--list-courses"]
        )
    assert result.exit_code == 0
    assert "课程" in result.output
    runner.assert_not_called()
    client.close.assert_called_once()


def test_incomplete_exit_code_and_summary_are_sent(tmp_path: Path) -> None:
    client = MagicMock()
    client.courses.return_value = [COURSE]
    summary = Summary(
        [
            Result(
                COURSE, Chapter("c", "章节"), Task("workid", "q"), Status.SKIPPED, "测验需手动完成"
            )
        ]
    )
    with (
        patch("chaoxing.cli.ChaoxingClient", return_value=client),
        patch("chaoxing.cli.Runner") as runner,
        patch("chaoxing.cli.Telegram") as telegram,
    ):
        runner.return_value.run.return_value = summary
        result = cli.invoke(app, ["-c", str(config_file(tmp_path / "config.toml"))])
    assert result.exit_code == 2
    telegram.return_value.send.assert_called_once_with(summary.render())
    client.close.assert_called_once()


def test_keyboard_interrupt_closes_client_and_notifies(tmp_path: Path) -> None:
    client = MagicMock()
    client.login.side_effect = KeyboardInterrupt
    with (
        patch("chaoxing.cli.ChaoxingClient", return_value=client),
        patch("chaoxing.cli.Telegram") as telegram,
    ):
        result = cli.invoke(app, ["-c", str(config_file(tmp_path / "config.toml"))])
    assert result.exit_code == 130
    assert "手动中断" in telegram.return_value.send.call_args.args[0]
    client.close.assert_called_once()


def test_noninteractive_missing_credentials_fails(tmp_path: Path) -> None:
    path = tmp_path / "empty.toml"
    path.write_text("", encoding="utf-8")
    with patch("chaoxing.cli.load_config", return_value=Config()):
        result = cli.invoke(app, ["-c", str(path)])
    assert result.exit_code == 1
    assert "非交互" in result.output
