/*
 * shim.c - generic launcher for ndev shimgen.
 *
 * Copied (or hard-linked) to <shimdir>\<name>.exe. On start it reads
 * <shimdir>\<name>.shim (UTF-8, one "key = value" per line, '#' = comment):
 *
 *     path = C:\ndev\php\8.3\php.exe
 *     args = -c %NDEV_HOME%\php\8.3\php.ini    (optional, prepended to your args)
 *     cwd  = C:\some\dir                        (optional)
 *     path_prepend = C:\ndev\php\8.3            (optional, put first on PATH)
 *     env.FOO = bar                             (optional, repeatable)
 *
 * %VAR% references in values are expanded; env.* and path_prepend are applied
 * first, so path/args/cwd may reference them (whatever the order in the file).
 * The target is run with your original
 * arguments appended; stdio and the exit code are forwarded. Ctrl+C goes to the
 * child. If the shim is killed, the child is killed too - but once the child
 * exits normally, anything it left running (daemons) is NOT killed.
 * Targets that require elevation are re-launched via "runas".
 *
 * Build (MinGW):  x86_64-w64-mingw32-gcc -Os -s -static -o shim.exe shim.c
 * Build (MSVC):   cl /O1 /nologo shim.c /link /out:shim.exe
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

static void eprint(const wchar_t *s) {
    HANDLE h = GetStdHandle(STD_ERROR_HANDLE);
    DWORD m, w;
    if (!h || h == INVALID_HANDLE_VALUE) return;
    if (GetConsoleMode(h, &m)) { WriteConsoleW(h, s, (DWORD)wcslen(s), &w, NULL); return; }
    int n = WideCharToMultiByte(CP_UTF8, 0, s, -1, NULL, 0, NULL, NULL);
    char *b = (char *)malloc(n);
    if (!b) return;
    WideCharToMultiByte(CP_UTF8, 0, s, -1, b, n, NULL, NULL);
    WriteFile(h, b, n - 1, &w, NULL);
    free(b);
}

static int fail(const wchar_t *what, const wchar_t *arg, DWORD err) {
    eprint(L"shim: ");
    eprint(what);
    if (arg) { eprint(L" "); eprint(arg); }
    wchar_t *m = NULL;
    if (err && FormatMessageW(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
                              FORMAT_MESSAGE_IGNORE_INSERTS, NULL, err, 0, (LPWSTR)&m, 0, NULL) && m) {
        eprint(L": ");
        eprint(m);              /* system messages already end in CRLF */
        LocalFree(m);
    } else {
        eprint(L"\r\n");
    }
    return 1;
}

static BOOL WINAPI on_ctrl(DWORD t) { (void)t; return TRUE; }   /* child handles Ctrl+C */

static wchar_t *read_utf8_file(const wchar_t *p, DWORD *err) {
    HANDLE h = CreateFileW(p, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                           NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) { *err = GetLastError(); return NULL; }
    DWORD n = GetFileSize(h, NULL), r = 0;
    char *b = (char *)malloc((size_t)n + 1);
    if (!b || !ReadFile(h, b, n, &r, NULL)) { *err = GetLastError(); CloseHandle(h); free(b); return NULL; }
    CloseHandle(h);
    b[r] = 0;
    int skip = (r >= 3 && (unsigned char)b[0] == 0xEF && (unsigned char)b[1] == 0xBB &&
                (unsigned char)b[2] == 0xBF) ? 3 : 0;
    int wl = MultiByteToWideChar(CP_UTF8, 0, b + skip, -1, NULL, 0);
    wchar_t *w = (wchar_t *)malloc((size_t)wl * sizeof(wchar_t));
    MultiByteToWideChar(CP_UTF8, 0, b + skip, -1, w, wl);
    free(b);
    return w;
}

static wchar_t *trim(wchar_t *s) {
    while (*s == L' ' || *s == L'\t') s++;
    wchar_t *e = s + wcslen(s);
    while (e > s && (e[-1] == L' ' || e[-1] == L'\t' || e[-1] == L'\r')) *--e = 0;
    return s;
}

static wchar_t *expand(const wchar_t *s) {
    DWORD n = ExpandEnvironmentStringsW(s, NULL, 0);
    wchar_t *o = (wchar_t *)malloc((n ? n : 1) * sizeof(wchar_t));
    if (!n || !ExpandEnvironmentStringsW(s, o, n)) wcscpy(o, s);
    return o;
}

/* skip argv[0] in the raw command line; return the remaining args verbatim */
static const wchar_t *rest_of_cmdline(const wchar_t *c) {
    if (*c == L'"') { c++; while (*c && *c != L'"') c++; if (*c) c++; }
    else while (*c && *c != L' ' && *c != L'\t') c++;
    while (*c == L' ' || *c == L'\t') c++;
    return c;
}

int main(void) {
    wchar_t self[MAX_PATH * 2];
    DWORD n = GetModuleFileNameW(NULL, self, MAX_PATH * 2), err = 0;
    if (n < 5 || n >= MAX_PATH * 2 || _wcsicmp(self + n - 4, L".exe"))
        return fail(L"cannot determine own path", NULL, 0);
    wcscpy(self + n - 3, L"shim");                               /* foo.exe -> foo.shim */

    wchar_t *cfg = read_utf8_file(self, &err);
    if (!cfg) return fail(L"cannot read", self, err);

    wchar_t *target = NULL, *pre = NULL, *cwd = NULL, *prepend = NULL;
    for (wchar_t *p = cfg; *p;) {
        wchar_t *line = p;
        while (*p && *p != L'\n') p++;
        if (*p) *p++ = 0;
        line = trim(line);
        if (!*line || *line == L'#') continue;
        wchar_t *eq = wcschr(line, L'=');
        if (!eq) continue;
        *eq = 0;
        wchar_t *k = trim(line), *v = trim(eq + 1);
        if (!_wcsicmp(k, L"path")) target = v;
        else if (!_wcsicmp(k, L"args")) pre = v;
        else if (!_wcsicmp(k, L"cwd")) cwd = v;
        else if (!_wcsicmp(k, L"path_prepend")) prepend = v;
        else if (!_wcsnicmp(k, L"env.", 4) && k[4]) SetEnvironmentVariableW(k + 4, expand(v));
    }
    if (!target || !*target) return fail(L"no 'path' in", self, 0);

    /* Order matters: env.* (above) and PATH first, so %VAR% in path/args/cwd can see them. */
    if (prepend && *prepend) {
        prepend = expand(prepend);
        DWORD l = GetEnvironmentVariableW(L"PATH", NULL, 0);
        wchar_t *neu = (wchar_t *)malloc((wcslen(prepend) + l + 2) * sizeof(wchar_t));
        wcscpy(neu, prepend);
        if (l) {
            wcscat(neu, L";");
            GetEnvironmentVariableW(L"PATH", neu + wcslen(neu), l);
        }
        SetEnvironmentVariableW(L"PATH", neu);
    }
    target = expand(target);
    if (pre) pre = expand(pre);
    if (cwd) cwd = expand(cwd);

    const wchar_t *rest = rest_of_cmdline(GetCommandLineW());
    size_t plen = (pre ? wcslen(pre) : 0) + wcslen(rest) + 2;
    wchar_t *params = (wchar_t *)malloc((plen + 1) * sizeof(wchar_t));
    params[0] = 0;
    if (pre && *pre) { wcscpy(params, pre); if (*rest) wcscat(params, L" "); }
    wcscat(params, rest);

    size_t clen = wcslen(target) + plen + 8;
    if (clen >= 32768) return fail(L"command line too long", NULL, 0);
    wchar_t *cmd = (wchar_t *)malloc(clen * sizeof(wchar_t));
    wcscpy(cmd, L"\"");
    wcscat(cmd, target);
    wcscat(cmd, L"\"");
    if (*params) { wcscat(cmd, L" "); wcscat(cmd, params); }

    SetConsoleCtrlHandler(on_ctrl, TRUE);

    /* Kill the child if we get killed; released again on normal exit (see below). */
    HANDLE job = CreateJobObjectW(NULL, NULL);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION jl;
    ZeroMemory(&jl, sizeof(jl));
    jl.BasicLimitInformation.LimitFlags =
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK;
    if (job) SetInformationJobObject(job, JobObjectExtendedLimitInformation, &jl, sizeof(jl));

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    GetStartupInfoW(&si);

    HANDLE proc;
    if (CreateProcessW(NULL, cmd, NULL, NULL, TRUE, CREATE_SUSPENDED, NULL,
                       (cwd && *cwd) ? cwd : NULL, &si, &pi)) {
        if (job) AssignProcessToJobObject(job, pi.hProcess);   /* may fail if already jobbed; harmless */
        ResumeThread(pi.hThread);
        CloseHandle(pi.hThread);
        proc = pi.hProcess;
    } else if ((err = GetLastError()) == ERROR_ELEVATION_REQUIRED) {
        SHELLEXECUTEINFOW sei;
        ZeroMemory(&sei, sizeof(sei));
        sei.cbSize = sizeof(sei);
        sei.fMask = SEE_MASK_NOCLOSEPROCESS;
        sei.lpVerb = L"runas";
        sei.lpFile = target;
        sei.lpParameters = params;
        sei.lpDirectory = (cwd && *cwd) ? cwd : NULL;
        sei.nShow = SW_SHOWNORMAL;
        if (!ShellExecuteExW(&sei) || !sei.hProcess) return fail(L"cannot run elevated", target, GetLastError());
        proc = sei.hProcess;
    } else {
        return fail(L"cannot run", target, err);
    }

    WaitForSingleObject(proc, INFINITE);
    DWORD code = 0;
    GetExitCodeProcess(proc, &code);

    if (job) {                       /* child finished on its own: let its daemons live on */
        jl.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_BREAKAWAY_OK;
        SetInformationJobObject(job, JobObjectExtendedLimitInformation, &jl, sizeof(jl));
        CloseHandle(job);
    }
    CloseHandle(proc);
    return (int)code;
}
