#ifndef DE_ANZA_COLLEGE_COURSE_MONITOR_WATCHLIST_H
#define DE_ANZA_COLLEGE_COURSE_MONITOR_WATCHLIST_H

#include <string>
#include <unordered_map>
#include <vector>

#include "sqlite_db.h"

struct WatchedCourse {
    std::string term;
    int crn = 0;
    std::string department;
    std::string course_number;
    std::string section;
    std::string course_name;
    std::string added_at; // UTC, "YYYY-MM-DD HH:MM:SS"

    std::string code() const { return department + " " + course_number; }
};

// 监控列表：内存里按 学期 -> CRN 建哈希索引，每次修改同步写入 SQLite。
class Watchlist {
public:
    explicit Watchlist(const std::string& db_path);

    // 已在列表中时返回 false
    bool add(const std::string& term, int crn, const std::string& department,
             const std::string& course_number, const std::string& section,
             const std::string& course_name);

    // 不在列表中时返回 false
    bool remove(const std::string& term, int crn);

    bool contains(const std::string& term, int crn) const;

    // 该学期的全部课程，按 前缀、课程号、section、CRN 排序
    std::vector<WatchedCourse> courses(const std::string& term) const;

    std::size_t size() const;

private:
    void load();

    Database db_;
    // CRN 只在同一个学期内唯一
    std::unordered_map<std::string, std::unordered_map<int, WatchedCourse>> by_term_;
};

#endif //DE_ANZA_COLLEGE_COURSE_MONITOR_WATCHLIST_H
