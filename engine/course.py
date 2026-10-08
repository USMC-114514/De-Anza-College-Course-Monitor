"""课程数据结构：Course 以及它用到的 MeetingTime、Status。"""

from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    OPEN = "OPEN"
    WAITLIST = "WAITLIST"
    FULL = "FULL"


@dataclass(frozen=True)
class MeetingTime:
    """上课时间，字段含义对应 C 的 struct tm，但年和月存的是实际值。"""

    year: int  # year/month/date 是开课日期
    month: int
    date: int
    hour: int | None  # 上课开始时间；线上异步课没有固定时间，为 None
    minute: int | None
    days_of_the_week: tuple[int, ...]  # 同 tm_wday：0 = 周日 ... 6 = 周六


@dataclass(frozen=True)
class Course:
    crn: int  # primary key
    course_name: str
    department: str  # course prefix
    instructor: str
    time: MeetingTime | None  # if fully online then None
    course_number: str
    section: str
    seats_available: int
    capacity: int
    wait_available: int
    wait_capacity: int
    wait_count: int

    @property
    def code(self) -> str:
        return f"{self.department} {self.course_number}"

    @property
    def status(self) -> Status:
        if self.seats_available > 0 and self.wait_count == 0:
            return Status.OPEN
        if self.wait_available > 0:
            return Status.WAITLIST
        return Status.FULL
