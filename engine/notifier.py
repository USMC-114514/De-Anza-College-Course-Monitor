import os
import time

import requests

API_URL = "https://api.telegram.org"
TIMEOUT = 15
ATTEMPTS = 3
RETRY_DELAY = 2.0  # seconds, multiplied by the attempt number


class NotifyError(Exception):
    """The message could not be delivered."""


class TelegramNotifier:
    """Sends text messages to one Telegram chat through a bot."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        api_url: str = API_URL,
        session: requests.Session | None = None,
    ):
        self._token = token
        self._chat_id = chat_id
        self._api_url = api_url
        self._session = session or requests.Session()

    @classmethod
    def from_env(cls) -> "TelegramNotifier":
        """Build from TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."""
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat_id:
            raise NotifyError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set")
        return cls(token, chat_id)

    def send(self, text: str, buttons: list[list[dict]] | None = None) -> None:
        """Send one message, retrying a few times before raising NotifyError.

        `buttons` is an inline keyboard: rows of {"text", "callback_data"}.
        """
        payload = {"chat_id": self._chat_id, "text": text}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        error = None
        for attempt in range(1, ATTEMPTS + 1):
            try:
                self._call("sendMessage", payload)
                return
            except NotifyError as e:
                error = e
                if attempt < ATTEMPTS:
                    time.sleep(RETRY_DELAY * attempt)
        raise error

    @property
    def chat_id(self) -> str:
        return self._chat_id

    def get_updates(self, offset: int, wait: int) -> list[dict]:
        """Messages sent to the bot since `offset`.

        Telegram holds the request open for up to `wait` seconds until
        something arrives, so this doubles as an interruptible sleep.
        """
        payload = {
            "offset": offset,
            "timeout": wait,
            "allowed_updates": ["message", "callback_query"],
        }
        return self._call("getUpdates", payload, timeout=wait + TIMEOUT)["result"]

    def edit(
        self, message_id: int, text: str, buttons: list[list[dict]] | None = None
    ) -> None:
        """Replace the text and buttons of a message the bot sent earlier."""
        payload = {
            "chat_id": self._chat_id,
            "message_id": message_id,
            "text": text,
            "reply_markup": {"inline_keyboard": buttons or []},
        }
        self._call("editMessageText", payload)

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        """Acknowledge a button press; `text` shows up as a small popup."""
        self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    def set_commands(self, commands: dict[str, str]) -> None:
        """Publish the command menu shown in the Telegram app."""
        listed = [{"command": name, "description": text} for name, text in commands.items()]
        self._call("setMyCommands", {"commands": listed})

    def _call(self, method: str, payload: dict, timeout: float = TIMEOUT) -> dict:
        try:
            response = self._session.post(
                f"{self._api_url}/bot{self._token}/{method}",
                json=payload,
                timeout=timeout,
            )
            body = response.json()
        except (requests.RequestException, ValueError) as e:
            # the URL contains the bot token, so keep it out of the message
            reason = str(e).replace(self._token, "<token>")
            raise NotifyError(f"{method} failed: {reason}") from None
        if not body.get("ok"):
            raise NotifyError(f"{method} rejected: {body.get('description', body)}")
        return body


def find_chats(token: str, api_url: str = API_URL) -> dict[int, str]:
    """Chats that recently wrote to the bot, as {chat_id: name}."""
    notifier = TelegramNotifier(token, "", api_url)
    chats = {}
    for update in notifier._call("getUpdates", {})["result"]:
        chat = (update.get("message") or {}).get("chat")
        if chat:
            name = chat.get("title") or chat.get("username") or chat.get("first_name")
            chats[chat["id"]] = name or ""
    return chats


if __name__ == "__main__":
    import sys
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        sys.exit("Set TELEGRAM_BOT_TOKEN first (in .env or the environment).")
    try:
        if os.environ.get("TELEGRAM_CHAT_ID", "").strip():
            TelegramNotifier.from_env().send("Course monitor: test message.")
            print("Test message sent.")
        else:
            found = find_chats(bot_token)
            if not found:
                print("No chats yet. Send any message to your bot, then run this again.")
            for chat_id, chat_name in found.items():
                print(f"TELEGRAM_CHAT_ID={chat_id}    ({chat_name})")
    except NotifyError as e:
        sys.exit(str(e))
