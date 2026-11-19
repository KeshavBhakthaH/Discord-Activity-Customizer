"""Thread-safe pypresence wrapper with automatic reconnection and status callbacks."""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable, Dict, Optional

from pypresence import (
    ActivityType,
    DiscordError,
    DiscordNotFound,
    InvalidID,
    InvalidPipe,
    PipeClosed,
    Presence,
    PyPresenceException,
    StatusDisplayType,
)

from src.constants import (
    DEFAULT_CLIENT_ID,
    MAX_FIELD_LENGTH,
    MIN_FIELD_LENGTH,
    is_placeholder_client_id,
)

logger = logging.getLogger(__name__)

# Status constants
STATUS_DISCONNECTED = "Disconnected"
STATUS_CONNECTING = "Connecting..."
STATUS_CONNECTED = "Connected to Discord"
STATUS_ACTIVE = "Active on Discord"
STATUS_ERROR = "Error"


def sanitize_rpc_string(val: Optional[str]) -> Optional[str]:
    """Sanitize string for Discord RPC payload.

    Discord RPC requires strings to be at least 2 characters if provided.
    Empty or whitespace-only strings are converted to None.
    Single-character strings are padded to 2 characters.
    Strings exceeding 128 characters are truncated.
    """
    if val is None:
        return None
    cleaned = str(val).strip()
    if not cleaned:
        return None
    if len(cleaned) == 1:
        # Discord requires >= 2 characters; pad with a space
        cleaned = f"{cleaned} "
    elif len(cleaned) > MAX_FIELD_LENGTH:
        cleaned = cleaned[:MAX_FIELD_LENGTH]
    return cleaned


class RPCManager:
    """Manages Discord Rich Presence IPC connection on a background thread."""

    def __init__(
        self,
        client_id: str = DEFAULT_CLIENT_ID,
        status_callback: Optional[Callable[[str, str, bool], None]] = None,
    ) -> None:
        """Initialize RPCManager.

        Args:
            client_id: The Discord Application ID.
            status_callback: Callback func(state, display_message, is_error).
        """
        self.client_id: str = client_id.strip()
        self.status_callback = status_callback

        self._presence: Optional[Presence] = None
        self._is_connected: bool = False
        self._is_active: bool = False

        self._current_activity: Dict[str, Any] = {}
        self._activity_start_time: Optional[int] = None

        self._task_queue: queue.Queue = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # Start background worker thread
        self._start_worker()

    # -----------------------------------------------------------------------
    # Worker Lifecycle
    # -----------------------------------------------------------------------
    def _start_worker(self) -> None:
        """Spawn the dedicated background worker thread for IPC calls."""
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="RPCWorkerThread",
            daemon=True,
        )
        self._worker_thread.start()

    def _worker_loop(self) -> None:
        """Process RPC tasks sequentially off the main thread."""
        logger.info("RPC worker thread started.")
        while not self._stop_event.is_set():
            try:
                task = self._task_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            action = task.get("action")
            data = task.get("data", {})

            try:
                if action == "UPDATE":
                    self._handle_update(data)
                elif action == "STOP":
                    self._handle_stop()
                elif action == "CLOSE":
                    self._handle_close()
                    break
            except Exception as exc:
                logger.exception("Unexpected error in RPC worker: %s", exc)
                self._notify_status(STATUS_ERROR, f"RPC worker error: {exc}", is_error=True)
            finally:
                self._task_queue.task_done()

        logger.info("RPC worker thread terminated.")

    def _notify_status(self, state: str, message: str, is_error: bool = False) -> None:
        """Dispatch status notification to callback."""
        if self.status_callback:
            try:
                self.status_callback(state, message, is_error)
            except Exception as exc:
                logger.error("Error in status callback: %s", exc)

    # -----------------------------------------------------------------------
    # IPC Operations (Executed on worker thread)
    # -----------------------------------------------------------------------
    def _ensure_connected(self) -> bool:
        """Establish connection to local Discord IPC if not already connected."""
        if is_placeholder_client_id(self.client_id):
            self._notify_status(
                STATUS_ERROR,
                "Warning: DEFAULT_CLIENT_ID is not configured in src/constants.py.",
                is_error=True,
            )
            return False

        if self._is_connected and self._presence:
            return True

        self._notify_status(STATUS_CONNECTING, "Connecting to Discord desktop IPC...")

        try:
            # Clean up any leftover presence instance
            if self._presence:
                try:
                    self._presence.close()
                except Exception:
                    pass
                self._presence = None

            self._presence = Presence(self.client_id)
            self._presence.connect()
            self._is_connected = True
            logger.info("Connected to Discord IPC successfully.")
            return True

        except (DiscordNotFound, InvalidPipe, FileNotFoundError) as exc:
            self._is_connected = False
            self._presence = None
            msg = (
                "Discord desktop app not detected. Make sure the Windows Discord app "
                "(not just the web browser) is open."
            )
            logger.warning("Discord IPC connect failed: %s (%s)", exc, type(exc).__name__)
            self._notify_status(STATUS_ERROR, msg, is_error=True)
            return False

        except InvalidID as exc:
            self._is_connected = False
            self._presence = None
            msg = (
                f"Invalid Application ID '{self.client_id}'. "
                "Please configure a valid Application ID from Discord Developer Portal."
            )
            logger.error("Invalid Discord Application ID: %s", exc)
            self._notify_status(STATUS_ERROR, msg, is_error=True)
            return False

        except Exception as exc:
            self._is_connected = False
            self._presence = None
            msg = f"Failed to connect to Discord IPC: {exc}"
            logger.error("Unexpected connect error: %s", exc)
            self._notify_status(STATUS_ERROR, msg, is_error=True)
            return False

    def _handle_update(self, payload: Dict[str, Any]) -> None:
        """Apply presence update via pypresence."""
        if not self._ensure_connected():
            return

        # Prepare arguments according to field mapping:
        # App Name -> details
        # Subdetails -> state
        # Logo Hover Text -> large_text
        # Main Logo -> large_image (HTTPS URL)
        # Elapsed Timer -> start (Unix timestamp or None)
        details = sanitize_rpc_string(payload.get("details"))
        state = sanitize_rpc_string(payload.get("state"))
        large_text = sanitize_rpc_string(payload.get("large_text"))
        large_image = payload.get("large_image")
        if large_image:
            large_image = str(large_image).strip()
            if not (large_image.startswith("https://") or large_image.startswith("http://") or len(large_image) >= 1):
                large_image = None
        else:
            large_image = None

        show_timer = bool(payload.get("show_timer", False))
        if show_timer:
            if self._activity_start_time is None:
                self._activity_start_time = int(time.time())
            start_timestamp = self._activity_start_time
        else:
            self._activity_start_time = None
            start_timestamp = None

        update_kwargs: Dict[str, Any] = {
            "activity_type": ActivityType.PLAYING,
            "status_display_type": StatusDisplayType.DETAILS,
            "name": details,
            "details": details,
            "state": state,
            "large_image": large_image,
            "large_text": large_text,
            "start": start_timestamp,
        }

        # Attempt to update presence, with resilient auto-reconnect on broken pipe
        for attempt in range(2):
            try:
                if not self._presence:
                    if not self._ensure_connected():
                        return

                assert self._presence is not None
                self._presence.update(**update_kwargs)
                self._is_active = True
                self._current_activity = update_kwargs

                display_title = details or state or "Custom Activity"
                self._notify_status(
                    STATUS_ACTIVE,
                    f"Active on Discord: {display_title}",
                    is_error=False,
                )
                logger.info("Discord Rich Presence updated successfully: %s", update_kwargs)
                return

            except (BrokenPipeError, PipeClosed, OSError, PyPresenceException) as exc:
                logger.warning(
                    "Connection lost during update (attempt %d/2): %s. Reconnecting...",
                    attempt + 1,
                    exc,
                )
                self._is_connected = False
                if attempt == 0:
                    time.sleep(0.5)
                    if not self._ensure_connected():
                        return
                else:
                    self._notify_status(
                        STATUS_ERROR,
                        "Discord connection lost. Please ensure Discord is running.",
                        is_error=True,
                    )
                    return
            except Exception as exc:
                logger.error("Error executing presence update: %s", exc)
                self._notify_status(STATUS_ERROR, f"Error updating activity: {exc}", is_error=True)
                return

    def _handle_stop(self) -> None:
        """Clear presence and mark inactive."""
        if self._presence and self._is_connected:
            try:
                self._presence.clear()
                logger.info("Presence cleared successfully.")
            except Exception as exc:
                logger.warning("Error clearing presence: %s", exc)

        self._is_active = False
        self._activity_start_time = None
        self._current_activity.clear()
        self._notify_status(STATUS_DISCONNECTED, "Activity stopped.", is_error=False)

    def _handle_close(self) -> None:
        """Cleanly close presence and connection."""
        try:
            if self._presence:
                try:
                    self._presence.clear()
                except Exception:
                    pass
                try:
                    self._presence.close()
                except Exception:
                    pass
                self._presence = None
        finally:
            self._is_connected = False
            self._is_active = False
            self._activity_start_time = None

    # -----------------------------------------------------------------------
    # Public Thread-Safe API (Called from UI / Main Thread)
    # -----------------------------------------------------------------------
    def update_activity(
        self,
        details: Optional[str],
        state: Optional[str],
        large_image: Optional[str],
        large_text: Optional[str],
        show_timer: bool,
    ) -> None:
        """Enqueue an activity start/update task."""
        payload = {
            "details": details,
            "state": state,
            "large_image": large_image,
            "large_text": large_text,
            "show_timer": show_timer,
        }
        self._task_queue.put({"action": "UPDATE", "data": payload})

    def stop_activity(self) -> None:
        """Enqueue an activity stop task."""
        self._task_queue.put({"action": "STOP", "data": {}})

    def close(self) -> None:
        """Signal worker to clear and close IPC connection, then join worker."""
        self._task_queue.put({"action": "CLOSE", "data": {}})
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)

    def set_client_id(self, new_client_id: str) -> None:
        """Switch Discord Application ID dynamically."""
        cleaned = new_client_id.strip()
        if self.client_id == cleaned:
            return
        logger.info("Switching RPC client ID from %s to %s", self.client_id, cleaned)
        self.client_id = cleaned
        # Clean up existing connection
        if self._presence:
            try:
                self._presence.clear()
            except Exception:
                pass
            try:
                self._presence.close()
            except Exception:
                pass
            self._presence = None
        self._is_connected = False
        self._is_active = False

    @property
    def is_active(self) -> bool:
        """Return True if Rich Presence is actively showing on Discord."""
        return self._is_active

    @property
    def is_connected(self) -> bool:
        """Return True if connected to Discord IPC."""
        return self._is_connected
