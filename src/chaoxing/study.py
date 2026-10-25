"""课程学习请求及媒体进度协议。"""

import logging
import math
import random
import re
import time
from dataclasses import dataclass
from enum import Enum
from hashlib import md5
from typing import Literal

import httpx

from chaoxing.client import MOOC, ChaoxingClient
from chaoxing.models import Chapter, Course, ProtocolError, Task
from chaoxing.output import media_progress

logger = logging.getLogger(__name__)
type MediaKind = Literal["Video", "Audio"]


class MediaResult(Enum):
    SUCCESS = 0
    FORBIDDEN = 1
    ERROR = 2


class RateLimiter:
    def __init__(self, interval: float) -> None:
        self.interval = interval
        self.last_call = time.time()

    def wait(self, random_max: float) -> None:
        now = time.time()
        delay = max(self.last_call + self.interval - now, 0) + random.uniform(0, random_max)
        self.last_call = now + delay
        time.sleep(delay)


@dataclass
class Media:
    token: str
    duration: int
    kind: MediaKind
    rt: str = ""
    played_seconds: float | None = None


def progress_enc(course: Course, uid: str, task: Task, position: int, duration: int) -> str:
    value = (
        f"[{course.class_id}][{uid}][{task.id}][{task.object_id}]"
        f"[{position * 1000}][d_yHJ!$pdA~5][{duration * 1000}][0_{duration}]"
    )
    return md5(value.encode()).hexdigest()


class Study:
    def __init__(self, client: ChaoxingClient, speed: float) -> None:
        self.client = client
        self.speed = speed
        self._report_limiter = RateLimiter(2)
        self._status_limiter = RateLimiter(0.5)

    def execute(self, course: Course, chapter: Chapter, task: Task, interval: float = 60) -> None:
        logger.info("学习：%s / %s / %s", course.title, chapter.title, task.title)
        if task.kind == "video":
            result = self._video(course, task, "Video")
            if result != MediaResult.SUCCESS:
                logger.warning("视频任务失败，尝试音频任务解码")
                result = self._video(course, task, "Audio")
            if result != MediaResult.SUCCESS:
                raise ProtocolError(f"媒体学习失败：{result.name}")
        elif task.kind == "document":
            node = re.search(r"nodeId_(.*?)-", task.other_info)
            self._simple("document", course, chapter, task, node.group(1) if node else chapter.id)
        elif task.kind == "read":
            self._simple("readv2", course, chapter, task, chapter.id)
        else:
            raise ProtocolError("试图执行不支持的学习任务")

    def _simple(
        self, endpoint: str, course: Course, chapter: Chapter, task: Task, knowledge_id: str
    ) -> None:
        response = self.client.request(
            "GET",
            f"{MOOC}/ananas/job/{endpoint}",
            params={
                "jobid": task.id,
                "knowledgeid": knowledge_id,
                "courseid": course.id,
                "clazzid": course.class_id,
                "jtoken": task.token,
                "_dc": str(int(time.time() * 1000)),
            },
        )
        data = self.client.json(response)
        if data.get("status") not in (True, "success", 1) and data.get("success") is not True:
            raise ProtocolError(f"{chapter.title} 的{task.kind}任务未得到成功确认")

    def _media(self, task: Task, kind: MediaKind, *, refresh: bool = False) -> Media | None:
        if refresh:
            self._status_limiter.wait(0.2)
        response = self.client.media_get(
            f"{MOOC}/ananas/status/{task.object_id}",
            params={"k": self.client.fid, "flag": "normal"},
            headers=self._headers(kind),
            timeout=8 if refresh else 5,
        )
        if refresh and response.status_code != 200:
            return None
        data = self.client.json(response)
        if data.get("status") != "success":
            return None
        try:
            duration = int(data["duration"])
            token = data["dtoken"]
            played = data.get("playTime") if refresh else None
            if duration < 0 or not isinstance(token, str) or not token:
                raise ValueError
            if played is not None:
                played = float(played)
                if not math.isfinite(played) or played < 0:
                    raise ValueError
        except (KeyError, ValueError, TypeError, OverflowError) as exc:
            raise ProtocolError("媒体元数据缺少有效时长或播放令牌") from exc
        return Media(token, duration, kind, task.rt, played)

    @staticmethod
    def _headers(kind: MediaKind) -> dict[str, str]:
        page = "video/index.html" if kind == "Video" else "audio/index_new.html"
        return {"Referer": f"{MOOC}/ananas/modules/{page}?v=2025-0725-1842"}

    def _report(
        self,
        course: Course,
        task: Task,
        media: Media,
        position: int,
        *,
        isdrag: int = 3,
    ) -> tuple[bool, int]:
        self._report_limiter.wait(2)
        if "courseId" in task.other_info:
            raise ProtocolError("媒体 otherInfo 含有无效 courseId 参数")
        hint = re.search(r"-rt_([1d])", task.other_info)
        rt = media.rt or (("0.9" if hint.group(1) == "d" else "1") if hint else "")
        if rt:
            media.rt = rt
        candidates = [rt] if rt else ["0.9", "1"]
        for candidate in candidates:
            response = self.client.media_get(
                f"{MOOC}/mooc-ans/multimedia/log/a/{course.cpi}/{media.token}",
                params={
                    "clazzId": course.class_id,
                    "playingTime": str(position),
                    "duration": str(media.duration),
                    "clipTime": f"0_{media.duration}",
                    "objectId": task.object_id,
                    "otherInfo": task.other_info,
                    "courseId": course.id,
                    "jobid": task.id,
                    "userid": self.client.uid,
                    "isdrag": str(isdrag),
                    "view": "pc",
                    "dtype": media.kind,
                    "enc": progress_enc(course, self.client.uid, task, position, media.duration),
                    "rt": candidate,
                    "_t": str(int(time.time() * 1000)),
                    **task.extra,
                },
                headers=self._headers(media.kind),
                timeout=5,
                solve_captcha=True,
            )
            if response.status_code == 200:
                passed = self.client.json(response).get("isPassed")
                if not isinstance(passed, bool):
                    raise ProtocolError("视频进度上报缺少有效的完成状态")
                return passed, 200
            if response.status_code != 403:
                break
        return False, response.status_code

    def _recover_after_forbidden(self, task: Task, kind: MediaKind) -> Media | None:
        self.client.reload_cookies()
        refreshed = self._refresh(task, kind)
        if refreshed is not None:
            return refreshed
        if self.client.relogin_if_needed():
            return self._refresh(task, kind)
        return None

    def _refresh(self, task: Task, kind: MediaKind) -> Media | None:
        try:
            return self._media(task, kind, refresh=True)
        except (httpx.HTTPError, ProtocolError):
            return None

    def _video(self, course: Course, task: Task, kind: MediaKind) -> MediaResult:
        if not task.object_id or not math.isfinite(task.played_seconds):
            raise ProtocolError("媒体任务缺少有效的对象 ID 或播放进度")
        media = self._media(task, kind)
        if media is None:
            return MediaResult.ERROR
        # 卡片 playTime 以毫秒提供；初始进度不使用状态接口的 playTime。
        play_time = float(int(task.played_seconds))
        last_log_time = 0.0
        last_iter = time.time()
        wait_time = int(random.uniform(30, 90))
        forbidden_retry = 0

        passed, state = self._report(course, task, media, media.duration, isdrag=4)
        if passed:
            logger.info("任务已完成：%s", task.title)
            return MediaResult.SUCCESS

        with media_progress(task.title, media.duration, play_time) as update:
            while not passed:
                if play_time - last_log_time >= wait_time or play_time == media.duration:
                    passed, state = self._report(course, task, media, int(play_time))
                    if state == 403:
                        if forbidden_retry >= 2:
                            return MediaResult.FORBIDDEN
                        forbidden_retry += 1
                        logger.warning(
                            "视频上报 403，刷新会话和播放令牌（第 %s 次）", forbidden_retry
                        )
                        time.sleep(random.uniform(2, 4))
                        refreshed = self._recover_after_forbidden(task, kind)
                        if refreshed is None:
                            return MediaResult.ERROR
                        # rt 属于任务参数，状态刷新不能覆盖已经提取出的值。
                        refreshed.rt = media.rt
                        media = refreshed
                        if media.played_seconds is not None:
                            play_time = media.played_seconds
                        continue
                    if not passed and state != 200:
                        return MediaResult.ERROR
                    wait_time = int(random.uniform(30, 90))
                    last_log_time = play_time
                    logger.info("进度：%s %s/%s 秒", task.title, int(play_time), media.duration)
                elapsed = (time.time() - last_iter) * self.speed
                last_iter = time.time()
                play_time = min(media.duration, play_time + elapsed)
                update(play_time)
                time.sleep(1)
        logger.info("完成：%s", task.title)
        return MediaResult.SUCCESS
