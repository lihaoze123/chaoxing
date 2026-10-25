from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from chaoxing.client import ChaoxingClient
from chaoxing.config import AccountConfig
from chaoxing.cookies import cookie_value, read_cookies, save_cookies
from chaoxing.models import (
    AuthenticationError,
    CaptchaRequired,
    Chapter,
    Course,
    NoChapters,
    ProtocolError,
)

COURSE = Course("c", "class", "cpi", "课程")


def test_explicit_empty_chapter_page_is_distinct_from_unknown_page(tmp_path: Path) -> None:
    client = ChaoxingClient(
        AccountConfig(cookies_file=tmp_path / "cookie"),
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, text='<div class="chapter_body"><p>暂无章节内容</p></div>'
                )
            ),
        ),
    )
    with pytest.raises(NoChapters, match="暂无章节内容"):
        client.chapters(COURSE)
    client.close()


def test_password_login_is_encrypted_and_persists_cookies(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert form["uname"] != ["user"]
        assert form["password"] != ["password"]
        return httpx.Response(
            200,
            json={"status": True},
            headers={
                "set-cookie": "_uid=42; Domain=.chaoxing.com; Path=/",
            },
        )

    path = tmp_path / "cookies.txt"
    client = ChaoxingClient(
        AccountConfig(username="user", password=SecretStr("password"), cookies_file=path),
        httpx.Client(transport=httpx.MockTransport(handle)),
    )
    client.login()
    assert cookie_value(read_cookies(path), "_uid") == "42"
    client.close()


def test_stale_cookie_falls_back_to_password(tmp_path: Path) -> None:
    path = tmp_path / "cookies.txt"
    path.write_text("_uid=old", encoding="utf-8")
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("courselistdata"):
            return httpx.Response(200, text='<input name="password">')
        return httpx.Response(
            200,
            json={"status": True},
            headers={
                "set-cookie": "_uid=new; Domain=.chaoxing.com; Path=/",
            },
        )

    client = ChaoxingClient(
        AccountConfig(
            username="u",
            password=SecretStr("p"),
            use_cookies=True,
            cookies_file=path,
        ),
        httpx.Client(transport=httpx.MockTransport(handle)),
    )
    client.login()
    assert len(calls) == 2
    assert client.uid == "new"
    client.close()


def test_cookie_only_login_requires_valid_cookie(tmp_path: Path) -> None:
    client = ChaoxingClient(AccountConfig(use_cookies=True, cookies_file=tmp_path / "missing"))
    with pytest.raises(AuthenticationError):
        client.login()
    client.close()


def test_unrecognized_task_page_never_completes_chapter(tmp_path: Path) -> None:
    client = ChaoxingClient(
        AccountConfig(cookies_file=tmp_path / "cookie"),
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text="unexpected")),
        ),
    )
    with pytest.raises(ProtocolError, match="不能将该章节视为已完成"):
        client.cards(COURSE, Chapter("1", "有任务", task_count=1))
    assert client.cards(COURSE, Chapter("2", "空章节", task_count=0))
    client.close()


def test_captcha_html_with_http_200_is_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = ChaoxingClient(
        AccountConfig(cookies_file=tmp_path / "cookie"),
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text="请输入验证码")),
        ),
    )
    monkeypatch.setattr(client.captcha, "solve", lambda _: False)
    with pytest.raises(CaptchaRequired):
        client.request("GET", "https://mooc1.chaoxing.com/test")
    client.close()


def test_cookie_values_with_equals_and_atomic_replace(tmp_path: Path) -> None:
    path = tmp_path / "cookies.txt"
    path.write_text("token=a=b; _uid=1;", encoding="utf-8")
    cookies = read_cookies(path)
    assert cookie_value(cookies, "token") == "a=b"
    cookies.set("token", "next", domain=".chaoxing.com")
    save_cookies(cookies, path)
    assert cookie_value(read_cookies(path), "token") == "next"
    assert not list(tmp_path.glob(".cookies-*"))
