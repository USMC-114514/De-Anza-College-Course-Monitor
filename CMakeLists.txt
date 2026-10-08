cmake_minimum_required(VERSION 3.18)
project(course_monitor LANGUAGES CXX)

add_library(course_map STATIC
        src/bidict_course_perfix_list.cpp
        src/bidict_course_perfix_list.h
)

target_compile_features(course_map PUBLIC cxx_std_17)
target_include_directories(course_map PUBLIC
        "${CMAKE_CURRENT_SOURCE_DIR}/src"
)

# ---- Python 扩展模块：engine/_native ----
# 默认用项目自己的 .venv，保证编译出来的模块和运行时的 Python 版本一致
if (NOT DEFINED Python_EXECUTABLE AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/.venv/bin/python")
    set(Python_EXECUTABLE "${CMAKE_CURRENT_SOURCE_DIR}/.venv/bin/python")
endif ()
find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)

execute_process(
        COMMAND "${Python_EXECUTABLE}" -m pybind11 --cmakedir
        OUTPUT_VARIABLE pybind11_DIR
        OUTPUT_STRIP_TRAILING_WHITESPACE
)
find_package(pybind11 CONFIG REQUIRED)
find_package(SQLite3 REQUIRED)

pybind11_add_module(_native
        src/bindings.cpp
        src/sqlite_db.cpp
        src/sqlite_db.h
        src/status_log.cpp
        src/status_log.h
        src/trie.h
        src/watchlist.cpp
        src/watchlist.h
)
target_compile_features(_native PRIVATE cxx_std_17)
# 新版 CMake 把目标改名为 SQLite3::SQLite3，旧名字会报弃用警告
if (TARGET SQLite3::SQLite3)
    target_link_libraries(_native PRIVATE SQLite3::SQLite3)
else ()
    target_link_libraries(_native PRIVATE SQLite::SQLite3)
endif ()
# 直接输出到 engine/ 下，编译完就能 import
set_target_properties(_native PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/engine"
)
