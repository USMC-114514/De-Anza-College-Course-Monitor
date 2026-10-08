from collections.abc import Iterable

from engine.course import Course
from engine._native import Trie


def _sort_key(course: Course):
    return course.department, course.course_number, course.section, course.crn


class CourseSearch:
    """Prefix search over course codes ("CIS 22A") and course names."""

    def __init__(self, courses: Iterable[Course]):
        self._codes = Trie()
        self._names = Trie()
        for course in courses:
            self.add(course)

    def add(self, course: Course) -> None:
        # codes are stored without spaces so "cis22", "CIS 22" and "cis 22a" all match
        self._codes.insert("".join(course.code.lower().split()), course)

        # the full name plus each of its words, so "chem" finds "General Chemistry I"
        words = course.course_name.lower().split()
        for key in {" ".join(words), *words}:
            self._names.insert(key, course)

    def search(self, query: str) -> list[Course]:
        """Return the matching courses in alphabetical order of course code."""
        words = query.lower().split()
        if not words:
            return []
        matches = self._codes.search("".join(words)) + self._names.search(
            " ".join(words)
        )
        unique = {course.crn: course for course in matches}
        return sorted(unique.values(), key=_sort_key)


if __name__ == "__main__":
    import sys

    from engine.course_status_scraper import CourseStatusScraper

    if len(sys.argv) < 4:
        sys.exit(
            "usage: python -m engine.course_search TERM SUBJECT QUERY...\n"
            "   e.g. python -m engine.course_search 202732 CIS 22"
        )
    index = CourseSearch(CourseStatusScraper(sys.argv[1]).fetch_subject(sys.argv[2]))
    for c in index.search(" ".join(sys.argv[3:])):
        print(f"{c.crn:05d}  {c.code:<10} {c.section:<4} {c.course_name}")
