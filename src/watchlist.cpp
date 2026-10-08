#include "watchlist.h"

#include <algorithm>
#include <stdexcept>
#include <tuple>

namespace {

const char* const kSchema = R"sql(
CREATE TABLE IF NOT EXISTS watch (
    term          TEXT    NOT NULL,
    crn           INTEGER NOT NULL,
    department    TEXT    NOT NULL,
    course_number TEXT    NOT NULL,
    section       TEXT    NOT NULL,
    course_name   TEXT    NOT NULL,
    added_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (term, crn)
)
)sql";

} // namespace

Watchlist::Watchlist(const std::string& db_path) : db_(db_path) {
    db_.execute(kSchema);
    load();
}

void Watchlist::load() {
    Statement select(db_, "SELECT term, crn, department, course_number, section, "
                          "course_name, added_at FROM watch");
    while (select.step()) {
        WatchedCourse course{select.text(0), select.integer(1), select.text(2), select.text(3),
                             select.text(4), select.text(5),    select.text(6)};
        by_term_[course.term].emplace(course.crn, std::move(course));
    }
}

bool Watchlist::add(const std::string& term, int crn, const std::string& department,
                    const std::string& course_number, const std::string& section,
                    const std::string& course_name) {
    if (contains(term, crn)) return false;

    Statement insert(db_, "INSERT INTO watch "
                          "(term, crn, department, course_number, section, course_name) "
                          "VALUES (?, ?, ?, ?, ?, ?) RETURNING added_at");
    insert.bind(1, term);
    insert.bind(2, crn);
    insert.bind(3, department);
    insert.bind(4, course_number);
    insert.bind(5, section);
    insert.bind(6, course_name);
    if (!insert.step()) {
        throw std::runtime_error("insert returned no row");
    }
    WatchedCourse course{term, crn, department, course_number, section, course_name,
                         insert.text(0)};
    insert.step(); // 走到 SQLITE_DONE 才算提交

    by_term_[term].emplace(crn, std::move(course));
    return true;
}

bool Watchlist::remove(const std::string& term, int crn) {
    if (!contains(term, crn)) return false;

    Statement del(db_, "DELETE FROM watch WHERE term = ? AND crn = ?");
    del.bind(1, term);
    del.bind(2, crn);
    del.step();

    auto courses = by_term_.find(term);
    courses->second.erase(crn);
    if (courses->second.empty()) by_term_.erase(courses);
    return true;
}

bool Watchlist::contains(const std::string& term, int crn) const {
    const auto courses = by_term_.find(term);
    return courses != by_term_.end() && courses->second.count(crn) > 0;
}

std::vector<WatchedCourse> Watchlist::courses(const std::string& term) const {
    std::vector<WatchedCourse> result;
    const auto courses = by_term_.find(term);
    if (courses == by_term_.end()) return result;

    result.reserve(courses->second.size());
    for (const auto& [crn, course] : courses->second) {
        result.push_back(course);
    }
    std::sort(result.begin(), result.end(), [](const WatchedCourse& a, const WatchedCourse& b) {
        return std::tie(a.department, a.course_number, a.section, a.crn) <
               std::tie(b.department, b.course_number, b.section, b.crn);
    });
    return result;
}

std::size_t Watchlist::size() const {
    std::size_t total = 0;
    for (const auto& [term, courses] : by_term_) {
        total += courses.size();
    }
    return total;
}
