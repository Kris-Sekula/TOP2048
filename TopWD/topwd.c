/*
 * TopWD - user-mode replacement for Jungo WinDriver 6 (windrvr6.sys)
 *         for TopWin and the TOP2049 USB programmer (TOP853/TOP2004 untested)
 *         (USB VID_2471 & PID_0853) on 64-bit Windows.
 *
 * Build result: version.dll (32-bit). Drop it next to TopWinEn.exe.
 *
 * How it works
 *   TopWinEn.exe contains a statically linked copy of WinDriver 6.03's
 *   user-mode library. That library talks to the kernel driver only via
 *   CreateFileA("\\\\.\\WINDRVR6") + DeviceIoControl(). This DLL is loaded
 *   by TopWin in place of the system version.dll (it forwards every
 *   version.dll API to the real one), patches TopWin's import table for
 *   CreateFileA / DeviceIoControl / CloseHandle, and answers the WinDriver
 *   IOCTLs itself, performing the USB I/O through Microsoft's WinUSB
 *   (install WinUSB for the programmer with Zadig).
 *
 * Environment variables (optional)
 *   TOPWD_LOG=1     verbose log (every USB transfer) in TopWD.log
 *   TOPWD_SIM=1     simulate a programmer (for testing without hardware)
 *
 * Copyright (c) 2026. MIT licence.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <setupapi.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <stdlib.h>
#include <ctype.h>
#include <objbase.h>
#include "windrvr6_compat.h"

#define TOPWD_VERSION "1.3"

/* ======================================================================
 *  Logging
 * ====================================================================*/
static CRITICAL_SECTION g_logLock;
static FILE *g_log;
static int g_verbose;

static void log_open(void)
{
    char path[MAX_PATH], *p;
    InitializeCriticalSection(&g_logLock);
    g_verbose = GetEnvironmentVariableA("TOPWD_LOG", NULL, 0) > 0;

    GetModuleFileNameA(NULL, path, MAX_PATH);
    p = strrchr(path, '\\');
    if (p) strcpy(p + 1, "TopWD.log"); else strcpy(path, "TopWD.log");
    g_log = fopen(path, "w");
    if (!g_log) {                        /* e.g. Program Files not writable */
        DWORD n = GetTempPathA(MAX_PATH, path);
        if (n && n < MAX_PATH - 16) { strcat(path, "TopWD.log"); g_log = fopen(path, "w"); }
    }
}

static void LOG(const char *fmt, ...)
{
    va_list ap;
    SYSTEMTIME t;
    if (!g_log) return;
    EnterCriticalSection(&g_logLock);
    GetLocalTime(&t);
    fprintf(g_log, "%02d:%02d:%02d.%03d [%5lu] ", t.wHour, t.wMinute, t.wSecond,
            t.wMilliseconds, GetCurrentThreadId());
    va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    va_end(ap);
    fputc('\n', g_log);
    fflush(g_log);
    LeaveCriticalSection(&g_logLock);
}
#define VLOG(...) do { if (g_verbose) LOG(__VA_ARGS__); } while (0)

static void log_hex(const char *pfx, const void *buf, DWORD len)
{
    const UCHAR *b = (const UCHAR *)buf;
    char line[3 * 32 + 1];
    DWORD i, n = len > 256 ? 256 : len;
    if (!g_verbose || !g_log) return;
    for (i = 0; i < n; i += 32) {
        DWORD j, k = 0;
        for (j = i; j < n && j < i + 32; j++) k += sprintf(line + k, "%02x ", b[j]);
        LOG("   %s %04lx: %s", pfx, i, line);
    }
    if (len > n) LOG("   %s ... (%lu bytes total)", pfx, len);
}

/* ======================================================================
 *  version.dll proxy: forward every export to the real system DLL
 * ====================================================================*/
static HMODULE g_realVersion;

static FARPROC real_ver(const char *name)
{
    if (!g_realVersion) {
        char path[MAX_PATH];
        UINT n = GetSystemDirectoryA(path, MAX_PATH);   /* SysWOW64 for 32-bit */
        if (n == 0 || n > MAX_PATH - 14) return NULL;
        strcat(path, "\\version.dll");
        g_realVersion = LoadLibraryA(path);
        if (!g_realVersion) return NULL;
    }
    return GetProcAddress(g_realVersion, name);
}

#define FWD(ret, name, params, args)                                      \
    __declspec(dllexport) ret WINAPI name params {                        \
        typedef ret (WINAPI *fn_t) params;                                \
        static fn_t fn;                                                   \
        if (!fn) fn = (fn_t)real_ver(#name);                              \
        if (!fn) { SetLastError(ERROR_PROC_NOT_FOUND); return (ret)0; }   \
        return fn args;                                                   \
    }

FWD(BOOL,  GetFileVersionInfoA, (LPCSTR f, DWORD h, DWORD l, LPVOID d), (f, h, l, d))
FWD(BOOL,  GetFileVersionInfoW, (LPCWSTR f, DWORD h, DWORD l, LPVOID d), (f, h, l, d))
FWD(BOOL,  GetFileVersionInfoExA, (DWORD fl, LPCSTR f, DWORD h, DWORD l, LPVOID d), (fl, f, h, l, d))
FWD(BOOL,  GetFileVersionInfoExW, (DWORD fl, LPCWSTR f, DWORD h, DWORD l, LPVOID d), (fl, f, h, l, d))
FWD(DWORD, GetFileVersionInfoSizeA, (LPCSTR f, LPDWORD h), (f, h))
FWD(DWORD, GetFileVersionInfoSizeW, (LPCWSTR f, LPDWORD h), (f, h))
FWD(DWORD, GetFileVersionInfoSizeExA, (DWORD fl, LPCSTR f, LPDWORD h), (fl, f, h))
FWD(DWORD, GetFileVersionInfoSizeExW, (DWORD fl, LPCWSTR f, LPDWORD h), (fl, f, h))
FWD(BOOL,  GetFileVersionInfoByHandle, (DWORD fl, HANDLE h, LPVOID *d, LPDWORD l), (fl, h, d, l))
FWD(BOOL,  VerQueryValueA, (LPCVOID b, LPCSTR s, LPVOID *p, PUINT l), (b, s, p, l))
FWD(BOOL,  VerQueryValueW, (LPCVOID b, LPCWSTR s, LPVOID *p, PUINT l), (b, s, p, l))
FWD(DWORD, VerFindFileA, (DWORD f, LPSTR a, LPSTR b, LPSTR c, LPSTR d, PUINT e, LPSTR g, PUINT h), (f, a, b, c, d, e, g, h))
FWD(DWORD, VerFindFileW, (DWORD f, LPWSTR a, LPWSTR b, LPWSTR c, LPWSTR d, PUINT e, LPWSTR g, PUINT h), (f, a, b, c, d, e, g, h))
FWD(DWORD, VerInstallFileA, (DWORD f, LPSTR a, LPSTR b, LPSTR c, LPSTR d, LPSTR e, LPSTR g, PUINT h), (f, a, b, c, d, e, g, h))
FWD(DWORD, VerInstallFileW, (DWORD f, LPWSTR a, LPWSTR b, LPWSTR c, LPWSTR d, LPWSTR e, LPWSTR g, PUINT h), (f, a, b, c, d, e, g, h))
FWD(DWORD, VerLanguageNameA, (DWORD l, LPSTR s, DWORD n), (l, s, n))
FWD(DWORD, VerLanguageNameW, (DWORD l, LPWSTR s, DWORD n), (l, s, n))

/* ======================================================================
 *  WinUSB (loaded dynamically)
 * ====================================================================*/
typedef PVOID WINUSB_INTERFACE_HANDLE;
#pragma pack(push, 1)
typedef struct { UCHAR RequestType, Request; USHORT Value, Index, Length; } WINUSB_SETUP_PACKET;
#pragma pack(pop)
#define PIPE_TRANSFER_TIMEOUT 0x03

static BOOL (WINAPI *pWinUsb_Initialize)(HANDLE, WINUSB_INTERFACE_HANDLE *);
static BOOL (WINAPI *pWinUsb_Free)(WINUSB_INTERFACE_HANDLE);
static BOOL (WINAPI *pWinUsb_GetAssociatedInterface)(WINUSB_INTERFACE_HANDLE, UCHAR, WINUSB_INTERFACE_HANDLE *);
static BOOL (WINAPI *pWinUsb_GetDescriptor)(WINUSB_INTERFACE_HANDLE, UCHAR, UCHAR, USHORT, PUCHAR, ULONG, PULONG);
static BOOL (WINAPI *pWinUsb_SetCurrentAlternateSetting)(WINUSB_INTERFACE_HANDLE, UCHAR);
static BOOL (WINAPI *pWinUsb_GetCurrentAlternateSetting)(WINUSB_INTERFACE_HANDLE, PUCHAR);
static BOOL (WINAPI *pWinUsb_SetPipePolicy)(WINUSB_INTERFACE_HANDLE, UCHAR, ULONG, ULONG, PVOID);
static BOOL (WINAPI *pWinUsb_ReadPipe)(WINUSB_INTERFACE_HANDLE, UCHAR, PUCHAR, ULONG, PULONG, LPOVERLAPPED);
static BOOL (WINAPI *pWinUsb_WritePipe)(WINUSB_INTERFACE_HANDLE, UCHAR, PUCHAR, ULONG, PULONG, LPOVERLAPPED);
static BOOL (WINAPI *pWinUsb_ControlTransfer)(WINUSB_INTERFACE_HANDLE, WINUSB_SETUP_PACKET, PUCHAR, ULONG, PULONG, LPOVERLAPPED);
static BOOL (WINAPI *pWinUsb_ResetPipe)(WINUSB_INTERFACE_HANDLE, UCHAR);
static BOOL (WINAPI *pWinUsb_AbortPipe)(WINUSB_INTERFACE_HANDLE, UCHAR);

static BOOL winusb_load(void)
{
    static int state;               /* 0 untried, 1 ok, -1 failed */
    HMODULE h;
    if (state) return state > 0;
    h = LoadLibraryA("winusb.dll");
    if (!h) { LOG("ERROR: cannot load winusb.dll (%lu)", GetLastError()); state = -1; return FALSE; }
#define GP(n) if (!(*(FARPROC *)&p##n = GetProcAddress(h, #n))) { LOG("ERROR: winusb.dll lacks " #n); state = -1; return FALSE; }
    GP(WinUsb_Initialize) GP(WinUsb_Free) GP(WinUsb_GetAssociatedInterface) GP(WinUsb_GetDescriptor)
    GP(WinUsb_SetCurrentAlternateSetting) GP(WinUsb_GetCurrentAlternateSetting) GP(WinUsb_SetPipePolicy)
    GP(WinUsb_ReadPipe) GP(WinUsb_WritePipe) GP(WinUsb_ControlTransfer) GP(WinUsb_ResetPipe) GP(WinUsb_AbortPipe)
#undef GP
    state = 1;
    return TRUE;
}

/* ======================================================================
 *  Device objects
 * ====================================================================*/
#define MAX_IFACES 8

typedef struct Device {
    struct Device *next;
    DWORD  id;                       /* WinDriver dwUniqueID handed to TopWin */
    char   path[512];                /* device path used for identity */
    USHORT vid, pid;
    BOOL   sim;                      /* simulated device */
    BOOL   gone;                     /* unplugged */
    int    misses;                   /* consecutive scans that did not see it */
    HANDLE hFile;
    WINUSB_INTERFACE_HANDLE hIf[MAX_IFACES];   /* [0] = first interface */
    UCHAR  ifNum[MAX_IFACES];        /* bInterfaceNumber for each hIf[] */
    int    nIf;
    WDU_DEVICE_DESCRIPTOR devDesc;
    UCHAR *cfg;                      /* full configuration descriptor */
    DWORD  cfgLen;
    UCHAR  curAlt[MAX_IFACES];
    ULONG  timeout[256];             /* current PIPE_TRANSFER_TIMEOUT per endpoint, +1 (0 = unknown) */
    CRITICAL_SECTION pipeLock[32];   /* serialises "set timeout + transfer" per endpoint */
} Device;

static CRITICAL_SECTION g_lock;       /* protects the lists below */
static CRITICAL_SECTION g_scanLock;   /* one bus scan at a time */
static Device *g_devices;
static DWORD g_nextDevId = 0x1001;

static Device *dev_find(DWORD id)
{
    Device *d;
    EnterCriticalSection(&g_lock);
    for (d = g_devices; d; d = d->next) if (d->id == id) break;
    LeaveCriticalSection(&g_lock);
    return d;
}

/* ---- parse configuration descriptor ---- */
typedef struct { const UCHAR *p; DWORD n; } Span;

/* interface index (into hIf[]) that owns endpoint 'ep' in the current alt settings */
static int iface_for_ep(Device *d, UCHAR ep)
{
    DWORD i = 0;
    int curIf = -1, curAltOk = 0;
    if ((ep & 0x7f) == 0) return 0;
    while (d->cfg && i + 2 <= d->cfgLen && d->cfg[i] >= 2) {
        const UCHAR *b = d->cfg + i;
        if (b[1] == 4 && b[0] >= 9) {
            int k; curIf = -1;
            for (k = 0; k < d->nIf; k++) if (d->ifNum[k] == b[2]) curIf = k;
            curAltOk = curIf >= 0 && d->curAlt[curIf] == b[3];
        } else if (b[1] == 5 && b[0] >= 7 && curAltOk && b[2] == ep) {
            return curIf;
        }
        i += b[0];
    }
    return 0;
}

/* Build the WinDriver WDU_DEVICE tree. buf may be NULL (size query). */
static DWORD build_device_info(Device *d, UCHAR *buf)
{
    DWORD len = 0, i;
    WDU_DEVICE *udi = (WDU_DEVICE *)buf;
    WDU_CONFIGURATION *cfg;
    WDU_INTERFACE *ifaces;
    int nIfaces = 0, nAlts = 0, nEps = 0;
    const WDU_CONFIGURATION_DESCRIPTOR *cd = (const WDU_CONFIGURATION_DESCRIPTOR *)d->cfg;

    /* pass 1: count */
    for (i = 0; i + 2 <= d->cfgLen && d->cfg[i] >= 2; i += d->cfg[i]) {
        if (d->cfg[i + 1] == 4) { nAlts++; if (d->cfg[i + 3] == 0) nIfaces++; }
        if (d->cfg[i + 1] == 5) nEps++;
    }
    if (nIfaces > WD_USB_MAX_INTERFACES) nIfaces = WD_USB_MAX_INTERFACES;

    len = sizeof(WDU_DEVICE) + sizeof(WDU_CONFIGURATION) + nIfaces * sizeof(WDU_INTERFACE)
        + nAlts * sizeof(WDU_ALTERNATE_SETTING)
        + nEps * (sizeof(WDU_ENDPOINT_DESCRIPTOR) + sizeof(WDU_PIPE_INFO)) + 16;
    if (!buf) return len;

    memset(buf, 0, len);
    udi->Descriptor = d->devDesc;
    udi->Pipe0.dwNumber = 0;
    udi->Pipe0.dwMaximumPacketSize = d->devDesc.bMaxPacketSize0;
    udi->Pipe0.type = 0;
    udi->Pipe0.direction = 3;

    cfg = (WDU_CONFIGURATION *)(buf + sizeof(WDU_DEVICE));
    ifaces = (WDU_INTERFACE *)(cfg + 1);
    udi->pConfigs = cfg;
    udi->pActiveConfig = cfg;
    memcpy(&cfg->Descriptor, cd, sizeof(cfg->Descriptor));
    cfg->dwNumInterfaces = nIfaces;
    cfg->pInterfaces = ifaces;

    {
        UCHAR *p = (UCHAR *)(ifaces + nIfaces);
        int ifIdx = -1;
        WDU_ALTERNATE_SETTING *alt = NULL;
        for (i = 0; i + 2 <= d->cfgLen && d->cfg[i] >= 2; i += d->cfg[i]) {
            const UCHAR *b = d->cfg + i;
            if (b[1] == 4 && b[0] >= 9) {
                int k;
                if (b[3] == 0) ifIdx++;
                if (ifIdx < 0 || ifIdx >= nIfaces) { alt = NULL; continue; }
                alt = (WDU_ALTERNATE_SETTING *)p;
                p += sizeof(*alt);
                memcpy(&alt->Descriptor, b, 9);
                alt->pEndpointDescriptors = NULL;
                alt->pPipes = NULL;
                if (!ifaces[ifIdx].pAlternateSettings) ifaces[ifIdx].pAlternateSettings = alt;
                ifaces[ifIdx].dwNumAltSettings++;
                /* active alt setting */
                for (k = 0; k < d->nIf; k++)
                    if (d->ifNum[k] == b[2] && d->curAlt[k] == b[3]) ifaces[ifIdx].pActiveAltSetting = alt;
                if (!ifaces[ifIdx].pActiveAltSetting && b[3] == 0) ifaces[ifIdx].pActiveAltSetting = alt;
                udi->pActiveInterface[ifIdx] = &ifaces[ifIdx];
                /* endpoints of this alt setting follow; lay out descriptors then pipes */
                {
                    DWORD j = i + b[0];
                    int ne = 0, e;
                    WDU_ENDPOINT_DESCRIPTOR *ed;
                    WDU_PIPE_INFO *pi;
                    for (; j + 2 <= d->cfgLen && d->cfg[j] >= 2 && d->cfg[j + 1] != 4; j += d->cfg[j])
                        if (d->cfg[j + 1] == 5) ne++;
                    ed = (WDU_ENDPOINT_DESCRIPTOR *)p;
                    p += ne * sizeof(*ed);
                    pi = (WDU_PIPE_INFO *)p;
                    p += ne * sizeof(*pi);
                    alt->pEndpointDescriptors = ne ? ed : NULL;
                    alt->pPipes = ne ? pi : NULL;
                    for (j = i + b[0], e = 0; j + 2 <= d->cfgLen && d->cfg[j] >= 2 && d->cfg[j + 1] != 4; j += d->cfg[j]) {
                        const UCHAR *x = d->cfg + j;
                        USHORT mps;
                        if (x[1] != 5 || x[0] < 7) continue;
                        mps = (USHORT)(x[4] | (x[5] << 8));
                        ed[e].bLength = x[0]; ed[e].bDescriptorType = x[1];
                        ed[e].bEndpointAddress = x[2]; ed[e].bmAttributes = x[3];
                        ed[e].wMaxPacketSize = mps; ed[e].bInterval = x[6];
                        pi[e].dwNumber = x[2];
                        pi[e].dwMaximumPacketSize = (mps & 0x7ff) * (1 + ((mps >> 11) & 3));
                        pi[e].type = x[3] & 3;
                        pi[e].direction = pi[e].type == 0 ? 3 : ((x[2] & 0x80) ? 1 : 2);
                        pi[e].dwInterval = x[6];
                        e++;
                    }
                }
            }
        }
    }
    return len;
}

/* ---- simulated device (TOPWD_SIM=1) ---- */
static const UCHAR sim_cfg[] = {
    9, 2, 32, 0, 1, 1, 0, 0x80, 50,           /* config, 1 interface */
    9, 4, 0, 0, 2, 0xff, 0, 0, 0,             /* interface 0, 2 endpoints */
    7, 5, 0x02, 2, 64, 0, 0,                  /* EP2 OUT bulk 64 */
    7, 5, 0x82, 2, 64, 0, 0,                  /* EP2 IN  bulk 64 */
};

static Device *dev_new(const char *path, USHORT vid, USHORT pid)
{
    int k;
    Device *d = (Device *)calloc(1, sizeof(Device));
    if (!d) return NULL;
    lstrcpynA(d->path, path, sizeof(d->path));
    d->vid = vid; d->pid = pid;
    d->hFile = INVALID_HANDLE_VALUE;
    for (k = 0; k < 32; k++) InitializeCriticalSection(&d->pipeLock[k]);
    return d;
}

static void dev_close_handles(Device *d)
{
    int k;
    for (k = d->nIf - 1; k >= 0; k--) if (d->hIf[k]) { pWinUsb_Free(d->hIf[k]); d->hIf[k] = NULL; }
    if (d->hFile != INVALID_HANDLE_VALUE) { CloseHandle(d->hFile); d->hFile = INVALID_HANDLE_VALUE; }
}

/* open with WinUSB and read descriptors */
static BOOL dev_open_winusb(Device *d, const char *openPath)
{
    ULONG got = 0;
    UCHAR hdr[9];
    if (!winusb_load()) return FALSE;
    d->hFile = CreateFileA(openPath, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OVERLAPPED, NULL);
    if (d->hFile == INVALID_HANDLE_VALUE) {
        LOG("  open %s failed (err %lu)", openPath, GetLastError());
        return FALSE;
    }
    if (!pWinUsb_Initialize(d->hFile, &d->hIf[0])) {
        LOG("  WinUsb_Initialize failed (err %lu) - is WinUSB installed for this device (Zadig)?", GetLastError());
        CloseHandle(d->hFile); d->hFile = INVALID_HANDLE_VALUE;
        return FALSE;
    }
    d->nIf = 1;
    if (!pWinUsb_GetDescriptor(d->hIf[0], 1, 0, 0, (PUCHAR)&d->devDesc, sizeof(d->devDesc), &got) || got < 18) {
        LOG("  cannot read device descriptor (err %lu)", GetLastError());
        dev_close_handles(d); return FALSE;
    }
    if (!pWinUsb_GetDescriptor(d->hIf[0], 2, 0, 0, hdr, 9, &got) || got < 9) {
        LOG("  cannot read configuration descriptor (err %lu)", GetLastError());
        dev_close_handles(d); return FALSE;
    }
    d->cfgLen = hdr[2] | (hdr[3] << 8);
    d->cfg = (UCHAR *)malloc(d->cfgLen);
    if (!d->cfg || !pWinUsb_GetDescriptor(d->hIf[0], 2, 0, 0, d->cfg, d->cfgLen, &got)) {
        LOG("  cannot read full configuration descriptor (err %lu)", GetLastError());
        dev_close_handles(d); return FALSE;
    }
    d->cfgLen = got;
    /* interface numbers: hIf[0] is the first interface; associated ones follow */
    {
        DWORD i; int first = 1;
        for (i = 0; i + 2 <= d->cfgLen && d->cfg[i] >= 2; i += d->cfg[i]) {
            if (d->cfg[i + 1] == 4 && d->cfg[i + 3] == 0) {
                if (first) { d->ifNum[0] = d->cfg[i + 2]; first = 0; }
                else if (d->nIf < MAX_IFACES) {
                    WINUSB_INTERFACE_HANDLE h;
                    if (pWinUsb_GetAssociatedInterface(d->hIf[0], (UCHAR)(d->nIf - 1), &h)) {
                        d->hIf[d->nIf] = h; d->ifNum[d->nIf] = d->cfg[i + 2]; d->nIf++;
                    }
                }
            }
        }
    }
    return TRUE;
}

static BOOL dev_open_sim(Device *d)
{
    d->sim = TRUE;
    memset(&d->devDesc, 0, sizeof(d->devDesc));
    d->devDesc.bLength = 18; d->devDesc.bDescriptorType = 1; d->devDesc.bcdUSB = 0x0110;
    d->devDesc.bMaxPacketSize0 = 64; d->devDesc.idVendor = d->vid; d->devDesc.idProduct = d->pid;
    d->devDesc.bNumConfigurations = 1;
    d->cfgLen = sizeof(sim_cfg);
    d->cfg = (UCHAR *)malloc(d->cfgLen);
    memcpy(d->cfg, sim_cfg, d->cfgLen);
    d->nIf = 1;
    return TRUE;
}

/* ---- enumeration ---- */
static const GUID GUID_USB_DEVICE = { 0xA5DCBF10, 0x6530, 0x11D2, { 0x90, 0x1F, 0x00, 0xC0, 0x4F, 0xB9, 0x51, 0xED } };

typedef struct { char path[512]; char openPath[512]; USHORT vid, pid; } Found;

static int parse_hex4(const char *s) { char t[5]; memcpy(t, s, 4); t[4] = 0; return (int)strtol(t, NULL, 16); }

static BOOL vidpid_from_path(const char *path, USHORT *vid, USHORT *pid)
{
    char low[512]; const char *v, *p; int i;
    for (i = 0; path[i] && i < 511; i++) low[i] = (char)tolower((unsigned char)path[i]);
    low[i] = 0;
    v = strstr(low, "vid_"); p = strstr(low, "pid_");
    if (!v || !p) return FALSE;
    *vid = (USHORT)parse_hex4(v + 4); *pid = (USHORT)parse_hex4(p + 4);
    return TRUE;
}

/* Zadig registers a custom DeviceInterfaceGUID; prefer that interface path when present */
static BOOL interface_path_from_registry(HDEVINFO di, SP_DEVINFO_DATA *dd, char *out, DWORD outLen)
{
    HKEY k;
    char buf[1024], inst[512];
    DWORD type, n = sizeof(buf) - 2;
    GUID g;
    WCHAR wg[64];
    BOOL ok = FALSE;
    memset(buf, 0, sizeof(buf));
    k = SetupDiOpenDevRegKey(di, dd, DICS_FLAG_GLOBAL, 0, DIREG_DEV, KEY_READ);
    if (k == INVALID_HANDLE_VALUE) return FALSE;
    if (RegQueryValueExA(k, "DeviceInterfaceGUIDs", NULL, &type, (LPBYTE)buf, &n) != ERROR_SUCCESS) {
        n = sizeof(buf) - 2;
        if (RegQueryValueExA(k, "DeviceInterfaceGUID", NULL, &type, (LPBYTE)buf, &n) != ERROR_SUCCESS) buf[0] = 0;
    }
    RegCloseKey(k);
    if (!buf[0]) return FALSE;
    MultiByteToWideChar(CP_ACP, 0, buf, -1, wg, 64);
    if (FAILED(CLSIDFromString(wg, &g))) return FALSE;
    if (!SetupDiGetDeviceInstanceIdA(di, dd, inst, sizeof(inst), NULL)) return FALSE;
    {
        HDEVINFO d2 = SetupDiGetClassDevsA(&g, inst, NULL, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
        SP_DEVICE_INTERFACE_DATA ifd;
        if (d2 == INVALID_HANDLE_VALUE) return FALSE;
        ifd.cbSize = sizeof(ifd);
        if (SetupDiEnumDeviceInterfaces(d2, NULL, &g, 0, &ifd)) {
            DWORD need = 0;
            SetupDiGetDeviceInterfaceDetailA(d2, &ifd, NULL, 0, &need, NULL);
            if (need) {
                SP_DEVICE_INTERFACE_DETAIL_DATA_A *det = (SP_DEVICE_INTERFACE_DETAIL_DATA_A *)malloc(need);
                det->cbSize = sizeof(*det);
                if (SetupDiGetDeviceInterfaceDetailA(d2, &ifd, det, need, NULL, NULL)) {
                    lstrcpynA(out, det->DevicePath, outLen);
                    ok = TRUE;
                }
                free(det);
            }
        }
        SetupDiDestroyDeviceInfoList(d2);
    }
    return ok;
}

/* ---- transfer statistics / history (always on, cheap) ---- */
static volatile LONG g_lastIoTick;          /* GetTickCount() of last USB transfer start/end */
static volatile LONG g_ioActive;            /* transfers currently in progress */
typedef struct { DWORD tick, thread, ep, req, got, ms, status, timeout; } Hist;
#define HIST_N 48
static Hist g_hist[HIST_N];
static LONG g_histPos;
static LONG g_nXfer, g_nFail, g_nSlow;
static DWORD g_maxMs;

static void hist_add(DWORD ep, DWORD req, DWORD got, DWORD ms, DWORD status, DWORD timeout)
{
    LONG i = InterlockedIncrement(&g_histPos) % HIST_N;
    Hist *h = &g_hist[i];
    h->tick = GetTickCount(); h->thread = GetCurrentThreadId(); h->ep = ep; h->req = req;
    h->got = got; h->ms = ms; h->status = status; h->timeout = timeout;
    InterlockedIncrement(&g_nXfer);
    if (ms > g_maxMs) g_maxMs = ms;
}

static void hist_dump(const char *why)
{
    static LONG dumps;
    LONG pos = g_histPos, k;
    if (InterlockedIncrement(&dumps) > 10) return;      /* don't flood the log */
    LOG("---- last %d USB transfers before %s (oldest first) ----", HIST_N, why);
    for (k = HIST_N - 1; k >= 0; k--) {
        Hist *h = &g_hist[((pos - k) % HIST_N + HIST_N) % HIST_N];
        if (!h->tick) continue;
        LOG("   t=%lu thr=%lu %s ep%02lx req=%lu got=%lu %lums timeout=%lu status=0x%lx",
            h->tick, h->thread, (h->ep & 0x80) ? "IN " : "OUT", h->ep, h->req, h->got, h->ms, h->timeout, h->status);
    }
    LOG("---- totals: %ld transfers, %ld failed, %ld slow (>250ms), max %lums ----", g_nXfer, g_nFail, g_nSlow, g_maxMs);
}

static BOOL wanted_vidpid(USHORT vid, USHORT pid);

/* ---- transfer pacing ----
 * On the original XP setup (USB 1.1 UHCI/OHCI host + windrvr6) every bulk
 * transfer took at least one 1 ms USB frame. TopWin's command stream may
 * rely on that implicit delay (e.g. relay / programming-voltage settling
 * before it reads back pin state). An xHCI controller on Windows 11 can
 * issue back-to-back transfers within the same millisecond, so by default
 * successive transfers are spaced at least TOPWD_PACE_US microseconds apart
 * (default 1000, 0 = off). */
static LONG g_paceUs = 1000;
static LONG g_chunk = 4096;     /* TOPWD_CHUNK: max bytes per WinUSB call, 0 = no split */
static LARGE_INTEGER g_qpf;
static LONGLONG g_lastStart;
static CRITICAL_SECTION g_paceLock;

static void pace_init(void)
{
    char v[32];
    InitializeCriticalSection(&g_paceLock);
    QueryPerformanceFrequency(&g_qpf);
    if (GetEnvironmentVariableA("TOPWD_PACE_US", v, sizeof(v)) > 0) g_paceUs = atol(v);
    if (g_paceUs < 0) g_paceUs = 0;
    if (g_paceUs > 100000) g_paceUs = 100000;
    if (GetEnvironmentVariableA("TOPWD_CHUNK", v, sizeof(v)) > 0) g_chunk = atol(v);
    if (g_chunk < 0) g_chunk = 0;
    if (g_chunk) g_chunk = (g_chunk + 63) & ~63;     /* whole packets */
}

static void pace_wait(void)
{
    LARGE_INTEGER now;
    LONGLONG need;
    if (!g_paceUs || !g_qpf.QuadPart) return;
    need = g_qpf.QuadPart * g_paceUs / 1000000;
    EnterCriticalSection(&g_paceLock);
    for (;;) {
        LONGLONG left;
        QueryPerformanceCounter(&now);
        left = g_lastStart + need - now.QuadPart;
        if (g_lastStart == 0 || left <= 0) break;
        if (left > g_qpf.QuadPart / 500) Sleep(1);      /* > 2 ms to go */
        else SwitchToThread();
    }
    g_lastStart = now.QuadPart;
    LeaveCriticalSection(&g_paceLock);
}

static int enumerate_usb(Found *out, int max)
{
    int n = 0;
    DWORD idx;
    HDEVINFO di = SetupDiGetClassDevsA(&GUID_USB_DEVICE, NULL, NULL, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
    if (di == INVALID_HANDLE_VALUE) return 0;
    for (idx = 0; n < max; idx++) {
        SP_DEVICE_INTERFACE_DATA ifd;
        SP_DEVINFO_DATA dd;
        DWORD need = 0;
        SP_DEVICE_INTERFACE_DETAIL_DATA_A *det;
        ifd.cbSize = sizeof(ifd);
        if (!SetupDiEnumDeviceInterfaces(di, NULL, &GUID_USB_DEVICE, idx, &ifd)) break;
        SetupDiGetDeviceInterfaceDetailA(di, &ifd, NULL, 0, &need, NULL);
        if (!need) continue;
        det = (SP_DEVICE_INTERFACE_DETAIL_DATA_A *)malloc(need);
        det->cbSize = sizeof(*det);
        dd.cbSize = sizeof(dd);
        if (SetupDiGetDeviceInterfaceDetailA(di, &ifd, det, need, NULL, &dd) &&
            vidpid_from_path(det->DevicePath, &out[n].vid, &out[n].pid) &&
            wanted_vidpid(out[n].vid, out[n].pid)) {
            lstrcpynA(out[n].path, det->DevicePath, sizeof(out[n].path));
            if (!interface_path_from_registry(di, &dd, out[n].openPath, sizeof(out[n].openPath)))
                lstrcpynA(out[n].openPath, det->DevicePath, sizeof(out[n].openPath));
            n++;
        }
        free(det);
    }
    SetupDiDestroyDeviceInfoList(di);
    return n;
}

/* ======================================================================
 *  Event registrations (hot-plug notification emulation)
 * ====================================================================*/
#define MAX_QUEUE 32
typedef struct Reg {
    struct Reg *next;
    DWORD handle;
    DWORD dwOptions;
    DWORD dwActionMask;
    DWORD nMatch;
    WDU_MATCH_TABLE match[8];
    HANDLE hSem;                     /* one count per queued event */
    HANDLE hStop;                    /* manual reset: INT_DISABLE */
    BOOL enabled;
    struct { DWORD action, devId; USHORT vid, pid; } q[MAX_QUEUE];
    int qHead, qCount;
    DWORD eventId;
} Reg;

static Reg *g_regs;
static DWORD g_nextRegHandle = 0x5101;
static HANDLE g_hotplugThread, g_hotplugStop;
static BOOL g_sim;

static BOOL reg_matches(Reg *r, USHORT vid, USHORT pid)
{
    DWORD i;
    for (i = 0; i < r->nMatch; i++) {
        if ((r->match[i].VendorId == 0 || r->match[i].VendorId == vid) &&
            (r->match[i].ProductId == 0 || r->match[i].ProductId == pid))
            return TRUE;
    }
    return FALSE;
}

static BOOL wanted_vidpid(USHORT vid, USHORT pid)
{
    Reg *r; BOOL w = FALSE;
    EnterCriticalSection(&g_lock);
    for (r = g_regs; r; r = r->next) if (reg_matches(r, vid, pid)) w = TRUE;
    LeaveCriticalSection(&g_lock);
    return w;
}

/* caller holds g_lock */
static void reg_queue(Reg *r, DWORD action, Device *d)
{
    int slot;
    if (!(r->dwActionMask & action) && r->dwActionMask) return;
    if (r->qCount >= MAX_QUEUE) { LOG("WARN: event queue full"); return; }
    slot = (r->qHead + r->qCount) % MAX_QUEUE;
    r->q[slot].action = action; r->q[slot].devId = d->id;
    r->q[slot].vid = d->vid; r->q[slot].pid = d->pid;
    r->qCount++;
    ReleaseSemaphore(r->hSem, 1, NULL);
    LOG("queued %s event for device 0x%lx (%04x:%04x) on registration 0x%lx",
        action == WD_INSERT ? "INSERT" : "REMOVE", d->id, d->vid, d->pid, r->handle);
}

/* Scan the bus; open newly found devices, flag vanished ones. */
static void rescan_locked(void);
static void rescan(void)
{
    EnterCriticalSection(&g_scanLock);
    rescan_locked();
    LeaveCriticalSection(&g_scanLock);
}

static void rescan_locked(void)
{
    static Found found[32];
    int n, i;
    Device *d;
    Reg *r;

    if (g_sim) {
        /* one simulated device matching the first match table */
        EnterCriticalSection(&g_lock);
        if (!g_devices && g_regs && g_regs->nMatch) {
            Device *nd = dev_new("SIMULATED", g_regs->match[0].VendorId, g_regs->match[0].ProductId);
            if (nd && dev_open_sim(nd)) {
                nd->id = g_nextDevId++;
                nd->next = g_devices; g_devices = nd;
                LOG("simulated device 0x%lx %04x:%04x created", nd->id, nd->vid, nd->pid);
                for (r = g_regs; r; r = r->next) if (reg_matches(r, nd->vid, nd->pid)) reg_queue(r, WD_INSERT, nd);
            }
        }
        LeaveCriticalSection(&g_lock);
        return;
    }

    n = enumerate_usb(found, 32);

    /* removals */
    EnterCriticalSection(&g_lock);
    for (d = g_devices; d; d = d->next) {
        BOOL present = FALSE;
        if (d->gone) continue;
        for (i = 0; i < n; i++) if (!lstrcmpiA(found[i].path, d->path)) present = TRUE;
        if (present) { d->misses = 0; continue; }
        /* the device list can be momentarily incomplete; require 3 misses in a row */
        if (++d->misses < 3) { LOG("device 0x%lx not seen in scan (%d/3)", d->id, d->misses); continue; }
        {
            d->gone = TRUE;
            LOG("device 0x%lx removed", d->id);
            hist_dump("device removal");
            for (r = g_regs; r; r = r->next) if (reg_matches(r, d->vid, d->pid)) reg_queue(r, WD_REMOVE, d);
        }
    }
    LeaveCriticalSection(&g_lock);

    /* arrivals */
    for (i = 0; i < n; i++) {
        BOOL wanted = FALSE, known = FALSE;
        Device *nd;
        EnterCriticalSection(&g_lock);
        for (r = g_regs; r; r = r->next) if (reg_matches(r, found[i].vid, found[i].pid)) wanted = TRUE;
        for (d = g_devices; d; d = d->next) if (!d->gone && !lstrcmpiA(found[i].path, d->path)) known = TRUE;
        LeaveCriticalSection(&g_lock);
        if (!wanted || known) continue;

        nd = dev_new(found[i].path, found[i].vid, found[i].pid);
        if (!nd) continue;
        LOG("found %04x:%04x at %s", nd->vid, nd->pid, found[i].path);
        if (strcmp(found[i].openPath, found[i].path)) LOG("  WinUSB interface path %s", found[i].openPath);
        if (!dev_open_winusb(nd, found[i].openPath) &&
            !(strcmp(found[i].openPath, found[i].path) && dev_open_winusb(nd, found[i].path))) {
            /* keep a tombstone so we don't retry every second; retry if replugged */
            static char lastFail[512];
            if (strcmp(lastFail, found[i].path)) {
                lstrcpynA(lastFail, found[i].path, sizeof(lastFail));
                LOG("  -> could not open the programmer. Install the WinUSB driver for it with Zadig.");
            }
            free(nd->cfg); free(nd);
            continue;
        }
        EnterCriticalSection(&g_lock);
        nd->id = g_nextDevId++;
        nd->next = g_devices; g_devices = nd;
        LOG("  opened as device 0x%lx (bcdUSB %04x, %d interface(s), config %lu bytes)",
            nd->id, nd->devDesc.bcdUSB, nd->nIf, nd->cfgLen);
        for (r = g_regs; r; r = r->next) if (reg_matches(r, nd->vid, nd->pid)) reg_queue(r, WD_INSERT, nd);
        LeaveCriticalSection(&g_lock);
    }
}

static DWORD WINAPI hotplug_thread(LPVOID unused)
{
    (void)unused;
    while (WaitForSingleObject(g_hotplugStop, 1000) == WAIT_TIMEOUT) {
        BOOL any;
        EnterCriticalSection(&g_lock);
        any = g_regs != NULL;
        LeaveCriticalSection(&g_lock);
        /* never touch the bus while TopWin is talking to the programmer */
        if (any && !g_ioActive && GetTickCount() - (DWORD)g_lastIoTick > 3000) rescan();
    }
    return 0;
}

static Reg *reg_find(DWORD h)
{
    Reg *r;
    EnterCriticalSection(&g_lock);
    for (r = g_regs; r; r = r->next) if (r->handle == h) break;
    LeaveCriticalSection(&g_lock);
    return r;
}

/* ======================================================================
 *  WinDriver IOCTL emulation
 * ====================================================================*/
static DWORD map_winerr(DWORD e)
{
    switch (e) {
    case ERROR_SEM_TIMEOUT: return WD_TIME_OUT_EXPIRED;
    case ERROR_OPERATION_ABORTED: return WD_IRP_CANCELED;
    case ERROR_GEN_FAILURE: return WD_USBD_STATUS_STALL_PID;
    case ERROR_BAD_COMMAND: case ERROR_DEVICE_NOT_CONNECTED: case ERROR_FILE_NOT_FOUND:
    case ERROR_INVALID_HANDLE: return WD_DEVICE_NOT_FOUND;
    default: return WD_SYSTEM_INTERNAL_ERROR;
    }
}

static DWORD do_transfer(WDU_TRANSFER *t)
{
    Device *d = dev_find(t->dwUniqueID);
    ULONG got = 0;
    BOOL ok;
    UCHAR ep;
    int ifx;
    WINUSB_INTERFACE_HANDLE h;

    t->dwBytesTransferred = 0;
    if (!d) return WD_WRONG_UNIQUE_ID;
    if (d->gone) return WD_DEVICE_NOT_FOUND;

    if (t->dwPipeNum == 0) {                                   /* control pipe */
        WINUSB_SETUP_PACKET sp;
        memcpy(&sp, t->SetupPacket, 8);
        VLOG("CTRL %02x %02x val=%04x idx=%04x len=%u", sp.RequestType, sp.Request, sp.Value, sp.Index, sp.Length);
        if (!(sp.RequestType & 0x80)) log_hex("ctrl->", t->pBuffer, sp.Length);
        if (d->sim) { t->dwBytesTransferred = sp.Length; if (sp.RequestType & 0x80) memset(t->pBuffer, 0, sp.Length); return 0; }
        DWORD t0, ms;
        pace_wait();
        t0 = GetTickCount();
        InterlockedIncrement(&g_ioActive);
        EnterCriticalSection(&d->pipeLock[0]);
        if (d->timeout[0] != t->dwTimeout + 1) {
            ULONG to = t->dwTimeout;
            pWinUsb_SetPipePolicy(d->hIf[0], 0, PIPE_TRANSFER_TIMEOUT, sizeof(to), &to);
            d->timeout[0] = t->dwTimeout + 1;
        }
        ok = pWinUsb_ControlTransfer(d->hIf[0], sp, (PUCHAR)t->pBuffer,
                                     sp.Length < t->dwBufferSize ? sp.Length : t->dwBufferSize, &got, NULL);
        { DWORD le = ok ? 0 : GetLastError();
        LeaveCriticalSection(&d->pipeLock[0]);
        SetLastError(le); }
        ms = GetTickCount() - t0;
        g_lastIoTick = (LONG)GetTickCount();
        InterlockedDecrement(&g_ioActive);
        hist_add(sp.RequestType & 0x80, sp.Length, got, ms, ok ? 0 : GetLastError(), t->dwTimeout);
        if (!ok) {
            DWORD e = GetLastError();
            InterlockedIncrement(&g_nFail);
            LOG("control transfer failed after %lums, err %lu", ms, e);
            hist_dump("failure");
            return map_winerr(e);
        }
        t->dwBytesTransferred = got;
        if (sp.RequestType & 0x80) log_hex("ctrl<-", t->pBuffer, got);
        return 0;
    }

    ep = (UCHAR)((t->dwPipeNum & 0x0f) | (t->fRead ? 0x80 : 0x00));
    if (!t->fRead) { VLOG("OUT ep%02x %lu bytes (timeout %lu)", ep, t->dwBufferSize, t->dwTimeout); log_hex("->", t->pBuffer, t->dwBufferSize); }
    else VLOG("IN  ep%02x up to %lu bytes (timeout %lu)", ep, t->dwBufferSize, t->dwTimeout);

    if (d->sim) {
        t->dwBytesTransferred = t->dwBufferSize;
        if (t->fRead) memset(t->pBuffer, 0, t->dwBufferSize);
        return 0;
    }

    ifx = iface_for_ep(d, ep);
    h = d->hIf[ifx];
    {
        DWORD t0, ms, err;
        CRITICAL_SECTION *cs = &d->pipeLock[(ep & 0x0f) | ((ep & 0x80) ? 16 : 0)];
        pace_wait();
        InterlockedIncrement(&g_ioActive);
        EnterCriticalSection(cs);
        t0 = GetTickCount();
        if (d->timeout[ep] != t->dwTimeout + 1) {
            ULONG to = t->dwTimeout;
            pWinUsb_SetPipePolicy(h, ep, PIPE_TRANSFER_TIMEOUT, sizeof(to), &to);
            d->timeout[ep] = t->dwTimeout + 1;
        }
        /* WinDriver on XP split large transfers into USBD-sized pieces
           (4 KB) and the timeout applied to each piece. TopWin relies on
           that: it writes ~10 KB blocks with a 1 s timeout while the
           programmer only accepts data as fast as it burns the chip. */
        ok = TRUE;
        while (got < t->dwBufferSize) {
            ULONG part = 0, want = t->dwBufferSize - got;
            if (g_chunk && want > (ULONG)g_chunk) want = g_chunk;
            if (t->fRead) ok = pWinUsb_ReadPipe(h, ep, (PUCHAR)t->pBuffer + got, want, &part, NULL);
            else          ok = pWinUsb_WritePipe(h, ep, (PUCHAR)t->pBuffer + got, want, &part, NULL);
            got += part;
            if (!ok) break;
            if (t->fRead && part < want) break;      /* short packet ends a read */
            if (!t->fRead && part == 0) break;
        }
        err = ok ? 0 : GetLastError();
        ms = GetTickCount() - t0;
        LeaveCriticalSection(cs);
        g_lastIoTick = (LONG)GetTickCount();
        InterlockedDecrement(&g_ioActive);
        hist_add(ep, t->dwBufferSize, got, ms, err, t->dwTimeout);
        if (!ok || (ms > 250 && t->dwBufferSize <= 4096)) {
            InterlockedIncrement(&g_nSlow);
            LOG("slow %s ep%02x: %lums for %lu/%lu bytes (timeout %lu)%s", t->fRead ? "read" : "write",
                ep, ms, got, t->dwBufferSize, t->dwTimeout, ok ? "" : " - FAILED");
        }
        SetLastError(err);
    }
    t->dwBytesTransferred = got;
    if (!ok) {
        DWORD e = GetLastError();
        InterlockedIncrement(&g_nFail);
        LOG("%s ep%02x failed after %lu of %lu bytes, err %lu (%s)", t->fRead ? "read" : "write", ep, got,
            t->dwBufferSize, e, e == ERROR_SEM_TIMEOUT ? "timeout" : e == ERROR_GEN_FAILURE ? "stall/device error" : "see Win32 error list");
        hist_dump("failure");
        return map_winerr(e);
    }
    if (t->fRead) { VLOG("IN  ep%02x got %lu bytes", ep, got); log_hex("<-", t->pBuffer, got); }
    return 0;
}

static DWORD wd_ioctl(DWORD code, void *in, DWORD inLen)
{
    DWORD fn = WD_FUNC(code);

    switch (fn) {
    case FN_VERSION: {
        WD_VERSION *v = (WD_VERSION *)in;
        if (inLen < sizeof(*v)) return WD_INVALID_PARAMETER;
        v->dwVer = WD_VER_603;
        lstrcpynA(v->cVer, "WinDriver V6.03 (TopWD user-mode emulation " TOPWD_VERSION ")", sizeof(v->cVer));
        VLOG("VERSION -> 603");
        return 0;
    }
    case FN_LICENSE: {
        WD_LICENSE *l = (WD_LICENSE *)in;
        if (inLen >= sizeof(*l)) { l->dwLicense = 0xffffffff; l->dwLicense2 = 0xffffffff; }
        VLOG("LICENSE");
        return 0;
    }
    case FN_DEBUG_ADD:
        if (inLen >= 9) VLOG("WD debug: %.255s", (char *)in + 8);
        return 0;

    case FN_EVENT_REGISTER_OLD: {
        WD_EVENT *e = (WD_EVENT *)in;
        Reg *r;
        DWORD i;
        if (inLen < sizeof(WD_EVENT)) return WD_INVALID_PARAMETER;
        r = (Reg *)calloc(1, sizeof(Reg));
        if (!r) return WD_INSUFFICIENT_RESOURCES;
        r->dwOptions = e->dwOptions;
        r->dwActionMask = e->dwAction;
        r->nMatch = e->dwNumMatchTables > 8 ? 8 : e->dwNumMatchTables;
        if (r->nMatch * sizeof(WDU_MATCH_TABLE) + offsetof(WD_EVENT, matchTables) > inLen + 2)
            r->nMatch = (inLen - offsetof(WD_EVENT, matchTables)) / sizeof(WDU_MATCH_TABLE);
        for (i = 0; i < r->nMatch; i++) r->match[i] = e->matchTables[i];
        r->hSem = CreateSemaphoreA(NULL, 0, MAX_QUEUE, NULL);
        r->hStop = CreateEventA(NULL, TRUE, FALSE, NULL);
        EnterCriticalSection(&g_lock);
        r->handle = g_nextRegHandle++;
        r->next = g_regs; g_regs = r;
        LeaveCriticalSection(&g_lock);
        e->handle = r->handle;
        LOG("EVENT_REGISTER handle 0x%lx: action mask 0x%lx options 0x%lx, %lu match table(s), first %04x:%04x",
            r->handle, r->dwActionMask, r->dwOptions, r->nMatch,
            r->nMatch ? r->match[0].VendorId : 0, r->nMatch ? r->match[0].ProductId : 0);
        /* report devices that are already plugged in */
        rescan();
        EnterCriticalSection(&g_lock);
        {
            Device *d;
            for (d = g_devices; d; d = d->next) {
                int k, dup = 0;
                if (d->gone || !reg_matches(r, d->vid, d->pid)) continue;
                for (k = 0; k < r->qCount; k++) if (r->q[(r->qHead + k) % MAX_QUEUE].devId == d->id) dup = 1;
                if (!dup) reg_queue(r, WD_INSERT, d);
            }
        }
        if (!g_hotplugThread) {
            g_hotplugStop = CreateEventA(NULL, TRUE, FALSE, NULL);
            g_hotplugThread = CreateThread(NULL, 0, hotplug_thread, NULL, 0, NULL);
        }
        LeaveCriticalSection(&g_lock);
        return 0;
    }

    case FN_INT_ENABLE_OLD: {
        WD_INTERRUPT *it = (WD_INTERRUPT *)in;
        Reg *r = reg_find(it->hInterrupt);
        if (!r) { LOG("INT_ENABLE: unknown handle 0x%lx", it->hInterrupt); return WD_INVALID_HANDLE; }
        ResetEvent(r->hStop);
        r->enabled = TRUE;
        it->fEnableOk = 1; it->fStopped = 0; it->dwCounter = 0; it->dwLost = 0;
        VLOG("INT_ENABLE 0x%lx", it->hInterrupt);
        return 0;
    }
    case FN_INT_DISABLE: {
        WD_INTERRUPT *it = (WD_INTERRUPT *)in;
        Reg *r = reg_find(it->hInterrupt);
        if (!r) return WD_INVALID_HANDLE;
        r->enabled = FALSE;
        SetEvent(r->hStop);
        it->fStopped = INTERRUPT_STOPPED;
        LOG("INT_DISABLE 0x%lx", it->hInterrupt);
        return 0;
    }
    case FN_INT_WAIT: {
        WD_INTERRUPT *it = (WD_INTERRUPT *)in;
        Reg *r = reg_find(it->hInterrupt);
        HANDLE hs[2];
        DWORD w;
        if (!r) { it->fStopped = INTERRUPT_STOPPED; return 0; }
        hs[0] = r->hStop; hs[1] = r->hSem;
        w = WaitForMultipleObjects(2, hs, FALSE, INFINITE);
        if (w == WAIT_OBJECT_0 || !r->enabled) { it->fStopped = INTERRUPT_STOPPED; VLOG("INT_WAIT -> stopped"); return 0; }
        it->fStopped = INTERRUPT_RUNNING;
        it->dwCounter++;
        VLOG("INT_WAIT -> event");
        return 0;
    }
    case FN_EVENT_PULL: {
        WD_EVENT *e = (WD_EVENT *)in;
        Reg *r = reg_find(e->handle);
        if (!r) return WD_INVALID_HANDLE;
        EnterCriticalSection(&g_lock);
        if (r->qCount == 0) {
            e->dwAction = 0;
        } else {
            int s = r->qHead;
            r->qHead = (r->qHead + 1) % MAX_QUEUE; r->qCount--;
            e->dwAction = r->q[s].action;
            e->dwStatus = 0;
            e->dwEventId = ++r->eventId;
            e->dwCardType = WD_BUS_USB;
            e->hKernelPlugIn = 0;
            e->dwOptions = r->dwOptions;
            e->u.Usb.dwVendorId = r->q[s].vid;
            e->u.Usb.dwProductId = r->q[s].pid;
            e->u.Usb.dwUniqueID = r->q[s].devId;
            e->dwEventVer = 1;
            if (inLen >= sizeof(WD_EVENT)) {
                Device *d;
                e->dwNumMatchTables = 1;
                memset(&e->matchTables[0], 0, sizeof(WDU_MATCH_TABLE));
                e->matchTables[0].VendorId = r->q[s].vid;
                e->matchTables[0].ProductId = r->q[s].pid;
                for (d = g_devices; d; d = d->next) if (d->id == r->q[s].devId) {
                    e->matchTables[0].bDeviceClass = d->devDesc.bDeviceClass;
                    e->matchTables[0].bDeviceSubClass = d->devDesc.bDeviceSubClass;
                    if (d->cfgLen > 9 + 7) {
                        e->matchTables[0].bInterfaceClass = d->cfg[9 + 5];
                        e->matchTables[0].bInterfaceSubClass = d->cfg[9 + 6];
                        e->matchTables[0].bInterfaceProtocol = d->cfg[9 + 7];
                    }
                }
            }
            LOG("EVENT_PULL -> %s device 0x%lx", e->dwAction == WD_INSERT ? "INSERT" : "REMOVE", e->u.Usb.dwUniqueID);
        }
        LeaveCriticalSection(&g_lock);
        return 0;
    }
    case FN_EVENT_SEND:
        VLOG("EVENT_SEND (ack)");
        return 0;
    case FN_EVENT_UNREGISTER: {
        WD_EVENT *e = (WD_EVENT *)in;
        Reg **pp, *r = NULL;
        EnterCriticalSection(&g_lock);
        for (pp = &g_regs; *pp; pp = &(*pp)->next)
            if ((*pp)->handle == e->handle) { r = *pp; *pp = r->next; break; }
        LeaveCriticalSection(&g_lock);
        LOG("EVENT_UNREGISTER 0x%lx (session totals: %ld transfers, %ld failed, %ld slow, max %lums)",
            e->handle, g_nXfer, g_nFail, g_nSlow, g_maxMs);
        if (r) { SetEvent(r->hStop); /* keep object alive: a waiter may still reference it */ }
        return 0;
    }

    case FN_USB_GET_DEV_DATA: {
        WDU_GET_DEVICE_DATA *g = (WDU_GET_DEVICE_DATA *)in;
        Device *d = dev_find(g->dwUniqueID);
        DWORD need;
        if (!d) return WD_WRONG_UNIQUE_ID;
        need = build_device_info(d, NULL);
        if (g->pBuf && g->dwBytes) {
            if (g->dwBytes < need) return WD_INSUFFICIENT_RESOURCES;
            build_device_info(d, (UCHAR *)g->pBuf);
        }
        g->dwBytes = need;
        VLOG("GET_DEVICE_DATA 0x%lx -> %lu bytes%s", g->dwUniqueID, need, g->pBuf ? " (filled)" : "");
        return 0;
    }
    case FN_USB_SET_INTERFACE: {
        WDU_SET_INTERFACE *s = (WDU_SET_INTERFACE *)in;
        Device *d = dev_find(s->dwUniqueID);
        int k;
        if (!d) return WD_WRONG_UNIQUE_ID;
        LOG("SET_INTERFACE dev 0x%lx iface %lu alt %lu", s->dwUniqueID, s->dwInterfaceNum, s->dwAlternateSetting);
        if (d->sim) return 0;
        for (k = 0; k < d->nIf; k++) if (d->ifNum[k] == s->dwInterfaceNum) break;
        if (k == d->nIf) k = 0;
        if (d->curAlt[k] != s->dwAlternateSetting || s->dwAlternateSetting != 0) {
            if (!pWinUsb_SetCurrentAlternateSetting(d->hIf[k], (UCHAR)s->dwAlternateSetting)) {
                LOG("  SetCurrentAlternateSetting failed, err %lu", GetLastError());
                if (s->dwAlternateSetting != 0) return map_winerr(GetLastError());
            }
            d->curAlt[k] = (UCHAR)s->dwAlternateSetting;
        }
        return 0;
    }
    case FN_USB_TRANSFER:
        if (inLen < sizeof(WDU_TRANSFER)) return WD_INVALID_PARAMETER;
        return do_transfer((WDU_TRANSFER *)in);

    case FN_USB_RESET_PIPE:
    case FN_USB_HALT_TRANSFER: {
        WDU_PIPE_CMD *p = (WDU_PIPE_CMD *)in;
        Device *d = dev_find(p->dwUniqueID);
        UCHAR ep = (UCHAR)p->dwPipeNum;
        if (!d) return WD_WRONG_UNIQUE_ID;
        LOG("%s dev 0x%lx pipe 0x%02x", fn == FN_USB_RESET_PIPE ? "RESET_PIPE" : "HALT_TRANSFER", p->dwUniqueID, ep);
        if (d->sim || ep == 0) return 0;
        {
            WINUSB_INTERFACE_HANDLE h = d->hIf[iface_for_ep(d, ep)];
            BOOL ok = fn == FN_USB_RESET_PIPE ? pWinUsb_ResetPipe(h, ep) : pWinUsb_AbortPipe(h, ep);
            if (!ok) LOG("  failed, err %lu", GetLastError());
        }
        return 0;
    }
    case FN_USB_WAKEUP:
    case FN_USB_RESET_DEVICE: {
        WDU_DEV_CMD *c = (WDU_DEV_CMD *)in;
        LOG("%s dev 0x%lx (no-op)", fn == FN_USB_WAKEUP ? "WAKEUP" : "RESET_DEVICE", c->dwUniqueID);
        return dev_find(c->dwUniqueID) ? 0 : WD_WRONG_UNIQUE_ID;
    }
    default:
        LOG("WARN: unsupported WinDriver IOCTL 0x%08lx (function 0x%03lx, %lu bytes)", code, fn, inLen);
        return WD_NOT_IMPLEMENTED;
    }
}

/* ======================================================================
 *  Import hooks (CreateFileA / DeviceIoControl / CloseHandle)
 * ====================================================================*/
#define MAX_FAKE 64
static HANDLE g_fake[MAX_FAKE];
static CRITICAL_SECTION g_fakeLock;

static HANDLE (WINAPI *real_CreateFileA)(LPCSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
static BOOL (WINAPI *real_DeviceIoControl)(HANDLE, DWORD, LPVOID, DWORD, LPVOID, DWORD, LPDWORD, LPOVERLAPPED);
static BOOL (WINAPI *real_CloseHandle)(HANDLE);

static BOOL is_fake(HANDLE h)
{
    int i; BOOL r = FALSE;
    if (!h || h == INVALID_HANDLE_VALUE) return FALSE;
    EnterCriticalSection(&g_fakeLock);
    for (i = 0; i < MAX_FAKE; i++) if (g_fake[i] == h) { r = TRUE; break; }
    LeaveCriticalSection(&g_fakeLock);
    return r;
}

static BOOL is_windrvr_name(LPCSTR n)
{
    return n && (!lstrcmpiA(n, "\\\\.\\WINDRVR6") || !lstrcmpiA(n, "\\\\.\\WINDRVR"));
}

static HANDLE WINAPI hook_CreateFileA(LPCSTR name, DWORD acc, DWORD share, LPSECURITY_ATTRIBUTES sa,
                                      DWORD disp, DWORD flags, HANDLE tmpl)
{
    if (is_windrvr_name(name)) {
        /* a real (dummy) kernel handle, so any CloseHandle on it just works */
        HANDLE h = CreateEventA(NULL, TRUE, FALSE, NULL);
        int i;
        EnterCriticalSection(&g_fakeLock);
        for (i = 0; i < MAX_FAKE; i++) if (!g_fake[i]) { g_fake[i] = h; break; }
        LeaveCriticalSection(&g_fakeLock);
        if (i == MAX_FAKE) { LOG("ERROR: too many WinDriver handles"); real_CloseHandle(h); SetLastError(ERROR_TOO_MANY_OPEN_FILES); return INVALID_HANDLE_VALUE; }
        VLOG("open %s -> %p", name, h);
        return h;
    }
    return real_CreateFileA(name, acc, share, sa, disp, flags, tmpl);
}

static BOOL WINAPI hook_CloseHandle(HANDLE h)
{
    int i;
    EnterCriticalSection(&g_fakeLock);
    for (i = 0; i < MAX_FAKE; i++) if (g_fake[i] == h) { g_fake[i] = NULL; break; }
    LeaveCriticalSection(&g_fakeLock);
    return real_CloseHandle(h);
}

static BOOL WINAPI hook_DeviceIoControl(HANDLE h, DWORD code, LPVOID in, DWORD inLen, LPVOID out,
                                        DWORD outLen, LPDWORD ret, LPOVERLAPPED ov)
{
    DWORD status;
    if (!is_fake(h)) return real_DeviceIoControl(h, code, in, inLen, out, outLen, ret, ov);
    if ((code & 0xffff0000u) != 0x95380000u) {
        LOG("WARN: foreign IOCTL 0x%08lx on WinDriver handle", code);
        SetLastError(ERROR_INVALID_FUNCTION);
        return FALSE;
    }
    status = in ? wd_ioctl(code, in, inLen) : WD_INVALID_PARAMETER;
    if (status) VLOG("IOCTL fn 0x%03lx -> status 0x%08lx", WD_FUNC(code), status);
    if (out && outLen >= 4) *(DWORD *)out = status;
    if (ret) *ret = 4;
    return TRUE;
}

/* patch one import of the main executable; returns TRUE if patched */
static BOOL patch_iat(HMODULE mod, const char *dll, const char *func, void *hook, void **orig)
{
    BYTE *base = (BYTE *)mod;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + dos->e_lfanew);
    IMAGE_DATA_DIRECTORY *dir = &nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    IMAGE_IMPORT_DESCRIPTOR *imp;
    FARPROC target = GetProcAddress(GetModuleHandleA(dll), func);
    BOOL done = FALSE;

    if (!dir->VirtualAddress) return FALSE;
    for (imp = (IMAGE_IMPORT_DESCRIPTOR *)(base + dir->VirtualAddress); imp->Name; imp++) {
        IMAGE_THUNK_DATA *ft, *oft;
        if (lstrcmpiA((char *)(base + imp->Name), dll)) continue;
        ft = (IMAGE_THUNK_DATA *)(base + imp->FirstThunk);
        oft = imp->OriginalFirstThunk ? (IMAGE_THUNK_DATA *)(base + imp->OriginalFirstThunk) : NULL;
        for (; ft->u1.Function; ft++, oft = oft ? oft + 1 : NULL) {
            BOOL match = FALSE;
            if (oft && !(oft->u1.Ordinal & IMAGE_ORDINAL_FLAG)) {
                IMAGE_IMPORT_BY_NAME *ibn = (IMAGE_IMPORT_BY_NAME *)(base + oft->u1.AddressOfData);
                match = !strcmp((char *)ibn->Name, func);
            } else if ((FARPROC)ft->u1.Function == target) {
                match = TRUE;
            }
            if (match) {
                DWORD old;
                if ((void *)ft->u1.Function == hook) return TRUE;   /* already done */
                if (!*orig) *orig = (void *)target;
                VirtualProtect(&ft->u1.Function, sizeof(void *), PAGE_READWRITE, &old);
                ft->u1.Function = (DWORD_PTR)hook;
                VirtualProtect(&ft->u1.Function, sizeof(void *), old, &old);
                done = TRUE;
            }
        }
    }
    return done;
}

static BOOL install_hooks(void)
{
    HMODULE exe = GetModuleHandleA(NULL);
    BOOL a, b, c;
    a = patch_iat(exe, "KERNEL32.DLL", "CreateFileA", (void *)hook_CreateFileA, (void **)&real_CreateFileA);
    b = patch_iat(exe, "KERNEL32.DLL", "DeviceIoControl", (void *)hook_DeviceIoControl, (void **)&real_DeviceIoControl);
    c = patch_iat(exe, "KERNEL32.DLL", "CloseHandle", (void *)hook_CloseHandle, (void **)&real_CloseHandle);
    if (!real_CreateFileA) real_CreateFileA = (void *)GetProcAddress(GetModuleHandleA("kernel32.dll"), "CreateFileA");
    if (!real_DeviceIoControl) real_DeviceIoControl = (void *)GetProcAddress(GetModuleHandleA("kernel32.dll"), "DeviceIoControl");
    if (!real_CloseHandle) real_CloseHandle = (void *)GetProcAddress(GetModuleHandleA("kernel32.dll"), "CloseHandle");
    return a && b && c;
}

/* re-check shortly after start-up in case the loader re-snapped the IAT */
static DWORD WINAPI late_hook_thread(LPVOID p)
{
    int i;
    (void)p;
    /* TopWin programs on its GUI thread and repaints the progress bar itself.
       After 5 s without reading its message queue Windows replaces the window
       with a frozen "ghost" copy, which is why the progress bar appeared to
       stop at ~30%. Turn ghosting off for this process (TOPWD_GHOSTING=1 keeps it). */
    if (!GetEnvironmentVariableA("TOPWD_GHOSTING", NULL, 0)) {
        HMODULE u = GetModuleHandleA("user32.dll");
        void (WINAPI *dpwg)(void) = u ? (void (WINAPI *)(void))GetProcAddress(u, "DisableProcessWindowsGhosting") : NULL;
        if (dpwg) { dpwg(); LOG("window ghosting disabled"); }
    }
    for (i = 0; i < 20; i++) { Sleep(i < 5 ? 10 : 200); install_hooks(); }
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        char exe[MAX_PATH];
        OSVERSIONINFOA osv;
        DisableThreadLibraryCalls(inst);
        InitializeCriticalSection(&g_lock);
        InitializeCriticalSection(&g_scanLock);
        InitializeCriticalSection(&g_fakeLock);
        log_open();
        g_sim = GetEnvironmentVariableA("TOPWD_SIM", NULL, 0) > 0;
        pace_init();
        GetModuleFileNameA(NULL, exe, MAX_PATH);
        memset(&osv, 0, sizeof(osv)); osv.dwOSVersionInfoSize = sizeof(osv);
        LOG("TopWD %s (WinDriver 6.03 emulation via WinUSB) loaded into %s%s", TOPWD_VERSION, exe,
            g_sim ? " [SIMULATION MODE]" : "");
        LOG("transfer pacing: %ld us (TOPWD_PACE_US), chunk size: %ld bytes (TOPWD_CHUNK)", g_paceUs, g_chunk);
        if (install_hooks()) LOG("hooks installed");
        else LOG("WARN: could not hook all imports yet; will retry");
        CloseHandle(CreateThread(NULL, 0, late_hook_thread, NULL, 0, NULL));
    }
    return TRUE;
}
