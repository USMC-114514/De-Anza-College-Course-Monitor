import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from engine.course import Course, Status
from engine.course_status_scraper import CourseStatusScraper, ScraperError

DEFAULT_INTERVAL = 15.0  # seconds between polls
DEFAULT_JITTER = (1.0, 3.0)  # every wait is moved earlier or later by 1-3 seconds
MIN_INTERVAL = 5.0
MAX_BACKOFF = 8  # after repeated failures, wait at most this many intervals


@dataclass(frozen=True)
class StatusChange:
    course: Course
    old: Status
    new: Status


@dataclass(frozen=True)
class PollResult:
    courses: dict[int, Course]  # fresh data for every watched CRN that was found
    changes: list[StatusChange]  # status differs from the previous poll
    missing: list[int]  # watched CRNs that the term no longer lists
    first: bool  # True for the poll that set the baseline


def _offset(jitter: tuple[float, float]) -> float:
    """A random amount within the jitter range, with a random sign."""
    return random.choice((-1, 1)) * random.uniform(*jitter)


class Monitor:
    """Polls the watched courses of one term and reports status changes."""

    def __init__(
        self, scraper: CourseStatusScraper, watchlist, term: str, status_log=None
    ):
        self._scraper = scraper
        self._watchlist = watchlist
        self._term = term
        self._log = status_log
        self._last: dict[int, Status] = {}
        self._polled = False

    def poll(self) -> PollResult:
        """Fetch the watched courses once. Raises ScraperError if the request fails."""
        watched = self._watchlist.courses(self._term)
        crns = {entry.crn for entry in watched}
        courses: dict[int, Course] = {}
        if watched:
            # one request covers every department on the list
            departments = sorted({entry.department for entry in watched})
            courses = self._scraper.fetch_status(",".join(departments), crns)

        changes = []
        for crn, course in courses.items():
            old = self._last.get(crn) or self._logged_status(crn)
            if old is not None and old != course.status:
                changes.append(StatusChange(course, old, course.status))
            if self._log is not None:
                # the log itself skips entries that repeat the previous one
                self._log.record(
                    self._term,
                    crn,
                    course.status.value,
                    course.seats_available,
                    course.capacity,
                    course.wait_count,
                    course.wait_capacity,
                )
        # courses added since the last poll get their baseline here;
        # removed ones are forgotten
        self._last = {crn: course.status for crn, course in courses.items()}

        first = not self._polled
        self._polled = True
        return PollResult(courses, changes, sorted(crns - courses.keys()), first)

    def _logged_status(self, crn: int) -> Status | None:
        """The status saved by an earlier run, so changes made while the
        program was closed are still reported."""
        if self._log is None:
            return None
        record = self._log.latest(self._term, crn)
        return Status(record.status) if record else None

    def run(
        self,
        on_result: Callable[[PollResult, float], None],
        on_error: Callable[[ScraperError, float], None],
        interval: float = DEFAULT_INTERVAL,
        jitter: tuple[float, float] = DEFAULT_JITTER,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Poll forever; stop it with KeyboardInterrupt.

        Each callback also receives the number of seconds until the next poll.
        A failed poll does not stop the loop, it only makes the next wait longer.
        """
        interval = max(interval, MIN_INTERVAL)
        failures = 0
        while True:
            try:
                result = self.poll()
            except ScraperError as e:
                failures += 1
                delay = interval * min(2**failures, MAX_BACKOFF) + _offset(jitter)
                on_error(e, delay)
            else:
                failures = 0
                delay = interval + _offset(jitter)
                on_result(result, delay)
            sleep(delay)
