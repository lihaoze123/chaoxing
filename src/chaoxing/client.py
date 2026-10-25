"""持有单一 HTTP 会话的同步客户端。"""

import time
from typing import Any

import httpx

from chaoxing.captcha import CaptchaSolver
from chaoxing.cipher import encrypt_login
from chaoxing.config import AccountConfig
from chaoxing.cookies import cookie_value, read_cookies, save_cookies
from chaoxing.models import (
    AuthenticationError,
    CaptchaRequired,
    Card,
    Chapter,
    Course,
    ProtocolError,
)
from chaoxing.parsing import parse_card, parse_chapters, parse_courses, parse_folders

PASSPORT = "https://passport2.chaoxing.com"
MOOC = "https://mooc1.chaoxing.com"
MOOC2 = "https://mooc2-ans.chaoxing.com/mooc2-ans"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
)


class ChaoxingClient:
    def __init__(self, account: AccountConfig, http: httpx.Client | None = None) -> None:
        self.account = account
        self.http = (
            http
            if http is not None
            else httpx.Client(
                timeout=15,
                follow_redirects=True,
            )
        )
        self.http.headers.update({"User-Agent": USER_AGENT})
        self.captcha = CaptchaSolver()
        self._last_request = 0.0

    def close(self) -> None:
        self.http.close()

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        # 串行请求至少相隔 0.5 秒；视频进度上报另有较长间隔。
        time.sleep(max(0, self._last_request + 0.5 - time.monotonic()))
        try:
            response = self.http.request(method, url, **kwargs)
            if self._is_captcha(response):
                if not self.captcha.solve(self.http):
                    raise CaptchaRequired("验证码或 403 拦截，请在浏览器手动验证后重新运行")
                save_cookies(self.http.cookies, self.account.cookies_file)
                response = self.http.request(method, url, **kwargs)
                if self._is_captcha(response):
                    raise CaptchaRequired("验证码验证后仍被拦截，请手动处理")
            response.raise_for_status()
            if (
                "passport2.chaoxing.com" in response.url.host
                and "fanyalogin" not in response.url.path
            ):
                raise AuthenticationError("登录已失效，请更新 Cookie 或账号密码后重试")
            if any(
                marker in response.text
                for marker in ('name="password"', "name='password'", "请先登录", "请重新登录")
            ):
                raise AuthenticationError("服务端返回登录页面，请更新登录信息")
            return response
        finally:
            self._last_request = time.monotonic()

    @staticmethod
    def _is_captcha(response: httpx.Response) -> bool:
        return response.status_code == 403 or any(
            marker in response.text for marker in ("processVerify", "请输入验证码", "验证码验证")
        )

    @staticmethod
    def json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise ProtocolError("服务端未返回有效 JSON 数据") from exc
        if not isinstance(data, dict):
            raise ProtocolError("服务端返回的数据结构无效")
        return data

    def login(self) -> None:
        if self.account.use_cookies:
            self.http.cookies.update(read_cookies(self.account.cookies_file))
            if cookie_value(self.http.cookies, "_uid") or cookie_value(self.http.cookies, "UID"):
                try:
                    self.request("POST", f"{MOOC2}/visit/courselistdata", data=self._course_query())
                    return
                except AuthenticationError:
                    pass
            if not self.account.username or not self.account.password.get_secret_value():
                raise AuthenticationError("Cookie 不存在或已失效，请更新文件或配置账号密码")
        if not self.account.username or not self.account.password.get_secret_value():
            raise AuthenticationError("账号密码不能为空")
        self.http.cookies.clear()
        result = self.json(
            self.request(
                "POST",
                f"{PASSPORT}/fanyalogin",
                data={
                    "fid": "-1",
                    "uname": encrypt_login(self.account.username),
                    "password": encrypt_login(self.account.password.get_secret_value()),
                    "refer": "https%3A%2F%2Fi.chaoxing.com",
                    "t": "true",
                    "forbidotherlogin": "0",
                    "validate": "",
                    "doubleFactorLogin": "0",
                    "independentId": "0",
                },
            )
        )
        if result.get("status") is not True:
            raise AuthenticationError("登录失败，请检查账号密码或在浏览器完成登录验证")
        if not cookie_value(self.http.cookies, "_uid") and not cookie_value(
            self.http.cookies, "UID"
        ):
            raise AuthenticationError("登录响应未包含用户 Cookie，请在浏览器获取 Cookie 后登录")
        save_cookies(self.http.cookies, self.account.cookies_file)

    @staticmethod
    def _course_query(folder: str = "0") -> dict[str, str]:
        return {"courseType": "1", "courseFolderId": folder, "query": "", "superstarClass": "0"}

    def courses(self) -> list[Course]:
        headers = {"Referer": f"{MOOC2}/visit/interaction?moocDomain={MOOC}/mooc-ans"}
        first = self.request(
            "POST", f"{MOOC2}/visit/courselistdata", data=self._course_query(), headers=headers
        )
        courses = parse_courses(first.text)
        folders = self.request("GET", f"{MOOC2}/visit/interaction")
        for folder in dict.fromkeys(parse_folders(folders.text)):
            response = self.request(
                "POST",
                f"{MOOC2}/visit/courselistdata",
                data=self._course_query(folder),
                headers=headers,
            )
            courses.extend(parse_courses(response.text))
        return list({(course.id, course.class_id): course for course in courses}.values())

    def chapters(self, course: Course) -> list[Chapter]:
        response = self.request(
            "GET",
            f"{MOOC2}/mycourse/studentcourse",
            params={
                "courseid": course.id,
                "clazzid": course.class_id,
                "cpi": course.cpi,
                "ut": "s",
            },
        )
        chapters = parse_chapters(response.text)
        if not chapters:
            raise ProtocolError("未读取到章节，请检查课程状态或页面结构")
        return chapters

    def cards(self, course: Course, chapter: Chapter) -> list[Card]:
        cards = []
        # 读取七页任务卡，防止遗漏后续任务。
        for number in range(7):
            response = self.request(
                "GET",
                f"{MOOC}/mooc-ans/knowledge/cards",
                params={
                    "clazzid": course.class_id,
                    "courseid": course.id,
                    "knowledgeid": chapter.id,
                    "cpi": course.cpi,
                    "ut": "s",
                    "mooc2": "1",
                    "num": str(number),
                },
            )
            card = parse_card(response.text)
            cards.append(card)
            if card.locked:
                break
        if not any(card.recognized for card in cards) and chapter.task_count != 0:
            raise ProtocolError("未识别到任务卡片，不能将该章节视为已完成")
        return cards

    def visit_empty(self, course: Course, chapter: Chapter) -> None:
        response = self.request(
            "GET",
            f"{MOOC}/mooc-ans/mycourse/studentstudyAjax",
            params={
                "courseId": course.id,
                "clazzid": course.class_id,
                "chapterId": chapter.id,
                "cpi": course.cpi,
                "verificationcode": "",
                "mooc2": "1",
                "microTopicId": "0",
                "editorPreview": "0",
            },
        )
        if "章节未开放" in response.text:
            raise ProtocolError("章节访问被拒绝，可能需要先完成测验")

    @property
    def uid(self) -> str:
        uid = cookie_value(self.http.cookies, "_uid") or cookie_value(self.http.cookies, "UID")
        if not uid:
            raise AuthenticationError("登录 Cookie 缺少用户 ID")
        return uid

    @property
    def fid(self) -> str:
        return cookie_value(self.http.cookies, "fid", "1024")
