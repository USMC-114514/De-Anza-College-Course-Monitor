import logging
import time
from datetime import datetime, timezone

from engine._native import StatusLog, Watchlist
from engine.course import Course
from engine.course_search import CourseSearch
from engine.notifier import NotifyError, TelegramNotifier

MAX_RESULTS = 15
LOG_LINES = 15
MAX_MESSAGE = 4000  # Telegram rejects messages longer than 4096 characters
LONG_POLL = 25  # longest single wait for new messages, in seconds
RETRY_DELAY = 5.0  # pause after a failed getUpdates

COMMANDS = {
    "search": "Find courses: /search cis 22",
    "add": "Watch courses: /add 12345 23456",
    "remove": "Stop watching: /remove 12345",
    "list": "Show the watchlist",
    "log": "Recent status records",
    "help": "Show the commands",
}

log = logging.getLogger("bot")


def describe(course: Course) -> str:
    return (
        f"{course.crn:05d} | {course.code} {course.section} | {course.status.value} "
        f"| seats {course.seats_available}/{course.capacity} | {course.course_name}"
    )


def local_time(utc: str) -> str:
    """Convert the database's UTC "YYYY-MM-DD HH:MM:SS" to local time."""
    moment = datetime.fromisoformat(utc).replace(tzinfo=timezone.utc)
    return moment.astimezone().strftime("%m-%d %H:%M:%S")


class CourseBot:
    """Answers Telegram commands that search courses and edit the watchlist.

    Only the chat the notifier is configured for is answered; a bot can be
    messaged by anyone who finds its name.
    """

    def __init__(
        self,
        telegram: TelegramNotifier,
        term: str,
        courses: list[Course],
        db_path: str,
    ):
        self._telegram = telegram
        self._term = term
        self._index = CourseSearch(courses)
        self.by_crn = {course.crn: course for course in courses}
        self._db_path = db_path
        self._log = StatusLog(db_path)
        self._offset = 0

    def serve_for(self, seconds: float) -> None:
        """Answer incoming commands for this long, then return.

        The monitor uses this in place of time.sleep between polls.
        """
        deadline = time.monotonic() + seconds
        while (remaining := deadline - time.monotonic()) > 0:
            if remaining < 1:
                time.sleep(remaining)
                return
            try:
                wait = int(min(remaining, LONG_POLL))
                updates = self._telegram.get_updates(self._offset, wait)
            except NotifyError as e:
                log.error("could not read messages: %s", e)
                time.sleep(min(RETRY_DELAY, max(deadline - time.monotonic(), 0)))
                continue
            for update in updates:
                self._offset = update["update_id"] + 1
                self._handle(update.get("message") or {})

    def _handle(self, message: dict) -> None:
        chat_id = str((message.get("chat") or {}).get("id", ""))
        text = (message.get("text") or "").strip()
        if not text:
            return
        if chat_id != self._telegram.chat_id:
            log.warning("ignored a message from chat %s", chat_id)
            return
        try:
            reply = self.answer(text)
        except Exception:
            # one bad command must not take the monitor down with it
            log.exception("command failed: %r", text)
            reply = "Something went wrong while handling that command."
        if len(reply) > MAX_MESSAGE:
            reply = reply[:MAX_MESSAGE] + "\n..."
        try:
            self._telegram.send(reply)
        except NotifyError as e:
            log.error("could not reply: %s", e)

    def answer(self, text: str) -> str:
        """The reply to one message."""
        if not text.startswith("/"):
            return self._search(text)
        name, *args = text[1:].split() or [""]
        name = name.split("@")[0].lower()  # groups send "/add@BotName"
        if name == "search":
            return self._search(" ".join(args)) if args else "Usage: /search QUERY"
        if name in ("add", "remove"):
            if not args or not all(word.isdecimal() for word in args):
                return f"Usage: /{name} CRN..."
            crns = [int(word) for word in args]
            return self._add(crns) if name == "add" else self._remove(crns)
        if name == "list":
            return self._list()
        if name == "log":
            return self._recent_log()
        return "\n".join(
            [f"Term {self._term}. Send any text to search, or use:"]
            + [f"/{command} - {about}" for command, about in COMMANDS.items()]
        )

    def _search(self, query: str) -> str:
        results = self._index.search(query)
        if not results:
            return "No matches."
        # the index holds the courses as loaded at startup; by_crn has newer
        # data for the ones that are being watched
        lines = [
            describe(self.by_crn.get(course.crn, course))
            for course in results[:MAX_RESULTS]
        ]
        if len(results) > MAX_RESULTS:
            lines.append(f"... {len(results) - MAX_RESULTS} more, type more to narrow down")
        return "\n".join(lines)

    def _watchlist(self) -> Watchlist:
        # opened per command so changes made by main.py are never overwritten
        # by a stale in-memory copy
        return Watchlist(self._db_path)

    def _add(self, crns: list[int]) -> str:
        watchlist = self._watchlist()
        lines = []
        for crn in crns:
            course = self.by_crn.get(crn)
            if course is None:
                lines.append(f"{crn:05d} not found in this term")
            elif watchlist.add(
                self._term,
                course.crn,
                course.department,
                course.course_number,
                course.section,
                course.course_name,
            ):
                lines.append(f"Added {describe(course)}")
            else:
                lines.append(f"{crn:05d} is already on the watchlist")
        return "\n".join(lines)

    def _remove(self, crns: list[int]) -> str:
        watchlist = self._watchlist()
        lines = []
        for crn in crns:
            if watchlist.remove(self._term, crn):
                lines.append(f"{crn:05d} removed")
            else:
                lines.append(f"{crn:05d} was not on the watchlist")
        return "\n".join(lines)

    def _list(self) -> str:
        watched = self._watchlist().courses(self._term)
        if not watched:
            return "The watchlist is empty. Use /add CRN"
        lines = []
        for entry in watched:
            course = self.by_crn.get(entry.crn)
            if course is not None:
                lines.append(describe(course))
            else:
                lines.append(f"{entry.crn:05d} | {entry.code} {entry.section} | not found")
        return "\n".join(lines)

    def _recent_log(self) -> str:
        # a fresh StatusLog would also work, but recent() always reads the database
        records = self._log.recent(self._term, LOG_LINES)
        if not records:
            return "The log is empty."
        lines = []
        for record in records:
            course = self.by_crn.get(record.crn)
            name = f"{course.code} {course.section} | " if course else ""
            lines.append(
                f"{local_time(record.checked_at)} | {record.crn:05d} | {name}"
                f"{record.status} | seats {record.seats_available}/{record.capacity} "
                f"| waitlist {record.wait_count}/{record.wait_capacity}"
            )
        return "\n".join(lines)
