from dataclasses import dataclass

from engine.models.course import Course
from engine.catalog.search import CourseSearch
from engine.catalog.scraper import CourseStatusScraper


@dataclass
class TermData:
    """Everything loaded for one term."""

    index: CourseSearch
    by_crn: dict[int, Course]


class Terms:
    """Per-term scrapers and course lists, shared by every user on that term.

    A scraper is cheap and made on first use. The course list is a download
    of the whole term, so it is loaded once and kept.
    """

    def __init__(self):
        self._scrapers: dict[str, CourseStatusScraper] = {}
        self._data: dict[str, TermData] = {}

    def scraper(self, term: str) -> CourseStatusScraper:
        if term not in self._scrapers:
            self._scrapers[term] = CourseStatusScraper(term)
        return self._scrapers[term]

    def loaded(self, term: str) -> bool:
        return term in self._data

    def load(self, term: str) -> TermData:
        """The term's courses, downloaded on first use. Raises ScraperError."""
        if term not in self._data:
            courses = self.scraper(term).fetch_all()
            self._data[term] = TermData(
                CourseSearch(courses), {course.crn: course for course in courses}
            )
        return self._data[term]

    def update(self, term: str, courses: dict[int, Course]) -> None:
        """Replace courses with fresher copies, e.g. from a poll."""
        if term in self._data:
            self._data[term].by_crn.update(courses)
