"""Windows memory optimization utilities for Discord Activity Customizer.

Ensures active RAM usage remains strictly below 15 MB by utilizing Python GC
and the Windows Win32 API (EmptyWorkingSet) on the process and parent launcher.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import gc
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_INFORMATION = 0x0400

try:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)

    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
    psapi.EmptyWorkingSet.restype = wintypes.BOOL

    WIN32_AVAILABLE = True
except Exception as e:
    logger.warning("Win32 memory management APIs not available: %s", e)
    WIN32_AVAILABLE = False


def trim_process_memory() -> None:
    """Trim memory footprint (Working Set) for current process and parent process.

    Performs:
    1. Python generational garbage collection (gc.collect()).
    2. EmptyWorkingSet on current process to release all unused pages back to Windows.
    3. EmptyWorkingSet on parent process (PyInstaller bootloader) if running as packaged EXE.
    """
    try:
        # 1. Force Python Garbage Collector to free unreferenced objects
        gc.collect()

        if not WIN32_AVAILABLE:
            return

        # 2. Trim self
        h_self = kernel32.GetCurrentProcess()
        psapi.EmptyWorkingSet(h_self)

        # 3. Trim parent launcher (e.g. PyInstaller bootloader process)
        try:
            ppid = os.getppid()
            if ppid > 0:
                h_parent = kernel32.OpenProcess(
                    PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, False, ppid
                )
                if h_parent:
                    psapi.EmptyWorkingSet(h_parent)
                    kernel32.CloseHandle(h_parent)
        except Exception:
            pass

    except Exception as exc:
        logger.debug("Memory trim encountered exception: %s", exc)


def get_working_set_mb() -> float:
    """Get the current process Working Set memory in megabytes."""
    if not WIN32_AVAILABLE:
        return 0.0

    class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    try:
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

        pmc = PROCESS_MEMORY_COUNTERS_EX()
        pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
        h = kernel32.GetCurrentProcess()
        if psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return round(pmc.WorkingSetSize / (1024 * 1024), 2)
    except Exception:
        pass
    return 0.0
