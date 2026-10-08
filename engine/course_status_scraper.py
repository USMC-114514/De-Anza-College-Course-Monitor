import html
from collections.abc import Iterable

import requests

from engine.course import Course, MeetingTime

BASE_URL = "https://reg.oci.fhda.edu/StudentRegistrationSsb/ssb"
PAGE_SIZE = 500
TIMEOUT = 15


_QUARTER_DIGIT = {"summer": 1, "fall": 2, "winter": 3, "spring": 4}
_DE_ANZA = 2


class ScraperError(Exception):
    """请求失败，或接口返回了无法解析的内容。"""


def term_code(year: int, quarter: str) -> str:
    """把 (2026, "fall") 转成接口用的学期代码 "202722"。

    代码里的年份是学年的结束年：夏、秋两季要 +1，冬、春两季不变。
    """
    quarter = quarter.lower()
    if quarter not in _QUARTER_DIGIT:
        raise ValueError(f"unknown quarter: {quarter!r}")
    academic_year = year + 1 if quarter in ("summer", "fall") else year
    return f"{academic_year}{_QUARTER_DIGIT[quarter]}{_DE_ANZA}"


def term_name(code: str) -> str:
    """term_code 的逆运算："202722" -> "2026 fall"。"""
    quarter = next(q for q, digit in _QUARTER_DIGIT.items() if str(digit) == code[4])
    year = int(code[:4]) - 1 if quarter in ("summer", "fall") else int(code[:4])
    return f"{year} {quarter}"


def _normalize_crn(crn: str | int) -> int:
    return int(str(crn).strip())


def _parse_course_number(raw: str) -> str:
    # "D003." -> "3", "D022A" -> "22A", "D01AH" -> "1AH"
    return raw.removeprefix("D").rstrip(".").lstrip("0")


# 顺序同 tm_wday
_WEEKDAY_KEYS = (
    "sunday",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
)


def _parse_meeting_time(raw: dict) -> MeetingTime | None:
    meetings = [m["meetingTime"] for m in raw.get("meetingsFaculty") or []]
    if not meetings:
        return None
    # 一个 section 可能有多条安排（如 lecture + lab），目前只取第一条有固定时间的
    meeting = next((m for m in meetings if m["beginTime"]), meetings[0])
    month, date, year = (int(part) for part in meeting["startDate"].split("/"))
    begin = meeting["beginTime"]  # "HHMM" 或 None
    return MeetingTime(
        year=year,
        month=month,
        date=date,
        hour=int(begin[:2]) if begin else None,
        minute=int(begin[2:]) if begin else None,
        days_of_the_week=tuple(
            i for i, key in enumerate(_WEEKDAY_KEYS) if meeting[key]
        ),
    )


def _parse_course(raw: dict) -> Course:
    try:
        instructors = [f["displayName"] for f in raw.get("faculty") or []]
        return Course(
            crn=int(raw["courseReferenceNumber"]),
            course_name=html.unescape(raw["courseTitle"] or ""),
            department=raw["subject"],
            instructor="; ".join(instructors) or "TBA",
            time=_parse_meeting_time(raw),
            course_number=_parse_course_number(raw["courseNumber"]),
            section=raw["sequenceNumber"],
            seats_available=raw["seatsAvailable"] or 0,
            capacity=raw["maximumEnrollment"] or 0,
            wait_available=raw["waitAvailable"] or 0,
            wait_capacity=raw["waitCapacity"] or 0,
            wait_count=raw["waitCount"] or 0,
        )
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise ScraperError(f"unexpected course format: {e!r}") from e


class CourseStatusScraper:
    """绑定一个学期的抓取器，可以反复调用来轮询。"""

    def __init__(self, term: str, session: requests.Session | None = None):
        self.term = term
        self._session = session or requests.Session()
        self._term_selected = False

    def fetch_subject(self, subject: str) -> list[Course]:
        """抓取一个课程前缀（如 "CIS"）下的全部 section。"""
        return self._fetch(subject.upper())

    def fetch_all(self) -> list[Course]:
        """抓取整个学期所有科目的 section。"""
        return self._fetch(None)

    def _fetch(self, subject: str | None) -> list[Course]:
        if not self._term_selected:
            self._select_term()
        sections = self._search(subject)
        if sections is None:
            # 会话过期后接口不报错，只返回 data: null；重新选一次学期再试
            self._select_term()
            sections = self._search(subject)
        if sections is None:
            raise ScraperError(f"no data returned for term {self.term}")
        return sections

    def fetch_status(
        self, subject: str, crns: Iterable[str | int]
    ) -> dict[int, Course]:
        """只返回指定 CRN 的 section；查不到的 CRN 不会出现在结果里。"""
        wanted = {_normalize_crn(crn) for crn in crns}
        return {s.crn: s for s in self.fetch_subject(subject) if s.crn in wanted}

    def _select_term(self) -> None:
        self._request(
            "POST", "/term/search", params={"mode": "search"}, data={"term": self.term}
        )
        self._term_selected = True

    def _search(self, subject: str | None) -> list[Course] | None:
        # 不先 reset，接口会原样返回同一会话里上一次搜索的结果
        self._request("POST", "/classSearch/resetDataForm")

        sections: list[Course] = []
        while True:
            payload = self._request(
                "GET",
                "/searchResults/searchResults",
                params={
                    "txt_subject": subject,  # None 时 requests 会省略这个参数
                    "txt_term": self.term,
                    "pageOffset": len(sections),
                    "pageMaxSize": PAGE_SIZE,
                    "sortColumn": "subjectDescription",
                    "sortDirection": "asc",
                },
            )
            if not isinstance(payload, dict) or "data" not in payload:
                raise ScraperError("unexpected search response format")
            page = payload["data"]
            if page is None:
                return None
            sections.extend(_parse_course(raw) for raw in page)
            if not page or len(sections) >= (payload.get("totalCount") or 0):
                return sections

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = self._session.request(
                method, BASE_URL + path, timeout=TIMEOUT, **kwargs
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise ScraperError(f"{method} {path} failed: {e}") from e
        except ValueError as e:
            raise ScraperError(f"{method} {path} returned non-JSON content") from e


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        sys.exit(
            "usage: python -m engine.course_status_scraper TERM SUBJECT [CRN ...]\n"
            "   e.g. python -m engine.course_status_scraper 202732 CIS 00439"
        )
    scraper = CourseStatusScraper(sys.argv[1])
    if sys.argv[3:]:
        found = list(scraper.fetch_status(sys.argv[2], sys.argv[3:]).values())
    else:
        found = scraper.fetch_subject(sys.argv[2])
    for s in found:
        print(
            f"{s.crn:05d}  {s.code:<10} {s.section:<4} {s.status.value:<8} "
            f"seats {s.seats_available}/{s.capacity}  "
            f"waitlist {s.wait_count}/{s.wait_capacity}  {s.course_name}"
        )
