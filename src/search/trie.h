#ifndef DE_ANZA_COLLEGE_COURSE_MONITOR_TRIE_H
#define DE_ANZA_COLLEGE_COURSE_MONITOR_TRIE_H

#include <cstddef>
#include <map>
#include <memory>
#include <string_view>
#include <utility>
#include <vector>

// 前缀树：字符串键 -> 值，同一个键可以挂多个值。
// 键按字节处理，所以 UTF-8 字符串也能正确做前缀匹配。
template <typename V>
class Trie {
public:
    // O(键长)
    void insert(std::string_view key, V value) {
        Node* node = &root_;
        for (const char ch : key) {
            auto& child = node->children[static_cast<unsigned char>(ch)];
            if (!child) child = std::make_unique<Node>();
            node = child.get();
        }
        node->values.push_back(std::move(value));
        ++size_;
    }

    // 返回所有以 prefix 开头的键的值，按键的字典序排列；同一个键内按插入顺序。
    // O(前缀长 + 子树大小)
    std::vector<V> search(std::string_view prefix) const {
        std::vector<V> found;
        const Node* node = &root_;
        for (const char ch : prefix) {
            const auto child = node->children.find(static_cast<unsigned char>(ch));
            if (child == node->children.end()) return found;
            node = child->second.get();
        }

        // 用显式栈做先序遍历，子节点逆序入栈，弹出时就是字典序
        std::vector<const Node*> stack{node};
        while (!stack.empty()) {
            node = stack.back();
            stack.pop_back();
            found.insert(found.end(), node->values.begin(), node->values.end());
            for (auto child = node->children.rbegin(); child != node->children.rend(); ++child) {
                stack.push_back(child->second.get());
            }
        }
        return found;
    }

    // 已插入的值的个数
    std::size_t size() const { return size_; }

private:
    struct Node {
        // 有序 map：遍历时子节点天然按字节序排列
        std::map<unsigned char, std::unique_ptr<Node>> children;
        std::vector<V> values;
    };

    Node root_;
    std::size_t size_ = 0;
};

#endif //DE_ANZA_COLLEGE_COURSE_MONITOR_TRIE_H
