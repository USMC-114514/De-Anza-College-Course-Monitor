#ifndef DE_ANZA_COLLEGE_COURSE_MONITOR_WATCHLIST_H
#define DE_ANZA_COLLEGE_COURSE_MONITOR_WATCHLIST_H

#include <cstdint>
#include <map>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "sqlite_db.h"

struct WatchedCourse {
    std::int64_t chat_id = 0; // 用户，也就是 Telegram 的 chat id
    std::string term;
    int crn = 0;
    std::string department;
    std::string course_number;
    std::string section;
    std::string course_name;
    std::string added_at; // UTC, "YYYY-MM-DD HH:MM:SS"

    std::string code() const { return department + " " + course_number; }
};

// 多用户监控列表：每个用户有自己的列表，每次修改同步写入 SQLite。
// 内存里维护两个方向的哈希索引：
//   课程 -> 关注它的用户（轮询、发通知时用）
//   用户 -> 他关注的课程（显示某个人的列表时用）
class Watchlist {
public:
    explicit Watchlist(const std::string& db_path);

    // 把旧版（不分用户）的表整体划给 owner。已经是新版或还没有表时什么都不做，返回 false
    static bool migrate(const std::string& db_path, std::int64_t owner);

    // 该用户已经关注这门课时返回 false
    bool add(std::int64_t chat_id, const std::string& term, int crn,
             const std::string& department, const std::string& course_number,
             const std::string& section, const std::string& course_name);

    // 该用户没有关注这门课时返回 false
    bool remove(std::int64_t chat_id, const std::string& term, int crn);

    // 删掉一个用户的全部课程，返回删掉的条数
    std::size_t remove_user(std::int64_t chat_id);

    bool contains(std::int64_t chat_id, const std::string& term, int crn) const;

    // 一个用户在该学期的课程，按 前缀、课程号、section、CRN 排序
    std::vector<WatchedCourse> courses(std::int64_t chat_id, const std::string& term) const;

    // 该学期所有用户关注的课程，每个 CRN 只出现一次，排序同上
    std::vector<WatchedCourse> watched(const std::string& term) const;

    // 关注这门课的用户，按 id 升序
    std::vector<std::int64_t> watchers(const std::string& term, int crn) const;

    // 至少有一门课被关注的学期，升序
    std::vector<std::string> terms() const;

    // 所有用户的条数之和
    std::size_t size() const;

private:
    // 用有序 map 存关注者，watchers() 的结果天然有序
    using Watchers = std::map<std::int64_t, WatchedCourse>;

    void load();
    void index(WatchedCourse course);

    Database db_;
    // CRN 只在同一个学期内唯一
    std::unordered_map<std::string, std::unordered_map<int, Watchers>> by_course_;
    std::unordered_map<std::int64_t, std::unordered_map<std::string, std::unordered_set<int>>>
        by_user_;
    std::size_t size_ = 0;
};

#endif //DE_ANZA_COLLEGE_COURSE_MONITOR_WATCHLIST_H
