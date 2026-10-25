from pathlib import Path

import pytest
from pydantic import SecretStr

from chaoxing.config import Config, load_config
from chaoxing.models import ChaoxingError


def test_precedence_and_relative_cookie_path(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[account]\nusername="file"\npassword=" keep spaces "\n'
        '[study]\nspeed=1.1\ncourse_ids=["1"]\n',
        encoding="utf-8",
    )
    config = load_config(
        path,
        {"speed": 1.8, "use_cookies": False},
        {
            "CHAOXING_USERNAME": " env ",
            "CHAOXING_SPEED": "1.5",
            "CHAOXING_COURSE_IDS": " 2, 3, ",
            "CHAOXING_USE_COOKIES": "true",
        },
    )
    assert config.account.username == "env"
    assert config.account.password.get_secret_value() == " keep spaces "
    assert config.account.use_cookies is False
    assert config.account.cookies_file == tmp_path / "cookies.txt"
    assert config.study.speed == 1.8
    assert config.study.course_ids == ("2", "3")


@pytest.mark.parametrize(
    "variable,value",
    [
        ("CHAOXING_SPEED", "nan"),
        ("CHAOXING_SPEED", "2.1"),
        ("CHAOXING_MAX_ATTEMPTS", "0"),
        ("CHAOXING_MAX_ATTEMPTS", "1.5"),
        ("CHAOXING_RETRY_INTERVAL", "inf"),
        ("CHAOXING_RETRY_INTERVAL", "-1"),
        ("CHAOXING_USE_COOKIES", "maybe"),
    ],
)
def test_invalid_env_fails(tmp_path: Path, variable: str, value: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ChaoxingError, match="配置无效"):
        load_config(path, environ={variable: value})


@pytest.mark.parametrize(
    "body",
    [
        "[study]\njobs=4",
        "[study]\nspeed=true",
        "[study]\ncourse_ids=[1]",
        "[telegram]\nchat_id=123",
        '[telegram]\nbot_token="private-token"',
        '[telegram]\napi_base="file:///tmp/test"',
        '[unknown]\nkey="value"',
    ],
)
def test_invalid_toml_schema(tmp_path: Path, body: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ChaoxingError) as info:
        load_config(path, environ={})
    assert "private-token" not in str(info.value)


def test_missing_or_malformed_file(tmp_path: Path) -> None:
    path = tmp_path / "missing.toml"
    with pytest.raises(ChaoxingError, match="无法读取"):
        load_config(path, environ={})
    path.write_text("[account", encoding="utf-8")
    with pytest.raises(ChaoxingError, match="无法读取"):
        load_config(path, environ={})


def test_secrets_hidden_and_example_valid() -> None:
    config = load_config(
        Path("config.example.toml"),
        environ={
            "CHAOXING_PASSWORD": "private-password",
            "TELEGRAM_BOT_TOKEN": "private-token",
            "TELEGRAM_CHAT_ID": "123",
        },
    )
    assert isinstance(config.account.password, SecretStr)
    assert "private-password" not in repr(config)
    assert "private-token" not in repr(config)
    assert config.telegram.chat_id == "123"
    assert Config().study.max_attempts == 3
