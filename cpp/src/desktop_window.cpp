#ifdef _WIN32

#include "desktop_window.h"

#include <windows.h>
#include <shellapi.h>
#include <wrl.h>
#include <WebView2.h>

#include <algorithm>
#include <filesystem>
#include <sstream>
#include <string>

namespace {

using Microsoft::WRL::Callback;
using Microsoft::WRL::ComPtr;

constexpr wchar_t kWindowClass[] = L"ConvManagerCppWebViewWindow";
constexpr int kAppIconResourceId = 101;

ComPtr<ICoreWebView2Controller> g_controller;
ComPtr<ICoreWebView2> g_webview;
std::wstring g_initial_url;

HICON load_app_icon(HINSTANCE instance, int width, int height) {
    auto icon = reinterpret_cast<HICON>(LoadImageW(
        instance,
        MAKEINTRESOURCEW(kAppIconResourceId),
        IMAGE_ICON,
        width,
        height,
        LR_DEFAULTCOLOR));
    if (icon) return icon;
    return LoadIconW(nullptr, MAKEINTRESOURCEW(32512));
}

std::wstring utf8_to_wide(const std::string& value) {
    if (value.empty()) return {};
    const int size = MultiByteToWideChar(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0);
    if (size <= 0) return {};
    std::wstring out(static_cast<size_t>(size), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), out.data(), size);
    return out;
}

std::wstring hresult_message(HRESULT hr) {
    wchar_t* buffer = nullptr;
    const DWORD flags = FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS;
    FormatMessageW(flags, nullptr, static_cast<DWORD>(hr), 0, reinterpret_cast<wchar_t*>(&buffer), 0, nullptr);

    std::wstringstream ss;
    ss << L"WebView2 initialization failed. Please install Microsoft Edge WebView2 Runtime.\n\nHRESULT: 0x"
       << std::hex << static_cast<unsigned long>(hr);
    if (buffer && *buffer) ss << L"\n" << buffer;
    if (buffer) LocalFree(buffer);
    return ss.str();
}

void resize_webview(HWND hwnd) {
    if (!g_controller) return;
    RECT bounds{};
    GetClientRect(hwnd, &bounds);
    g_controller->put_Bounds(bounds);
}

void configure_webview(HWND hwnd, ICoreWebView2Controller* controller) {
    g_controller = controller;
    g_controller->get_CoreWebView2(&g_webview);
    resize_webview(hwnd);

    if (g_webview) {
        ComPtr<ICoreWebView2Settings> settings;
        if (SUCCEEDED(g_webview->get_Settings(&settings)) && settings) {
            settings->put_AreDevToolsEnabled(TRUE);
            settings->put_IsStatusBarEnabled(FALSE);
        }

        EventRegistrationToken token{};
        g_webview->add_NewWindowRequested(
            Callback<ICoreWebView2NewWindowRequestedEventHandler>(
                [](ICoreWebView2*, ICoreWebView2NewWindowRequestedEventArgs* args) -> HRESULT {
                    LPWSTR uri = nullptr;
                    if (SUCCEEDED(args->get_Uri(&uri)) && uri && *uri) {
                        ShellExecuteW(nullptr, L"open", uri, nullptr, nullptr, SW_SHOWNORMAL);
                    }
                    if (uri) CoTaskMemFree(uri);
                    args->put_Handled(TRUE);
                    return S_OK;
                })
                .Get(),
            &token);

        g_webview->Navigate(g_initial_url.c_str());
    }
}

void start_webview(HWND hwnd, const std::wstring& user_data_dir) {
    const HRESULT hr = CreateCoreWebView2EnvironmentWithOptions(
        nullptr,
        user_data_dir.empty() ? nullptr : user_data_dir.c_str(),
        nullptr,
        Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>(
            [hwnd](HRESULT result, ICoreWebView2Environment* env) -> HRESULT {
                if (FAILED(result) || !env) {
                    MessageBoxW(hwnd, hresult_message(result).c_str(), L"WebView2", MB_ICONERROR | MB_OK);
                    PostMessageW(hwnd, WM_CLOSE, 0, 0);
                    return S_OK;
                }

                env->CreateCoreWebView2Controller(
                    hwnd,
                    Callback<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler>(
                        [hwnd](HRESULT controller_result, ICoreWebView2Controller* controller) -> HRESULT {
                            if (FAILED(controller_result) || !controller) {
                                MessageBoxW(hwnd, hresult_message(controller_result).c_str(), L"WebView2", MB_ICONERROR | MB_OK);
                                PostMessageW(hwnd, WM_CLOSE, 0, 0);
                                return S_OK;
                            }
                            configure_webview(hwnd, controller);
                            return S_OK;
                        })
                        .Get());
                return S_OK;
            })
            .Get());

    if (FAILED(hr)) {
        MessageBoxW(hwnd, hresult_message(hr).c_str(), L"WebView2", MB_ICONERROR | MB_OK);
        PostMessageW(hwnd, WM_CLOSE, 0, 0);
    }
}

void enable_dpi_awareness() {
    using SetDpiAwarenessContextFn = BOOL(WINAPI*)(HANDLE);
    HMODULE user32 = GetModuleHandleW(L"user32.dll");
    auto set_context = user32 ? reinterpret_cast<SetDpiAwarenessContextFn>(
        GetProcAddress(user32, "SetProcessDpiAwarenessContext")) : nullptr;
    if (set_context && set_context(reinterpret_cast<HANDLE>(-4))) return;
    SetProcessDPIAware();
}

LRESULT CALLBACK window_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
    switch (message) {
    case WM_SIZE:
        resize_webview(hwnd);
        return 0;
    case WM_GETMINMAXINFO: {
        auto* info = reinterpret_cast<MINMAXINFO*>(lparam);
        info->ptMinTrackSize.x = 900;
        info->ptMinTrackSize.y = 560;
        return 0;
    }
    case WM_DESTROY:
        if (g_controller) g_controller->Close();
        g_webview.Reset();
        g_controller.Reset();
        PostQuitMessage(0);
        return 0;
    default:
        return DefWindowProcW(hwnd, message, wparam, lparam);
    }
}

} // namespace

int run_desktop_window(
    const std::string& title_utf8,
    const std::string& url_utf8,
    const std::filesystem::path& user_data_dir) {
    enable_dpi_awareness();
    const HRESULT ole_hr = OleInitialize(nullptr);
    if (FAILED(ole_hr)) {
        MessageBoxW(nullptr, hresult_message(ole_hr).c_str(), L"OLE", MB_ICONERROR | MB_OK);
        return 1;
    }

    g_initial_url = utf8_to_wide(url_utf8);
    const auto title = utf8_to_wide(title_utf8);
    const auto profile_dir = user_data_dir.wstring();

    WNDCLASSEXW wc{};
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = window_proc;
    wc.hInstance = GetModuleHandleW(nullptr);
    wc.hCursor = LoadCursorW(nullptr, MAKEINTRESOURCEW(32512));
    wc.hIcon = load_app_icon(wc.hInstance, GetSystemMetrics(SM_CXICON), GetSystemMetrics(SM_CYICON));
    wc.hIconSm = load_app_icon(wc.hInstance, GetSystemMetrics(SM_CXSMICON), GetSystemMetrics(SM_CYSMICON));
    wc.hbrBackground = reinterpret_cast<HBRUSH>(COLOR_WINDOW + 1);
    wc.lpszClassName = kWindowClass;
    RegisterClassExW(&wc);

    const int screen_width = std::max(1024, GetSystemMetrics(SM_CXSCREEN));
    const int screen_height = std::max(720, GetSystemMetrics(SM_CYSCREEN));
    const int width = 2560;
    const int height = 1440;
    const int x = std::max(0, (screen_width - width) / 2);
    const int y = std::max(0, (screen_height - height) / 2);

    HWND hwnd = CreateWindowExW(
        0,
        kWindowClass,
        title.empty() ? L"Conversation Manager" : title.c_str(),
        WS_OVERLAPPEDWINDOW,
        x,
        y,
        width,
        height,
        nullptr,
        nullptr,
        GetModuleHandleW(nullptr),
        nullptr);

    if (!hwnd) {
        MessageBoxW(nullptr, L"Failed to create the main window.", L"Conversation Manager", MB_ICONERROR | MB_OK);
        OleUninitialize();
        return 1;
    }

    SendMessageW(hwnd, WM_SETICON, ICON_BIG, reinterpret_cast<LPARAM>(wc.hIcon));
    SendMessageW(hwnd, WM_SETICON, ICON_SMALL, reinterpret_cast<LPARAM>(wc.hIconSm));

    ShowWindow(hwnd, SW_SHOW);
    UpdateWindow(hwnd);
    start_webview(hwnd, profile_dir);

    MSG msg{};
    while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    OleUninitialize();
    return static_cast<int>(msg.wParam);
}

#endif
