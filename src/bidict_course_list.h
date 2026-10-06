//
// Created by Daniel Sun on 10/5/26.
//

#ifndef DE_ANZA_COLLEGE_COURSE_MONITOR_BIDICT_COURSE_LIST_H
#define DE_ANZA_COLLEGE_COURSE_MONITOR_BIDICT_COURSE_LIST_H

#include <string>
#include <unordered_map>
#include <vector>

using Key = std::string;    // 学科名称
using Value = std::string;  // 课程前缀

// 学科名称 -> 课程前缀（一个学科可能有多个前缀）
extern const std::unordered_map<Key, std::vector<Value>> forward_map;

// 课程前缀 -> 学科名称
extern const std::unordered_map<Value, Key> reverse_map;

#endif //DE_ANZA_COLLEGE_COURSE_MONITOR_BIDICT_COURSE_LIST_H
