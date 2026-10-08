from engine.course import Course
from engine.course_search import CourseSearch
from engine.course_status_scraper import CourseStatusScraper, ScraperError, term_code
from engine.monitor import DEFAULT_INTERVAL, Monitor, PollResult
try:
    from engine._native import StatusLog, Watchlist
except ImportError as e:
    raise SystemExit(
        f"C++ module engine._native is not built ({e}).\n"
        "Build the _native target in CLion, or run:\n"
        "  cmake -S . -B cmake-build-debug && "
        "cmake --build cmake-build-debug --target _native"
    )
import time
from datetime import datetime, timezone
from pathlib import Path

MAX_RESULTS = 30
LOG_LINES = 30
DB_PATH = Path(__file__).resolve().parent / "course_monitor.db"
year = time.localtime()[0]
month = time.localtime()[1]
day = time.localtime()[2]
md = (month, day)
def get_year():
    return year
def get_month():
    return month
def get_day():
    return day

def get_season(md):
    if (3, 27) <= md < (6, 26):
        return "spring"
    if (6, 26) <= md < (8, 6):
        return "summer"
    if (8, 6) <= md < (12, 12):
        return "fall"
    return "winter"  # 12/12 - 3/26


def current_term() -> tuple[int, str]:
    """The (year, quarter) that today's local date falls in."""
    season = get_season(md)
    # the winter quarter that starts in December belongs to the next year
    if season == "winter" and get_month() == 12:
        return get_year() + 1, season
    return get_year(), season


def prompt_term() -> str:
    default_year, default_quarter = current_term()
    while True:
        answer = input(
            f"Enter the term you want to snipe. (Return = [{default_year} {default_quarter}]): "
        ).split()
        if not answer:
            return term_code(default_year, default_quarter)
        try:
            year, quarter = answer
            return term_code(int(year), quarter)
        except ValueError:
            print("  Enter a year and a quarter: summer, fall, winter or spring.")


def load_courses() -> tuple[CourseStatusScraper, list[Course]]:
    while True:
        scraper = CourseStatusScraper(prompt_term())
        print("Loading courses...")
        try:
            return scraper, scraper.fetch_all()
        except ScraperError as e:
            print(f"  Could not load term {scraper.term}: {e}")


def print_course(course: Course) -> None:
    print(
        f"  {course.crn:05d}  {course.code:<10} {course.section:<4} "
        f"{course.status.value:<8} "
        f"seats {course.seats_available:>3}/{course.capacity:<3}  "
        f"{course.course_name}  ({course.instructor})"
    )


def parse_crns(words: list[str]) -> list[int] | None:
    """Return the CRNs, or None if any word is not a number."""
    if not words or not all(word.isdecimal() for word in words):
        return None
    return [int(word) for word in words]


def add_to_watchlist(
    watchlist: Watchlist, term: str, by_crn: dict[int, Course], crns: list[int]
) -> None:
    for crn in crns:
        course = by_crn.get(crn)
        if course is None:
            print(f"  {crn:05d}  not found in this term")
        elif watchlist.add(
            term,
            course.crn,
            course.department,
            course.course_number,
            course.section,
            course.course_name,
        ):
            print(f"  {crn:05d}  added: {course.code} {course.section}")
        else:
            print(f"  {crn:05d}  already on the watchlist")


def remove_from_watchlist(watchlist: Watchlist, term: str, crns: list[int]) -> None:
    for crn in crns:
        if watchlist.remove(term, crn):
            print(f"  {crn:05d}  removed")
        else:
            print(f"  {crn:05d}  was not on the watchlist")


def print_watchlist(watchlist: Watchlist, term: str, by_crn: dict[int, Course]) -> None:
    watched = watchlist.courses(term)
    if not watched:
        print("  The watchlist is empty. Use: /add")
        return
    for entry in watched:
        course = by_crn.get(entry.crn)
        if course is not None:
            print_course(course)
        else:
            # still on the list but no longer offered this term
            print(
                f"  {entry.crn:05d}  {entry.code:<10} {entry.section:<4} "
                f"not found in this term  {entry.course_name}"
            )


def print_status(course: Course) -> None:
    print(
        f"           {course.crn:05d}  {course.code:<10} {course.section:<4} "
        f"{course.status.value:<8} "
        f"seats {course.seats_available}/{course.capacity}  "
        f"waitlist {course.wait_count}/{course.wait_capacity}"
    )


def local_time(utc: str) -> str:
    """Convert the database's UTC "YYYY-MM-DD HH:MM:SS" to local time."""
    moment = datetime.fromisoformat(utc).replace(tzinfo=timezone.utc)
    return moment.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def watch(monitor: Monitor, by_crn: dict[int, Course]) -> None:
    """Poll the watchlist until Ctrl+C, printing every status change."""
    reported_missing: set[int] = set()

    def on_result(result: PollResult, delay: float) -> None:
        by_crn.update(result.courses)  # keeps search and list output fresh
        now = time.strftime("%H:%M:%S")
        if result.first:
            print(f"[{now}] watching {len(result.courses)} sections:")
            for course in result.courses.values():
                print_status(course)
        for change in result.changes:
            print(f"[{now}] CHANGED  {change.old.value} -> {change.new.value}")
            print_status(change.course)
        for crn in result.missing:
            if crn not in reported_missing:
                reported_missing.add(crn)
                print(f"[{now}] {crn:05d} is no longer listed in this term")
        if not result.first and not result.changes:
            print(f"[{now}] no changes, next check in {delay:.0f}s")

    def on_error(error: ScraperError, delay: float) -> None:
        now = time.strftime("%H:%M:%S")
        print(f"[{now}] check failed, retrying in {delay:.0f}s: {error}")

    print(f"Checking about every {DEFAULT_INTERVAL:.0f}s. Press Ctrl+C to stop.")
    try:
        monitor.run(on_result, on_error)
    except KeyboardInterrupt:
        print("\nStopped watching.")


MENU = """
  1. Search courses
  2. Snipe courses
  q. Quit"""
COMMANDS = (
    "Commands, usable at any prompt:\n"
    "  /search    /add    /remove    /list    /snipe    /log    /back    /menu    /quit"
)
SNIPE_OPTIONS = "Options: /add    /remove    /back"


class Goto(Exception):
    """Leave the current prompt and switch to another mode ("back" = the previous one)."""

    def __init__(self, mode: str):
        self.mode = mode


class Quit(Exception):
    pass


class App:
    def __init__(self, scraper: CourseStatusScraper, courses: list[Course]):
        self.scraper = scraper
        self.term = scraper.term
        self.index = CourseSearch(courses)
        self.by_crn = {course.crn: course for course in courses}
        self.watchlist = Watchlist(str(DB_PATH))
        self.status_log = StatusLog(str(DB_PATH))

    def search(self, query: str) -> None:
        results = self.index.search(query)
        if not results:
            print("  No matches.")
            return
        for course in results[:MAX_RESULTS]:
            print_course(course)
        if len(results) > MAX_RESULTS:
            print(f"  ... {len(results) - MAX_RESULTS} more, type more to narrow down")

    def ask_crns(self, action: str) -> list[int]:
        """Prompt for CRNs; an empty line cancels and goes to the menu."""
        while True:
            words = input(f"  CRNs to {action} (Enter = cancel): ").split()
            if not words:
                raise Goto("menu")
            crns = parse_crns(words)
            if crns:
                return crns
            print("  Enter CRN numbers separated by spaces.")

    def check_once(self) -> None:
        """Poll the watchlist a single time and show the result."""
        if not self.watchlist.courses(self.term):
            print("  The watchlist is empty. Use: /add")
            return
        print("Checking the watchlist...")
        try:
            result = self.new_monitor().poll()
        except ScraperError as e:
            print(f"  Check failed, showing the last known status: {e}")
        else:
            self.by_crn.update(result.courses)
            for crn in result.missing:
                self.by_crn.pop(crn, None)
            for change in result.changes:
                print(
                    f"  CHANGED since the last check: {change.course.crn:05d} "
                    f"{change.old.value} -> {change.new.value}"
                )
        print_watchlist(self.watchlist, self.term, self.by_crn)

    def keep_watching(self) -> None:
        """Poll the watchlist until Ctrl+C."""
        if not self.watchlist.courses(self.term):
            print("  The watchlist is empty. Use: /add")
            return
        watch(self.new_monitor(), self.by_crn)

    def new_monitor(self) -> Monitor:
        return Monitor(self.scraper, self.watchlist, self.term, self.status_log)

    def print_log(self) -> None:
        """Show the latest status records of this term, newest first."""
        records = self.status_log.recent(self.term, LOG_LINES)
        if not records:
            print("  The log is empty. Statuses are recorded by /snipe and /list.")
            return
        for record in records:
            course = self.by_crn.get(record.crn)
            name = f"{course.code} {course.section}" if course else ""
            print(
                f"  {local_time(record.checked_at)}  {record.crn:05d}  {name:<15} "
                f"{record.status:<8} "
                f"seats {record.seats_available}/{record.capacity}  "
                f"waitlist {record.wait_count}/{record.wait_capacity}"
            )

    def command(self, line: str) -> None:
        """Run a line that starts with "/"."""
        name, *args = line[1:].split() or [""]
        name = name.lower()
        if name == "search":
            if not args:
                raise Goto("search")
            self.search(" ".join(args))
        elif name == "add":
            crns = parse_crns(args) or self.ask_crns("add")
            add_to_watchlist(self.watchlist, self.term, self.by_crn, crns)
        elif name == "remove":
            crns = parse_crns(args) or self.ask_crns("remove")
            remove_from_watchlist(self.watchlist, self.term, crns)
        elif name == "list" and not args:
            self.keep_watching()
        elif name == "log" and not args:
            self.print_log()
        elif name == "snipe" and not args:
            raise Goto("snipe")
        elif name in ("menu", "back") and not args:
            raise Goto(name)
        elif name in ("quit", "q", "exit") and not args:
            raise Quit
        else:
            print(COMMANDS)

    def read(self, prompt: str) -> str:
        """Read one line; slash commands are run here and never returned."""
        while True:
            line = input(f"\n{prompt}> ").strip()
            if not line.startswith("/"):
                return line
            self.command(line)

    def menu_mode(self) -> None:
        print(MENU)
        while True:
            choice = self.read("menu").lower()
            if choice == "1":
                raise Goto("search")
            if choice == "2":
                raise Goto("snipe")
            if choice in ("q", "quit", "exit"):
                raise Quit

    def search_mode(self) -> None:
        print('Search by course code ("cis 22") or name ("python"). /back to go back.')
        while True:
            query = self.read("search")
            if query:
                self.search(query)

    def snipe_mode(self) -> None:
        self.check_once()
        print(SNIPE_OPTIONS)
        while True:
            if self.read("snipe"):
                print(SNIPE_OPTIONS)

    def run(self) -> None:
        modes = {
            "menu": self.menu_mode,
            "search": self.search_mode,
            "snipe": self.snipe_mode,
        }
        history = ["menu"]  # the modes entered so far; the last one is current
        while True:
            try:
                modes[history[-1]]()
            except Goto as goto:
                if goto.mode == "back":
                    if len(history) > 1:
                        history.pop()
                elif goto.mode == "menu":
                    history = ["menu"]
                elif goto.mode != history[-1]:
                    history.append(goto.mode)


def main() -> None:
    scraper, courses = load_courses()
    print(f"Loaded {len(courses)} sections.")
    print(COMMANDS)
    try:
        App(scraper, courses).run()
    except Quit:
        pass


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print()
