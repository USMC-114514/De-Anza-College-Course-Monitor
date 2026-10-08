import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from engine._native import StatusLog, Watchlist
from engine.course import Course
from engine.course_search import CourseSearch
from engine.course_status_scraper import (
    CourseStatusScraper,
    ScraperError,
    term_code,
    term_name,
)
from engine.notifier import NotifyError, TelegramNotifier

PAGE_SIZE = 10  # lines per message
LOG_LINES = 200  # how far back /log can page
MAX_CALLBACK = 64  # Telegram's limit for a button's callback_data, in bytes
MAX_MESSAGE = 4000  # Telegram rejects messages longer than 4096 characters
LONG_POLL = 25  # longest single wait for new messages, in seconds
RETRY_DELAY = 5.0  # pause after a failed getUpdates

COMMANDS = {
    "search": "Find courses: /search cis 22",
    "add": "Watch courses: /add 12345 23456",
    "remove": "Stop watching: /remove 12345",
    "list": "Show the watchlist",
    "log": "Recent status records",
    "term": "Show or switch the term: /term 2027 winter",
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


@dataclass(frozen=True)
class Reply:
    text: str
    buttons: list[list[dict]] | None = None


class TermChanged(Exception):
    """Raised out of serve_for after /term switched the bot to another term."""


class CourseBot:
    """Answers Telegram commands that search courses and edit the watchlist.

    Only the chat the notifier is configured for is answered; a bot can be
    messaged by anyone who finds its name.
    """

    def __init__(
        self,
        telegram: TelegramNotifier,
        scraper: CourseStatusScraper,
        courses: list[Course],
        db_path: str,
    ):
        self._telegram = telegram
        self._use(scraper, courses)
        self._db_path = db_path
        self._log = StatusLog(db_path)
        self._offset = 0

    def _use(self, scraper: CourseStatusScraper, courses: list[Course]) -> None:
        self.scraper = scraper
        self._term = scraper.term
        self._index = CourseSearch(courses)
        self.by_crn = {course.crn: course for course in courses}

    @property
    def term(self) -> str:
        return self._term

    def serve_for(self, seconds: float) -> None:
        """Answer incoming commands for this long, then return.

        The monitor uses this in place of time.sleep between polls.
        Raises TermChanged as soon as a /term command has switched terms.
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
                if "callback_query" in update:
                    self._handle_button(update["callback_query"])
                else:
                    self._handle(update.get("message") or {})

    def _allowed(self, message: dict) -> bool:
        chat_id = str((message.get("chat") or {}).get("id", ""))
        if chat_id == self._telegram.chat_id:
            return True
        log.warning("ignored a message from chat %s", chat_id)
        return False

    def _handle(self, message: dict) -> None:
        text = (message.get("text") or "").strip()
        if not text or not self._allowed(message):
            return
        try:
            reply = self.answer(text)
        except TermChanged:
            raise
        except Exception:
            # one bad command must not take the monitor down with it
            log.exception("command failed: %r", text)
            reply = "Something went wrong while handling that command."
        if isinstance(reply, str):
            reply = Reply(reply)
        text = reply.text
        if len(text) > MAX_MESSAGE:
            text = text[:MAX_MESSAGE] + "\n..."
        try:
            self._telegram.send(text, reply.buttons)
        except NotifyError as e:
            log.error("could not reply: %s", e)

    def _handle_button(self, callback: dict) -> None:
        """A page button was pressed: redraw that message with the other page."""
        message = callback.get("message") or {}
        if not self._allowed(message):
            return
        popup = ""
        try:
            reply = self.turn_page(callback.get("data") or "")
            if reply is None:
                popup = "This list is out of date, send the command again."
            elif reply.text != message.get("text"):
                # Telegram rejects an edit that changes nothing
                self._telegram.edit(message["message_id"], reply.text, reply.buttons)
        except NotifyError as e:
            log.error("could not turn the page: %s", e)
        except Exception:
            log.exception("button failed: %r", callback.get("data"))
        try:
            # without this the button keeps showing a loading spinner
            self._telegram.answer_callback(callback["id"], popup)
        except NotifyError as e:
            log.error("could not answer the button: %s", e)

    def turn_page(self, data: str) -> Reply | None:
        """The page a button's callback_data asks for, or None if it is stale."""
        try:
            kind, term, page, arg = data.split(":", 3)
            page = int(page)
        except ValueError:
            return None
        if term != self._term or kind not in self._views():
            return None
        return self._page(kind, arg, page)

    def _views(self) -> dict:
        """Paged lists: kind -> function(arg) returning (title, lines)."""
        return {"s": self._search, "l": self._list, "g": self._recent_log}

    def _page(self, kind: str, arg: str, page: int = 0) -> Reply:
        title, lines = self._views()[kind](arg)
        pages = max(1, -(-len(lines) // PAGE_SIZE))
        page = min(max(page, 0), pages - 1)
        shown = lines[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
        text = "\n".join([title, *shown])
        if pages == 1:
            return Reply(text)

        def button(label: str, target: int) -> dict:
            return {"text": label, "callback_data": f"{kind}:{self._term}:{target}:{arg}"}

        if len(button("", pages)["callback_data"].encode()) > MAX_CALLBACK:
            # the query does not fit in a button, so this list cannot be paged
            more = len(lines) - len(shown)
            return Reply(f"{text}\n... {more} more, type more to narrow down")
        row = [button(f"{page + 1} / {pages}", page)]
        if page > 0:
            row.insert(0, button("< Prev", page - 1))
        if page < pages - 1:
            row.append(button("Next >", page + 1))
        return Reply(text, [row])

    def answer(self, text: str) -> str | Reply:
        """The reply to one message."""
        if not text.startswith("/"):
            return self._page("s", " ".join(text.split()))
        name, *args = text[1:].split() or [""]
        name = name.split("@")[0].lower()  # groups send "/add@BotName"
        if name == "search":
            return self._page("s", " ".join(args)) if args else "Usage: /search QUERY"
        if name in ("add", "remove"):
            if not args or not all(word.isdecimal() for word in args):
                return f"Usage: /{name} CRN..."
            crns = [int(word) for word in args]
            return self._add(crns) if name == "add" else self._remove(crns)
        if name == "list":
            return self._page("l", "")
        if name == "log":
            return self._page("g", "")
        if name == "term":
            return self._switch_term(args)
        return "\n".join(
            [f"Term: {term_name(self._term)}. Send any text to search, or use:"]
            + [f"/{command} - {about}" for command, about in COMMANDS.items()]
        )

    def _switch_term(self, args: list[str]) -> str:
        current = f"Current term: {term_name(self._term)}"
        if not args:
            return f"{current}\nTo switch: /term 2027 winter"
        try:
            year, quarter = args
            code = term_code(int(year), quarter)
        except ValueError:
            return "Usage: /term YEAR QUARTER    (summer, fall, winter or spring)"
        if code == self._term:
            return current

        # loading a term can take a while, so say something first
        self._say(f"Loading {term_name(code)}...")
        scraper = CourseStatusScraper(code)
        try:
            courses = scraper.fetch_all()
        except ScraperError as e:
            return f"Could not load {term_name(code)}, staying on {term_name(self._term)}.\n{e}"
        self._use(scraper, courses)
        watched = len(self._watchlist().courses(code))
        self._say(
            f"Switched to {term_name(code)}: {len(courses)} sections, "
            f"{watched} on the watchlist."
        )
        raise TermChanged

    def _say(self, text: str) -> None:
        try:
            self._telegram.send(text)
        except NotifyError as e:
            log.error("could not reply: %s", e)

    def _search(self, query: str) -> tuple[str, list[str]]:
        results = self._index.search(query)
        if not results:
            return "No matches.", []
        # the index holds the courses as loaded at startup; by_crn has newer
        # data for the ones that are being watched
        lines = [describe(self.by_crn.get(course.crn, course)) for course in results]
        return f'"{query}": {len(lines)} sections', lines

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

    def _list(self, _arg: str = "") -> tuple[str, list[str]]:
        watched = self._watchlist().courses(self._term)
        if not watched:
            return "The watchlist is empty. Use /add CRN", []
        lines = []
        for entry in watched:
            course = self.by_crn.get(entry.crn)
            if course is not None:
                lines.append(describe(course))
            else:
                lines.append(f"{entry.crn:05d} | {entry.code} {entry.section} | not found")
        return f"Watchlist, {term_name(self._term)}: {len(lines)} sections", lines

    def _recent_log(self, _arg: str = "") -> tuple[str, list[str]]:
        # a fresh StatusLog would also work, but recent() always reads the database
        records = self._log.recent(self._term, LOG_LINES)
        if not records:
            return "The log is empty.", []
        lines = []
        for record in records:
            course = self.by_crn.get(record.crn)
            name = f"{course.code} {course.section} | " if course else ""
            lines.append(
                f"{local_time(record.checked_at)} | {record.crn:05d} | {name}"
                f"{record.status} | seats {record.seats_available}/{record.capacity} "
                f"| waitlist {record.wait_count}/{record.wait_capacity}"
            )
        return f"Status log, newest first: {len(lines)} records", lines
