"""兼容浏览器 Cookie 请求头格式；写入采用原子替换。"""

import os
import tempfile
from pathlib import Path

import httpx

from chaoxing.models import ChaoxingError


def read_cookies(path: Path) -> httpx.Cookies:
    cookies = httpx.Cookies()
    if not path.exists():
        return cookies
    try:
        for entry in path.read_text(encoding="utf-8").strip().split(";"):
            if not entry.strip():
                continue
            name, separator, value = entry.strip().partition("=")
            if not separator or not name:
                raise ValueError
            cookies.set(name, value, domain=".chaoxing.com")
    except (OSError, ValueError) as exc:
        raise ChaoxingError("无法读取 Cookie 文件，请使用 name=value; name2=value2 格式") from exc
    return cookies


def save_cookies(cookies: httpx.Cookies, path: Path) -> None:
    values = {item.name: item.value for item in cookies.jar}
    temporary: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".cookies-", dir=path.parent)
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            target.write("; ".join(f"{name}={value}" for name, value in values.items()))
        os.replace(temporary, path)
    except OSError as exc:
        raise ChaoxingError("无法保存 Cookie 文件，请检查目录权限") from exc
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def cookie_value(cookies: httpx.Cookies, name: str, default: str = "") -> str:
    # 同名 Cookie 可能来自不同子域，避免 httpx.Cookies.get 的 CookieConflict。
    values = [item.value for item in cookies.jar if item.name == name]
    return (values[-1] or default) if values else default
