#include "watchlist.h"

#include <algorithm>
#include <stdexcept>
#include <tuple>

namespace {

const char* const kSchema = R"sql(
CREATE TABLE IF NOT EXISTS watch (
    chat_id       INTEGER NOT NULL,
    term          TEXT    NOT NULL,
    crn           INTEGER NOT NULL,
    department    TEXT    NOT NULL,
    course_number TEXT    NOT NULL,
    section       TEXT    NOT NULL,
    course_name   TEXT    NOT NULL,
    added_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, term, crn)
)
)sql";

void sort_courses(std::vector<WatchedCourse>& courses) {
    std::sort(courses.begin(), courses.end(), [](const WatchedCourse& a, const WatchedCourse& b) {
        return std::tie(a.department, a.course_number, a.section, a.crn) <
               std::tie(b.department, b.course_number, b.section, b.crn);
    });
}

} // namespace

Watchlist::Watchlist(const std::string& db_path) : db_(db_path) {
    db_.execute(kSchema);
    load();
}

bool Watchlist::migrate(const std::string& db_path, std::int64_t owner) {
    Database db(db_path);
    bool exists = false;
    bool has_chat_id = false;
    {
        Statement columns(db, "SELECT name FROM pragma_table_info('watch')");
        while (columns.step()) {
            exists = true;
            if (columns.text(0) == "chat_id") has_chat_id = true;
        }
    }
    if (!exists || has_chat_id) return false;

    // 主键变了，SQLite 改不了主键，只能建新表再把数据搬过去。
    // 中途出错时连接关闭，事务自动回滚，旧表原样保留。
    db.execute("BEGIN IMMEDIATE");
    db.execute("ALTER TABLE watch RENAME TO watch_legacy");
    db.execute(kSchema);
    {
        Statement copy(db, "INSERT INTO watch (chat_id, term, crn, department, course_number, "
                           "section, course_name, added_at) "
                           "SELECT ?, term, crn, department, course_number, section, "
                           "course_name, added_at FROM watch_legacy");
        copy.bind(1, owner);
        copy.step();
    }
    db.execute("DROP TABLE watch_legacy");
    db.execute("COMMIT");
    return true;
}

void Watchlist::load() {
    Statement select(db_, "SELECT chat_id, term, crn, department, course_number, section, "
                          "course_name, added_at FROM watch");
    while (select.step()) {
        index(WatchedCourse{select.integer64(0), select.text(1), select.integer(2),
                            select.text(3),      select.text(4), select.text(5),
                            select.text(6),      select.text(7)});
    }
}

void Watchlist::index(WatchedCourse course) {
    by_user_[course.chat_id][course.term].insert(course.crn);
    Watchers& watchers = by_course_[course.term][course.crn];
    watchers.emplace(course.chat_id, std::move(course));
    ++size_;
}

bool Watchlist::add(std::int64_t chat_id, const std::string& term, int crn,
                    const std::string& department, const std::string& course_number,
                    const std::string& section, const std::string& course_name) {
    if (contains(chat_id, term, crn)) return false;

    Statement insert(db_, "INSERT INTO watch "
                          "(chat_id, term, crn, department, course_number, section, course_name) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING added_at");
    insert.bind(1, chat_id);
    insert.bind(2, term);
    insert.bind(3, crn);
    insert.bind(4, department);
    insert.bind(5, course_number);
    insert.bind(6, section);
    insert.bind(7, course_name);
    if (!insert.step()) {
        throw std::runtime_error("insert returned no row");
    }
    WatchedCourse course{chat_id, term, crn, department, course_number, section, course_name,
                         insert.text(0)};
    insert.step(); // 走到 SQLITE_DONE 才算提交

    index(std::move(course));
    return true;
}

bool Watchlist::remove(std::int64_t chat_id, const std::string& term, int crn) {
    if (!contains(chat_id, term, crn)) return false;

    Statement del(db_, "DELETE FROM watch WHERE chat_id = ? AND term = ? AND crn = ?");
    del.bind(1, chat_id);
    del.bind(2, term);
    del.bind(3, crn);
    del.step();

    // 两个方向的索引都要删，空掉的桶一并清理，terms() 才不会返回没人关注的学期
    const auto user = by_user_.find(chat_id);
    const auto user_term = user->second.find(term);
    user_term->second.erase(crn);
    if (user_term->second.empty()) user->second.erase(user_term);
    if (user->second.empty()) by_user_.erase(user);

    const auto sections = by_course_.find(term);
    const auto watchers = sections->second.find(crn);
    watchers->second.erase(chat_id);
    if (watchers->second.empty()) sections->second.erase(watchers);
    if (sections->second.empty()) by_course_.erase(sections);

    --size_;
    return true;
}

std::size_t Watchlist::remove_user(std::int64_t chat_id) {
    const auto user = by_user_.find(chat_id);
    if (user == by_user_.end()) return 0;

    // remove() 会改动 by_user_，所以先把要删的键抄出来
    std::vector<std::pair<std::string, int>> keys;
    for (const auto& [term, crns] : user->second) {
        for (const int crn : crns) keys.emplace_back(term, crn);
    }
    for (const auto& [term, crn] : keys) remove(chat_id, term, crn);
    return keys.size();
}

bool Watchlist::contains(std::int64_t chat_id, const std::string& term, int crn) const {
    const auto user = by_user_.find(chat_id);
    if (user == by_user_.end()) return false;
    const auto crns = user->second.find(term);
    return crns != user->second.end() && crns->second.count(crn) > 0;
}

std::vector<WatchedCourse> Watchlist::courses(std::int64_t chat_id,
                                              const std::string& term) const {
    std::vector<WatchedCourse> result;
    const auto user = by_user_.find(chat_id);
    if (user == by_user_.end()) return result;
    const auto crns = user->second.find(term);
    if (crns == user->second.end()) return result;

    const auto& sections = by_course_.at(term);
    result.reserve(crns->second.size());
    for (const int crn : crns->second) {
        result.push_back(sections.at(crn).at(chat_id));
    }
    sort_courses(result);
    return result;
}

std::vector<WatchedCourse> Watchlist::watched(const std::string& term) const {
    std::vector<WatchedCourse> result;
    const auto sections = by_course_.find(term);
    if (sections == by_course_.end()) return result;

    result.reserve(sections->second.size());
    for (const auto& [crn, watchers] : sections->second) {
        // 课程信息每个关注者存的都一样，取第一个即可
        result.push_back(watchers.begin()->second);
    }
    sort_courses(result);
    return result;
}

std::vector<std::int64_t> Watchlist::watchers(const std::string& term, int crn) const {
    std::vector<std::int64_t> result;
    const auto sections = by_course_.find(term);
    if (sections == by_course_.end()) return result;
    const auto watchers = sections->second.find(crn);
    if (watchers == sections->second.end()) return result;

    result.reserve(watchers->second.size());
    for (const auto& [chat_id, course] : watchers->second) {
        result.push_back(chat_id);
    }
    return result;
}

std::vector<std::string> Watchlist::terms() const {
    std::vector<std::string> result;
    result.reserve(by_course_.size());
    for (const auto& [term, sections] : by_course_) {
        result.push_back(term);
    }
    std::sort(result.begin(), result.end());
    return result;
}

std::size_t Watchlist::size() const { return size_; }
