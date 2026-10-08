#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "status_log.h"
#include "trie.h"
#include "watchlist.h"

namespace py = pybind11;

// 编译产物是 engine/_native.*.so，Python 里用 from engine._native import ... 导入
PYBIND11_MODULE(_native, m) {
    py::class_<WatchedCourse>(m, "WatchedCourse")
        .def_readonly("term", &WatchedCourse::term)
        .def_readonly("crn", &WatchedCourse::crn)
        .def_readonly("department", &WatchedCourse::department)
        .def_readonly("course_number", &WatchedCourse::course_number)
        .def_readonly("section", &WatchedCourse::section)
        .def_readonly("course_name", &WatchedCourse::course_name)
        .def_readonly("added_at", &WatchedCourse::added_at)
        .def_property_readonly("code", &WatchedCourse::code);

    py::class_<Watchlist>(m, "Watchlist")
        .def(py::init<const std::string&>(), py::arg("db_path"))
        .def("add", &Watchlist::add, py::arg("term"), py::arg("crn"), py::arg("department"),
             py::arg("course_number"), py::arg("section"), py::arg("course_name"))
        .def("remove", &Watchlist::remove, py::arg("term"), py::arg("crn"))
        .def("contains", &Watchlist::contains, py::arg("term"), py::arg("crn"))
        .def("courses", &Watchlist::courses, py::arg("term"))
        .def("__len__", &Watchlist::size);

    py::class_<StatusRecord>(m, "StatusRecord")
        .def_readonly("term", &StatusRecord::term)
        .def_readonly("crn", &StatusRecord::crn)
        .def_readonly("status", &StatusRecord::status)
        .def_readonly("seats_available", &StatusRecord::seats_available)
        .def_readonly("capacity", &StatusRecord::capacity)
        .def_readonly("wait_count", &StatusRecord::wait_count)
        .def_readonly("wait_capacity", &StatusRecord::wait_capacity)
        .def_readonly("checked_at", &StatusRecord::checked_at);

    py::class_<StatusLog>(m, "StatusLog")
        .def(py::init<const std::string&>(), py::arg("db_path"))
        .def("record", &StatusLog::record, py::arg("term"), py::arg("crn"), py::arg("status"),
             py::arg("seats_available"), py::arg("capacity"), py::arg("wait_count"),
             py::arg("wait_capacity"))
        .def("latest", &StatusLog::latest, py::arg("term"), py::arg("crn"))
        .def("recent", &StatusLog::recent, py::arg("term"), py::arg("limit"));

    // 值可以是任意 Python 对象
    using PyTrie = Trie<py::object>;
    py::class_<PyTrie>(m, "Trie")
        .def(py::init<>())
        .def(
            "insert",
            [](PyTrie& trie, const std::string& key, py::object value) {
                trie.insert(key, std::move(value));
            },
            py::arg("key"), py::arg("value"))
        .def(
            "search",
            [](const PyTrie& trie, const std::string& prefix) { return trie.search(prefix); },
            py::arg("prefix"))
        .def("__len__", &PyTrie::size);
}
