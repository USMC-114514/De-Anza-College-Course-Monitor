"""Headless monitor: polls the watchlist forever and reports changes to Telegram.

    python service.py                # the current term
    python service.py 2027 winter    # a specific term

The watchlist is the one managed with main.py; both use the same database.
"""

import logging
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

from engine._native import StatusLog, Watchlist
from engine.course_status_scraper import CourseStatusScraper, ScraperError, term_code
from engine.monitor import Monitor, PollResult, StatusChange
from engine.notifier import NotifyError, TelegramNotifier
from main import DB_PATH, current_term

ROOT = Path(__file__).resolve().parent
FAILURES_BEFORE_ALERT = 5  # consecutive failed polls before Telegram is told

log = logging.getLogger("service")


class FreshWatchlist:
    """Re-reads the watchlist from the database on every poll.

    Watchlist caches its rows in memory, so a long-lived one would never see
    the courses that main.py adds or removes from another process.
    """

    def __init__(self, path: str):
        self._path = path

    def courses(self, term: str):
        return Watchlist(self._path).courses(term)


def describe(change: StatusChange) -> str:
    course = change.course
    return (
        f"{change.new.value}: {course.code} {course.section} "
        f"(was {change.old.value})\n"
        f"{course.course_name}\n"
        f"CRN {course.crn:05d} | seats {course.seats_available}/{course.capacity} "
        f"| waitlist {course.wait_count}/{course.wait_capacity}"
    )


def parse_term(args: list[str]) -> str:
    if not args:
        return term_code(*current_term())
    try:
        year, quarter = args
        return term_code(int(year), quarter)
    except ValueError:
        sys.exit("usage: python service.py [YEAR QUARTER]    e.g. 2027 winter")


def stop(signum, frame):
    # lets `kill`, systemd and docker stop the service the same way Ctrl+C does
    raise KeyboardInterrupt


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    load_dotenv(ROOT / ".env")
    term = parse_term(sys.argv[1:])

    try:
        notifier = TelegramNotifier.from_env()
        watchlist = FreshWatchlist(str(DB_PATH))
        watched = len(watchlist.courses(term))
        # also proves the token and chat id work before the loop starts
        notifier.send(f"Course monitor started: term {term}, watching {watched} sections.")
    except NotifyError as e:
        sys.exit(f"Telegram is not set up: {e}")

    def notify(text: str) -> None:
        try:
            notifier.send(text)
        except NotifyError as e:
            log.error("could not notify: %s", e)

    failures = 0
    reported_missing: set[int] = set()

    def on_result(result: PollResult, delay: float) -> None:
        nonlocal failures
        if failures >= FAILURES_BEFORE_ALERT:
            notify("Course monitor: checks are working again.")
        failures = 0

        for change in result.changes:
            log.info(
                "%05d %s -> %s", change.course.crn, change.old.value, change.new.value
            )
            notify(describe(change))
        for crn in result.missing:
            if crn not in reported_missing:
                reported_missing.add(crn)
                log.warning("%05d is no longer listed in term %s", crn, term)
                notify(f"CRN {crn:05d} is no longer listed in term {term}.")
        log.info(
            "checked %d sections, %d changes, next check in %.0fs",
            len(result.courses),
            len(result.changes),
            delay,
        )

    def on_error(error: ScraperError, delay: float) -> None:
        nonlocal failures
        failures += 1
        log.error("check failed (%d in a row), retrying in %.0fs: %s", failures, delay, error)
        if failures == FAILURES_BEFORE_ALERT:
            notify(f"Course monitor: {failures} checks in a row have failed.\n{error}")

    signal.signal(signal.SIGTERM, stop)
    monitor = Monitor(
        CourseStatusScraper(term), watchlist, term, StatusLog(str(DB_PATH))
    )
    log.info("monitoring term %s, %d sections on the watchlist", term, watched)
    try:
        monitor.run(on_result, on_error)
    except KeyboardInterrupt:
        log.info("stopped")


if __name__ == "__main__":
    main()
