/*
 * Switch Bay GUI launcher — Start Menu / desktop shortcut.
 * Opens Edge as an app window on the loopback PWA. Does not spawn Python.
 * If the daemon is not up, starts the per-user Scheduled Task then polls health.
 *
 * Build: cl /nologo /O2 /Fe:SwitchBay.exe switchbay-gui.c shell32.lib wininet.lib
 */
#include <windows.h>
#include <shellapi.h>
#include <wininet.h>
#include <stdio.h>

static const wchar_t kUrl[] = L"http://127.0.0.1:8765";
static const wchar_t kHealth[] = L"http://127.0.0.1:8765/api/health";
static const wchar_t kTask[] = L"SwitchBay";

static int health_ok(void)
{
    HINTERNET n = InternetOpenW(L"SwitchBay", INTERNET_OPEN_TYPE_PRECONFIG, NULL, NULL, 0);
    if (!n) return 0;
    HINTERNET r = InternetOpenUrlW(n, kHealth, NULL, 0,
                                   INTERNET_FLAG_RELOAD | INTERNET_FLAG_NO_CACHE_WRITE, 0);
    int ok = 0;
    if (r) {
        DWORD status = 0, len = sizeof(status);
        HttpQueryInfoW(r, HTTP_QUERY_STATUS_CODE | HTTP_QUERY_FLAG_NUMBER, &status, &len, NULL);
        ok = (status == 200);
        InternetCloseHandle(r);
    }
    InternetCloseHandle(n);
    return ok;
}

static void kick_task(void)
{
    wchar_t cmd[128];
    swprintf(cmd, 128, L"schtasks /Run /TN %s", kTask);
    STARTUPINFOW si = { .cb = sizeof(si) };
    PROCESS_INFORMATION pi;
    if (CreateProcessW(NULL, cmd, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi)) {
        WaitForSingleObject(pi.hProcess, 5000);
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
    }
}

static void open_edge(void)
{
    /* Edge app-window. No Chrome/WebView2 fallback (product decision). */
    wchar_t args[256];
    swprintf(args, 256, L"--app=%s", kUrl);
    HINSTANCE e = ShellExecuteW(NULL, L"open", L"msedge", args, NULL, SW_SHOWNORMAL);
    if ((INT_PTR)e <= 32) {
        ShellExecuteW(NULL, L"open", kUrl, NULL, NULL, SW_SHOWNORMAL);
    }
}

int WINAPI wWinMain(HINSTANCE a, HINSTANCE b, PWSTR c, int d)
{
    (void)a; (void)b; (void)c; (void)d;
    if (!health_ok()) {
        kick_task();
        for (int i = 0; i < 40 && !health_ok(); i++) Sleep(250);
    }
    open_edge();
    return 0;
}
