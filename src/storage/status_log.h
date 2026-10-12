#ifndef DE_ANZA_COLLEGE_COURSE_MONITOR_STATUS_LOG_H
#define DE_ANZA_COLLEGE_COURSE_MONITOR_STATUS_LOG_H

#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "sqlite_db.h"

struct StatusRecord {
    std::string term;
    int crn = 0;
    std::string status; // "OPEN" / "WAITLIST" / "FULL"
    int seats_available = 0;
    int capacity = 0;
    int wait_count = 0;
    int wait_capacity = 0;
    std::string checked_at; // UTC, "YYYY-MM-DD HH:MM:SS"
};

// 状态日志：每门课的状态历史存在 SQLite 里，只在状态或人数变化时追加一条。
// 每门课最新的一条同时缓存在内存里，查询和去重都不用读数据库。
class StatusLog {
public:
    explicit StatusLog(const std::string& db_path);

    // 和这门课的上一条记录相同就不写，返回 false；第一次见到或有变化时写入，返回 true
    bool record(const std::string& term, int crn, const std::string& status,
                int seats_available, int capacity, int wait_count, int wait_capacity);

    // 这门课最近一次记录；从没记录过时为空
    std::optional<StatusRecord> latest(const std::string& term, int crn) const;

    // 该学期最近的 limit 条记录，新的在前
    std::vector<StatusRecord> recent(const std::string& term, int limit) const;

private:
    void load();

    Database db_;
    std::unordered_map<std::string, std::unordered_map<int, StatusRecord>> latest_;
};

#endif //DE_ANZA_COLLEGE_COURSE_MONITOR_STATUS_LOG_H
