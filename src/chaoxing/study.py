"""串行执行视频/音频、文档、阅读和空章节的学习请求。"""

import logging
import math
import re
import time
from dataclasses import dataclass
from hashlib import md5
from typing import Literal

from chaoxing.client import MOOC, ChaoxingClient
from chaoxing.models import CaptchaRequired, Chapter, Course, ProtocolError, Task
from chaoxing.output import media_progress

logger = logging.getLogger(__name__)


@dataclass
class Media:
    token: str
    duration: int
    kind: Literal["Video", "Audio"]
    rt: str = ""
    played_seconds: float = 0


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
        self._last_report = 0.0

    def execute(self, course: Course, chapter: Chapter, task: Task, interval: float) -> None:
        logger.info("学习：%s / %s / %s", course.title, chapter.title, task.title)
        if task.kind == "video":
            self._video(course, task, interval)
        elif task.kind == "document":
            node = re.search(r"nodeId_(.*?)-", task.other_info)
            self._simple(
                "document",
                course,
                chapter,
                task,
                knowledge_id=node.group(1) if node else chapter.id,
            )
        elif task.kind == "read":
            self._simple("readv2", course, chapter, task, knowledge_id=chapter.id)
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
        # 两种接口均会返回业务状态，不能只根据 HTTP 200 判定完成。
        if data.get("status") not in (True, "success", 1) and data.get("success") is not True:
            raise ProtocolError(f"{chapter.title} 的{task.kind}任务未得到成功确认")

    def _media(self, task: Task) -> Media:
        kinds: list[Literal["Video", "Audio"]] = [task.media_type]
        if task.media_type == "Video":
            kinds.append("Audio")
        for kind in kinds:
            response = self.client.request(
                "GET",
                f"{MOOC}/ananas/status/{task.object_id}",
                params={"k": self.client.fid, "flag": "normal"},
                headers=self._headers(kind),
            )
            data = self.client.json(response)
            if data.get("status") != "success":
                continue
            try:
                duration = int(data["duration"])
                token = str(data["dtoken"])
                played = float(data.get("playTime", task.played_seconds))
                if duration < 0 or not token or not math.isfinite(played) or played < 0:
                    raise ValueError
            except (KeyError, ValueError, TypeError, OverflowError) as exc:
                raise ProtocolError("媒体元数据缺少有效时长或播放令牌") from exc
            return Media(token, duration, kind, task.rt, played)
        raise ProtocolError("媒体尚未转码完成或无法取得播放信息")

    @staticmethod
    def _headers(kind: Literal["Video", "Audio"]) -> dict[str, str]:
        page = "video/index.html" if kind == "Video" else "audio/index_new.html"
        return {"Referer": f"{MOOC}/ananas/modules/{page}"}

    def _report(self, course: Course, task: Task, media: Media, position: int) -> bool:
        hint = re.search(r"-rt_([1d])", task.other_info)
        rt = media.rt or (("0.9" if hint.group(1) == "d" else "1") if hint else "")
        candidates = [rt] if rt else ["0.9", "1"]
        for index, candidate in enumerate(candidates):
            time.sleep(max(0, self._last_report + 2 - time.monotonic()))
            try:
                response = self.client.request(
                    "GET",
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
                        "isdrag": "3",
                        "view": "pc",
                        "dtype": media.kind,
                        "enc": progress_enc(
                            course, self.client.uid, task, position, media.duration
                        ),
                        "rt": candidate,
                        "_t": str(int(time.time() * 1000)),
                        **task.extra,
                    },
                    headers=self._headers(media.kind),
                )
            except CaptchaRequired:
                if index == len(candidates) - 1:
                    raise
                continue
            finally:
                self._last_report = time.monotonic()
            passed = self.client.json(response).get("isPassed")
            if not isinstance(passed, bool):
                raise ProtocolError("视频进度上报缺少有效的完成状态")
            media.rt = candidate
            return passed
        raise ProtocolError("无法上报媒体进度")

    def _video(self, course: Course, task: Task, interval: float) -> None:
        if not task.object_id or not math.isfinite(task.played_seconds):
            raise ProtocolError("媒体任务缺少有效的对象 ID 或播放进度")
        media = self._media(task)
        initial = min(media.duration, media.played_seconds)
        started = time.monotonic()
        final_attempts = 0
        with media_progress(task.title, media.duration, initial) as update:
            while True:
                position = min(
                    media.duration, int(initial + (time.monotonic() - started) * self.speed)
                )
                update(position)
                if self._report(course, task, media, position):
                    update(media.duration)
                    logger.info("完成：%s", task.title)
                    return
                logger.info("进度：%s %s/%s 秒", task.title, position, media.duration)
                if position >= media.duration:
                    final_attempts += 1
                    if final_attempts >= 5:
                        raise ProtocolError("媒体已到结尾，但服务端连续五次未确认完成")
                    delay = 2.0
                else:
                    elapsed = initial + (time.monotonic() - started) * self.speed
                    delay = max(0, min(interval, media.duration - elapsed) / self.speed)
                until = time.monotonic() + delay
                while time.monotonic() < until:
                    time.sleep(min(1, until - time.monotonic()))
                    update(min(media.duration, initial + (time.monotonic() - started) * self.speed))
