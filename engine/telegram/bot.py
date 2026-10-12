import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from engine._native import StatusLog, Watchlist
from engine.catalog.cache import TermData, Terms
from engine.catalog.scraper import ScraperError
from engine.models.course import Course
from engine.models.term import term_code, term_name
from engine.telegram.notifier import NotifyError, TelegramNotifier
from engine.telegram.users import APPROVED, BLOCKED, PENDING, User, Users

PAGE_SIZE = 10  # lines per message
LOG_LINES = 200  # how far back /log can page
LOG_SCAN = 2000  # records read to find the ones about a user's own courses
MAX_WATCHED = 30  # sections one user may watch in a term
MAX_PENDING = 20  # access requests kept waiting; more are ignored
MAX_CALLBACK = 64  # Telegram's limit for a button's callback_data, in bytes
MAX_MESSAGE = 4000  # Telegram rejects messages longer than 4096 characters
LONG_POLL = 25  # longest single wait for new messages, in seconds
RETRY_DELAY = 5.0  # pause after a failed getUpdates

COMMANDS = {
    "search": "Find courses: /search cis 22",
    "add": "Watch courses: /add 12345 23456",
    "remove": "Stop watching: /remove 12345",
    "list": "Show your watchlist",
    "log": "Recent status records of your courses",
    "term": "Show or switch your term: /term 2027 winter",
    "help": "Show the commands",
}
ADMIN_COMMANDS = {
    "users": "Everyone who has asked for access",
    "approve": "Let someone in: /approve ID",
    "kick": "Remove someone and their watchlist: /kick ID",
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


class CourseBot:
    """Answers Telegram commands that search courses and edit watchlists.

    Every private chat is a user with a watchlist and a term of their own.
    A bot can be messaged by anyone who finds its name, so a new chat has to
    be approved by the admin before it is answered.
    """

    def __init__(
        self,
        telegram: TelegramNotifier,
        terms: Terms,
        users: Users,
        db_path: str,
        admin_id: int,
    ):
        self._telegram = telegram
        self._terms = terms
        self._users = users
        self._db_path = db_path
        self._admin_id = admin_id
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
                if "callback_query" in update:
                    self._handle_button(update["callback_query"])
                else:
                    self._handle(update.get("message") or {})

    def _say(self, chat_id: int, text: str, buttons: list[list[dict]] | None = None) -> None:
        if len(text) > MAX_MESSAGE:
            text = text[:MAX_MESSAGE] + "\n..."
        try:
            self._telegram.send(text, buttons, chat_id)
        except NotifyError as e:
            log.error("could not message chat %s: %s", chat_id, e)

    def _admit(self, message: dict) -> User | None:
        """The approved user this message is from. Anyone else gets None,
        after being told where their access request stands."""
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat.get("type") != "private" or not isinstance(chat_id, int):
            return None  # watchlists belong to people, not to groups
        user = self._users.get(chat_id)
        if user is None:
            self._request_access(chat_id, chat)
        elif user.status == PENDING:
            self._say(chat_id, "Your request is still waiting for approval.")
        elif user.status == APPROVED:
            return user
        return None

    def _request_access(self, chat_id: int, chat: dict) -> None:
        if self._users.count(PENDING) >= MAX_PENDING:
            log.warning("ignored chat %s: too many pending requests", chat_id)
            return
        name = " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
        if chat.get("username"):
            name = f"{name} (@{chat['username']})".strip()
        self._users.add(chat_id, name or str(chat_id), PENDING)
        log.info("access requested by %s, chat %s", name, chat_id)
        self._say(
            chat_id,
            "This bot is invite-only. Your request was sent to the owner, "
            "and you will get a message here once it is approved.",
        )
        self._say(
            self._admin_id,
            f"{name or 'Someone'} wants to use the bot.\nid {chat_id}",
            [[
                {"text": "Approve", "callback_data": f"u:approve:{chat_id}"},
                {"text": "Deny", "callback_data": f"u:deny:{chat_id}"},
            ]],
        )

    def _handle(self, message: dict) -> None:
        text = (message.get("text") or "").strip()
        if not text:
            return
        user = self._admit(message)
        if user is None:
            return
        try:
            reply = self.answer(user, text)
        except ScraperError as e:
            log.error("could not load term %s: %s", user.term, e)
            reply = "The class schedule could not be reached. Try again in a minute."
        except Exception:
            # one bad command must not take the monitor down with it
            log.exception("command failed: %r", text)
            reply = "Something went wrong while handling that command."
        if isinstance(reply, str):
            reply = Reply(reply)
        self._say(user.chat_id, reply.text, reply.buttons)

    def _handle_button(self, callback: dict) -> None:
        """A button was pressed: redraw its message with the result."""
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        user = self._users.get(chat["id"]) if isinstance(chat.get("id"), int) else None
        if user is None or user.status != APPROVED:
            return
        data = callback.get("data") or ""
        popup = ""
        try:
            if data.startswith("u:"):
                reply = self._decide(user, data)
            else:
                reply = self.turn_page(user, data)
            if reply is None:
                popup = "This list is out of date, send the command again."
            elif reply.text != message.get("text"):
                # Telegram rejects an edit that changes nothing
                self._telegram.edit(
                    message["message_id"], reply.text, reply.buttons, user.chat_id
                )
        except ScraperError:
            popup = "The class schedule could not be reached. Try again in a minute."
        except NotifyError as e:
            log.error("could not redraw the message: %s", e)
        except Exception:
            log.exception("button failed: %r", data)
        try:
            # without this the button keeps showing a loading spinner
            self._telegram.answer_callback(callback["id"], popup)
        except NotifyError as e:
            log.error("could not answer the button: %s", e)

    def turn_page(self, user: User, data: str) -> Reply | None:
        """The page a button's callback_data asks for, or None if it is stale."""
        try:
            kind, term, page, arg = data.split(":", 3)
            page = int(page)
        except ValueError:
            return None
        if term != user.term or kind not in self._views():
            return None
        return self._page(user, kind, arg, page)

    def _views(self) -> dict:
        """Paged lists: kind -> function(user, arg) returning (title, lines)."""
        return {"s": self._search, "l": self._list, "g": self._recent_log}

    def _page(self, user: User, kind: str, arg: str, page: int = 0) -> Reply:
        title, lines = self._views()[kind](user, arg)
        pages = max(1, -(-len(lines) // PAGE_SIZE))
        page = min(max(page, 0), pages - 1)
        shown = lines[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
        text = "\n".join([title, *shown])
        if pages == 1:
            return Reply(text)

        def button(label: str, target: int) -> dict:
            return {"text": label, "callback_data": f"{kind}:{user.term}:{target}:{arg}"}

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

    def answer(self, user: User, text: str) -> str | Reply:
        """The reply to one message from an approved user."""
        if not text.startswith("/"):
            return self._page(user, "s", " ".join(text.split()))
        name, *args = text[1:].split() or [""]
        name = name.split("@")[0].lower()  # groups send "/add@BotName"
        if name == "search":
            return self._page(user, "s", " ".join(args)) if args else "Usage: /search QUERY"
        if name in ("add", "remove"):
            if not args or not all(word.isdecimal() for word in args):
                return f"Usage: /{name} CRN..."
            crns = [int(word) for word in args]
            return self._add(user, crns) if name == "add" else self._remove(user, crns)
        if name == "list":
            return self._page(user, "l", "")
        if name == "log":
            return self._page(user, "g", "")
        if name == "term":
            return self._switch_term(user, args)
        commands = dict(COMMANDS)
        if user.chat_id == self._admin_id:
            if name == "users":
                return self._list_users()
            if name in ("approve", "kick"):
                if len(args) != 1 or not args[0].isdecimal():
                    return f"Usage: /{name} ID    (ids are shown by /users)"
                return self._set_access(int(args[0]), name == "approve")
            commands.update(ADMIN_COMMANDS)
        return "\n".join(
            [f"Term: {term_name(user.term)}. Send any text to search, or use:"]
            + [f"/{command} - {about}" for command, about in commands.items()]
        )

    # ---- access ----

    def _decide(self, admin: User, data: str) -> Reply | None:
        """An Approve or Deny button under an access request."""
        try:
            _, action, chat_id = data.split(":")
            chat_id = int(chat_id)
        except ValueError:
            return None
        if admin.chat_id != self._admin_id or action not in ("approve", "deny"):
            return None
        return Reply(self._set_access(chat_id, action == "approve"))

    def _set_access(self, chat_id: int, allow: bool) -> str:
        user = self._users.get(chat_id)
        if user is None:
            return f"Nobody with id {chat_id} has messaged the bot."
        if chat_id == self._admin_id:
            return "That is you."
        label = f"{user.name}, id {chat_id}"
        if allow:
            if user.status == APPROVED:
                return f"{label}: already approved."
            self._users.set_status(chat_id, APPROVED)
            if user.term is None:
                # new users start on the term the admin is looking at
                self._users.set_term(chat_id, self._users.get(self._admin_id).term)
            self._say(chat_id, "You are in. Send /help to see what the bot can do.")
            return f"{label}: approved."
        removed = Watchlist(self._db_path).remove_user(chat_id)
        was_approved = user.status == APPROVED
        self._users.set_status(chat_id, BLOCKED)
        if was_approved:
            return f"{label}: removed, along with {removed} watched sections."
        return f"{label}: denied."

    def _list_users(self) -> str:
        watchlist = Watchlist(self._db_path)
        lines = []
        for user in self._users.all():
            line = f"{user.chat_id} | {user.name} | {user.status}"
            if user.status == APPROVED:
                watched = len(watchlist.courses(user.chat_id, user.term))
                line += f" | {term_name(user.term)}, {watched} sections"
            lines.append(line)
        return "\n".join(lines)

    # ---- per-user commands ----

    def _data(self, user: User) -> TermData:
        return self._terms.load(user.term)

    def _switch_term(self, user: User, args: list[str]) -> str:
        current = f"Current term: {term_name(user.term)}"
        if not args:
            return f"{current}\nTo switch: /term 2027 winter"
        try:
            year, quarter = args
            code = term_code(int(year), quarter)
        except ValueError:
            return "Usage: /term YEAR QUARTER    (summer, fall, winter or spring)"
        if code == user.term:
            return current

        if not self._terms.loaded(code):
            # loading a term can take a while, so say something first
            self._say(user.chat_id, f"Loading {term_name(code)}...")
        try:
            sections = len(self._terms.load(code).by_crn)
        except ScraperError as e:
            return f"Could not load {term_name(code)}, staying on {term_name(user.term)}.\n{e}"
        self._users.set_term(user.chat_id, code)
        watched = len(self._watchlist().courses(user.chat_id, code))
        return (
            f"Switched to {term_name(code)}: {sections} sections, "
            f"{watched} on your watchlist."
        )

    def _search(self, user: User, query: str) -> tuple[str, list[str]]:
        data = self._data(user)
        results = data.index.search(query)
        if not results:
            return "No matches.", []
        # the index holds the courses as loaded at startup; by_crn has newer
        # data for the ones that are being watched
        lines = [describe(data.by_crn.get(course.crn, course)) for course in results]
        return f'"{query}": {len(lines)} sections', lines

    def _watchlist(self) -> Watchlist:
        # opened per command so changes made by main.py are never overwritten
        # by a stale in-memory copy
        return Watchlist(self._db_path)

    def _add(self, user: User, crns: list[int]) -> str:
        by_crn = self._data(user).by_crn
        watchlist = self._watchlist()
        watched = len(watchlist.courses(user.chat_id, user.term))
        lines = []
        for crn in crns:
            course = by_crn.get(crn)
            if course is None:
                lines.append(f"{crn:05d} not found in this term")
            elif watchlist.contains(user.chat_id, user.term, crn):
                lines.append(f"{crn:05d} is already on your watchlist")
            elif watched >= MAX_WATCHED:
                lines.append(f"{crn:05d} not added: the limit is {MAX_WATCHED} sections")
            else:
                watchlist.add(
                    user.chat_id,
                    user.term,
                    course.crn,
                    course.department,
                    course.course_number,
                    course.section,
                    course.course_name,
                )
                watched += 1
                lines.append(f"Added {describe(course)}")
        return "\n".join(lines)

    def _remove(self, user: User, crns: list[int]) -> str:
        watchlist = self._watchlist()
        lines = []
        for crn in crns:
            if watchlist.remove(user.chat_id, user.term, crn):
                lines.append(f"{crn:05d} removed")
            else:
                lines.append(f"{crn:05d} was not on your watchlist")
        return "\n".join(lines)

    def _list(self, user: User, _arg: str = "") -> tuple[str, list[str]]:
        watched = self._watchlist().courses(user.chat_id, user.term)
        if not watched:
            return "Your watchlist is empty. Use /add CRN", []
        by_crn = self._data(user).by_crn
        lines = []
        for entry in watched:
            course = by_crn.get(entry.crn)
            if course is not None:
                lines.append(describe(course))
            else:
                lines.append(f"{entry.crn:05d} | {entry.code} {entry.section} | not found")
        return f"Watchlist, {term_name(user.term)}: {len(lines)} sections", lines

    def _recent_log(self, user: User, _arg: str = "") -> tuple[str, list[str]]:
        # the log is shared, so keep only the courses this user watches
        mine = {entry.crn for entry in self._watchlist().courses(user.chat_id, user.term)}
        records = [
            record
            for record in self._log.recent(user.term, LOG_SCAN)
            if record.crn in mine
        ][:LOG_LINES]
        if not records:
            return "The log is empty.", []
        by_crn = self._data(user).by_crn
        lines = []
        for record in records:
            course = by_crn.get(record.crn)
            name = f"{course.code} {course.section} | " if course else ""
            lines.append(
                f"{local_time(record.checked_at)} | {record.crn:05d} | {name}"
                f"{record.status} | seats {record.seats_available}/{record.capacity} "
                f"| waitlist {record.wait_count}/{record.wait_capacity}"
            )
        return f"Status log, newest first: {len(lines)} records", lines
