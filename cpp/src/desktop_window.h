#pragma once

#include <filesystem>
#include <string>

#ifdef _WIN32
int run_desktop_window(
    const std::string& title_utf8,
    const std::string& url_utf8,
    const std::filesystem::path& user_data_dir);
#endif
