#ifndef DE_ANZA_COLLEGE_COURSE_MONITOR_SQLITE_DB_H
#define DE_ANZA_COLLEGE_COURSE_MONITOR_SQLITE_DB_H

#include <string>

struct sqlite3;
struct sqlite3_stmt;

// SQLite 连接的 RAII 封装。出错时抛 std::runtime_error。
class Database {
public:
    explicit Database(const std::string& path);
    ~Database();

    Database(const Database&) = delete;
    Database& operator=(const Database&) = delete;

    // 执行不需要参数、不返回结果的语句（建表等）
    void execute(const char* sql);

    sqlite3* handle() const { return db_; }

private:
    sqlite3* db_ = nullptr;
};

// 预编译语句的 RAII 封装，析构时自动 finalize。参数下标从 1 开始，列下标从 0 开始。
class Statement {
public:
    Statement(const Database& db, const char* sql);
    ~Statement();

    Statement(const Statement&) = delete;
    Statement& operator=(const Statement&) = delete;

    void bind(int index, const std::string& value);
    void bind(int index, int value);

    // 有一行结果时返回 true，执行完毕返回 false
    bool step();

    std::string text(int column) const;
    int integer(int column) const;

private:
    sqlite3* db_;
    sqlite3_stmt* stmt_ = nullptr;
};

#endif //DE_ANZA_COLLEGE_COURSE_MONITOR_SQLITE_DB_H
