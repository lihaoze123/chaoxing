from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import SecretStr

from chaoxing.client import ChaoxingClient
from chaoxing.config import AccountConfig
from chaoxing.cookies import cookie_value, save_cookies
from chaoxing.models import Task
from chaoxing.study import Media, Study


def test_refresh_failure_relogs_in_before_refreshing_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = ChaoxingClient(AccountConfig(cookies_file=tmp_path / "cookies.txt"))
    calls = []
    study = Study(client, 1)
    values = iter([None, Media("new-token", 100, "Video", played_seconds=30)])

    def refresh(*args: object) -> Media | None:
        calls.append("refresh")
        return next(values)

    monkeypatch.setattr(client, "reload_cookies", lambda: calls.append("reload"))
    monkeypatch.setattr(client, "relogin_if_needed", lambda: calls.append("relogin") or True)
    monkeypatch.setattr(study, "_refresh", refresh)
    media = study._recover_after_forbidden(Task("video", "v", object_id="o"), "Video")
    assert calls == ["reload", "refresh", "relogin", "refresh"]
    assert media is not None and media.token == "new-token"
    client.close()


def test_relogin_forces_password_login_after_cookie_validation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = ChaoxingClient(
        AccountConfig(
            username="u",
            password=SecretStr("p"),
            use_cookies=True,
            cookies_file=tmp_path / "cookies.txt",
        ),
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, text="login"))),
    )
    client.http.cookies.set("_uid", "old", domain=".chaoxing.com")
    save_cookies(client.http.cookies, client.account.cookies_file)
    login = MagicMock()
    monkeypatch.setattr(client, "login", login)
    assert client.relogin_if_needed()
    login.assert_called_once_with(use_cookies=False)
    assert cookie_value(client.http.cookies, "_uid") == "old"
    client.close()
