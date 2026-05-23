cmake_minimum_required(VERSION 3.21)

project(ConvManagerCpp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(MANAGER_KIND "codex" CACHE STRING "Conversation format: codex or claude")
set_property(CACHE MANAGER_KIND PROPERTY STRINGS codex claude)

include(FetchContent)
set(JSON_BuildTests OFF CACHE INTERNAL "")
set(HTTPLIB_COMPILE OFF CACHE BOOL "" FORCE)
set(HTTPLIB_USE_OPENSSL_IF_AVAILABLE OFF CACHE BOOL "" FORCE)
set(HTTPLIB_USE_ZLIB_IF_AVAILABLE OFF CACHE BOOL "" FORCE)
set(HTTPLIB_USE_BROTLI_IF_AVAILABLE OFF CACHE BOOL "" FORCE)
set(HTTPLIB_USE_ZSTD_IF_AVAILABLE OFF CACHE BOOL "" FORCE)
set(HTTPLIB_USE_CERTS_FROM_MACOSX_KEYCHAIN OFF CACHE BOOL "" FORCE)

FetchContent_Declare(
  cpp_httplib
  GIT_REPOSITORY https://github.com/yhirose/cpp-httplib.git
  GIT_TAG v0.26.0
  GIT_SHALLOW TRUE
)

FetchContent_Declare(
  nlohmann_json
  GIT_REPOSITORY https://github.com/nlohmann/json.git
  GIT_TAG v3.12.0
  GIT_SHALLOW TRUE
)

FetchContent_MakeAvailable(cpp_httplib nlohmann_json)

set(CONV_MANAGER_SOURCES
  src/main.cpp
  src/desktop_window.cpp
)

if(WIN32)
  enable_language(RC)
  set(APP_ICON_ICO "${CMAKE_CURRENT_LIST_DIR}/../icon.ico")
  string(REPLACE "\\" "/" APP_ICON_ICO_RC "${APP_ICON_ICO}")
  configure_file(src/app_icon.rc.in "${CMAKE_CURRENT_BINARY_DIR}/app_icon.rc" @ONLY)
  list(APPEND CONV_MANAGER_SOURCES "${CMAKE_CURRENT_BINARY_DIR}/app_icon.rc")
endif()

if(APPLE)
  enable_language(OBJCXX)
  set(APP_ICON_ICNS "${CMAKE_CURRENT_LIST_DIR}/../icon.icns")
  list(APPEND CONV_MANAGER_SOURCES src/desktop_window_mac.mm "${APP_ICON_ICNS}")
  set_source_files_properties("${APP_ICON_ICNS}" PROPERTIES MACOSX_PACKAGE_LOCATION Resources)
endif()

add_executable(conv_manager_cpp ${CONV_MANAGER_SOURCES})

target_compile_definitions(conv_manager_cpp PRIVATE
  CONV_MANAGER_KIND="${MANAGER_KIND}"
  DEFAULT_WEB_DIR="${CMAKE_CURRENT_LIST_DIR}/../web"
)

target_link_libraries(conv_manager_cpp PRIVATE
  httplib::httplib
  nlohmann_json::nlohmann_json
)

if(WIN32)
  target_compile_definitions(conv_manager_cpp PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
  set(WEBVIEW2_DIR "${CMAKE_CURRENT_LIST_DIR}/external/webview2" CACHE PATH "Microsoft WebView2 SDK directory")
  if(CMAKE_SIZEOF_VOID_P EQUAL 8)
    set(WEBVIEW2_ARCH x64)
  else()
    set(WEBVIEW2_ARCH x86)
  endif()
  set(WEBVIEW2_INCLUDE_DIR "${WEBVIEW2_DIR}/build/native/include")
  set(WEBVIEW2_LOADER_LIB "${WEBVIEW2_DIR}/build/native/${WEBVIEW2_ARCH}/WebView2LoaderStatic.lib")
  if(NOT EXISTS "${WEBVIEW2_INCLUDE_DIR}/WebView2.h" OR NOT EXISTS "${WEBVIEW2_LOADER_LIB}")
    message(FATAL_ERROR "WebView2 SDK not found. Run build.bat to download ${WEBVIEW2_DIR}.")
  endif()
  target_compile_definitions(conv_manager_cpp PRIVATE HAS_WEBVIEW2=1)
  target_include_directories(conv_manager_cpp PRIVATE "${WEBVIEW2_INCLUDE_DIR}")
  target_link_libraries(conv_manager_cpp PRIVATE
    ws2_32 shell32 user32 gdi32 ole32 oleaut32 advapi32
    "${WEBVIEW2_LOADER_LIB}"
  )
  set_target_properties(conv_manager_cpp PROPERTIES WIN32_EXECUTABLE TRUE)
endif()

if(APPLE)
  set_source_files_properties(src/desktop_window_mac.mm PROPERTIES COMPILE_FLAGS "-fobjc-arc")
  target_link_libraries(conv_manager_cpp PRIVATE
    "-framework Cocoa"
    "-framework WebKit"
  )
  set_target_properties(conv_manager_cpp PROPERTIES
    MACOSX_BUNDLE TRUE
    MACOSX_BUNDLE_ICON_FILE "icon.icns"
    MACOSX_BUNDLE_GUI_IDENTIFIER "local.codex.manager.cpp"
    MACOSX_BUNDLE_BUNDLE_NAME "Codex Manager"
  )
endif()

if(MSVC)
  target_compile_options(conv_manager_cpp PRIVATE /W4 /permissive-)
else()
  target_compile_options(conv_manager_cpp PRIVATE -Wall -Wextra -Wpedantic)
endif()
