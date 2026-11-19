"""Entry point wiring UI, RPC Manager, and System Tray for Discord Activity Customizer."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("DiscordActivityCustomizer")

from src.constants import (
    DEFAULT_CLIENT_ID,
    ensure_appdata_dir,
    ensure_default_assets,
    is_placeholder_client_id,
)
from src.rpc_manager import RPCManager
from src.storage import StorageManager
from src.tray_manager import TrayManager
from src.ui import MainWindow


def ensure_start_menu_shortcut() -> None:
    """Ensure a Start Menu shortcut exists so Windows Search indexes the app without .exe."""
    try:
        appdata = os.getenv("APPDATA")
        if not appdata:
            return
        programs_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        shortcut_file = programs_dir / "Discord Activity Customizer.lnk"
        if shortcut_file.exists():
            return

        if getattr(sys, "frozen", False):
            target_exe = Path(sys.executable).resolve()
        else:
            target_exe = Path(__file__).resolve().parent / "dist" / "DiscordActivityCustomizer.exe"
            if not target_exe.exists():
                return

        icon_path = Path(__file__).resolve().parent / "assets" / "app_icon.ico"
        icon_arg = f"$s.IconLocation = '{icon_path}, 0'; " if icon_path.exists() else ""

        ps_script = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{shortcut_file}'); "
            f"$s.TargetPath = '{target_exe}'; "
            f"$s.WorkingDirectory = '{target_exe.parent}'; "
            f"{icon_arg}"
            f"$s.Description = 'Customize Discord Rich Presence locally'; "
            f"$s.Save()"
        )
        import subprocess

        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
            creationflags=0x08000000,
            check=False,
            timeout=5,
        )
        logger.info("Created Start Menu shortcut at %s", shortcut_file)
    except Exception as exc:
        logger.debug("Failed to ensure Start Menu shortcut: %s", exc)


def main() -> None:
    """Initialize and run Discord Activity Customizer."""
    # 0. Enforce Single Instance
    from src.single_instance import SingleInstanceManager

    single_instance_mgr = SingleInstanceManager()
    if not single_instance_mgr.check_single_instance():
        logger.info("Another instance is already running. Brought it to foreground. Exiting duplicate.")
        sys.exit(0)

    logger.info("Initializing Discord Activity Customizer...")

    # 1. Ensure %APPDATA% directory, default assets, and Start Menu shortcut exist
    ensure_appdata_dir()
    ensure_default_assets()
    ensure_start_menu_shortcut()

    # 2. Check Client ID status
    if is_placeholder_client_id(DEFAULT_CLIENT_ID):
        logger.warning(
            "DEFAULT_CLIENT_ID is not configured in src/constants.py. "
            "Local Discord RPC will require a valid Discord Application ID."
        )

    # 3. Initialize Persistent Storage & RPC Manager
    storage = StorageManager()
    rpc = RPCManager(client_id=DEFAULT_CLIENT_ID)

    # 4. Initialize UI Window
    app = MainWindow(storage=storage, rpc=rpc)

    # 5. Tray Action Callbacks
    def show_window() -> None:
        """Restore and bring the application window to foreground."""
        def _restore() -> None:
            app.deiconify()
            app.lift()
            app.focus_force()
            app.state("normal")
        app.after(0, _restore)

    # Listen for secondary instance launch events to bring window to front
    single_instance_mgr.start_show_listener(show_window)

    def stop_activity_action() -> None:
        """Stop activity from system tray menu."""
        app.after(0, app._on_stop_clicked)

    def quit_application() -> None:
        """Cleanly terminate RPC, system tray, and main application window."""
        logger.info("Quitting application...")
        def _clean_exit() -> None:
            try:
                rpc.stop_activity()
                rpc.close()
            except Exception as exc:
                logger.warning("Error stopping RPC on exit: %s", exc)

            try:
                tray.stop()
            except Exception as exc:
                logger.warning("Error stopping tray on exit: %s", exc)

            try:
                app.quit()
                app.destroy()
            except Exception as exc:
                logger.warning("Error destroying window on exit: %s", exc)

            try:
                single_instance_mgr.close()
            except Exception:
                pass

            sys.exit(0)

        app.after(0, _clean_exit)

    # 6. Initialize System Tray Manager
    tray = TrayManager(
        show_window_fn=show_window,
        stop_activity_fn=stop_activity_action,
        quit_app_fn=quit_application,
    )
    tray.start()

    # 7. Intercept Window Close (WM_DELETE_WINDOW) to hide to System Tray
    def on_window_close_clicked() -> None:
        """Minimize to system tray instead of exiting."""
        logger.info("Window close requested. Minimizing to system tray.")
        app.withdraw()
        try:
            from src.memory_optimizer import trim_process_memory
            trim_process_memory()
        except Exception:
            pass

    app.protocol("WM_DELETE_WINDOW", on_window_close_clicked)

    # 8. Run CustomTkinter Main Loop
    try:
        app.mainloop()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received.")
        quit_application()
    except Exception as exc:
        logger.exception("Unexpected exception in main loop: %s", exc)
        quit_application()


if __name__ == "__main__":
    main()
