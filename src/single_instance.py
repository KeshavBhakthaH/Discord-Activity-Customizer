"""Single-instance enforcement and IPC activation for Discord Activity Customizer.

Ensures only a single instance of the application runs at any time.
If the user tries to launch a second instance (e.g. from the Start Menu or by
double-clicking the EXE), the new instance signals the existing instance to
restore and focus its window, then exits immediately.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
WAIT_OBJECT_0 = 0

MUTEX_NAME = r"Local\DiscordActivityCustomizer_SingleInstance_Mutex"
EVENT_NAME = r"Local\DiscordActivityCustomizer_ShowEvent"

try:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateEventW.restype = wintypes.HANDLE
    kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    kernel32.SetEvent.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    WIN32_AVAILABLE = True
except Exception as err:
    logger.warning("Win32 API not available for single-instance manager: %s", err)
    WIN32_AVAILABLE = False


class SingleInstanceManager:
    """Ensures only one instance of Discord Activity Customizer runs at any time."""

    def __init__(self) -> None:
        self.h_mutex: Optional[wintypes.HANDLE] = None
        self.h_event: Optional[wintypes.HANDLE] = None
        self._listener_thread: Optional[threading.Thread] = None
        self._stop_listener: bool = False

    def check_single_instance(self) -> bool:
        """Check if this is the primary instance.

        Returns:
            True if this is the first/primary instance.
            False if another instance is already running (it signals it and should exit).
        """
        if not WIN32_AVAILABLE:
            return True

        try:
            self.h_mutex = kernel32.CreateMutexW(None, True, MUTEX_NAME)
            err = ctypes.get_last_error()
            if err == ERROR_ALREADY_EXISTS:
                logger.info("Another instance is already running. Signaling it to restore window...")
                h_event = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, EVENT_NAME)
                if h_event:
                    kernel32.SetEvent(h_event)
                    kernel32.CloseHandle(h_event)
                if self.h_mutex:
                    kernel32.CloseHandle(self.h_mutex)
                    self.h_mutex = None
                return False

            # Primary instance: create named activation event
            self.h_event = kernel32.CreateEventW(None, False, False, EVENT_NAME)
            return True
        except Exception as exc:
            logger.warning("Error checking single instance: %s", exc)
            return True

    def start_show_listener(self, on_show_callback: Callable[[], None]) -> None:
        """Start a background listener that restores the window when secondary launches occur."""
        if not WIN32_AVAILABLE or not self.h_event:
            return

        def _worker() -> None:
            while not self._stop_listener and self.h_event:
                wait_res = kernel32.WaitForSingleObject(self.h_event, 1000)
                if wait_res == WAIT_OBJECT_0:
                    logger.info("Received show activation signal from secondary launch.")
                    try:
                        on_show_callback()
                    except Exception as exc:
                        logger.warning("Error invoking show callback: %s", exc)

        self._listener_thread = threading.Thread(
            target=_worker,
            name="SingleInstanceShowListener",
            daemon=True,
        )
        self._listener_thread.start()

    def close(self) -> None:
        """Clean up Win32 handles."""
        self._stop_listener = True
        if self.h_event:
            try:
                kernel32.CloseHandle(self.h_event)
            except Exception:
                pass
            self.h_event = None
        if self.h_mutex:
            try:
                kernel32.CloseHandle(self.h_mutex)
            except Exception:
                pass
            self.h_mutex = None
