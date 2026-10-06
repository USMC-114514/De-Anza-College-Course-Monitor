cmake_minimum_required(VERSION 3.15)
project(course_monitor LANGUAGES CXX)

add_library(course_map STATIC
        src/bidict_course_list.cpp
        src/bidict_course_list.h
)

target_compile_features(course_map PUBLIC cxx_std_17)
target_include_directories(course_map PUBLIC
        "${CMAKE_CURRENT_SOURCE_DIR}/src"
)