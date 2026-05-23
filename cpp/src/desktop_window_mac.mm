#ifdef __APPLE__

#include "desktop_window.h"

#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

#include <filesystem>
#include <string>

constexpr CGFloat kDefaultWidth = 2560.0;
constexpr CGFloat kDefaultHeight = 1440.0;
constexpr CGFloat kMinWidth = 900.0;
constexpr CGFloat kMinHeight = 560.0;

static NSString* ns_string(const std::string& value) {
    return [[NSString alloc] initWithBytes:value.data()
                                    length:value.size()
                                  encoding:NSUTF8StringEncoding];
}

@interface ConvManagerAppDelegate : NSObject <NSApplicationDelegate, WKUIDelegate>
@property(nonatomic, copy) NSString* windowTitle;
@property(nonatomic, copy) NSString* initialURL;
@property(nonatomic, strong) NSWindow* window;
@property(nonatomic, strong) WKWebView* webView;
@end

@implementation ConvManagerAppDelegate

- (void)applicationDidFinishLaunching:(NSNotification*)notification {
    (void)notification;

    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];

    NSScreen* screen = [NSScreen mainScreen];
    NSRect visible = screen ? [screen visibleFrame] : NSMakeRect(0, 0, kDefaultWidth, kDefaultHeight);
    CGFloat x = NSMidX(visible) - kDefaultWidth / 2.0;
    CGFloat y = NSMidY(visible) - kDefaultHeight / 2.0;
    if (x < NSMinX(visible)) x = NSMinX(visible);
    if (y < NSMinY(visible)) y = NSMinY(visible);

    NSRect frame = NSMakeRect(x, y, kDefaultWidth, kDefaultHeight);
    NSWindowStyleMask style = NSWindowStyleMaskTitled |
                              NSWindowStyleMaskClosable |
                              NSWindowStyleMaskMiniaturizable |
                              NSWindowStyleMaskResizable;
    self.window = [[NSWindow alloc] initWithContentRect:frame
                                              styleMask:style
                                                backing:NSBackingStoreBuffered
                                                  defer:NO];
    self.window.title = self.windowTitle ? self.windowTitle : @"Conversation Manager";
    self.window.minSize = NSMakeSize(kMinWidth, kMinHeight);
    [self.window center];

    WKWebViewConfiguration* config = [[WKWebViewConfiguration alloc] init];
    self.webView = [[WKWebView alloc] initWithFrame:self.window.contentView.bounds configuration:config];
    self.webView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.webView.UIDelegate = self;
    self.window.contentView = self.webView;

    NSURL* url = [NSURL URLWithString:(self.initialURL ? self.initialURL : @"")];
    if (url) {
        [self.webView loadRequest:[NSURLRequest requestWithURL:url]];
    }

    [self.window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication*)sender {
    (void)sender;
    return YES;
}

- (WKWebView*)webView:(WKWebView*)webView
createWebViewWithConfiguration:(WKWebViewConfiguration*)configuration
  forNavigationAction:(WKNavigationAction*)navigationAction
       windowFeatures:(WKWindowFeatures*)windowFeatures {
    (void)webView;
    (void)configuration;
    (void)windowFeatures;
    NSURL* url = navigationAction.request.URL;
    if (url) [[NSWorkspace sharedWorkspace] openURL:url];
    return nil;
}

@end

static ConvManagerAppDelegate* g_delegate = nil;

int run_desktop_window(
    const std::string& title_utf8,
    const std::string& url_utf8,
    const std::filesystem::path& user_data_dir) {
    (void)user_data_dir;
    @autoreleasepool {
        NSApplication* app = [NSApplication sharedApplication];
        g_delegate = [[ConvManagerAppDelegate alloc] init];
        g_delegate.windowTitle = ns_string(title_utf8);
        g_delegate.initialURL = ns_string(url_utf8);
        app.delegate = g_delegate;
        [app run];
        return 0;
    }
}

#endif
