"""Headless monitor: polls every user's watchlist forever, tells each user on
Telegram when one of their courses changes, and answers bot commands in between.

    python service.py

TELEGRAM_CHAT_ID is the admin: the only user at first, and the one who
approves everybody else. The database is shared with main.py.
"""

import logging
import signal
import sqlite3
import sys
from contextlib import closing

from engine._native import StatusLog, Watchlist
from engine.catalog.cache import Terms
from engine.catalog.scraper import ScraperError
from engine.config import DB_PATH
from engine.models.term import current_term, term_code, term_name
from engine.monitor import PollResult, StatusChange, TermMonitors
from engine.telegram.bot import COMMANDS, CourseBot
from engine.telegram.notifier import NotifyError, TelegramNotifier
from engine.telegram.users import APPROVED, Users

FAILURES_BEFORE_ALERT = 5  # consecutive failed polls before the admin is told

log = logging.getLogger("service")


class FreshWatchlist:
    """Re-reads the watchlist from the database on every call.

    Watchlist caches its rows in memory, so a long-lived one would never see
    the courses that main.py adds or removes from another process.
    """

    def __init__(self, path: str):
        self._path = path

    def terms(self) -> list[str]:
        return Watchlist(self._path).terms()

    def courses(self, term: str):
        """What all users together watch in this term."""
        return Watchlist(self._path).watched(term)

    def watchers(self, term: str, crn: int) -> list[int]:
        return Watchlist(self._path).watchers(term, crn)


def describe(change: StatusChange) -> str:
    course = change.course
    return (
        f"{change.new.value}: {course.code} {course.section} "
        f"(was {change.old.value})\n"
        f"{course.course_name}\n"
        f"CRN {course.crn:05d} | seats {course.seats_available}/{course.capacity} "
        f"| waitlist {course.wait_count}/{course.wait_capacity}"
    )


def legacy_term() -> str | None:
    """The term saved by the single-user version, if this database has one."""
    with closing(sqlite3.connect(DB_PATH)) as db:
        try:
            row = db.execute("SELECT value FROM setting WHERE key = 'term'").fetchone()
        except sqlite3.OperationalError:  # no such table
            return None
    return row[0] if row else None


def stop(signum, frame):
    # lets `kill`, systemd and docker stop the service the same way Ctrl+C does
    raise KeyboardInterrupt


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    db_path = str(DB_PATH)

    try:
        notifier = TelegramNotifier.from_env()
        admin_id = int(notifier.chat_id)
    except NotifyError as e:
        sys.exit(f"Telegram is not set up: {e}")
    except ValueError:
        sys.exit("TELEGRAM_CHAT_ID must be the numeric id of your private chat")

    if Watchlist.migrate(db_path, admin_id):
        log.info("moved the single-user watchlist to chat %d", admin_id)
    users = Users(db_path)
    if users.get(admin_id) is None:
        users.add(admin_id, "admin", APPROVED, legacy_term() or term_code(*current_term()))
    approved = [user for user in users.all() if user.status == APPROVED]
    watchlist = FreshWatchlist(db_path)

    try:
        # also proves the token and chat id work before the loop starts
        notifier.send(
            f"Course monitor started: {len(approved)} users, "
            f"watching {len(Watchlist(db_path))} sections.\n"
            "Send /help for the commands."
        )
        notifier.set_commands(COMMANDS)
    except NotifyError as e:
        sys.exit(f"Telegram is not set up: {e}")

    signal.signal(signal.SIGTERM, stop)
    terms = Terms()
    bot = CourseBot(notifier, terms, users, db_path, admin_id)

    def notify(text: str, chat_id: int = admin_id) -> None:
        try:
            notifier.send(text, chat_id=chat_id)
        except NotifyError as e:
            log.error("could not notify chat %s: %s", chat_id, e)

    failures = 0
    reported_missing: set[tuple[str, int]] = set()

    def report(term: str, result: PollResult) -> None:
        terms.update(term, result.courses)  # keeps /list and /search output fresh
        for change in result.changes:
            crn = change.course.crn
            watchers = watchlist.watchers(term, crn)
            log.info(
                "%s %05d %s -> %s, telling %d users",
                term, crn, change.old.value, change.new.value, len(watchers),
            )
            for chat_id in watchers:
                notify(describe(change), chat_id)
        for crn in result.missing:
            if (term, crn) not in reported_missing:
                reported_missing.add((term, crn))
                log.warning("%05d is no longer listed in term %s", crn, term)
                for chat_id in watchlist.watchers(term, crn):
                    notify(f"CRN {crn:05d} is no longer listed in {term_name(term)}.", chat_id)

    def on_cycle(
        results: dict[str, PollResult], errors: dict[str, ScraperError], delay: float
    ) -> None:
        nonlocal failures
        for term, result in results.items():
            report(term, result)
        for term, error in errors.items():
            log.error("check of term %s failed: %s", term, error)

        if errors:
            failures += 1
            if failures == FAILURES_BEFORE_ALERT:
                detail = "\n".join(f"{term_name(t)}: {e}" for t, e in errors.items())
                notify(f"Course monitor: {failures} checks in a row have failed.\n{detail}")
        else:
            if failures >= FAILURES_BEFORE_ALERT:
                notify("Course monitor: checks are working again.")
            failures = 0
        log.info(
            "checked %d sections in %d terms, %d changes, %d failed, next check in %.0fs",
            sum(len(result.courses) for result in results.values()),
            len(results) + len(errors),
            sum(len(result.changes) for result in results.values()),
            len(errors),
            delay,
        )

    # search needs the whole term; load the ones in use now so the first
    # command is not the one that waits. A term that fails here is loaded
    # again when somebody needs it.
    try:
        for term in sorted({user.term for user in approved if user.term}):
            try:
                log.info("loaded term %s: %d sections", term, len(terms.load(term).by_crn))
            except ScraperError as e:
                log.error("could not load term %s yet: %s", term, e)

        monitors = TermMonitors(terms.scraper, watchlist, StatusLog(db_path))
        # the wait between polls is spent answering bot commands
        monitors.run(on_cycle, sleep=bot.serve_for)
    except KeyboardInterrupt:
        log.info("stopped")


if __name__ == "__main__":
    main()
