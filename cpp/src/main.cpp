#include <httplib.h>
#include <nlohmann/json.hpp>

#include "desktop_window.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <map>
#include <mutex>
#include <optional>
#include <regex>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#ifdef _WIN32
#include <shellapi.h>
#include <windows.h>
#endif

namespace fs = std::filesystem;
using json = nlohmann::json;

#ifndef CONV_MANAGER_KIND
#define CONV_MANAGER_KIND "codex"
#endif

#ifndef DEFAULT_WEB_DIR
#define DEFAULT_WEB_DIR ""
#endif

namespace {

constexpr double kActiveWindowSecs = 180.0;

enum class UiMode {
    Window,
    Browser,
    Headless
};

struct Config {
    std::string kind = CONV_MANAGER_KIND;
    bool is_codex = kind == "codex";
    std::string app_name = is_codex ? "Codex Manager" : "Claude Manager";
    std::string host = "127.0.0.1";
    int port = is_codex ? 8766 : 8765;
#if defined(_WIN32) || defined(__APPLE__)
    UiMode ui_mode = UiMode::Window;
#else
    UiMode ui_mode = UiMode::Browser;
#endif
    fs::path web_dir;
    fs::path home;
    fs::path codex_home;
    fs::path codex_sessions;
    fs::path codex_backup_sessions;
    fs::path codex_backup_archived;
    fs::path claude_projects;
    fs::path index_file;
    fs::path exe_dir;
};

struct Candidate {
    std::string project;
    std::string sid;
    std::string storage;
    fs::path root;
    fs::path path;
    double mtime = 0.0;
    std::uintmax_t size = 0;
    int priority = 0;
};

struct SearchEntry {
    double mtime = 0.0;
    std::uintmax_t size = 0;
    std::string blob;
};

struct SearchPrepared {
    Candidate file;
    std::string blob;
    bool ok = false;
};

std::mutex g_index_mutex;
std::mutex g_search_mutex;
std::unordered_map<std::string, SearchEntry> g_search_blobs;
std::optional<json> g_index_cache;

std::string as_string(const json& v) {
    if (v.is_string()) return v.get<std::string>();
    if (v.is_number_integer()) return std::to_string(v.get<long long>());
    if (v.is_number_unsigned()) return std::to_string(v.get<unsigned long long>());
    if (v.is_number_float()) {
        std::ostringstream os;
        os << v.get<double>();
        return os.str();
    }
    if (v.is_boolean()) return v.get<bool>() ? "true" : "false";
    if (v.is_null()) return "";
    return v.dump();
}

std::string field_string(const json& obj, const std::string& key) {
    if (!obj.is_object()) return "";
    auto it = obj.find(key);
    if (it == obj.end()) return "";
    return as_string(*it);
}

long long field_int(const json& obj, const std::string& key) {
    if (!obj.is_object()) return 0;
    auto it = obj.find(key);
    if (it == obj.end() || it->is_null()) return 0;
    if (it->is_number_integer()) return it->get<long long>();
    if (it->is_number_unsigned()) return static_cast<long long>(it->get<unsigned long long>());
    if (it->is_number_float()) return static_cast<long long>(it->get<double>());
    if (it->is_string()) {
        try {
            return std::stoll(it->get<std::string>());
        } catch (...) {
            return 0;
        }
    }
    return 0;
}

bool field_bool(const json& obj, const std::string& key) {
    if (!obj.is_object()) return false;
    auto it = obj.find(key);
    if (it == obj.end() || it->is_null()) return false;
    if (it->is_boolean()) return it->get<bool>();
    if (it->is_number()) return field_int(obj, key) != 0;
    if (it->is_string()) {
        auto s = it->get<std::string>();
        std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        return s == "true" || s == "1" || s == "yes";
    }
    return false;
}

json field_object(const json& obj, const std::string& key) {
    if (!obj.is_object()) return json::object();
    auto it = obj.find(key);
    return it != obj.end() && it->is_object() ? *it : json::object();
}

json field_array(const json& obj, const std::string& key) {
    if (!obj.is_object()) return json::array();
    auto it = obj.find(key);
    return it != obj.end() && it->is_array() ? *it : json::array();
}

std::string trim(std::string s) {
    auto is_space = [](unsigned char c) { return std::isspace(c) != 0; };
    while (!s.empty() && is_space(static_cast<unsigned char>(s.front()))) s.erase(s.begin());
    while (!s.empty() && is_space(static_cast<unsigned char>(s.back()))) s.pop_back();
    return s;
}

bool starts_with(const std::string& s, const std::string& prefix) {
    return s.size() >= prefix.size() && std::equal(prefix.begin(), prefix.end(), s.begin());
}

std::string lower_ascii(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return s;
}

bool utf8_continuation(unsigned char c) {
    return (c & 0xC0) == 0x80;
}

size_t utf8_floor_boundary(const std::string& s, size_t pos) {
    pos = std::min(pos, s.size());
    while (pos > 0 && pos < s.size() && utf8_continuation(static_cast<unsigned char>(s[pos]))) {
        --pos;
    }
    return pos;
}

std::string utf8_prefix(const std::string& s, size_t max_bytes) {
    return s.substr(0, utf8_floor_boundary(s, max_bytes));
}

std::string utf8_slice(const std::string& s, size_t begin, size_t end) {
    begin = utf8_floor_boundary(s, begin);
    end = utf8_floor_boundary(s, end);
    if (end < begin) end = begin;
    return s.substr(begin, end - begin);
}

std::string replace_all(std::string s, const std::string& from, const std::string& to) {
    if (from.empty()) return s;
    size_t pos = 0;
    while ((pos = s.find(from, pos)) != std::string::npos) {
        s.replace(pos, from.size(), to);
        pos += to.size();
    }
    return s;
}

std::string url_decode(const std::string& in) {
    std::string out;
    out.reserve(in.size());
    for (size_t i = 0; i < in.size(); ++i) {
        if (in[i] == '%' && i + 2 < in.size()) {
            const auto hex = in.substr(i + 1, 2);
            char* end = nullptr;
            long v = std::strtol(hex.c_str(), &end, 16);
            if (end && *end == '\0') {
                out.push_back(static_cast<char>(v));
                i += 2;
                continue;
            }
        }
        out.push_back(in[i] == '+' ? ' ' : in[i]);
    }
    return out;
}

fs::path home_dir() {
#ifdef _WIN32
    if (const char* p = std::getenv("USERPROFILE")) return fs::path(p);
    const char* drive = std::getenv("HOMEDRIVE");
    const char* path = std::getenv("HOMEPATH");
    if (drive && path) return fs::path(std::string(drive) + path);
#else
    if (const char* p = std::getenv("HOME")) return fs::path(p);
#endif
    return fs::current_path();
}

fs::path env_path(const char* name, fs::path fallback) {
    if (const char* value = std::getenv(name); value && *value) return fs::path(value);
    return fallback;
}

double now_seconds() {
    using namespace std::chrono;
    return duration<double>(system_clock::now().time_since_epoch()).count();
}

double unix_mtime(const fs::path& path) {
    try {
        const auto ft = fs::last_write_time(path);
        const auto sctp = std::chrono::time_point_cast<std::chrono::system_clock::duration>(
            ft - fs::file_time_type::clock::now() + std::chrono::system_clock::now());
        return std::chrono::duration<double>(sctp.time_since_epoch()).count();
    } catch (...) {
        return 0.0;
    }
}

std::uintmax_t file_size_or_zero(const fs::path& path) {
    try {
        return fs::file_size(path);
    } catch (...) {
        return 0;
    }
}

bool is_relative_to(const fs::path& path, const fs::path& root) {
    auto p = fs::weakly_canonical(path);
    auto r = fs::weakly_canonical(root);
    auto pit = p.begin();
    auto rit = r.begin();
    for (; rit != r.end(); ++rit, ++pit) {
        if (pit == p.end() || *pit != *rit) return false;
    }
    return true;
}

std::string path_string(const fs::path& path) {
    return path.u8string();
}

std::string relative_key(const Candidate& c) {
    std::error_code ec;
    auto rel = fs::relative(c.path, c.root, ec);
    if (ec) rel = c.path.filename();
    auto s = path_string(rel);
    std::replace(s.begin(), s.end(), '\\', '/');
    if (c.storage.empty()) return c.project + "/" + c.sid;
    return c.storage + ":" + s;
}

std::string content_type(const fs::path& path) {
    auto ext = lower_ascii(path.extension().string());
    if (ext == ".html") return "text/html; charset=utf-8";
    if (ext == ".css") return "text/css; charset=utf-8";
    if (ext == ".js") return "application/javascript; charset=utf-8";
    if (ext == ".json" || ext == ".map") return "application/json; charset=utf-8";
    if (ext == ".png") return "image/png";
    if (ext == ".ico") return "image/x-icon";
    if (ext == ".svg") return "image/svg+xml";
    if (ext == ".woff2") return "font/woff2";
    return "application/octet-stream";
}

bool read_file(const fs::path& path, std::string& out) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return false;
    std::ostringstream ss;
    ss << in.rdbuf();
    out = ss.str();
    return true;
}

void json_response(httplib::Response& res, const json& payload, int status = 200) {
    res.status = status;
    res.set_header("Cache-Control", "no-store, max-age=0");
    res.set_content(payload.dump(), "application/json; charset=utf-8");
}

void error_response(httplib::Response& res, int status, const std::string& message) {
    json_response(res, json{{"ok", false}, {"error", message}}, status);
}

json parse_json_body(const httplib::Request& req) {
    auto body = json::parse(req.body, nullptr, false);
    return body.is_discarded() || !body.is_object() ? json::object() : body;
}

void iter_jsonl(const fs::path& path, const std::function<void(const json&)>& fn) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return;
    std::string line;
    while (std::getline(in, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (trim(line).empty()) continue;
        auto obj = json::parse(line, nullptr, false);
        if (!obj.is_discarded()) fn(obj);
    }
}

std::string extract_text(const json& content) {
    if (content.is_string()) return content.get<std::string>();
    if (!content.is_array()) {
        if (content.is_object() && content.contains("text")) return as_string(content.at("text"));
        return "";
    }

    std::vector<std::string> out;
    for (const auto& part : content) {
        if (!part.is_object()) continue;
        const auto type = field_string(part, "type");
        if (type == "text" || type == "input_text" || type == "output_text") {
            out.push_back(field_string(part, "text"));
        } else if (type == "tool_use") {
            out.push_back("[tool_use: " + field_string(part, "name") + "]");
        } else if (type == "tool_result") {
            const auto r = part.contains("content") ? part.at("content") : json();
            if (r.is_string()) {
                out.push_back("[tool_result] " + r.get<std::string>());
            } else if (r.is_array()) {
                for (const auto& rc : r) {
                    if (rc.is_object()) {
                        const auto rt = field_string(rc, "type");
                        if (rt == "text" || rt == "input_text" || rt == "output_text") {
                            out.push_back("[tool_result] " + field_string(rc, "text"));
                        }
                    }
                }
            }
        }
    }
    std::ostringstream ss;
    for (size_t i = 0; i < out.size(); ++i) {
        if (i) ss << '\n';
        ss << out[i];
    }
    return ss.str();
}

bool is_tool_result_content(const json& content) {
    if (!content.is_array()) return false;
    for (const auto& part : content) {
        if (part.is_object() && field_string(part, "type") == "tool_result") return true;
    }
    return false;
}

bool is_command_wrapper(const std::string& text) {
    const auto s = trim(text);
    return starts_with(s, "<command-") || starts_with(s, "<local-command");
}

std::string clean_user_text(const std::string& text) {
    if (!is_command_wrapper(text)) return text;
    static const std::regex args_re("<command-args>\\s*([\\s\\S]*?)\\s*</command-args>", std::regex::icase);
    static const std::regex name_re("<command-name>\\s*(\\S+?)\\s*</command-name>", std::regex::icase);
    std::smatch m;
    if (std::regex_search(text, m, args_re) && m.size() > 1 && !trim(m[1].str()).empty()) {
        return trim(m[1].str());
    }
    if (std::regex_search(text, m, name_re) && m.size() > 1) return trim(m[1].str());
    return "";
}

bool is_internal_codex_text(const std::string& text) {
    const auto s = trim(text);
    return s.empty() || starts_with(s, "<environment_context>") || starts_with(s, "<turn_aborted>") ||
           starts_with(s, "<permissions instructions>") || starts_with(s, "<collaboration_mode>") ||
           starts_with(s, "<skills_instructions>");
}

std::string codex_tool_text(const json& payload) {
    const auto ptype = field_string(payload, "type");
    if (ptype == "function_call") {
        auto text = field_string(payload, "name");
        auto args = field_string(payload, "arguments");
        if (!args.empty()) text += "\n" + args;
        return trim(text.empty() ? "tool" : text);
    }
    if (ptype == "function_call_output") return field_string(payload, "output");
    return "";
}

std::string uuid_from_stem(const fs::path& path) {
    static const std::regex uuid_re("([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})");
    const auto stem = path.stem().string();
    std::smatch m;
    if (std::regex_search(stem, m, uuid_re) && m.size() > 1) return lower_ascii(m[1].str());
    return stem;
}

std::string project_id_for_cwd(std::string cwd) {
    if (cwd.empty()) return "unknown";
    for (char& ch : cwd) {
        if (ch == ':' || ch == '\\' || ch == '/') ch = '-';
    }
    std::string out;
    bool last_dash = false;
    for (unsigned char c : cwd) {
        const bool ok = std::isalnum(c) || c == '.' || c == '_' || c == '-';
        if (ok) {
            out.push_back(static_cast<char>(c));
            last_dash = c == '-';
        } else if (!last_dash) {
            out.push_back('-');
            last_dash = true;
        }
    }
    while (!out.empty() && out.front() == '-') out.erase(out.begin());
    while (!out.empty() && out.back() == '-') out.pop_back();
    return out.empty() ? "unknown" : out;
}

json read_codex_meta(const fs::path& path) {
    json meta = {
        {"sid", uuid_from_stem(path)},
        {"cwd", ""},
        {"created", ""},
        {"cliVersion", ""},
        {"source", ""},
        {"modelProvider", ""}
    };
    std::ifstream in(path, std::ios::binary);
    if (!in) return meta;
    std::string line;
    while (std::getline(in, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (trim(line).empty()) continue;
        const auto obj = json::parse(line, nullptr, false);
        if (obj.is_discarded()) continue;
        if (field_string(obj, "type") != "session_meta") continue;
        const auto payload = field_object(obj, "payload");
        const auto sid = lower_ascii(field_string(payload, "id"));
        if (!sid.empty()) meta["sid"] = sid;
        meta["cwd"] = field_string(payload, "cwd");
        auto created = field_string(payload, "timestamp");
        if (created.empty()) created = field_string(obj, "timestamp");
        meta["created"] = created;
        meta["cliVersion"] = field_string(payload, "cli_version");
        auto source = field_string(payload, "source");
        if (source.empty()) source = field_string(payload, "originator");
        meta["source"] = source;
        meta["modelProvider"] = field_string(payload, "model_provider");
        break;
    }
    return meta;
}

std::string local_date_from_mtime(double mtime) {
    if (mtime <= 0) return "";
    std::time_t t = static_cast<std::time_t>(mtime);
    std::tm tm{};
#ifdef _WIN32
    localtime_s(&tm, &t);
#else
    localtime_r(&t, &tm);
#endif
    char buf[11]{};
    std::strftime(buf, sizeof(buf), "%Y-%m-%d", &tm);
    return buf;
}

json usage_snapshot(const json& usage) {
    const auto input = field_int(usage, "input_tokens");
    const auto output = field_int(usage, "output_tokens");
    auto total = field_int(usage, "total_tokens");
    if (!total) total = input + output;
    return {
        {"input", input},
        {"cached", field_int(usage, "cached_input_tokens")},
        {"output", output},
        {"reasoning", field_int(usage, "reasoning_output_tokens")},
        {"total", total}
    };
}

json usage_delta(const json& current, const json& previous) {
    if (!previous.is_object() || previous.empty()) return current;
    json out = json::object();
    for (const auto& key : {"input", "cached", "output", "reasoning", "total"}) {
        const auto cur = field_int(current, key);
        const auto prev = field_int(previous, key);
        out[key] = cur >= prev ? cur - prev : cur;
    }
    return out;
}

std::pair<json, json> scan_claude_session(const std::string& project, const Candidate& c) {
    const auto& path = c.path;
    std::string first_user_text;
    std::string cwd;
    std::string git_branch;
    std::string first_ts;
    std::string last_ts;
    int user_count = 0;
    int assistant_count = 0;
    std::string summary;
    json costs = json::array();
    std::unordered_set<std::string> seen_msg_ids;

    iter_jsonl(path, [&](const json& obj) {
        const auto t = field_string(obj, "type");
        const auto ts = field_string(obj, "timestamp");
        if (t == "summary") {
            auto s = field_string(obj, "summary");
            if (!s.empty()) summary = s;
        } else if (t == "user") {
            if (cwd.empty()) cwd = field_string(obj, "cwd");
            if (git_branch.empty()) git_branch = field_string(obj, "gitBranch");
            const auto msg = field_object(obj, "message");
            const auto content = msg.contains("content") ? msg.at("content") : json();
            const auto text = extract_text(content);
            const bool is_meta = field_bool(obj, "isMeta");
            const bool is_tool = is_tool_result_content(content);
            const auto cleaned = text.empty() ? std::string() : clean_user_text(text);
            if (!cleaned.empty() && !is_meta && !is_tool) {
                if (first_user_text.empty()) first_user_text = utf8_prefix(cleaned, 200);
                ++user_count;
            }
        } else if (t == "assistant") {
            ++assistant_count;
            const auto msg = field_object(obj, "message");
            const auto usage = field_object(msg, "usage");
            const auto in_t = field_int(usage, "input_tokens");
            const auto out_t = field_int(usage, "output_tokens");
            const auto cw_t = field_int(usage, "cache_creation_input_tokens");
            const auto cr_t = field_int(usage, "cache_read_input_tokens");
            if (in_t || out_t || cw_t || cr_t) {
                const auto msg_id = field_string(msg, "id");
                if (msg_id.empty() || !seen_msg_ids.count(msg_id)) {
                    if (!msg_id.empty()) seen_msg_ids.insert(msg_id);
                    auto model = field_string(msg, "model");
                    if (model.empty()) model = field_string(obj, "model");
                    costs.push_back(json::array({model, ts.size() >= 10 ? ts.substr(0, 10) : "", in_t, out_t, cw_t, cr_t}));
                }
            }
        }
        if (!ts.empty()) {
            if (first_ts.empty()) first_ts = ts;
            last_ts = ts;
        }
    });

    json summary_obj = {
        {"project", project},
        {"sid", c.sid},
        {"cwd", cwd},
        {"gitBranch", git_branch},
        {"firstTs", first_ts},
        {"lastTs", last_ts},
        {"mtime", c.mtime},
        {"size", c.size},
        {"userCount", user_count},
        {"assistantCount", assistant_count},
        {"summary", summary.empty() ? first_user_text : summary},
        {"preview", first_user_text},
        {"active", now_seconds() - c.mtime < kActiveWindowSecs}
    };
    return {summary_obj, costs};
}

std::pair<json, json> scan_codex_session(const std::string& project, const Candidate& c) {
    const auto meta = read_codex_meta(c.path);
    const auto sid = field_string(meta, "sid").empty() ? c.sid : field_string(meta, "sid");
    std::string first_user_text;
    std::string cwd = field_string(meta, "cwd");
    std::string first_ts = field_string(meta, "created");
    std::string last_ts = first_ts;
    int user_count = 0;
    int assistant_count = 0;
    std::string model;
    json rows = json::array();
    json usage_prev = json::object();
    json usage_last = json::object();
    std::string usage_last_ts;
    json usage_rate_limits = json::object();
    std::string usage_plan_type;
    long long usage_context_window = 0;

    iter_jsonl(c.path, [&](const json& obj) {
        const auto ts = field_string(obj, "timestamp");
        const auto t = field_string(obj, "type");
        const auto payload = field_object(obj, "payload");
        if (t == "turn_context") {
            if (cwd.empty()) cwd = field_string(payload, "cwd");
            auto m = field_string(payload, "model");
            if (!m.empty()) model = m;
        } else if (t == "event_msg" && field_string(payload, "type") == "token_count") {
            const auto info = field_object(payload, "info");
            const auto total_usage = field_object(info, "total_token_usage");
            const auto ctx = field_int(info, "model_context_window");
            if (ctx) usage_context_window = ctx;
            const auto rate_limits = field_object(payload, "rate_limits");
            if (!rate_limits.empty()) {
                usage_rate_limits = rate_limits;
                auto plan = field_string(rate_limits, "plan_type");
                if (!plan.empty()) usage_plan_type = plan;
            }
            if (!total_usage.empty()) {
                const auto snap = usage_snapshot(total_usage);
                const auto delta = usage_delta(snap, usage_prev);
                usage_prev = snap;
                usage_last = snap;
                if (!ts.empty()) usage_last_ts = ts;
                const auto date = (ts.empty() ? last_ts : ts).substr(0, std::min<size_t>(10, (ts.empty() ? last_ts : ts).size()));
                if (field_int(delta, "input") || field_int(delta, "cached") || field_int(delta, "output") ||
                    field_int(delta, "reasoning") || field_int(delta, "total")) {
                    rows.push_back(json::array({
                        model.empty() ? "codex" : model,
                        date,
                        field_int(delta, "input"),
                        field_int(delta, "cached"),
                        field_int(delta, "output"),
                        field_int(delta, "reasoning"),
                        field_int(delta, "total")
                    }));
                }
            }
        } else if (t == "response_item") {
            const auto ptype = field_string(payload, "type");
            if (ptype == "message") {
                const auto role = field_string(payload, "role");
                if (role == "user") {
                    const auto text = extract_text(payload.contains("content") ? payload.at("content") : json());
                    if (!is_internal_codex_text(text)) {
                        const auto cleaned = text.empty() ? std::string() : clean_user_text(text);
                        if (!cleaned.empty()) {
                            if (first_user_text.empty()) first_user_text = utf8_prefix(cleaned, 200);
                            ++user_count;
                        }
                    }
                } else if (role == "assistant") {
                    const auto text = extract_text(payload.contains("content") ? payload.at("content") : json());
                    if (!trim(text).empty()) ++assistant_count;
                }
            } else if (ptype == "function_call" || ptype == "function_call_output") {
                ++assistant_count;
            }
        }
        if (!ts.empty()) {
            if (first_ts.empty()) first_ts = ts;
            last_ts = ts;
        }
    });

    json summary_obj = {
        {"project", project},
        {"sid", sid},
        {"storage", c.storage},
        {"cwd", cwd},
        {"gitBranch", ""},
        {"model", model},
        {"firstTs", first_ts},
        {"lastTs", last_ts},
        {"mtime", c.mtime},
        {"size", c.size},
        {"userCount", user_count},
        {"assistantCount", assistant_count},
        {"summary", first_user_text},
        {"preview", first_user_text},
        {"active", now_seconds() - c.mtime < kActiveWindowSecs},
        {"usage", {
            {"lastTs", usage_last_ts},
            {"tokens", usage_last},
            {"rateLimits", usage_rate_limits},
            {"planType", usage_plan_type},
            {"contextWindow", usage_context_window}
        }}
    };
    return {summary_obj, rows};
}

json load_index(const Config& cfg) {
    if (g_index_cache) return *g_index_cache;
    std::ifstream in(cfg.index_file, std::ios::binary);
    if (in) {
        std::ostringstream ss;
        ss << in.rdbuf();
        auto data = json::parse(ss.str(), nullptr, false);
        if (data.is_object() && field_int(data, "version") == 1 && data.contains("entries") && data["entries"].is_object()) {
            g_index_cache = data;
            return *g_index_cache;
        }
    }
    g_index_cache = json{{"version", 1}, {"entries", json::object()}};
    return *g_index_cache;
}

void save_index(const Config& cfg, const json& data) {
    try {
        fs::create_directories(cfg.index_file.parent_path());
        const auto tmp = cfg.index_file.string() + ".tmp";
        std::ofstream out(tmp, std::ios::binary);
        out << data.dump();
        out.close();
        fs::rename(tmp, cfg.index_file);
    } catch (...) {
    }
}

std::vector<Candidate> enumerate_claude_files(const Config& cfg) {
    std::vector<Candidate> out;
    if (!fs::is_directory(cfg.claude_projects)) return out;
    for (const auto& project_entry : fs::directory_iterator(cfg.claude_projects)) {
        if (!project_entry.is_directory()) continue;
        const auto project = project_entry.path().filename().string();
        for (const auto& file_entry : fs::directory_iterator(project_entry.path())) {
            if (!file_entry.is_regular_file() || file_entry.path().extension() != ".jsonl") continue;
            Candidate c;
            c.project = project;
            c.sid = file_entry.path().stem().string();
            c.root = cfg.claude_projects;
            c.path = file_entry.path();
            c.mtime = unix_mtime(c.path);
            c.size = file_size_or_zero(c.path);
            c.priority = 1;
            out.push_back(std::move(c));
        }
    }
    std::sort(out.begin(), out.end(), [](const Candidate& a, const Candidate& b) {
        return a.mtime > b.mtime;
    });
    return out;
}

std::vector<Candidate> enumerate_codex_raw_files(const Config& cfg) {
    std::vector<std::pair<std::string, fs::path>> roots = {
        {"current", cfg.codex_sessions},
        {"backup", cfg.codex_backup_sessions},
        {"backup-archived", cfg.codex_backup_archived}
    };
    std::vector<Candidate> out;
    std::set<std::string> seen_roots;
    for (const auto& [label, root] : roots) {
        if (!fs::is_directory(root)) continue;
        const auto canon = path_string(fs::weakly_canonical(root));
        if (seen_roots.count(canon)) continue;
        seen_roots.insert(canon);
        for (const auto& entry : fs::recursive_directory_iterator(root)) {
            if (!entry.is_regular_file() || entry.path().extension() != ".jsonl") continue;
            Candidate c;
            c.storage = label;
            c.root = root;
            c.path = entry.path();
            c.mtime = unix_mtime(c.path);
            c.size = file_size_or_zero(c.path);
            c.priority = label == "current" ? 1 : 0;
            out.push_back(std::move(c));
        }
    }
    std::sort(out.begin(), out.end(), [](const Candidate& a, const Candidate& b) {
        if (a.mtime != b.mtime) return a.mtime > b.mtime;
        return a.priority > b.priority;
    });
    return out;
}

std::vector<Candidate> enumerate_codex_files(const Config& cfg) {
    auto raw = enumerate_codex_raw_files(cfg);
    std::vector<Candidate> out;
    std::set<std::pair<std::string, std::string>> seen;
    for (auto& c : raw) {
        const auto meta = read_codex_meta(c.path);
        c.sid = field_string(meta, "sid");
        if (c.sid.empty()) c.sid = uuid_from_stem(c.path);
        c.project = project_id_for_cwd(field_string(meta, "cwd"));
        const auto key = std::make_pair(c.project, c.sid);
        if (seen.count(key)) continue;
        seen.insert(key);
        out.push_back(std::move(c));
    }
    return out;
}

std::vector<Candidate> enumerate_files(const Config& cfg) {
    return cfg.is_codex ? enumerate_codex_files(cfg) : enumerate_claude_files(cfg);
}

std::optional<Candidate> find_session(const Config& cfg, std::string project, std::string sid) {
    if (project.find('/') != std::string::npos || project.find('\\') != std::string::npos || project.find("..") != std::string::npos ||
        sid.find('/') != std::string::npos || sid.find('\\') != std::string::npos || sid.find("..") != std::string::npos) {
        return std::nullopt;
    }
    project = url_decode(project);
    sid = lower_ascii(url_decode(sid));
    for (const auto& c : enumerate_files(cfg)) {
        if (c.project == project && lower_ascii(c.sid) == sid) return c;
    }
    return std::nullopt;
}

std::pair<json, json> scan_session(const Config& cfg, const Candidate& c) {
    return cfg.is_codex ? scan_codex_session(c.project, c) : scan_claude_session(c.project, c);
}

std::pair<json, json> load_session_summaries(const Config& cfg) {
    const auto files = enumerate_files(cfg);
    json projects = json::array();
    json sessions = json::array();
    std::map<std::string, int> project_counts;

    std::lock_guard<std::mutex> lock(g_index_mutex);
    auto index = load_index(cfg);
    auto& entries = index["entries"];
    std::set<std::string> seen_keys;
    bool dirty = false;

    for (const auto& c : files) {
        const auto key = relative_key(c);
        seen_keys.insert(key);
        json summary;
        auto cached_it = entries.find(key);
        const bool fresh = cached_it != entries.end() && cached_it->is_object() &&
                           std::abs(field_int(*cached_it, "size") - static_cast<long long>(c.size)) == 0 &&
                           std::abs(((*cached_it)["mtime"].is_number() ? (*cached_it)["mtime"].get<double>() : 0.0) - c.mtime) < 0.000001 &&
                           cached_it->contains("data") && (*cached_it)["data"].is_object();
        if (fresh) {
            summary = (*cached_it)["data"];
        } else {
            try {
                auto [scanned, costs] = scan_session(cfg, c);
                summary = scanned;
                entries[key] = json{{"mtime", c.mtime}, {"size", c.size}, {"data", scanned}, {"costs", costs}};
                dirty = true;
            } catch (const std::exception& e) {
                summary = {
                    {"project", c.project}, {"sid", c.sid}, {"error", e.what()},
                    {"mtime", c.mtime}, {"size", c.size},
                    {"summary", ""}, {"preview", ""}, {"cwd", ""},
                    {"firstTs", ""}, {"lastTs", ""},
                    {"userCount", 0}, {"assistantCount", 0}
                };
            }
        }
        summary["active"] = now_seconds() - c.mtime < kActiveWindowSecs;
        sessions.push_back(summary);
        project_counts[field_string(summary, "project").empty() ? c.project : field_string(summary, "project")]++;
    }

    std::vector<std::string> stale;
    for (auto it = entries.begin(); it != entries.end(); ++it) {
        if (!seen_keys.count(it.key())) stale.push_back(it.key());
    }
    for (const auto& key : stale) {
        entries.erase(key);
        dirty = true;
    }
    if (dirty) {
        g_index_cache = index;
        save_index(cfg, index);
    }

    for (const auto& [name, count] : project_counts) projects.push_back({{"name", name}, {"count", count}});
    std::sort(sessions.begin(), sessions.end(), [](const json& a, const json& b) {
        const auto am = a.contains("mtime") && a["mtime"].is_number() ? a["mtime"].get<double>() : 0.0;
        const auto bm = b.contains("mtime") && b["mtime"].is_number() ? b["mtime"].get<double>() : 0.0;
        return am > bm;
    });
    return {projects, sessions};
}

std::string build_search_blob(const Config& cfg, const Candidate& c) {
    (void)cfg;
    std::string raw;
    if (!read_file(c.path, raw)) return "";
    return lower_ascii(std::move(raw));
}

SearchPrepared ensure_blob(const Config& cfg, const Candidate& c) {
    const auto key = c.project + "/" + c.sid + "/" + relative_key(c);
    {
        std::lock_guard<std::mutex> lock(g_search_mutex);
        auto it = g_search_blobs.find(key);
        if (it != g_search_blobs.end() && it->second.mtime == c.mtime && it->second.size == c.size) {
            return SearchPrepared{c, it->second.blob, true};
        }
    }
    auto blob = build_search_blob(cfg, c);
    {
        std::lock_guard<std::mutex> lock(g_search_mutex);
        g_search_blobs[key] = SearchEntry{c.mtime, c.size, blob};
    }
    return SearchPrepared{c, blob, true};
}

json search_snippets(const Config& cfg, const Candidate& c, const std::string& query, const std::string& qlower) {
    json hits = json::array();
    auto consider = [&](const json& obj) {
        if (hits.size() >= 3) return;
        const auto t = field_string(obj, "type");
        std::string role;
        std::string text;
        if (cfg.is_codex) {
            if (t != "response_item") return;
            const auto payload = field_object(obj, "payload");
            const auto ptype = field_string(payload, "type");
            if (ptype == "message") {
                role = field_string(payload, "role");
                if (role != "user" && role != "assistant") return;
                text = extract_text(payload.contains("content") ? payload.at("content") : json());
                if (role == "user" && is_internal_codex_text(text)) return;
            } else if (ptype == "function_call" || ptype == "function_call_output") {
                role = "tool";
                text = codex_tool_text(payload);
            } else {
                return;
            }
        } else {
            if (t == "summary") {
                role = "summary";
                text = field_string(obj, "summary");
            } else if (t == "user" || t == "assistant") {
                role = t;
                const auto msg = field_object(obj, "message");
                text = extract_text(msg.contains("content") ? msg.at("content") : json());
            } else {
                return;
            }
        }
        if (text.empty()) return;
        const auto lower = lower_ascii(text);
        const auto pos = lower.find(qlower);
        if (pos == std::string::npos) return;
        const auto begin = pos > 40 ? pos - 40 : 0;
        const auto end = std::min(text.size(), pos + query.size() + 80);
        hits.push_back({{"role", role}, {"snippet", utf8_slice(text, begin, end)}, {"ts", field_string(obj, "timestamp")}});
    };

    std::ifstream in(c.path, std::ios::binary);
    if (!in) return hits;
    std::string line;
    while (hits.size() < 3 && std::getline(in, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (lower_ascii(line).find(qlower) == std::string::npos) continue;
        auto obj = json::parse(line, nullptr, false);
        if (!obj.is_discarded()) consider(obj);
    }
    return hits;
}

json build_session_detail(const Config& cfg, const Candidate& c) {
    json messages = json::array();
    std::string cwd;
    std::string git_branch;
    std::string model;
    if (cfg.is_codex) {
        const auto meta = read_codex_meta(c.path);
        cwd = field_string(meta, "cwd");
        iter_jsonl(c.path, [&](const json& obj) {
            const auto t = field_string(obj, "type");
            const auto payload = field_object(obj, "payload");
            if (t == "turn_context") {
                auto m = field_string(payload, "model");
                if (!m.empty()) model = m;
                if (cwd.empty()) cwd = field_string(payload, "cwd");
                return;
            }
            if (t != "response_item") return;
            const auto ptype = field_string(payload, "type");
            if (ptype == "message") {
                const auto role = field_string(payload, "role");
                if (role != "user" && role != "assistant") return;
                auto text = extract_text(payload.contains("content") ? payload.at("content") : json());
                if (role == "user" && is_internal_codex_text(text)) return;
                if (trim(text).empty()) return;
                messages.push_back({
                    {"role", role}, {"text", text}, {"ts", field_string(obj, "timestamp")},
                    {"meta", false}, {"toolResult", false}, {"model", role == "assistant" ? model : ""}
                });
            } else if (ptype == "function_call" || ptype == "function_call_output") {
                auto text = codex_tool_text(payload);
                if (text.empty()) return;
                messages.push_back({
                    {"role", "assistant"}, {"text", text}, {"ts", field_string(obj, "timestamp")},
                    {"meta", false}, {"toolResult", true}, {"model", ""}
                });
            }
        });
    } else {
        iter_jsonl(c.path, [&](const json& obj) {
            const auto t = field_string(obj, "type");
            if (t == "summary") {
                messages.push_back({{"role", "summary"}, {"text", field_string(obj, "summary")}, {"ts", ""}});
                return;
            }
            if (t != "user" && t != "assistant") return;
            if (cwd.empty()) cwd = field_string(obj, "cwd");
            if (git_branch.empty()) git_branch = field_string(obj, "gitBranch");
            const auto msg = field_object(obj, "message");
            const auto content = msg.contains("content") ? msg.at("content") : json();
            auto text = extract_text(content);
            if (text.empty()) return;
            const bool is_meta = field_bool(obj, "isMeta");
            const bool is_tool = is_tool_result_content(content);
            if (t == "user" && is_command_wrapper(text)) {
                auto cleaned = clean_user_text(text);
                if (cleaned.empty()) return;
                text = cleaned.find('/') == 0 || cleaned.find(' ') != std::string::npos ? cleaned : "/" + cleaned;
            }
            messages.push_back({
                {"role", t}, {"text", text}, {"ts", field_string(obj, "timestamp")},
                {"meta", is_meta}, {"toolResult", is_tool}, {"model", field_string(msg, "model")}
            });
        });
    }
    return {{"project", c.project}, {"sid", c.sid}, {"cwd", cwd}, {"gitBranch", git_branch}, {"messages", messages}};
}

std::pair<double, std::array<double, 4>> claude_price(const std::string& model) {
    const auto m = lower_ascii(model);
    if (m.find("opus") != std::string::npos) return {0, {15.0, 75.0, 18.75, 1.5}};
    if (m.find("sonnet") != std::string::npos) return {0, {3.0, 15.0, 3.75, 0.3}};
    if (m.find("haiku") != std::string::npos) return {0, {1.0, 5.0, 1.25, 0.1}};
    return {0, {0.0, 0.0, 0.0, 0.0}};
}

json aggregate_costs(const Config& cfg) {
    auto [projects, sessions] = load_session_summaries(cfg);
    (void)projects;
    std::lock_guard<std::mutex> lock(g_index_mutex);
    auto index = load_index(cfg);

    if (cfg.is_codex) {
        json by_model = json::object();
        std::map<std::string, long long, std::greater<>> by_day;
        std::map<std::string, json, std::greater<>> by_day_tokens;
        long long total_input = 0, total_cached = 0, total_output = 0, total_reasoning = 0, total_tokens = 0;
        int sessions_with_usage = 0;
        json latest_rate_limits = json::object();
        std::string latest_rate_ts;

        for (const auto& summary : sessions) {
            const auto usage = field_object(summary, "usage");
            const auto rate_limits = field_object(usage, "rateLimits");
            const auto rate_ts = field_string(usage, "lastTs");
            if (!rate_limits.empty() && rate_ts >= latest_rate_ts) {
                latest_rate_ts = rate_ts;
                latest_rate_limits = rate_limits;
                latest_rate_limits["lastTs"] = rate_ts;
                latest_rate_limits["contextWindow"] = field_int(usage, "contextWindow");
            }
        }

        for (auto it = index["entries"].begin(); it != index["entries"].end(); ++it) {
            const auto rows = field_array(*it, "costs");
            if (!rows.empty()) ++sessions_with_usage;
            for (const auto& row : rows) {
                if (!row.is_array() || row.size() < 7) continue;
                const auto model = as_string(row[0]);
                const auto date = as_string(row[1]);
                const auto input = row[2].get<long long>();
                const auto cached = row[3].get<long long>();
                const auto output = row[4].get<long long>();
                const auto reasoning = row[5].get<long long>();
                const auto total = row[6].get<long long>();
                const auto non_cached = std::max<long long>(0, input - cached);
                total_input += input;
                total_cached += cached;
                total_output += output;
                total_reasoning += reasoning;
                total_tokens += total;
                auto& bm = by_model[model.empty() ? "unknown" : model];
                if (!bm.is_object()) bm = json{{"input", 0}, {"cachedInput", 0}, {"nonCachedInput", 0}, {"output", 0}, {"reasoningOutput", 0}, {"total", 0}};
                bm["input"] = field_int(bm, "input") + input;
                bm["cachedInput"] = field_int(bm, "cachedInput") + cached;
                bm["nonCachedInput"] = field_int(bm, "nonCachedInput") + non_cached;
                bm["output"] = field_int(bm, "output") + output;
                bm["reasoningOutput"] = field_int(bm, "reasoningOutput") + reasoning;
                bm["total"] = field_int(bm, "total") + total;
                if (!date.empty()) {
                    by_day[date] += total;
                    auto& bd = by_day_tokens[date];
                    if (!bd.is_object()) bd = json{{"input", 0}, {"cachedInput", 0}, {"nonCachedInput", 0}, {"output", 0}, {"reasoningOutput", 0}, {"total", 0}};
                    bd["input"] = field_int(bd, "input") + input;
                    bd["cachedInput"] = field_int(bd, "cachedInput") + cached;
                    bd["nonCachedInput"] = field_int(bd, "nonCachedInput") + non_cached;
                    bd["output"] = field_int(bd, "output") + output;
                    bd["reasoningOutput"] = field_int(bd, "reasoningOutput") + reasoning;
                    bd["total"] = field_int(bd, "total") + total;
                }
            }
        }
        json by_day_json = json::object();
        for (const auto& [day, value] : by_day) by_day_json[day] = value;
        json by_day_tokens_json = json::object();
        for (const auto& [day, value] : by_day_tokens) by_day_tokens_json[day] = value;
        return {
            {"total", total_tokens},
            {"tokens", {{"input", total_input}, {"cachedInput", total_cached}, {"nonCachedInput", std::max<long long>(0, total_input - total_cached)}, {"output", total_output}, {"reasoningOutput", total_reasoning}, {"total", total_tokens}}},
            {"byModel", by_model},
            {"byDay", by_day_json},
            {"byDayTokens", by_day_tokens_json},
            {"sessions", sessions_with_usage},
            {"rateLimits", latest_rate_limits}
        };
    }

    json by_model = json::object();
    std::map<std::string, double, std::greater<>> by_day;
    std::map<std::string, json, std::greater<>> by_day_tokens;
    double total_cost = 0.0;
    long long total_in = 0, total_out = 0, total_cw = 0, total_cr = 0;
    int sessions_with_cost = 0;
    for (auto it = index["entries"].begin(); it != index["entries"].end(); ++it) {
        const auto rows = field_array(*it, "costs");
        if (!rows.empty()) ++sessions_with_cost;
        for (const auto& row : rows) {
            if (!row.is_array() || row.size() < 6) continue;
            const auto model = as_string(row[0]);
            const auto date = as_string(row[1]);
            const auto in_t = row[2].get<long long>();
            const auto out_t = row[3].get<long long>();
            const auto cw_t = row[4].get<long long>();
            const auto cr_t = row[5].get<long long>();
            const auto prices = claude_price(model).second;
            const auto cost = (in_t * prices[0] + out_t * prices[1] + cw_t * prices[2] + cr_t * prices[3]) / 1000000.0;
            total_cost += cost;
            total_in += in_t;
            total_out += out_t;
            total_cw += cw_t;
            total_cr += cr_t;
            auto& bm = by_model[model.empty() ? "unknown" : model];
            if (!bm.is_object()) bm = json{{"input", 0}, {"output", 0}, {"cacheWrite", 0}, {"cacheRead", 0}, {"cost", 0.0}};
            bm["input"] = field_int(bm, "input") + in_t;
            bm["output"] = field_int(bm, "output") + out_t;
            bm["cacheWrite"] = field_int(bm, "cacheWrite") + cw_t;
            bm["cacheRead"] = field_int(bm, "cacheRead") + cr_t;
            bm["cost"] = (bm["cost"].is_number() ? bm["cost"].get<double>() : 0.0) + cost;
            if (!date.empty()) {
                by_day[date] += cost;
                auto& bd = by_day_tokens[date];
                if (!bd.is_object()) bd = json{{"input", 0}, {"output", 0}, {"cacheWrite", 0}, {"cacheRead", 0}};
                bd["input"] = field_int(bd, "input") + in_t;
                bd["output"] = field_int(bd, "output") + out_t;
                bd["cacheWrite"] = field_int(bd, "cacheWrite") + cw_t;
                bd["cacheRead"] = field_int(bd, "cacheRead") + cr_t;
            }
        }
    }
    json by_day_json = json::object();
    for (const auto& [day, value] : by_day) by_day_json[day] = value;
    json by_day_tokens_json = json::object();
    for (const auto& [day, value] : by_day_tokens) by_day_tokens_json[day] = value;
    return {
        {"total", std::round(total_cost * 10000.0) / 10000.0},
        {"tokens", {{"input", total_in}, {"output", total_out}, {"cacheWrite", total_cw}, {"cacheRead", total_cr}}},
        {"byModel", by_model},
        {"byDay", by_day_json},
        {"byDayTokens", by_day_tokens_json},
        {"sessions", sessions_with_cost}
    };
}

std::time_t timegm_compat(std::tm* tm) {
#ifdef _WIN32
    return _mkgmtime(tm);
#else
    return timegm(tm);
#endif
}

std::optional<std::time_t> parse_iso_time(const std::string& ts) {
    if (ts.size() < 19) return std::nullopt;
    std::tm tm{};
    try {
        tm.tm_year = std::stoi(ts.substr(0, 4)) - 1900;
        tm.tm_mon = std::stoi(ts.substr(5, 2)) - 1;
        tm.tm_mday = std::stoi(ts.substr(8, 2));
        tm.tm_hour = std::stoi(ts.substr(11, 2));
        tm.tm_min = std::stoi(ts.substr(14, 2));
        tm.tm_sec = std::stoi(ts.substr(17, 2));
    } catch (...) {
        return std::nullopt;
    }
    return timegm_compat(&tm);
}

std::string date_from_time(std::time_t t) {
    std::tm tm{};
#ifdef _WIN32
    localtime_s(&tm, &t);
#else
    localtime_r(&t, &tm);
#endif
    char buf[11]{};
    std::strftime(buf, sizeof(buf), "%Y-%m-%d", &tm);
    return buf;
}

std::time_t local_midnight_now() {
    auto now = std::time(nullptr);
    std::tm tm{};
#ifdef _WIN32
    localtime_s(&tm, &now);
#else
    localtime_r(&now, &tm);
#endif
    tm.tm_hour = 0;
    tm.tm_min = 0;
    tm.tm_sec = 0;
    return std::mktime(&tm);
}

json build_stats(const Config& cfg) {
    auto [projects, sessions] = load_session_summaries(cfg);
    (void)projects;
    if (sessions.empty()) return {{"heatmap", json::array()}, {"totals", json::object()}};

    std::map<std::string, int> day_count;
    std::map<std::string, int> model_count;
    std::set<std::string> active_days;
    int total_sessions = 0;
    long long total_tokens_or_bytes = 0;
    long long longest = 0;
    std::pair<std::string, int> most_msgs_day{"", 0};

    for (const auto& summary : sessions) {
        ++total_sessions;
        const auto first_ts = field_string(summary, "firstTs");
        auto last_ts = field_string(summary, "lastTs");
        if (last_ts.empty()) last_ts = first_ts;
        auto day = last_ts.size() >= 10 ? last_ts.substr(0, 10) : "";
        if (day.empty()) day = local_date_from_mtime(summary.contains("mtime") && summary["mtime"].is_number() ? summary["mtime"].get<double>() : 0.0);
        const int msg_count = static_cast<int>(field_int(summary, "userCount") + field_int(summary, "assistantCount"));
        if (!day.empty()) {
            day_count[day]++;
            active_days.insert(day);
            if (msg_count > most_msgs_day.second) most_msgs_day = {day, msg_count};
        }
        const auto model = field_string(summary, "model");
        if (!model.empty()) model_count[model]++;
        if (cfg.is_codex) {
            const auto usage = field_object(summary, "usage");
            const auto tokens = field_object(usage, "tokens");
            total_tokens_or_bytes += field_int(tokens, "total");
        } else {
            total_tokens_or_bytes += field_int(summary, "size");
        }
        const auto first = parse_iso_time(first_ts);
        const auto last = parse_iso_time(last_ts);
        if (first && last && *last >= *first) longest = std::max<long long>(longest, *last - *first);
    }

    const auto today_mid = local_midnight_now();
    const auto today_iso = date_from_time(today_mid);
    int streak = 0;
    for (std::time_t t = today_mid; active_days.count(date_from_time(t)); t -= 86400) ++streak;

    int maxv = 1;
    for (const auto& [_, count] : day_count) maxv = std::max(maxv, count);
    constexpr int weeks = 53;
    json heatmap = json::array();
    for (int row = 0; row < 7; ++row) heatmap.push_back(json::array());
    const auto from = today_mid - static_cast<std::time_t>(weeks * 7 - 1) * 86400;
    for (int i = 0; i < weeks * 7; ++i) {
        const auto t = from + static_cast<std::time_t>(i) * 86400;
        std::tm tm{};
#ifdef _WIN32
        localtime_s(&tm, &t);
#else
        localtime_r(&t, &tm);
#endif
        const auto cnt = day_count[date_from_time(t)];
        const auto level = cnt == 0 ? 0 : std::min(4, 1 + static_cast<int>(std::floor(static_cast<double>(cnt) / maxv * 3.999)));
        const int dow = tm.tm_wday; // Sunday = 0.
        heatmap[dow].push_back(level);
    }

    json recent_days = json::array();
    for (int offset = 89; offset >= 0; --offset) {
        const auto t = today_mid - static_cast<std::time_t>(offset) * 86400;
        const auto date = date_from_time(t);
        const auto cnt = day_count[date];
        const auto level = cnt == 0 ? 0 : std::min(4, 1 + static_cast<int>(std::floor(static_cast<double>(cnt) / maxv * 3.999)));
        recent_days.push_back({{"date", date}, {"count", cnt}, {"level", level}});
    }

    std::string favorite_model;
    int best_model = 0;
    for (const auto& [model, count] : model_count) {
        if (count > best_model) {
            best_model = count;
            favorite_model = replace_all(model, "-", " ");
        }
    }

    auto fmt_duration = [](long long seconds) {
        if (seconds <= 0) return std::string("-");
        auto minutes = seconds / 60;
        auto hours = minutes / 60;
        minutes %= 60;
        auto days = hours / 24;
        hours %= 24;
        std::ostringstream os;
        if (days) os << days << "d ";
        if (hours) os << hours << "h ";
        os << minutes << "m";
        return os.str();
    };

    auto fmt_delta = [](long long seconds) {
        if (seconds <= 0) return std::string("soon");
        const auto hours = seconds / 3600;
        const auto minutes = (seconds % 3600) / 60;
        if (hours >= 24) return std::to_string(hours / 24) + "d";
        if (hours > 0) return std::to_string(hours) + "h " + std::to_string(minutes) + "m";
        return std::to_string(minutes) + "m";
    };

    std::time_t now = std::time(nullptr);
    std::tm today_tm{};
#ifdef _WIN32
    localtime_s(&today_tm, &today_mid);
#else
    localtime_r(&today_mid, &today_tm);
#endif
    const int days_since_monday = (today_tm.tm_wday + 6) % 7;
    const auto week_start = today_mid - static_cast<std::time_t>(days_since_monday) * 86400;
    int day_sessions = day_count[today_iso];
    int week_sessions = 0;
    int month_sessions = 0;
    for (const auto& [day, count] : day_count) {
        std::tm tm{};
        if (day.size() >= 10) {
            tm.tm_year = std::stoi(day.substr(0, 4)) - 1900;
            tm.tm_mon = std::stoi(day.substr(5, 2)) - 1;
            tm.tm_mday = std::stoi(day.substr(8, 2));
            auto t = std::mktime(&tm);
            if (t >= week_start) week_sessions += count;
            if (tm.tm_year == today_tm.tm_year && tm.tm_mon == today_tm.tm_mon) month_sessions += count;
        }
    }

    json totals = {
        {"favoriteModel", favorite_model},
        {"totalTokens", total_tokens_or_bytes ? std::to_string(total_tokens_or_bytes / 1000000.0).substr(0, 3) + "m" : "0"},
        {"sessions", total_sessions},
        {"longest", fmt_duration(longest)},
        {"mostActiveDay", most_msgs_day.first.empty() ? "-" : most_msgs_day.first},
        {"streak", std::to_string(streak) + " days"},
        {"activeDays", static_cast<int>(active_days.size())}
    };
    json plans = json::array({
        {{"label", "Today sessions"}, {"count", day_sessions}, {"cap", 20}, {"reset", fmt_delta(today_mid + 86400 - now)}, {"sub", "daily"}},
        {{"label", "This week"}, {"count", week_sessions}, {"cap", 80}, {"reset", fmt_delta(week_start + 7 * 86400 - now)}, {"sub", "weekly"}},
        {{"label", "This month"}, {"count", month_sessions}, {"cap", 300}, {"reset", "monthly"}, {"sub", "monthly"}},
        {{"label", "History"}, {"count", total_sessions}, {"cap", std::max(total_sessions, 500)}, {"reset", "never"}, {"sub", "all"}}
    });
    return {{"heatmap", heatmap}, {"totals", totals}, {"plans", plans}, {"recentDays", recent_days}};
}

std::string export_markdown(const Config& cfg, const Candidate& c) {
    std::ostringstream lines;
    lines << "# " << (cfg.is_codex ? "Codex" : "Claude Code") << " Session " << c.sid << "\n\n";
    bool cwd_shown = false;
    iter_jsonl(c.path, [&](const json& obj) {
        const auto t = field_string(obj, "type");
        if (cfg.is_codex) {
            if (t == "session_meta") {
                const auto payload = field_object(obj, "payload");
                if (!cwd_shown && !field_string(payload, "cwd").empty()) {
                    lines << "- cwd: `" << field_string(payload, "cwd") << "`\n";
                    lines << "- cli: `" << field_string(payload, "cli_version") << "`\n\n";
                    cwd_shown = true;
                }
                return;
            }
            if (t != "response_item") return;
            const auto payload = field_object(obj, "payload");
            const auto ptype = field_string(payload, "type");
            std::string role;
            std::string text;
            if (ptype == "message") {
                const auto msg_role = field_string(payload, "role");
                if (msg_role != "user" && msg_role != "assistant") return;
                text = extract_text(payload.contains("content") ? payload.at("content") : json());
                if (msg_role == "user" && is_internal_codex_text(text)) return;
                role = msg_role == "user" ? "User" : "Assistant";
            } else if (ptype == "function_call" || ptype == "function_call_output") {
                text = codex_tool_text(payload);
                role = "Tool";
            } else {
                return;
            }
            if (text.empty()) return;
            lines << "## " << role << " `" << field_string(obj, "timestamp") << "`\n\n" << text << "\n\n";
        } else {
            if (t == "summary") {
                lines << "> **Summary:** " << field_string(obj, "summary") << "\n\n";
                return;
            }
            if (t != "user" && t != "assistant") return;
            const auto msg = field_object(obj, "message");
            const auto content = msg.contains("content") ? msg.at("content") : json();
            auto text = extract_text(content);
            if (text.empty()) return;
            if (!cwd_shown && !field_string(obj, "cwd").empty()) {
                lines << "- cwd: `" << field_string(obj, "cwd") << "`\n";
                lines << "- gitBranch: `" << field_string(obj, "gitBranch") << "`\n\n";
                cwd_shown = true;
            }
            const auto role = is_tool_result_content(content) ? "Tool Result" : (t == "user" ? "User" : "Assistant");
            lines << "## " << role << " `" << field_string(obj, "timestamp") << "`\n\n" << text << "\n\n";
        }
    });
    return lines.str();
}

void open_path_native(const fs::path& path) {
#ifdef _WIN32
    ShellExecuteA(nullptr, "open", path.string().c_str(), nullptr, nullptr, SW_SHOWNORMAL);
#elif __APPLE__
    std::string cmd = "open \"" + path.string() + "\"";
    std::system(cmd.c_str());
#else
    std::string cmd = "xdg-open \"" + path.string() + "\" >/dev/null 2>&1 &";
    std::system(cmd.c_str());
#endif
}

void open_url_native(const std::string& url) {
#ifdef _WIN32
    ShellExecuteA(nullptr, "open", url.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
#elif __APPLE__
    std::string cmd = "open \"" + url + "\"";
    std::system(cmd.c_str());
#else
    std::string cmd = "xdg-open \"" + url + "\" >/dev/null 2>&1 &";
    std::system(cmd.c_str());
#endif
}

std::string ps_quote(const std::string& s) {
    return "'" + replace_all(s, "'", "''") + "'";
}

std::string sh_quote(const std::string& s) {
    return "'" + replace_all(s, "'", "'\\''") + "'";
}

std::string shell_path_prefix() {
#ifdef __APPLE__
    return "/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.npm-global/bin:$HOME/Library/pnpm:$HOME/.bun/bin:$HOME/.cargo/bin";
#else
    return "$HOME/.local/bin:$HOME/.npm-global/bin:$HOME/.bun/bin:$HOME/.cargo/bin";
#endif
}

std::vector<fs::path> path_dirs() {
    std::vector<fs::path> out;
    std::set<std::string> seen;
    const char sep =
#ifdef _WIN32
        ';';
#else
        ':';
#endif
    if (const char* path = std::getenv("PATH")) {
        std::stringstream ss(path);
        std::string item;
        while (std::getline(ss, item, sep)) {
            if (item.empty()) continue;
            fs::path p(item);
            std::error_code ec;
            auto key = path_string(fs::weakly_canonical(p, ec));
            if (ec) key = path_string(p);
            if (seen.insert(lower_ascii(key)).second) out.push_back(p);
        }
    }
    auto add = [&](const fs::path& p) {
        std::error_code ec;
        auto key = path_string(fs::weakly_canonical(p, ec));
        if (ec) key = path_string(p);
        if (seen.insert(lower_ascii(key)).second) out.push_back(p);
    };
    add("/opt/homebrew/bin");
    add("/usr/local/bin");
    add("/usr/bin");
    add("/bin");
    add("/usr/sbin");
    add("/sbin");
    add(home_dir() / ".local" / "bin");
    add(home_dir() / ".npm-global" / "bin");
    add(home_dir() / "Library" / "pnpm");
    add(home_dir() / ".bun" / "bin");
    add(home_dir() / ".cargo" / "bin");
    add(home_dir() / ".volta" / "bin");
    add(home_dir() / ".asdf" / "shims");
    add(home_dir() / ".nodenv" / "shims");
    const auto nvm_versions = home_dir() / ".nvm" / "versions" / "node";
    if (fs::is_directory(nvm_versions)) {
        for (const auto& entry : fs::directory_iterator(nvm_versions)) {
            std::error_code type_ec;
            if (entry.is_directory(type_ec)) add(entry.path() / "bin");
        }
    }
#ifdef _WIN32
    add(home_dir() / "AppData" / "Roaming" / "npm");
#endif
    return out;
}

std::optional<fs::path> find_cli(const Config& cfg, const std::string& name) {
    std::vector<std::string> names;
#ifdef _WIN32
    names = {name + ".exe", name + ".cmd", name + ".bat", name};
#else
    names = {name};
#endif
    auto sidecar = cfg.exe_dir / (name == "codex" ? "Codex.exe" : "Claude.exe");
    std::error_code ec;
    auto sidecar_key = lower_ascii(path_string(fs::weakly_canonical(sidecar, ec)));
    auto try_path = [&](const fs::path& p) -> std::optional<fs::path> {
        if (!fs::is_regular_file(p)) return std::nullopt;
        std::error_code pc_ec;
        auto p_key = lower_ascii(path_string(fs::weakly_canonical(p, pc_ec)));
        if (!sidecar_key.empty() && p_key == sidecar_key) return std::nullopt;
        return p;
    };
#ifdef __APPLE__
    std::vector<fs::path> app_candidates;
    if (name == "codex") {
        app_candidates.push_back("/Applications/Codex.app/Contents/Resources/codex");
        app_candidates.push_back(cfg.home / "Applications" / "Codex.app" / "Contents" / "Resources" / "codex");
    } else if (name == "claude") {
        app_candidates.push_back(cfg.home / ".claude" / "local" / "claude");
        app_candidates.push_back("/Applications/Claude Code.app/Contents/Resources/claude");
        app_candidates.push_back("/Applications/Claude.app/Contents/Resources/claude");
        app_candidates.push_back(cfg.home / "Applications" / "Claude Code.app" / "Contents" / "Resources" / "claude");
        app_candidates.push_back(cfg.home / "Applications" / "Claude.app" / "Contents" / "Resources" / "claude");
    }
    for (const auto& p : app_candidates) {
        if (auto found = try_path(p)) return found;
    }
#endif
    for (const auto& dir : path_dirs()) {
        for (const auto& candidate : names) {
            auto p = dir / candidate;
            if (auto found = try_path(p)) return found;
        }
    }
#ifndef _WIN32
    const auto probe = "/bin/zsh -lc " + sh_quote("command -v " + sh_quote(name) + " 2>/dev/null");
    if (FILE* pipe = popen(probe.c_str(), "r")) {
        char buffer[4096] = {};
        std::string line;
        if (std::fgets(buffer, sizeof(buffer), pipe)) line = trim(buffer);
        pclose(pipe);
        if (!line.empty()) {
            if (auto found = try_path(fs::path(line))) return found;
        }
    }
#endif
    return std::nullopt;
}

std::optional<fs::path> sidecar_exe(const Config& cfg) {
    const auto p = cfg.exe_dir / (cfg.is_codex ? "Codex.exe" : "Claude.exe");
    if (fs::is_regular_file(p)) return p;
    return std::nullopt;
}

std::string safe_slug(std::string value, const std::string& fallback) {
    std::string out;
    for (unsigned char c : value) {
        if (std::isalnum(c) || c == '.' || c == '_' || c == '-') out.push_back(static_cast<char>(c));
        else if (!out.empty() && out.back() != '-') out.push_back('-');
    }
    while (!out.empty() && out.front() == '-') out.erase(out.begin());
    while (!out.empty() && out.back() == '-') out.pop_back();
    return out.empty() ? fallback : out;
}

bool write_text_file(const fs::path& path, const std::string& text) {
    try {
        fs::create_directories(path.parent_path());
        std::ofstream out(path, std::ios::binary);
        out << text;
        return static_cast<bool>(out);
    } catch (...) {
        return false;
    }
}

fs::path write_transfer_file(const Config& cfg, const std::string& prefix, const std::string& sid, const std::string& text) {
    fs::create_directories(cfg.index_file.parent_path());
    const auto name = prefix + "-" + safe_slug(sid, "session") + "-" + std::to_string(static_cast<long long>(now_seconds())) + ".md";
    auto path = cfg.index_file.parent_path() / name;
    write_text_file(path, text);
    return path;
}

void spawn_terminal(const Config& cfg, const fs::path& cwd, const std::string& command, const std::string& title) {
    fs::create_directories(cfg.index_file.parent_path());
#ifdef _WIN32
    const auto script_path = cfg.index_file.parent_path() /
        ("launch-" + safe_slug(title, "terminal") + "-" + std::to_string(static_cast<long long>(now_seconds())) + ".ps1");
    std::ostringstream script;
    script << "$utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false\n"
           << "[Console]::InputEncoding = $utf8NoBom\n"
           << "[Console]::OutputEncoding = $utf8NoBom\n"
           << "$OutputEncoding = $utf8NoBom\n"
           << "$env:PYTHONUTF8 = '1'\n"
           << "$env:PYTHONIOENCODING = 'utf-8'\n"
           << "try { chcp.com 65001 > $null } catch {}\n"
           << "Set-Location -LiteralPath " << ps_quote(path_string(cwd)) << "\n"
           << command << "\n";
    if (!write_text_file(script_path, script.str())) throw std::runtime_error("failed to write launch script");
    const auto params = "-NoExit -ExecutionPolicy Bypass -File " + ps_quote(path_string(script_path));
    auto rc = reinterpret_cast<std::intptr_t>(ShellExecuteA(nullptr, "open", "powershell.exe", params.c_str(), nullptr, SW_SHOWNORMAL));
    if (rc <= 32) throw std::runtime_error("failed to launch PowerShell");
#elif __APPLE__
    const auto script_path = cfg.index_file.parent_path() /
        ("launch-" + safe_slug(title, "terminal") + "-" + std::to_string(static_cast<long long>(now_seconds())) + ".command");
    std::ostringstream script;
    script << "#!/bin/zsh\n"
           << "export PATH=\"" << shell_path_prefix() << ":$PATH\"\n"
           << "cd " << sh_quote(path_string(cwd)) << " || exit $?\n"
           << command << "\n";
    if (!write_text_file(script_path, script.str())) throw std::runtime_error("failed to write launch script");
    std::error_code perm_ec;
    fs::permissions(script_path,
                    fs::perms::owner_exec | fs::perms::group_exec | fs::perms::others_exec,
                    fs::perm_options::add,
                    perm_ec);
    const auto cmd = "/usr/bin/open -a Terminal " + sh_quote(path_string(script_path));
    if (std::system(cmd.c_str()) != 0) throw std::runtime_error("failed to launch Terminal");
#else
    const auto shell = "export PATH=\"" + shell_path_prefix() + ":$PATH\"; cd " + sh_quote(path_string(cwd)) + " && " + command + "; exec bash";
    const auto cmd = "x-terminal-emulator -e bash -lc " + sh_quote(shell) + " >/dev/null 2>&1 &";
    if (std::system(cmd.c_str()) != 0) throw std::runtime_error("failed to launch terminal");
#endif
}

std::string cli_command(const fs::path& cli, const std::vector<std::string>& args = {}) {
#ifdef _WIN32
    std::string out = "& " + ps_quote(path_string(cli));
    for (const auto& arg : args) out += " " + ps_quote(arg);
    return out;
#else
    std::string out = sh_quote(path_string(cli));
    for (const auto& arg : args) out += " " + sh_quote(arg);
    return out;
#endif
}

std::string prompt_file_prelude(const fs::path& path) {
#ifdef _WIN32
    return "$prompt = Get-Content -LiteralPath " + ps_quote(path_string(path)) + " -Raw -Encoding UTF8\n";
#else
    (void)path;
    return "";
#endif
}

std::string prompt_file_arg(const fs::path& path) {
#ifdef _WIN32
    (void)path;
    return "$prompt";
#else
    return "\"$(cat " + sh_quote(path_string(path)) + ")\"";
#endif
}

std::string session_markdown(const Config& cfg, const Candidate& c) {
    return export_markdown(cfg, c);
}

std::string session_cwd(const Config& cfg, const Candidate& c) {
    return field_string(build_session_detail(cfg, c), "cwd");
}

json read_json_file(const fs::path& path) {
    std::string body;
    if (!read_file(path, body)) return json::object();
    auto data = json::parse(body, nullptr, false);
    return data.is_object() ? data : json::object();
}

json auth_status(const Config& cfg) {
    (void)cfg;
    return {
        {"ok", true},
        {"reason", "privacy_disabled"},
        {"expiresInSec", nullptr},
        {"privacyMode", true}
    };
}

void launch_new_chat(const Config& cfg) {
    if (auto sidecar = sidecar_exe(cfg)) {
#ifdef _WIN32
        auto rc = reinterpret_cast<std::intptr_t>(ShellExecuteA(nullptr, "open", path_string(*sidecar).c_str(), nullptr, path_string(sidecar->parent_path()).c_str(), SW_SHOWNORMAL));
        if (rc <= 32) throw std::runtime_error("failed to launch sidecar");
        return;
#endif
    }
    const auto cli_name = cfg.is_codex ? "codex" : "claude";
    auto cli = find_cli(cfg, cli_name);
    if (!cli) throw std::runtime_error(cli_name + std::string(" CLI not found"));
    spawn_terminal(cfg, cfg.home, cli_command(*cli), cfg.is_codex ? "Codex" : "Claude");
}

void launch_login(const Config& cfg, const std::string& cli_name) {
    auto cli = find_cli(cfg, cli_name);
    if (!cli) throw std::runtime_error(cli_name + std::string(" CLI not found"));
    const auto arg = cli_name == "claude" ? "/login" : "login";
    spawn_terminal(cfg, cfg.home, cli_command(*cli, {arg}), cli_name == "claude" ? "Claude Login" : "Codex Login");
}

json account_payload(const Config& cfg) {
    auto auth = auth_status(cfg);
    if (cfg.is_codex) {
        return {{"name", "Codex"}, {"email", "local Codex"}, {"auth", auth}};
    }
    return {
        {"ok", true},
        {"name", "Claude"},
        {"email", "local Claude"},
        {"plan", "-"},
        {"tier", ""},
        {"auth", auth}
    };
}

Config make_config(int argc, char** argv) {
    Config cfg;
    if (argc > 0 && argv[0]) cfg.exe_dir = fs::absolute(fs::path(argv[0])).parent_path();
    else cfg.exe_dir = fs::current_path();
    cfg.home = home_dir();
    cfg.codex_home = env_path("CODEX_HOME", cfg.home / ".codex");
    cfg.codex_sessions = cfg.codex_home / "sessions";
    cfg.codex_backup_sessions = cfg.home / ".codex_backup" / "sessions";
    cfg.codex_backup_archived = cfg.home / ".codex_backup" / "archived_sessions";
    cfg.claude_projects = env_path("CLAUDE_HOME", cfg.home / ".claude") / "projects";
    cfg.index_file = cfg.is_codex ? cfg.home / ".codex_conv_manager_cpp" / "index.json"
                                  : cfg.home / ".claude_manager_cpp" / "index.json";
    if (const char* p = std::getenv(cfg.is_codex ? "CODEX_MANAGER_CPP_PORT" : "CLAUDE_MANAGER_CPP_PORT"); p && *p) {
        cfg.port = std::atoi(p);
    } else if (const char* p2 = std::getenv(cfg.is_codex ? "CODEX_MANAGER_PORT" : "CLAUDE_MANAGER_PORT"); p2 && *p2) {
        cfg.port = std::atoi(p2);
    }
    cfg.web_dir = fs::path(DEFAULT_WEB_DIR);
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--port" && i + 1 < argc) cfg.port = std::atoi(argv[++i]);
        else if (arg == "--web" && i + 1 < argc) cfg.web_dir = fs::path(argv[++i]);
        else if (arg == "--no-open") cfg.ui_mode = UiMode::Headless;
        else if (arg == "--browser") cfg.ui_mode = UiMode::Browser;
        else if (arg == "--window") cfg.ui_mode = UiMode::Window;
    }
    if (!fs::is_directory(cfg.web_dir)) {
        auto exe_web = cfg.exe_dir / "web";
        if (fs::is_directory(exe_web)) cfg.web_dir = exe_web;
    }
#ifdef __APPLE__
    if (!fs::is_directory(cfg.web_dir)) {
        auto app_web = cfg.exe_dir.parent_path() / "Resources" / "web";
        if (fs::is_directory(app_web)) cfg.web_dir = app_web;
    }
#endif
    if (!fs::is_directory(cfg.web_dir)) {
        auto cwd_web = fs::current_path() / "web";
        if (fs::is_directory(cwd_web)) cfg.web_dir = cwd_web;
    }
    return cfg;
}

void register_routes(httplib::Server& svr, const Config& cfg) {
    svr.set_exception_handler([](const httplib::Request&, httplib::Response& res, std::exception_ptr ep) {
        try {
            if (ep) std::rethrow_exception(ep);
        } catch (const std::exception& e) {
            error_response(res, 500, e.what());
            return;
        } catch (...) {
            error_response(res, 500, "unknown server exception");
            return;
        }
        error_response(res, 500, "server exception");
    });

    svr.Get("/", [&](const httplib::Request&, httplib::Response& res) {
        std::string body;
        if (!read_file(cfg.web_dir / "index.html", body)) {
            error_response(res, 404, "web/index.html not found");
            return;
        }
        res.set_content(body, "text/html; charset=utf-8");
    });

    svr.Get("/api/sessions", [&](const httplib::Request&, httplib::Response& res) {
        try {
            auto [projects, sessions] = load_session_summaries(cfg);
            json_response(res, {{"projects", projects}, {"sessions", sessions}});
        } catch (const std::exception& e) {
            error_response(res, 500, e.what());
        }
    });

    svr.Post("/api/refresh", [&](const httplib::Request&, httplib::Response& res) {
        {
            std::lock_guard<std::mutex> lock(g_index_mutex);
            g_index_cache.reset();
        }
        {
            std::lock_guard<std::mutex> lock(g_search_mutex);
            g_search_blobs.clear();
        }
        json_response(res, {{"ok", true}});
    });

    svr.Get(R"(/api/session/([^/]+)/([^/]+))", [&](const httplib::Request& req, httplib::Response& res) {
        auto c = find_session(cfg, req.matches[1], req.matches[2]);
        if (!c) {
            error_response(res, 404, "session not found");
            return;
        }
        json_response(res, build_session_detail(cfg, *c));
    });

    svr.Get("/api/search", [&](const httplib::Request& req, httplib::Response& res) {
        const auto query = req.has_param("q") ? url_decode(req.get_param_value("q")) : "";
        if (trim(query).empty()) {
            json_response(res, {{"results", json::array()}});
            return;
        }
        const auto qlower = lower_ascii(query);
        const auto files = enumerate_files(cfg);
        std::vector<SearchPrepared> prepared(files.size());
        std::atomic_size_t next{0};
        const auto workers = std::max<size_t>(1, std::min<size_t>(8, files.size()));
        std::vector<std::thread> threads;
        for (size_t w = 0; w < workers; ++w) {
            threads.emplace_back([&, w] {
                (void)w;
                while (true) {
                    const auto i = next.fetch_add(1);
                    if (i >= files.size()) break;
                    prepared[i] = ensure_blob(cfg, files[i]);
                }
            });
        }
        for (auto& thread : threads) thread.join();

        json results = json::array();
        for (const auto& p : prepared) {
            if (!p.ok || p.blob.find(qlower) == std::string::npos) continue;
            auto hits = search_snippets(cfg, p.file, query, qlower);
            if (!hits.empty()) {
                results.push_back({{"project", p.file.project}, {"sid", p.file.sid}, {"mtime", p.file.mtime}, {"hits", hits}});
            }
        }
        std::sort(results.begin(), results.end(), [](const json& a, const json& b) {
            return (a["mtime"].is_number() ? a["mtime"].get<double>() : 0.0) >
                   (b["mtime"].is_number() ? b["mtime"].get<double>() : 0.0);
        });
        json_response(res, {{"results", results}});
    });

    svr.Get(R"(/api/export/([^/]+)/([^/]+))", [&](const httplib::Request& req, httplib::Response& res) {
        auto c = find_session(cfg, req.matches[1], req.matches[2]);
        if (!c) {
            error_response(res, 404, "session not found");
            return;
        }
        const auto fmt = req.has_param("format") ? lower_ascii(req.get_param_value("format")) : "md";
        std::string body;
        if (fmt == "json") {
            if (!read_file(c->path, body)) {
                error_response(res, 404, "session file not found");
                return;
            }
            res.set_header("Content-Disposition", "attachment; filename=\"" + c->sid + ".jsonl\"");
            res.set_content(body, "application/jsonl; charset=utf-8");
        } else {
            body = export_markdown(cfg, *c);
            res.set_header("Content-Disposition", "attachment; filename=\"" + c->sid + ".md\"");
            res.set_content(body, "text/markdown; charset=utf-8");
        }
    });

    svr.Post("/api/delete", [&](const httplib::Request& req, httplib::Response& res) {
        const auto data = parse_json_body(req);
        auto c = find_session(cfg, field_string(data, "project"), field_string(data, "sid"));
        if (!c) {
            error_response(res, 404, "session not found");
            return;
        }
        std::error_code ec;
        fs::remove(c->path, ec);
        if (ec) {
            error_response(res, 500, ec.message());
            return;
        }
        json_response(res, {{"ok", true}});
    });

    svr.Post("/api/open-cwd", [&](const httplib::Request& req, httplib::Response& res) {
        const auto data = parse_json_body(req);
        auto c = find_session(cfg, field_string(data, "project"), field_string(data, "sid"));
        if (!c) {
            error_response(res, 404, "session not found");
            return;
        }
        auto detail = build_session_detail(cfg, *c);
        const auto cwd = field_string(detail, "cwd");
        if (cwd.empty() || !fs::is_directory(fs::path(cwd))) {
            error_response(res, 404, "cwd not found: " + cwd);
            return;
        }
        open_path_native(fs::path(cwd));
        json_response(res, {{"ok", true}, {"cwd", cwd}});
    });

    svr.Get("/api/costs", [&](const httplib::Request&, httplib::Response& res) {
        json_response(res, aggregate_costs(cfg));
    });

    svr.Get("/api/stats", [&](const httplib::Request&, httplib::Response& res) {
        json_response(res, build_stats(cfg));
    });

    svr.Get("/api/active", [&](const httplib::Request&, httplib::Response& res) {
        auto [projects, sessions] = load_session_summaries(cfg);
        (void)projects;
        json active = json::array();
        for (const auto& s : sessions) {
            if (field_bool(s, "active")) active.push_back({{"project", field_string(s, "project")}, {"sid", field_string(s, "sid")}});
        }
        json_response(res, {{"active", active}});
    });

    svr.Post("/api/notify", [&](const httplib::Request&, httplib::Response& res) {
        json_response(res, {{"ok", true}});
    });

    svr.Get("/api/account", [&](const httplib::Request&, httplib::Response& res) {
        json_response(res, account_payload(cfg));
    });

    svr.Get("/api/auth-status", [&](const httplib::Request&, httplib::Response& res) {
        json_response(res, auth_status(cfg));
    });

    svr.Post("/api/new-chat", [&](const httplib::Request&, httplib::Response& res) {
        try {
            launch_new_chat(cfg);
            json_response(res, {{"ok", true}});
        } catch (const std::exception& e) {
            error_response(res, 500, e.what());
        }
    });

    auto login_stub = [](const httplib::Request&, httplib::Response& res) {
        json_response(res, {{"ok", false}, {"error", "login is intentionally disabled in the desktop client"}}, 501);
    };
    svr.Post("/api/codex-login", login_stub);
    svr.Post("/api/claude-login", login_stub);

    svr.Post("/api/resume", [&](const httplib::Request& req, httplib::Response& res) {
        const auto data = parse_json_body(req);
        auto c = find_session(cfg, field_string(data, "project"), field_string(data, "sid"));
        if (!c) {
            error_response(res, 404, "session not found");
            return;
        }
        const auto cwd = session_cwd(cfg, *c);
        if (cwd.empty() || !fs::is_directory(fs::path(cwd))) {
            error_response(res, 400, "cwd not found: " + cwd);
            return;
        }
        try {
            if (cfg.is_codex) {
                auto codex = find_cli(cfg, "codex");
                if (!codex) throw std::runtime_error("codex CLI not found");
                spawn_terminal(cfg, fs::path(cwd), cli_command(*codex, {"resume", c->sid}), "Codex Resume");
            } else {
                auto claude = find_cli(cfg, "claude");
                if (!claude) throw std::runtime_error("claude CLI not found");
                const auto command = cli_command(*claude, {
                    "--permission-mode", "bypassPermissions",
                    "--dangerously-skip-permissions",
                    "--resume", c->sid
                });
                spawn_terminal(cfg, fs::path(cwd), command, "Claude Resume");
            }
            json_response(res, {{"ok", true}, {"cwd", cwd}});
        } catch (const std::exception& e) {
            error_response(res, 500, e.what());
        }
    });

    svr.Post("/api/claude", [&](const httplib::Request& req, httplib::Response& res) {
        if (!cfg.is_codex) {
            error_response(res, 501, "Claude transfer is only available in the Codex manager");
            return;
        }
        const auto data = parse_json_body(req);
        auto c = find_session(cfg, field_string(data, "project"), field_string(data, "sid"));
        if (!c) {
            error_response(res, 404, "session not found");
            return;
        }
        const auto cwd = session_cwd(cfg, *c);
        if (cwd.empty() || !fs::is_directory(fs::path(cwd))) {
            error_response(res, 400, "cwd not found: " + cwd);
            return;
        }
        try {
            auto claude = find_cli(cfg, "claude");
            if (!claude) throw std::runtime_error("claude CLI not found");
            const auto prompt = "This is context imported from a local Codex session. Continue the user's work in Claude Code.\n\n" +
                session_markdown(cfg, *c);
            const auto prompt_path = write_transfer_file(cfg, "codex-to-claude", c->sid, prompt);
            const auto command = prompt_file_prelude(prompt_path) +
                cli_command(*claude, {
                    "--add-dir", path_string(prompt_path.parent_path()),
                    "--permission-mode", "bypassPermissions",
                    "--dangerously-skip-permissions",
                    "--"
                }) + " " + prompt_file_arg(prompt_path);
            spawn_terminal(cfg, fs::path(cwd), command, "Claude");
            json_response(res, {{"ok", true}, {"cwd", cwd}, {"promptPath", path_string(prompt_path)}});
        } catch (const std::exception& e) {
            error_response(res, 500, e.what());
        }
    });

    svr.Post("/api/codex", [&](const httplib::Request& req, httplib::Response& res) {
        if (cfg.is_codex) {
            error_response(res, 501, "Codex transfer is only available in the Claude manager");
            return;
        }
        const auto data = parse_json_body(req);
        auto c = find_session(cfg, field_string(data, "project"), field_string(data, "sid"));
        if (!c) {
            error_response(res, 404, "session not found");
            return;
        }
        const auto cwd = session_cwd(cfg, *c);
        if (cwd.empty() || !fs::is_directory(fs::path(cwd))) {
            error_response(res, 400, "cwd not found: " + cwd);
            return;
        }
        try {
            auto codex = find_cli(cfg, "codex");
            if (!codex) throw std::runtime_error("codex CLI not found");
            const auto md_path = fs::path(cwd) / ("_claude_manager_" + c->sid + ".md");
            if (!write_text_file(md_path, session_markdown(cfg, *c))) throw std::runtime_error("failed to write transfer markdown");
            const auto prompt = "Reference " + md_path.filename().string() + " in the current directory and continue the task.";
            spawn_terminal(cfg, fs::path(cwd), cli_command(*codex, {prompt}), "Codex");
            json_response(res, {{"ok", true}, {"cwd", cwd}, {"mdPath", path_string(md_path)}});
        } catch (const std::exception& e) {
            error_response(res, 500, e.what());
        }
    });

    auto stub = [&](const httplib::Request&, httplib::Response& res) {
        json_response(res, {{"ok", false}, {"error", "not implemented in the C++ prototype"}}, 501);
    };
    svr.Post("/api/claude-to-codex", stub);
    svr.Post("/api/generate-skill", stub);
    svr.Post(R"(/api/generate-skill/([^/]+)/([^/]+))", stub);

    svr.Get(R"(/(.+))", [&](const httplib::Request& req, httplib::Response& res) {
        auto rel = url_decode(req.matches[1]);
        if (rel.find("..") != std::string::npos || rel.find(':') != std::string::npos) {
            error_response(res, 400, "bad path");
            return;
        }
        auto path = (cfg.web_dir / fs::path(rel)).lexically_normal();
        if (!is_relative_to(path, cfg.web_dir) || !fs::is_regular_file(path)) {
            error_response(res, 404, "not found");
            return;
        }
        std::string body;
        if (!read_file(path, body)) {
            error_response(res, 404, "not found");
            return;
        }
        res.set_content(body, content_type(path));
    });
}

bool port_available(const std::string& host, int port) {
#ifdef _WIN32
    SOCKET sock = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (sock == INVALID_SOCKET) return false;
    BOOL exclusive = TRUE;
    setsockopt(sock, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, reinterpret_cast<const char*>(&exclusive), sizeof(exclusive));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(static_cast<u_short>(port));
    addr.sin_addr.s_addr = host == "0.0.0.0" ? htonl(INADDR_ANY) : htonl(INADDR_LOOPBACK);
    const bool ok = bind(sock, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0;
    closesocket(sock);
    return ok;
#else
    (void)host;
    (void)port;
    return true;
#endif
}

} // namespace

int app_main(int argc, char** argv) {
    auto cfg = make_config(argc, argv);
    if (!fs::is_directory(cfg.web_dir)) {
        std::cerr << "Web directory not found: " << path_string(cfg.web_dir) << "\n";
        return 2;
    }

    httplib::Server svr;
    svr.new_task_queue = [] { return new httplib::ThreadPool(8); };
#ifdef _WIN32
    svr.set_socket_options([](socket_t sock) {
        BOOL exclusive = TRUE;
        setsockopt(sock, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, reinterpret_cast<const char*>(&exclusive), sizeof(exclusive));
    });
#endif
    register_routes(svr, cfg);

    int bound_port = 0;
    for (int p = cfg.port; p < cfg.port + 25; ++p) {
        if (!port_available(cfg.host, p)) continue;
        if (svr.bind_to_port(cfg.host, p)) {
            bound_port = p;
            break;
        }
        break;
    }
    if (!bound_port) {
        std::cerr << "Could not bind " << cfg.host << ":" << cfg.port << "\n";
        return 1;
    }

    const auto url = "http://" + cfg.host + ":" + std::to_string(bound_port) + "/";
    std::cout << cfg.app_name << " listening on " << url << "\n";
    std::cout << "Web: " << path_string(cfg.web_dir) << "\n";
    if (cfg.ui_mode == UiMode::Browser) {
        open_url_native(url);
        svr.listen_after_bind();
        return 0;
    }

#if defined(_WIN32) || defined(__APPLE__)
    if (cfg.ui_mode == UiMode::Window) {
        auto profile_dir = cfg.index_file.parent_path() / (
#ifdef _WIN32
            "webview2"
#else
            "webkit"
#endif
        );
        std::error_code ec;
        fs::create_directories(profile_dir, ec);
        std::thread server_thread([&svr] { svr.listen_after_bind(); });
        const int rc = run_desktop_window(cfg.app_name, url, profile_dir);
        svr.stop();
        if (server_thread.joinable()) server_thread.join();
        return rc;
    }
#else
    if (cfg.ui_mode == UiMode::Window) open_url_native(url);
#endif

    svr.listen_after_bind();
    return 0;
}

#ifdef _WIN32
std::string wide_to_utf8(const std::wstring& value) {
    if (value.empty()) return {};
    const int size = WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
    if (size <= 0) return {};
    std::string out(static_cast<size_t>(size), '\0');
    WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), out.data(), size, nullptr, nullptr);
    return out;
}

int WINAPI WinMain(HINSTANCE, HINSTANCE, LPSTR, int) {
    int argc = 0;
    LPWSTR* wargv = CommandLineToArgvW(GetCommandLineW(), &argc);
    std::vector<std::string> args;
    std::vector<char*> argv;
    if (wargv) {
        args.reserve(static_cast<size_t>(argc));
        argv.reserve(static_cast<size_t>(argc));
        for (int i = 0; i < argc; ++i) {
            args.push_back(wide_to_utf8(wargv[i] ? wargv[i] : L""));
        }
        LocalFree(wargv);
        for (auto& arg : args) argv.push_back(arg.data());
    }
    return app_main(static_cast<int>(argv.size()), argv.empty() ? nullptr : argv.data());
}
#endif

int main(int argc, char** argv) {
    return app_main(argc, argv);
}
