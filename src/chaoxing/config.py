"""Pydantic 配置模型；默认值 < TOML < 环境变量 < 显式命令行参数。"""

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from chaoxing.models import ChaoxingError


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class AccountConfig(ConfigModel):
    username: str = ""
    password: SecretStr = SecretStr("")
    use_cookies: bool = False
    cookies_file: Path = Path("cookies.txt")

    @field_validator("username")
    @classmethod
    def clean_username(cls, value: str) -> str:
        return value.strip()


class StudyConfig(ConfigModel):
    course_ids: tuple[str, ...] = ()
    speed: float = Field(default=1.0, ge=1, le=2, allow_inf_nan=False)
    max_attempts: int = Field(default=3, ge=1)
    retry_interval: float = Field(default=3.0, ge=0, allow_inf_nan=False)

    @field_validator("course_ids", mode="before")
    @classmethod
    def split_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        if isinstance(value, (tuple, list)) and all(isinstance(item, str) for item in value):
            return tuple(item.strip() for item in value if item.strip())
        return value

    @field_validator("speed", "max_attempts", "retry_interval", mode="before")
    @classmethod
    def reject_boolean(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("必须是数值，不能是布尔值")
        return value


class TelegramConfig(ConfigModel):
    bot_token: SecretStr = SecretStr("")
    chat_id: str = ""
    api_base: str = "https://api.telegram.org"

    @field_validator("api_base")
    @classmethod
    def validate_base(cls, value: str) -> str:
        base = urlparse(value)
        if (
            base.scheme not in {"http", "https"}
            or not base.netloc
            or base.query
            or base.fragment
            or base.username
            or base.password
        ):
            raise ValueError("必须是无凭证、查询参数和锚点的 HTTP(S) 基础地址")
        return value.rstrip("/")

    @model_validator(mode="after")
    def check_pair(self) -> Self:
        if bool(self.bot_token.get_secret_value()) != bool(self.chat_id):
            raise ValueError("bot_token 和 chat_id 必须同时配置或同时留空")
        return self


class Config(ConfigModel):
    account: AccountConfig = Field(default_factory=AccountConfig)
    study: StudyConfig = Field(default_factory=StudyConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)


def load_config(
    path: Path | None = None,
    overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> Config:
    active = path if path is not None else Path("config.toml")
    data: dict[str, Any] = {}
    try:
        if path is not None or active.exists():
            with active.open("rb") as source:
                data = tomllib.load(source)
    except (OSError, ValueError) as exc:
        raise ChaoxingError(f"无法读取 TOML 配置：{active}（{type(exc).__name__}）") from exc
    env = os.environ if environ is None else environ
    schemas = {"account": AccountConfig, "study": StudyConfig, "telegram": TelegramConfig}
    for name, schema in schemas.items():
        section = data.setdefault(name, {})
        if not isinstance(section, dict):
            raise ChaoxingError(f"{name} 必须是 TOML 配置节")
        for key in schema.model_fields:
            prefix = "TELEGRAM" if name == "telegram" else "CHAOXING"
            if (value := env.get(f"{prefix}_{key.upper()}")) is not None:
                section[key] = value
            if name != "telegram" and (value := (overrides or {}).get(key)) is not None:
                section[key] = value
    try:
        config = Config.model_validate(data)
    except ValidationError as exc:
        # 不输出输入值或校验上下文，避免未知字段和错误格式泄露密码/Token。
        details = "; ".join(
            f"{'.'.join(map(str, error['loc']))}: {error['msg']}"
            for error in exc.errors(include_input=False, include_context=False, include_url=False)
        )
        raise ChaoxingError(f"配置无效：{details}") from exc
    cookies_file = config.account.cookies_file.expanduser()
    if not cookies_file.is_absolute():
        cookies_file = active.resolve().parent / cookies_file
    account = config.account.model_copy(update={"cookies_file": cookies_file})
    return config.model_copy(update={"account": account})
