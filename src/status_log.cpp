#include "status_log.h"

#include <stdexcept>

namespace {

const char* const kSchema = R"sql(
CREATE TABLE IF NOT EXISTS status_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    term            TEXT    NOT NULL,
    crn             INTEGER NOT NULL,
    status          TEXT    NOT NULL,
    seats_available INTEGER NOT NULL,
    capacity        INTEGER NOT NULL,
    wait_count      INTEGER NOT NULL,
    wait_capacity   INTEGER NOT NULL,
    checked_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS status_log_term_crn ON status_log (term, crn, id);
)sql";

const char* const kColumns = "term, crn, status, seats_available, capacity, wait_count, "
                             "wait_capacity, checked_at";

StatusRecord read_record(const Statement& row) {
    return StatusRecord{row.text(0),    row.integer(1), row.text(2),    row.integer(3),
                        row.integer(4), row.integer(5), row.integer(6), row.text(7)};
}

} // namespace

StatusLog::StatusLog(const std::string& db_path) : db_(db_path) {
    db_.execute(kSchema);
    load();
}

void StatusLog::load() {
    // 每门课只取 id 最大（最新）的那一条
    const std::string sql = std::string("SELECT ") + kColumns +
                            " FROM status_log WHERE id IN "
                            "(SELECT MAX(id) FROM status_log GROUP BY term, crn)";
    Statement select(db_, sql.c_str());
    while (select.step()) {
        StatusRecord record = read_record(select);
        latest_[record.term][record.crn] = std::move(record);
    }
}

bool StatusLog::record(const std::string& term, int crn, const std::string& status,
                       int seats_available, int capacity, int wait_count, int wait_capacity) {
    if (const auto last = latest(term, crn)) {
        if (last->status == status && last->seats_available == seats_available &&
            last->capacity == capacity && last->wait_count == wait_count &&
            last->wait_capacity == wait_capacity) {
            return false;
        }
    }

    Statement insert(db_, "INSERT INTO status_log "
                          "(term, crn, status, seats_available, capacity, wait_count, "
                          "wait_capacity) VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING checked_at");
    insert.bind(1, term);
    insert.bind(2, crn);
    insert.bind(3, status);
    insert.bind(4, seats_available);
    insert.bind(5, capacity);
    insert.bind(6, wait_count);
    insert.bind(7, wait_capacity);
    if (!insert.step()) {
        throw std::runtime_error("insert returned no row");
    }
    StatusRecord record{term,       crn,           status,        seats_available, capacity,
                        wait_count, wait_capacity, insert.text(0)};
    insert.step(); // 走到 SQLITE_DONE 才算提交

    latest_[term][crn] = std::move(record);
    return true;
}

std::optional<StatusRecord> StatusLog::latest(const std::string& term, int crn) const {
    const auto records = latest_.find(term);
    if (records == latest_.end()) return std::nullopt;
    const auto record = records->second.find(crn);
    if (record == records->second.end()) return std::nullopt;
    return record->second;
}

std::vector<StatusRecord> StatusLog::recent(const std::string& term, int limit) const {
    const std::string sql = std::string("SELECT ") + kColumns +
                            " FROM status_log WHERE term = ? ORDER BY id DESC LIMIT ?";
    Statement select(db_, sql.c_str());
    select.bind(1, term);
    select.bind(2, limit);

    std::vector<StatusRecord> result;
    while (select.step()) {
        result.push_back(read_record(select));
    }
    return result;
}
