"""Headless monitor: polls the watchlist forever, reports changes to Telegram
and answers bot commands (/search, /add, /remove, /list, /log, /term) in between.

    python service.py                # the term used last time, else the current one
    python service.py 2027 winter    # a specific term

The watchlist is shared with main.py; both use the same database.
"""

import logging
import signal
import sqlite3
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from engine._native import StatusLog, Watchlist
from engine.bot import COMMANDS, CourseBot, TermChanged
from engine.course import Course
from engine.course_status_scraper import (
    CourseStatusScraper,
    ScraperError,
    term_code,
    term_name,
)
from engine.monitor import Monitor, PollResult, StatusChange
from engine.notifier import NotifyError, TelegramNotifier
from main import DB_PATH, current_term

ROOT = Path(__file__).resolve().parent
FAILURES_BEFORE_ALERT = 5  # consecutive failed polls before Telegram is told
STARTUP_RETRY = 30.0  # seconds between attempts to load the course list

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


def saved_term() -> str | None:
    """The term chosen with /term in an earlier run, if any."""
    with sqlite3.connect(DB_PATH) as db:
        db.execute("CREATE TABLE IF NOT EXISTS setting (key TEXT PRIMARY KEY, value TEXT)")
        row = db.execute("SELECT value FROM setting WHERE key = 'term'").fetchone()
    db.close()
    return row[0] if row else None


def save_term(term: str) -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.execute("INSERT OR REPLACE INTO setting (key, value) VALUES ('term', ?)", (term,))
    db.close()


def parse_term(args: list[str]) -> str:
    if not args:
        return saved_term() or term_code(*current_term())
    try:
        year, quarter = args
        return term_code(int(year), quarter)
    except ValueError:
        sys.exit("usage: python service.py [YEAR QUARTER]    e.g. 2027 winter")


def load_courses(scraper: CourseStatusScraper) -> list[Course]:
    """Load the whole term for search; keeps trying until it works."""
    while True:
        try:
            return scraper.fetch_all()
        except ScraperError as e:
            log.error("could not load term %s, retrying in %.0fs: %s", scraper.term, STARTUP_RETRY, e)
            time.sleep(STARTUP_RETRY)


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
        notifier.send(
            f"Course monitor started: {term_name(term)}, watching {watched} sections.\n"
            "Send /help for the commands."
        )
        notifier.set_commands(COMMANDS)
    except NotifyError as e:
        sys.exit(f"Telegram is not set up: {e}")

    signal.signal(signal.SIGTERM, stop)
    scraper = CourseStatusScraper(term)
    try:
        bot = CourseBot(notifier, scraper, load_courses(scraper), str(DB_PATH))
    except KeyboardInterrupt:
        sys.exit("stopped")

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
        bot.by_crn.update(result.courses)  # keeps /list and /search output fresh

        for change in result.changes:
            log.info(
                "%05d %s -> %s", change.course.crn, change.old.value, change.new.value
            )
            notify(describe(change))
        for crn in result.missing:
            if crn not in reported_missing:
                reported_missing.add(crn)
                log.warning("%05d is no longer listed in term %s", crn, bot.term)
                notify(f"CRN {crn:05d} is no longer listed in {term_name(bot.term)}.")
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

    status_log = StatusLog(str(DB_PATH))
    while True:
        # the bot owns the current term; /term makes it raise TermChanged
        monitor = Monitor(bot.scraper, watchlist, bot.term, status_log)
        log.info("monitoring term %s", bot.term)
        try:
            # the wait between polls is spent answering bot commands
            monitor.run(on_result, on_error, sleep=bot.serve_for)
        except TermChanged:
            save_term(bot.term)
            failures = 0
            reported_missing.clear()
        except KeyboardInterrupt:
            log.info("stopped")
            return


if __name__ == "__main__":
    main()
