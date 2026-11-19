"""System tray management using pystray with non-blocking thread-safe controls."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Optional

import pystray
from PIL import Image

from src.constants import APP_ICON_PATH, APP_NAME, ensure_default_assets

logger = logging.getLogger(__name__)


class TrayManager:
    """Manages the Windows System Tray icon, menu actions, and window visibility."""

    def __init__(
        self,
        show_window_fn: Callable[[], None],
        stop_activity_fn: Callable[[], None],
        quit_app_fn: Callable[[], None],
    ) -> None:
        """Initialize system tray manager.

        Args:
            show_window_fn: Callback to restore and focus the GUI window.
            stop_activity_fn: Callback to clear the active Discord Rich Presence.
            quit_app_fn: Callback to terminate the entire application cleanly.
        """
        self._show_window_fn = show_window_fn
        self._stop_activity_fn = stop_activity_fn
        self._quit_app_fn = quit_app_fn

        self._icon: Optional[pystray.Icon] = None
        self._tray_thread: Optional[threading.Thread] = None
        self._is_running = False

    def _load_tray_image(self) -> Image.Image:
        """Load or create the icon image for the system tray."""
        ensure_default_assets()
        try:
            if APP_ICON_PATH.exists():
                with Image.open(APP_ICON_PATH) as img:
                    return img.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
        except Exception as exc:
            logger.warning("Failed to load app icon for tray: %s. Generating fallback.", exc)

        # Fallback 64x64 image
        fallback = Image.new("RGBA", (64, 64), (88, 101, 242, 255))
        return fallback

    def start(self) -> None:
        """Start the system tray icon in a dedicated daemon thread."""
        if self._is_running:
            return

        icon_image = self._load_tray_image()

        menu = pystray.Menu(
            pystray.MenuItem("Show Customizer", self._on_menu_show, default=True),
            pystray.MenuItem("Stop Activity", self._on_menu_stop),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._on_menu_quit),
        )

        self._icon = pystray.Icon(
            name="DiscordActivityCustomizer",
            icon=icon_image,
            title=APP_NAME,
            menu=menu,
        )

        self._is_running = True
        self._tray_thread = threading.Thread(
            target=self._run_icon,
            name="SystemTrayThread",
            daemon=True,
        )
        self._tray_thread.start()
        logger.info("System tray initialized.")

    def _run_icon(self) -> None:
        """Target loop for system tray thread."""
        try:
            if self._icon:
                self._icon.run()
        except Exception as exc:
            logger.error("Error in system tray run loop: %s", exc)
        finally:
            self._is_running = False

    # -----------------------------------------------------------------------
    # Tray Menu Event Handlers
    # -----------------------------------------------------------------------
    def _on_menu_show(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """Handle 'Show Customizer' action."""
        try:
            self._show_window_fn()
        except Exception as exc:
            logger.error("Error invoking show_window_fn: %s", exc)

    def _on_menu_stop(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """Handle 'Stop Activity' action."""
        try:
            self._stop_activity_fn()
        except Exception as exc:
            logger.error("Error invoking stop_activity_fn: %s", exc)

    def _on_menu_quit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """Handle 'Quit' action."""
        try:
            self.stop()
        except Exception:
            pass
        try:
            self._quit_app_fn()
        except Exception as exc:
            logger.error("Error invoking quit_app_fn: %s", exc)

    def stop(self) -> None:
        """Stop and remove the system tray icon."""
        if self._icon and self._is_running:
            try:
                self._icon.stop()
            except Exception as exc:
                logger.warning("Error stopping tray icon: %s", exc)
            self._is_running = False
