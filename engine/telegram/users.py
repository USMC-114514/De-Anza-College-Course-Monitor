import sqlite3
from contextlib import closing
from dataclasses import dataclass

PENDING = "pending"  # asked for access, the admin has not answered yet
APPROVED = "approved"
BLOCKED = "blocked"  # denied or removed; their messages are ignored

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user (
    chat_id   INTEGER PRIMARY KEY,
    name      TEXT    NOT NULL,
    status    TEXT    NOT NULL,
    term      TEXT,
    joined_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


@dataclass(frozen=True)
class User:
    chat_id: int  # the Telegram private chat, which is also the user's id
    name: str
    status: str
    term: str | None  # the term this user is looking at


class Users:
    """Who may use the bot, and which term each of them is on."""

    def __init__(self, db_path: str):
        self._path = db_path
        self._run(_SCHEMA)

    def _run(self, sql: str, *args) -> list[tuple]:
        # a connection per call keeps this safe to use next to the C++ classes,
        # which hold their own connections to the same file
        with closing(sqlite3.connect(self._path, timeout=5)) as db, db:
            return db.execute(sql, args).fetchall()

    def get(self, chat_id: int) -> User | None:
        rows = self._run(
            "SELECT chat_id, name, status, term FROM user WHERE chat_id = ?", chat_id
        )
        return User(*rows[0]) if rows else None

    def all(self) -> list[User]:
        rows = self._run("SELECT chat_id, name, status, term FROM user ORDER BY joined_at, chat_id")
        return [User(*row) for row in rows]

    def count(self, status: str) -> int:
        return self._run("SELECT COUNT(*) FROM user WHERE status = ?", status)[0][0]

    def add(self, chat_id: int, name: str, status: str, term: str | None = None) -> None:
        self._run(
            "INSERT OR REPLACE INTO user (chat_id, name, status, term) VALUES (?, ?, ?, ?)",
            chat_id,
            name,
            status,
            term,
        )

    def set_status(self, chat_id: int, status: str) -> None:
        self._run("UPDATE user SET status = ? WHERE chat_id = ?", status, chat_id)

    def set_term(self, chat_id: int, term: str) -> None:
        self._run("UPDATE user SET term = ? WHERE chat_id = ?", term, chat_id)
