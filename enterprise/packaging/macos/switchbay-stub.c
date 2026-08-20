/*
 * Switch Bay macOS stub — Dock / Applications icon.
 * Opens Safari on the loopback PWA. Kickstarts the LaunchAgent if health fails.
 * Company codesigns + notarizes the wrapping .app / .pkg.
 *
 * cc -O2 -o SwitchBay switchbay-stub.c
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int health_ok(void)
{
    FILE *f = popen("curl -sf --max-time 1 http://127.0.0.1:8765/api/health >/dev/null 2>&1; echo $?", "r");
    if (!f) return 0;
    char buf[8] = {0};
    if (!fgets(buf, sizeof buf, f)) {
        pclose(f);
        return 0;
    }
    pclose(f);
    return atoi(buf) == 0;
}

int main(void)
{
    if (!health_ok()) {
        (void)system("launchctl kickstart -k gui/$(id -u)/com.switchbay.daemon >/dev/null 2>&1");
        for (int i = 0; i < 40 && !health_ok(); i++)
            usleep(250 * 1000);
    }
    execlp("open", "open", "-a", "Safari", "http://127.0.0.1:8765", (char *)0);
    return 1;
}
