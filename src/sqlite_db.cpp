#include "sqlite_db.h"

#include <stdexcept>

#include <sqlite3.h>

namespace {

[[noreturn]] void fail(sqlite3* db, const std::string& what) {
    throw std::runtime_error(what + ": " + sqlite3_errmsg(db));
}

} // namespace

Database::Database(const std::string& path) {
    if (sqlite3_open(path.c_str(), &db_) != SQLITE_OK) {
        const std::string message = db_ ? sqlite3_errmsg(db_) : "out of memory";
        sqlite3_close(db_);
        throw std::runtime_error("cannot open " + path + ": " + message);
    }
    // 监控列表和状态日志各开一个连接，写入撞车时等一会儿而不是立刻报错
    sqlite3_busy_timeout(db_, 5000);
}

Database::~Database() { sqlite3_close(db_); }

void Database::execute(const char* sql) {
    if (sqlite3_exec(db_, sql, nullptr, nullptr, nullptr) != SQLITE_OK) {
        fail(db_, "execute failed");
    }
}

Statement::Statement(const Database& db, const char* sql) : db_(db.handle()) {
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt_, nullptr) != SQLITE_OK) {
        fail(db_, "prepare failed");
    }
}

Statement::~Statement() { sqlite3_finalize(stmt_); }

void Statement::bind(int index, const std::string& value) {
    if (sqlite3_bind_text(stmt_, index, value.c_str(), -1, SQLITE_TRANSIENT) != SQLITE_OK) {
        fail(db_, "bind failed");
    }
}

void Statement::bind(int index, int value) {
    if (sqlite3_bind_int(stmt_, index, value) != SQLITE_OK) {
        fail(db_, "bind failed");
    }
}

bool Statement::step() {
    const int rc = sqlite3_step(stmt_);
    if (rc == SQLITE_ROW) return true;
    if (rc == SQLITE_DONE) return false;
    fail(db_, "step failed");
}

std::string Statement::text(int column) const {
    const unsigned char* value = sqlite3_column_text(stmt_, column);
    return value ? reinterpret_cast<const char*>(value) : "";
}

int Statement::integer(int column) const { return sqlite3_column_int(stmt_, column); }
