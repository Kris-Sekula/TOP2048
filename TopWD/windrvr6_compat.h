/*
 * windrvr6_compat.h - the subset of the Jungo WinDriver 6.03 user/kernel
 * interface used by TopWin (TOP2049 and other TOP-series programmer software).
 *
 * Layouts were recovered from TopWinEn.exe (statically linked WinDriver
 * 6.03 "wdu_lib" + "windrvr_events" code) and cross-checked against the
 * open-source Linux libusb-driver (usb-driver by Michael Gernoth).
 * All structures are the 32-bit (x86) layouts TopWin uses.
 */
#ifndef WINDRVR6_COMPAT_H
#define WINDRVR6_COMPAT_H

#include <windows.h>
#include <stddef.h>

/* IOCTL code = CTL_CODE(38200 (=0x9538), func, METHOD_NEITHER, FILE_ANY_ACCESS) */
#define WD_IOCTL(func) (0x95380000u | ((func) << 2) | 3u)
#define WD_FUNC(code)  (((code) >> 2) & 0xfffu)

enum {
    FN_VERSION            = 0x910,
    FN_INT_ENABLE_OLD     = 0x91e,
    FN_INT_DISABLE        = 0x91f,
    FN_INT_WAIT           = 0x94b,
    FN_LICENSE            = 0x952,
    FN_DEBUG_ADD          = 0x964,
    FN_USB_GET_DEV_DATA   = 0x980,
    FN_USB_SET_INTERFACE  = 0x981,
    FN_USB_RESET_PIPE     = 0x982,
    FN_USB_TRANSFER       = 0x983,
    FN_USB_HALT_TRANSFER  = 0x985,
    FN_EVENT_REGISTER_OLD = 0x986,
    FN_EVENT_UNREGISTER   = 0x987,
    FN_EVENT_PULL         = 0x988,
    FN_EVENT_SEND         = 0x989,
    FN_USB_WAKEUP         = 0x98a,
    FN_USB_RESET_DEVICE   = 0x98b,
};

#define WD_VER_603 603          /* TopWin insists on exactly 603 */

/* WinDriver status codes */
#define WD_STATUS_SUCCESS            0x00000000u
#define WD_INVALID_HANDLE            0x20000001u
#define WD_INVALID_PIPE_NUMBER       0x20000002u
#define WD_INSUFFICIENT_RESOURCES    0x20000005u
#define WD_SYSTEM_INTERNAL_ERROR     0x20000007u
#define WD_NOT_IMPLEMENTED           0x2000000au
#define WD_DEVICE_NOT_FOUND          0x2000000fu
#define WD_WRONG_UNIQUE_ID           0x20000010u
#define WD_TIME_OUT_EXPIRED          0x20000015u
#define WD_IRP_CANCELED              0x20000016u
#define WD_INVALID_PARAMETER         0x2000001bu
#define WD_USBD_STATUS_STALL_PID     0xC0000004u

/* event actions */
#define WD_INSERT 0x1
#define WD_REMOVE 0x2
#define WD_BUS_USB 0xfffffffeu

/* interrupt fStopped values */
#define INTERRUPT_RUNNING     0
#define INTERRUPT_STOPPED     1
#define INTERRUPT_INTERRUPTED 2

#pragma pack(push, 4)

typedef struct { DWORD dwVer; CHAR cVer[128]; } WD_VERSION;              /* 0x84 */
typedef struct { CHAR cLicense[128]; DWORD dwLicense; DWORD dwLicense2; } WD_LICENSE; /* 0x88 */

typedef struct {
    USHORT VendorId;
    USHORT ProductId;
    UCHAR  bDeviceClass;
    UCHAR  bDeviceSubClass;
    UCHAR  bInterfaceClass;
    UCHAR  bInterfaceSubClass;
    UCHAR  bInterfaceProtocol;
} WDU_MATCH_TABLE;                                                       /* 10 */

typedef struct {
    DWORD handle;
    DWORD dwAction;
    DWORD dwStatus;
    DWORD dwEventId;
    DWORD dwCardType;
    DWORD hKernelPlugIn;
    DWORD dwOptions;
    union {
        struct { DWORD dwVendorId, dwDeviceId, dwBus, dwSlot, dwFunction; } Pci;
        struct { DWORD dwVendorId, dwProductId, dwUniqueID; } Usb;
    } u;
    DWORD dwEventVer;
    DWORD dwNumMatchTables;
    WDU_MATCH_TABLE matchTables[1];
} WD_EVENT;                                                              /* 0x44 */

typedef struct {
    DWORD hInterrupt;
    DWORD dwOptions;
    DWORD pCmd;            /* WD_TRANSFER* (unused) */
    DWORD dwCmds;
    DWORD kpCall[4];
    DWORD fEnableOk;
    DWORD dwCounter;
    DWORD dwLost;
    DWORD fStopped;
} WD_INTERRUPT;                                                          /* 0x30 */

typedef struct { DWORD dwUniqueID; void *pBuf; DWORD dwBytes; DWORD dwOptions; } WDU_GET_DEVICE_DATA;
typedef struct { DWORD dwUniqueID; DWORD dwInterfaceNum; DWORD dwAlternateSetting; DWORD dwOptions; } WDU_SET_INTERFACE;
typedef struct { DWORD dwUniqueID; DWORD dwPipeNum; DWORD dwOptions; } WDU_PIPE_CMD;   /* reset pipe / halt */
typedef struct { DWORD dwUniqueID; DWORD dwOptions; } WDU_DEV_CMD;                    /* wakeup / reset dev */

typedef struct {
    DWORD dwUniqueID;
    DWORD dwPipeNum;
    DWORD fRead;
    DWORD dwOptions;
    void *pBuffer;
    DWORD dwBufferSize;
    DWORD dwBytesTransferred;
    UCHAR SetupPacket[8];
    DWORD dwTimeout;
} WDU_TRANSFER;                                                          /* 0x28 */

/* ---- device-information tree returned by USB_GET_DEVICE_DATA ---- */
typedef struct {
    UCHAR bLength, bDescriptorType, bInterfaceNumber, bAlternateSetting,
          bNumEndpoints, bInterfaceClass, bInterfaceSubClass, bInterfaceProtocol, iInterface;
} WDU_INTERFACE_DESCRIPTOR;
typedef struct {
    UCHAR bLength, bDescriptorType, bEndpointAddress, bmAttributes;
    USHORT wMaxPacketSize;
    UCHAR bInterval;
} WDU_ENDPOINT_DESCRIPTOR;
typedef struct {
    UCHAR bLength, bDescriptorType; USHORT wTotalLength;
    UCHAR bNumInterfaces, bConfigurationValue, iConfiguration, bmAttributes, MaxPower;
} WDU_CONFIGURATION_DESCRIPTOR;
typedef struct {
    UCHAR bLength, bDescriptorType; USHORT bcdUSB;
    UCHAR bDeviceClass, bDeviceSubClass, bDeviceProtocol, bMaxPacketSize0;
    USHORT idVendor, idProduct, bcdDevice;
    UCHAR iManufacturer, iProduct, iSerialNumber, bNumConfigurations;
} WDU_DEVICE_DESCRIPTOR;
typedef struct {
    DWORD dwNumber;              /* endpoint address; 0 = default pipe */
    DWORD dwMaximumPacketSize;
    DWORD type;                  /* 0 ctrl, 1 isoch, 2 bulk, 3 interrupt */
    DWORD direction;             /* 1 in, 2 out, 3 in/out */
    DWORD dwInterval;
} WDU_PIPE_INFO;
typedef struct {
    WDU_INTERFACE_DESCRIPTOR Descriptor;
    WDU_ENDPOINT_DESCRIPTOR *pEndpointDescriptors;
    WDU_PIPE_INFO *pPipes;
} WDU_ALTERNATE_SETTING;
typedef struct {
    WDU_ALTERNATE_SETTING *pAlternateSettings;
    DWORD dwNumAltSettings;
    WDU_ALTERNATE_SETTING *pActiveAltSetting;
} WDU_INTERFACE;
typedef struct {
    WDU_CONFIGURATION_DESCRIPTOR Descriptor;
    DWORD dwNumInterfaces;
    WDU_INTERFACE *pInterfaces;
} WDU_CONFIGURATION;
#define WD_USB_MAX_INTERFACES 30
typedef struct {
    WDU_DEVICE_DESCRIPTOR Descriptor;
    WDU_PIPE_INFO Pipe0;
    WDU_CONFIGURATION *pConfigs;
    WDU_CONFIGURATION *pActiveConfig;
    WDU_INTERFACE *pActiveInterface[WD_USB_MAX_INTERFACES];
} WDU_DEVICE;

#pragma pack(pop)

/* layout checks against what TopWinEn.exe expects */
_Static_assert(sizeof(WD_VERSION) == 0x84, "WD_VERSION");
_Static_assert(sizeof(WD_LICENSE) == 0x88, "WD_LICENSE");
_Static_assert(sizeof(WDU_MATCH_TABLE) == 10, "MATCH");
_Static_assert(offsetof(WD_EVENT, u) == 0x1c, "EV.u");
_Static_assert(offsetof(WD_EVENT, u.Usb.dwUniqueID) == 0x24, "EV.uid");
_Static_assert(offsetof(WD_EVENT, dwEventVer) == 0x30, "EV.ver");
_Static_assert(offsetof(WD_EVENT, matchTables) == 0x38, "EV.mt");
_Static_assert(sizeof(WD_EVENT) == 0x44, "WD_EVENT");
_Static_assert(sizeof(WD_INTERRUPT) == 0x30, "WD_INTERRUPT");
_Static_assert(offsetof(WD_INTERRUPT, fStopped) == 0x2c, "INT.fStopped");
_Static_assert(sizeof(WDU_TRANSFER) == 0x28, "WDU_TRANSFER");
_Static_assert(offsetof(WDU_TRANSFER, dwBytesTransferred) == 0x18, "XFER.bytes");
_Static_assert(sizeof(WDU_GET_DEVICE_DATA) == 0x10, "GDD");
_Static_assert(offsetof(WDU_DEVICE, Pipe0) == 0x14, "DEV.Pipe0");
_Static_assert(offsetof(WDU_DEVICE, pActiveInterface) == 0x30, "DEV.pActiveInterface");
_Static_assert(offsetof(WDU_ALTERNATE_SETTING, pEndpointDescriptors) == 12, "ALT");
_Static_assert(sizeof(WDU_ENDPOINT_DESCRIPTOR) == 8, "EPD");

#endif
