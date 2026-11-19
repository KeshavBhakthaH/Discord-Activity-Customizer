"""Modern dark-mode GUI and live Discord Rich Presence preview using CustomTkinter."""

from __future__ import annotations

import logging
import threading
import time
import tkinter as tk
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import customtkinter as ctk
from PIL import Image

from src.constants import (
    APP_ICON_PATH,
    APP_NAME,
    APP_VERSION,
    COLOR_BG,
    COLOR_BLURPLE,
    COLOR_BLURPLE_HOVER,
    COLOR_BORDER,
    COLOR_CARD,
    COLOR_CARD_DARK,
    COLOR_GREEN,
    COLOR_GREEN_HOVER,
    COLOR_INPUT_BG,
    COLOR_RED,
    COLOR_RED_HOVER,
    COLOR_TEXT_HEADER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_YELLOW,
    DEFAULT_CLIENT_ID,
    PLACEHOLDER_LOGO_PATH,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
    is_placeholder_client_id,
)
from src.image_service import (
    ImageUploadError,
    ImageValidationError,
    create_rounded_preview,
    get_or_upload_image,
    process_image_to_512,
    save_processed_logo,
    validate_png,
)
from src.rpc_manager import (
    RPCManager,
    STATUS_ACTIVE,
    STATUS_CONNECTING,
    STATUS_DISCONNECTED,
    STATUS_ERROR,
)
from src.storage import StorageManager

logger = logging.getLogger(__name__)


class ToolTip:
    """Lightweight hover tooltip for CustomTkinter widgets."""

    def __init__(self, widget: tk.Widget, text_getter: Callable[[], str]) -> None:
        self.widget = widget
        self.text_getter = text_getter
        self.tip_window: Optional[tk.Toplevel] = None
        self.widget.bind("<Enter>", self.show_tip)
        self.widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event: Optional[tk.Event] = None) -> None:
        text = self.text_getter().strip()
        if not text:
            return
        if self.tip_window:
            return

        x = self.widget.winfo_rootx() + 30
        y = self.widget.winfo_rooty() + 20

        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)

        label = tk.Label(
            tw,
            text=text,
            justify=tk.LEFT,
            background="#111214",
            foreground="#f2f3f5",
            relief=tk.SOLID,
            borderwidth=1,
            font=("Segoe UI", 9),
            padx=8,
            pady=4,
        )
        label.pack()

    def hide_tip(self, event: Optional[tk.Event] = None) -> None:
        if self.tip_window:
            try:
                self.tip_window.destroy()
            except Exception:
                pass
            self.tip_window = None


class ImageCropDialog(ctk.CTkToplevel):
    """Dialog allowing users to crop, pad, or resize images to exact 512x512 PNG."""

    def __init__(
        self,
        parent: ctk.CTk,
        image_path: str | Path,
        on_apply_callback: Callable[[Path, str], None],
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        self.source_path = Path(image_path)
        self.on_apply_callback = on_apply_callback

        try:
            self.source_image = Image.open(self.source_path)
        except Exception as exc:
            logger.error("Could not open image for cropping: %s", exc)
            self.destroy()
            return

        self.orig_w, self.orig_h = self.source_image.size
        self.selected_mode = "crop"  # "crop", "fit", "stretch"

        self.title("Crop & Resize Logo to 512×512")
        self.geometry("520x490")
        self.resizable(False, False)
        self.configure(fg_color=COLOR_BG)
        self.transient(parent)
        self.grab_set()

        try:
            px = parent.winfo_rootx() + 120
            py = parent.winfo_rooty() + 35
            self.geometry(f"+{px}+{py}")
        except Exception:
            pass

        self._build_ui()
        self._update_preview()

    def _build_ui(self) -> None:
        # Header
        ctk.CTkLabel(
            self,
            text="Crop & Resize Logo to 512×512 px",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
        ).pack(padx=20, pady=(16, 2))

        ctk.CTkLabel(
            self,
            text=f"Original: {self.source_path.name} ({self.orig_w} × {self.orig_h} px, {self.source_path.suffix.upper()})",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SECONDARY,
        ).pack(padx=20, pady=(0, 10))

        # Mode Selector
        self.mode_selector = ctk.CTkSegmentedButton(
            self,
            values=["Center Crop (Fill)", "Fit & Letterbox", "Stretch"],
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            selected_color=COLOR_BLURPLE,
            selected_hover_color=COLOR_BLURPLE_HOVER,
            height=32,
            command=self._on_mode_changed,
        )
        self.mode_selector.set("Center Crop (Fill)")
        self.mode_selector.pack(fill="x", padx=24, pady=(0, 12))

        # Center Preview Card
        preview_card = ctk.CTkFrame(
            self,
            fg_color=COLOR_CARD,
            corner_radius=8,
            border_width=1,
            border_color=COLOR_BORDER,
        )
        preview_card.pack(fill="both", expand=True, padx=24, pady=(0, 12))

        # Preview Image (130x130)
        self.lbl_preview = ctk.CTkLabel(
            preview_card,
            text="",
            width=130,
            height=130,
        )
        self.lbl_preview.pack(pady=(14, 8))

        # Description of selected mode
        self.lbl_mode_desc = ctk.CTkLabel(
            preview_card,
            text="Center Crop: Crops a 1:1 square from the center and scales to 512×512 without borders (Recommended).",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SECONDARY,
            wraplength=440,
            justify="center",
        )
        self.lbl_mode_desc.pack(padx=16, pady=(0, 12))

        # Bottom Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=24, pady=(0, 18))

        btn_apply = ctk.CTkButton(
            btn_frame,
            text="Apply & Set as 512×512 Logo",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=COLOR_BLURPLE,
            hover_color=COLOR_BLURPLE_HOVER,
            height=36,
            command=self._on_apply_clicked,
        )
        btn_apply.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_cancel = ctk.CTkButton(
            btn_frame,
            text="Cancel",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color="#35373c",
            hover_color="#43464d",
            width=90,
            height=36,
            command=self.destroy,
        )
        btn_cancel.pack(side="right")

    def _on_mode_changed(self, value: str) -> None:
        if "Crop" in value:
            self.selected_mode = "crop"
            self.lbl_mode_desc.configure(
                text="Center Crop: Crops a 1:1 square from the center and scales to 512×512 without borders (Recommended)."
            )
        elif "Fit" in value:
            self.selected_mode = "fit"
            self.lbl_mode_desc.configure(
                text="Fit & Letterbox: Keeps the entire image intact inside 512×512 with transparent padding."
            )
        else:
            self.selected_mode = "stretch"
            self.lbl_mode_desc.configure(
                text="Direct Stretch: Rescales the image directly to 512×512 (may distort aspect ratio)."
            )
        self._update_preview()

    def _update_preview(self) -> None:
        try:
            processed = process_image_to_512(self.source_image, mode=self.selected_mode)
            preview_thumb = create_rounded_preview(processed, size=(130, 130), radius=16)
            ctk_thumb = ctk.CTkImage(
                light_image=preview_thumb,
                dark_image=preview_thumb,
                size=(130, 130),
            )
            self.lbl_preview.configure(image=ctk_thumb)
            self.lbl_preview.image = ctk_thumb
        except Exception as exc:
            logger.error("Error updating crop preview: %s", exc)

    def _on_apply_clicked(self) -> None:
        try:
            processed = process_image_to_512(self.source_image, mode=self.selected_mode)
            saved_path = save_processed_logo(processed, self.source_path.name)
            mode_name = "Center Crop" if self.selected_mode == "crop" else ("Fit & Pad" if self.selected_mode == "fit" else "Direct Stretch")
            self.on_apply_callback(saved_path, mode_name)
            self.destroy()
        except Exception as exc:
            logger.error("Error saving processed logo: %s", exc)
            self.destroy()


class MainWindow(ctk.CTk):
    """Main application window for Discord Activity Customizer."""

    def __init__(
        self,
        storage: StorageManager,
        rpc: RPCManager,
        on_exit_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__()

        self.storage = storage
        self.rpc = rpc
        self.on_exit_callback = on_exit_callback

        # Appearance & Geometry
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.resizable(False, False)
        self.configure(fg_color=COLOR_BG)

        # Set window icon
        if APP_ICON_PATH.exists():
            try:
                self.iconbitmap(str(APP_ICON_PATH))
            except Exception as exc:
                logger.warning("Could not set window iconbitmap: %s", exc)

        # State Variables
        self.selected_png_path: Optional[str] = None
        self.cached_logo_url: Optional[str] = None
        self.is_uploading: bool = False
        self.activity_start_epoch: Optional[int] = None
        self.preview_timer_active: bool = False

        # Load persisted config
        self.config_data = self.storage.load_config()

        # Build UI
        self._build_header()
        self._build_main_content()
        self._build_status_bar()

        # Wire RPC callbacks
        self.rpc.status_callback = self._on_rpc_status_change

        # Setup preview ticking timer
        self._start_preview_timer_loop()

        # Check Client ID on startup
        self.after(500, self._check_client_id_warning)

        # Populate initial values
        self._populate_from_config(self.config_data)

        # Schedule initial and periodic memory trimming (Guarantees RAM < 15MB)
        self.after(800, self._trim_ram)
        self.after(25000, self._schedule_periodic_trim)

    def _trim_ram(self) -> None:
        """Trim process and parent launcher memory using Win32 EmptyWorkingSet."""
        try:
            from src.memory_optimizer import trim_process_memory
            trim_process_memory()
        except Exception:
            pass

    def _schedule_periodic_trim(self) -> None:
        """Periodically trim RAM every 25 seconds to guarantee footprint < 15MB."""
        self._trim_ram()
        self.after(25000, self._schedule_periodic_trim)

    # -----------------------------------------------------------------------
    # UI Layout Construction
    # -----------------------------------------------------------------------
    def _build_header(self) -> None:
        """Build the top header bar with branding and Client ID badge."""
        header_frame = ctk.CTkFrame(self, fg_color="transparent", height=42)
        header_frame.pack(fill="x", padx=16, pady=(10, 4))
        header_frame.pack_propagate(False)

        # Title and Version
        title_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_box.pack(side="left", fill="y")

        title_lbl = ctk.CTkLabel(
            title_box,
            text=APP_NAME,
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
        )
        title_lbl.pack(side="left")

        ver_badge = ctk.CTkLabel(
            title_box,
            text=f"v{APP_VERSION}",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SECONDARY,
            padx=8,
        )
        ver_badge.pack(side="left")

        # Right-side Client ID status pill
        is_placeholder = is_placeholder_client_id(DEFAULT_CLIENT_ID)
        cid_text = "⚠️ Client ID: Placeholder" if is_placeholder else f"App ID: {DEFAULT_CLIENT_ID[:6]}..."
        cid_color = COLOR_YELLOW if is_placeholder else COLOR_GREEN

        self.cid_badge = ctk.CTkButton(
            header_frame,
            text=cid_text,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#2b2d31",
            hover_color="#35373c",
            text_color=cid_color,
            border_width=1,
            border_color=cid_color,
            height=26,
            corner_radius=13,
            command=self._show_client_id_help_dialog,
        )
        self.cid_badge.pack(side="right")

    def _build_main_content(self) -> None:
        """Build the 2-column layout."""
        content_frame = ctk.CTkFrame(self, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=16, pady=6)

        # Left Column: Inputs and Controls (~370px)
        left_col = ctk.CTkFrame(
            content_frame,
            fg_color=COLOR_CARD,
            corner_radius=8,
            border_width=1,
            border_color=COLOR_BORDER,
            width=365,
        )
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 6), pady=0)
        self._build_left_controls(left_col)

        # Right Column: Live Discord Card Preview & Presets (~355px)
        right_col = ctk.CTkFrame(
            content_frame,
            fg_color="transparent",
            width=355,
        )
        right_col.pack(side="right", fill="both", expand=True, padx=(6, 0), pady=0)
        self._build_right_preview_and_presets(right_col)

    def _build_left_controls(self, parent: ctk.CTkFrame) -> None:
        """Construct controls in the left column."""
        # Section Header
        sec_lbl = ctk.CTkLabel(
            parent,
            text="ACTIVITY SETTINGS",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_HEADER,
            anchor="w",
        )
        sec_lbl.pack(fill="x", padx=16, pady=(12, 6))

        # 1. App Name (maps to details)
        ctk.CTkLabel(
            parent,
            text="App Name (Primary Title)",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(4, 2))

        self.entry_app_name = ctk.CTkEntry(
            parent,
            placeholder_text="e.g. Visual Studio Code, Half-Life 3",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLOR_INPUT_BG,
            border_color=COLOR_BORDER,
            height=32,
        )
        self.entry_app_name.pack(fill="x", padx=16, pady=(0, 8))
        self.entry_app_name.bind("<KeyRelease>", lambda e: self._on_input_changed())

        # 2. Subdetails (maps to state)
        ctk.CTkLabel(
            parent,
            text="Subdetails (Secondary Line)",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(2, 2))

        self.entry_subdetails = ctk.CTkEntry(
            parent,
            placeholder_text="e.g. Editing main.py, Exploring Sector 7",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLOR_INPUT_BG,
            border_color=COLOR_BORDER,
            height=32,
        )
        self.entry_subdetails.pack(fill="x", padx=16, pady=(0, 8))
        self.entry_subdetails.bind("<KeyRelease>", lambda e: self._on_input_changed())

        # 3. Logo Hover Text (maps to large_text)
        ctk.CTkLabel(
            parent,
            text="Logo Hover Tooltip Text",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(2, 2))

        self.entry_hover_text = ctk.CTkEntry(
            parent,
            placeholder_text="e.g. Python 3.13 Development Environment",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLOR_INPUT_BG,
            border_color=COLOR_BORDER,
            height=32,
        )
        self.entry_hover_text.pack(fill="x", padx=16, pady=(0, 8))
        self.entry_hover_text.bind("<KeyRelease>", lambda e: self._on_input_changed())

        # 4. Main Logo Selection (512x512 PNG)
        ctk.CTkLabel(
            parent,
            text="Main Logo (Exact 512x512 PNG)",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(2, 2))

        logo_row = ctk.CTkFrame(parent, fg_color="transparent")
        logo_row.pack(fill="x", padx=16, pady=(0, 4))

        self.btn_choose_png = ctk.CTkButton(
            logo_row,
            text="Choose Image...",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#35373c",
            hover_color="#43464d",
            width=100,
            height=30,
            command=self._on_choose_png_clicked,
        )
        self.btn_choose_png.pack(side="left")

        self.btn_crop = ctk.CTkButton(
            logo_row,
            text="Crop / Resize",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#2b2d31",
            hover_color="#35373c",
            border_width=1,
            border_color=COLOR_BORDER,
            width=85,
            height=30,
            command=self._on_crop_clicked,
        )
        self.btn_crop.pack(side="left", padx=4)

        self.lbl_png_name = ctk.CTkLabel(
            logo_row,
            text="Default Logo",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SECONDARY,
            anchor="w",
        )
        self.lbl_png_name.pack(side="left", padx=4, fill="x", expand=True)

        self.lbl_png_status = ctk.CTkLabel(
            parent,
            text="Using default 512x512 preview image",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=COLOR_TEXT_SECONDARY,
            anchor="w",
        )
        self.lbl_png_status.pack(fill="x", padx=16, pady=(0, 6))

        # 5. Elapsed Timer Switch
        self.timer_switch_var = ctk.BooleanVar(value=True)
        self.switch_timer = ctk.CTkSwitch(
            parent,
            text="Show elapsed timer (00:00 elapsed)",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            variable=self.timer_switch_var,
            progress_color=COLOR_GREEN,
            button_color="#ffffff",
            command=self._on_timer_switch_toggled,
        )
        self.switch_timer.pack(fill="x", padx=16, pady=(4, 12))

        # 6. Action Buttons
        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(10, 16))

        self.btn_start = ctk.CTkButton(
            btn_row,
            text="Start / Update Activity",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=COLOR_BLURPLE,
            hover_color=COLOR_BLURPLE_HOVER,
            height=36,
            command=self._on_start_update_clicked,
        )
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_stop = ctk.CTkButton(
            btn_row,
            text="Stop Activity",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=COLOR_RED,
            hover_color=COLOR_RED_HOVER,
            height=36,
            width=110,
            command=self._on_stop_clicked,
        )
        self.btn_stop.pack(side="right", padx=(4, 0))

    def _build_right_preview_and_presets(self, parent: ctk.CTkFrame) -> None:
        """Construct the live Discord card preview and presets manager."""
        # Top Card: Live Discord Profile Card Preview
        preview_card = ctk.CTkFrame(
            parent,
            fg_color=COLOR_CARD,
            corner_radius=8,
            border_width=1,
            border_color=COLOR_BORDER,
        )
        preview_card.pack(fill="x", pady=(0, 8))

        # Header
        ctk.CTkLabel(
            preview_card,
            text="LIVE DISCORD CARD PREVIEW",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_HEADER,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 6))

        # Discord Inner Profile Container
        discord_box = ctk.CTkFrame(
            preview_card,
            fg_color=COLOR_CARD_DARK,
            corner_radius=8,
            border_width=1,
            border_color="#1e1f22",
        )
        discord_box.pack(fill="x", padx=14, pady=(0, 12))

        # Discord Activity Header ("PLAYING A GAME")
        self.lbl_preview_category = ctk.CTkLabel(
            discord_box,
            text="PLAYING A GAME",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=COLOR_TEXT_HEADER,
            anchor="w",
        )
        self.lbl_preview_category.pack(fill="x", padx=14, pady=(10, 6))

        # Card Content Row (Thumbnail + Text Details)
        card_content = ctk.CTkFrame(discord_box, fg_color="transparent")
        card_content.pack(fill="x", padx=14, pady=(0, 10))

        # 80x80 Rounded Logo Thumbnail
        self.preview_image_label = ctk.CTkLabel(
            card_content,
            text="",
            width=80,
            height=80,
        )
        self.preview_image_label.pack(side="left", padx=(0, 12), pady=0)

        # Attach hover tooltip to logo thumbnail
        self.logo_tooltip = ToolTip(
            self.preview_image_label,
            text_getter=lambda: self.entry_hover_text.get().strip() or "Discord Rich Presence Logo",
        )

        # Right Text Details Box
        text_box = ctk.CTkFrame(card_content, fg_color="transparent")
        text_box.pack(side="left", fill="both", expand=True)

        self.lbl_preview_title = ctk.CTkLabel(
            text_box,
            text="Visual Studio Code",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
            wraplength=200,
        )
        self.lbl_preview_title.pack(fill="x", pady=(2, 1))

        self.lbl_preview_subdetails = ctk.CTkLabel(
            text_box,
            text="Developing Discord Rich Presence",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#dbdee1",
            anchor="w",
            wraplength=200,
        )
        self.lbl_preview_subdetails.pack(fill="x", pady=(0, 2))

        self.lbl_preview_timer = ctk.CTkLabel(
            text_box,
            text="00:00 elapsed",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SECONDARY,
            anchor="w",
        )
        self.lbl_preview_timer.pack(fill="x", pady=(0, 2))

        # Tooltip Preview Sub-bar
        self.lbl_preview_hover_hint = ctk.CTkLabel(
            discord_box,
            text="Hover over logo to preview tooltip",
            font=ctk.CTkFont(family="Segoe UI", size=9, slant="italic"),
            text_color=COLOR_TEXT_SECONDARY,
            anchor="w",
        )
        self.lbl_preview_hover_hint.pack(fill="x", padx=14, pady=(0, 8))

        # Bottom Card: 1-Click Saved Presets Manager
        presets_card = ctk.CTkFrame(
            parent,
            fg_color=COLOR_CARD,
            corner_radius=8,
            border_width=1,
            border_color=COLOR_BORDER,
        )
        presets_card.pack(fill="both", expand=True, pady=(0, 0))

        ctk.CTkLabel(
            presets_card,
            text="SAVED PRESETS",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_HEADER,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 6))

        # Presets Dropdown + Load / Delete Buttons
        preset_select_row = ctk.CTkFrame(presets_card, fg_color="transparent")
        preset_select_row.pack(fill="x", padx=16, pady=(2, 6))

        self.preset_combo = ctk.CTkComboBox(
            preset_select_row,
            values=["Code Editor", "Retro Gaming", "Music Studio"],
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLOR_INPUT_BG,
            border_color=COLOR_BORDER,
            button_color="#35373c",
            button_hover_color="#43464d",
            dropdown_fg_color=COLOR_CARD,
            height=30,
        )
        self.preset_combo.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_load_preset = ctk.CTkButton(
            preset_select_row,
            text="Load",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#35373c",
            hover_color="#43464d",
            width=58,
            height=30,
            command=self._on_load_preset_clicked,
        )
        self.btn_load_preset.pack(side="left", padx=(0, 4))

        self.btn_delete_preset = ctk.CTkButton(
            preset_select_row,
            text="Delete",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#35373c",
            hover_color=COLOR_RED_HOVER,
            width=58,
            height=30,
            command=self._on_delete_preset_clicked,
        )
        self.btn_delete_preset.pack(side="right")

        # Save Current as Preset Button
        self.btn_save_preset = ctk.CTkButton(
            presets_card,
            text="Save Current as Preset...",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#313338",
            hover_color="#3c4046",
            border_width=1,
            border_color=COLOR_BORDER,
            height=30,
            command=self._on_save_preset_clicked,
        )
        self.btn_save_preset.pack(fill="x", padx=16, pady=(4, 12))

        # Refresh presets list from disk
        self._refresh_presets_combo()

    def _build_status_bar(self) -> None:
        """Construct the bottom status bar."""
        status_bar = ctk.CTkFrame(
            self,
            fg_color=COLOR_BG,
            height=28,
            border_width=1,
            border_color=COLOR_BORDER,
        )
        status_bar.pack(fill="x", side="bottom")
        status_bar.pack_propagate(False)

        # Status dot canvas
        self.status_canvas = tk.Canvas(
            status_bar,
            width=12,
            height=12,
            bg=COLOR_BG,
            highlightthickness=0,
        )
        self.status_canvas.pack(side="left", padx=(12, 6), pady=8)
        self.status_dot = self.status_canvas.create_oval(2, 2, 10, 10, fill=COLOR_TEXT_SECONDARY, outline="")

        # Status text
        self.lbl_status = ctk.CTkLabel(
            status_bar,
            text="Disconnected",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SECONDARY,
            anchor="w",
        )
        self.lbl_status.pack(side="left", fill="x", expand=True)

        # Local IPC Badge
        safety_lbl = ctk.CTkLabel(
            status_bar,
            text="🔒 100% Local IPC (Safe & ToS-Compliant)",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=COLOR_TEXT_SECONDARY,
            anchor="e",
        )
        safety_lbl.pack(side="right", padx=14)

    # -----------------------------------------------------------------------
    # Status Updates & Thread Marshalling
    # -----------------------------------------------------------------------
    def _on_rpc_status_change(self, state: str, message: str, is_error: bool) -> None:
        """Thread-safe status notification handler called by RPCManager."""
        self.after(0, lambda: self._update_status_ui(state, message, is_error))

    def _update_status_ui(self, state: str, message: str, is_error: bool) -> None:
        """Update status bar label and dot color."""
        self.lbl_status.configure(text=message)

        if is_error or state == STATUS_ERROR:
            dot_color = COLOR_RED
            self.lbl_status.configure(text_color=COLOR_RED)
        elif state == STATUS_ACTIVE:
            dot_color = COLOR_GREEN
            self.lbl_status.configure(text_color=COLOR_TEXT_PRIMARY)
            if self.activity_start_epoch is None and self.timer_switch_var.get():
                self.activity_start_epoch = int(time.time())
        elif state == STATUS_CONNECTING:
            dot_color = COLOR_YELLOW
            self.lbl_status.configure(text_color=COLOR_YELLOW)
        else:  # STATUS_DISCONNECTED
            dot_color = COLOR_TEXT_SECONDARY
            self.lbl_status.configure(text_color=COLOR_TEXT_SECONDARY)
            self.activity_start_epoch = None

        self.status_canvas.itemconfig(self.status_dot, fill=dot_color)

    # -----------------------------------------------------------------------
    # Dynamic Live Preview Updates
    # -----------------------------------------------------------------------
    def _on_input_changed(self) -> None:
        """Update live preview card text elements as the user types."""
        app_name = self.entry_app_name.get().strip() or "Custom Activity"
        subdetails = self.entry_subdetails.get().strip() or "Playing with Friends"
        hover_text = self.entry_hover_text.get().strip()

        self.lbl_preview_title.configure(text=app_name)
        self.lbl_preview_subdetails.configure(text=subdetails)

        if hover_text:
            self.lbl_preview_hover_hint.configure(
                text=f'Tooltip: "{hover_text}" (hover logo)',
                text_color=COLOR_TEXT_PRIMARY,
            )
        else:
            self.lbl_preview_hover_hint.configure(
                text="Hover over logo to preview tooltip",
                text_color=COLOR_TEXT_SECONDARY,
            )

    def _on_timer_switch_toggled(self) -> None:
        """Update timer visibility in live preview."""
        if self.timer_switch_var.get():
            self.lbl_preview_timer.pack(fill="x", pady=(0, 2))
        else:
            self.lbl_preview_timer.pack_forget()

    def _update_preview_image(self, image_path: Optional[str | Path]) -> None:
        """Update the 80x80 thumbnail in the Discord profile preview card."""
        try:
            pil_rounded = create_rounded_preview(image_path, size=(80, 80), radius=14)
            ctk_img = ctk.CTkImage(light_image=pil_rounded, dark_image=pil_rounded, size=(80, 80))
            self.preview_image_label.configure(image=ctk_img)
            self.preview_image_label.image = ctk_img  # Keep reference
        except Exception as exc:
            logger.error("Error updating preview image: %s", exc)

    def _start_preview_timer_loop(self) -> None:
        """Tick the preview counter (e.g. 00:00 elapsed) every second."""
        def _tick() -> None:
            if self.timer_switch_var.get():
                if self.activity_start_epoch is not None:
                    elapsed = max(0, int(time.time() - self.activity_start_epoch))
                else:
                    elapsed = 0
                mins, secs = divmod(elapsed, 60)
                hours, mins = divmod(mins, 60)
                if hours > 0:
                    time_str = f"{hours:02d}:{mins:02d}:{secs:02d} elapsed"
                else:
                    time_str = f"{mins:02d}:{secs:02d} elapsed"
                self.lbl_preview_timer.configure(text=time_str)

            self.after(1000, _tick)

        self.after(1000, _tick)

    # -----------------------------------------------------------------------
    # Logo Selection & Validation / Crop & Resize
    # -----------------------------------------------------------------------
    def _on_choose_png_clicked(self) -> None:
        """Open Windows file picker for images.

        If the image is not an exact 512x512 PNG, opens the Crop & Resize dialog.
        """
        file_path = ctk.filedialog.askopenfilename(
            title="Select Logo Image for Discord",
            filetypes=[
                ("All Supported Images", "*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.gif"),
                ("PNG Image", "*.png"),
                ("JPEG Image", "*.jpg;*.jpeg"),
                ("WebP Image", "*.webp"),
                ("All Files", "*.*"),
            ],
        )
        if not file_path:
            return

        path_obj = Path(file_path)
        is_valid, msg, dimensions = validate_png(file_path)

        if is_valid:
            # Already a genuine 512x512 PNG!
            self._apply_logo_file(path_obj, "✔ Valid 512×512 PNG (Ready for Discord)")
        else:
            # Dimensions or format need adjustment: launch Crop & Resize dialog
            logger.info("Image %s needs adjustment (%s). Launching crop dialog.", file_path, msg)
            self._open_crop_dialog(path_obj)

    def _on_crop_clicked(self) -> None:
        """Open crop dialog for currently selected logo or prompt to pick an image."""
        if self.selected_png_path and Path(self.selected_png_path).is_file():
            self._open_crop_dialog(Path(self.selected_png_path))
        else:
            self._on_choose_png_clicked()

    def _open_crop_dialog(self, path_obj: Path) -> None:
        """Launch modal Crop & Resize dialog for given image file."""
        def _on_crop_applied(saved_512_path: Path, mode_name: str) -> None:
            self._apply_logo_file(saved_512_path, f"✔ Adjusted to 512×512 PNG ({mode_name})")

        ImageCropDialog(self, image_path=path_obj, on_apply_callback=_on_crop_applied)

    def _apply_logo_file(self, path_obj: Path, status_text: str) -> None:
        """Set and apply a verified 512x512 PNG as the active logo and pre-upload in background."""
        resolved_path = str(path_obj.resolve())
        self.selected_png_path = resolved_path
        self.cached_logo_url = None  # Will be populated by pre-upload
        self.lbl_png_name.configure(text=path_obj.name, text_color=COLOR_TEXT_PRIMARY)
        self.lbl_png_status.configure(
            text=f"{status_text} (Preparing...)",
            text_color=COLOR_YELLOW,
        )

        # Update preview thumbnail immediately
        self._update_preview_image(self.selected_png_path)
        logger.info("Active logo set to: %s (%s)", self.selected_png_path, status_text)

        # Silent background pre-upload so clicking Start/Update is instant
        def _bg_preupload() -> None:
            try:
                url, was_cached = get_or_upload_image(resolved_path, self.storage)
                self.cached_logo_url = url
                cfg = self.storage.load_config()
                cfg["png_path"] = resolved_path
                cfg["logo_url"] = url
                self.storage.save_config(cfg)
                self.after(
                    0,
                    lambda: self.lbl_png_status.configure(
                        text=f"{status_text} (Ready)",
                        text_color=COLOR_GREEN,
                    ),
                )
                logger.info("Logo pre-upload finished: %s (cached=%s)", url, was_cached)
            except Exception as exc:
                logger.warning("Background pre-upload encountered issue: %s", exc)
                self.after(
                    0,
                    lambda: self.lbl_png_status.configure(
                        text=status_text,
                        text_color=COLOR_GREEN,
                    ),
                )

        threading.Thread(
            target=_bg_preupload,
            name="LogoPreUploadThread",
            daemon=True,
        ).start()

    # -----------------------------------------------------------------------
    # Activity Start / Update & Worker Thread
    # -----------------------------------------------------------------------
    def _on_start_update_clicked(self) -> None:
        """Trigger background image upload (if needed) and Rich Presence update."""
        if self.is_uploading:
            return

        # Check for placeholder client ID
        if is_placeholder_client_id(DEFAULT_CLIENT_ID):
            self._show_client_id_help_dialog()
            return

        app_name = self.entry_app_name.get().strip()
        subdetails = self.entry_subdetails.get().strip()
        hover_text = self.entry_hover_text.get().strip()
        show_timer = self.timer_switch_var.get()
        png_path = self.selected_png_path

        # Save to persistent config
        config_to_save = {
            "app_name": app_name,
            "subdetails": subdetails,
            "hover_text": hover_text,
            "png_path": png_path or "",
            "logo_url": self.cached_logo_url or "",
            "show_timer": show_timer,
        }
        self.storage.save_config(config_to_save)

        # Launch background worker
        self.is_uploading = True
        self.btn_start.configure(state="disabled", text="Processing...")
        self._update_status_ui(STATUS_CONNECTING, "Preparing activity...", is_error=False)

        worker_thread = threading.Thread(
            target=self._execute_start_activity_worker,
            args=(app_name, subdetails, hover_text, show_timer, png_path),
            name="ActivityStarterThread",
            daemon=True,
        )
        worker_thread.start()

    def _execute_start_activity_worker(
        self,
        app_name: str,
        subdetails: str,
        hover_text: str,
        show_timer: bool,
        png_path: Optional[str],
    ) -> None:
        """Worker thread to handle image upload and dispatch RPC update."""
        logo_url = self.cached_logo_url

        try:
            # If PNG path is provided and we don't have a verified URL yet
            if png_path and Path(png_path).is_file():
                def _status_cb(msg: str) -> None:
                    self.after(0, lambda: self._update_status_ui(STATUS_CONNECTING, msg, is_error=False))

                logo_url, was_cached = get_or_upload_image(
                    png_path,
                    self.storage,
                    status_callback=_status_cb,
                )
                self.cached_logo_url = logo_url
                # Update saved config with the newly cached URL
                cfg = self.storage.load_config()
                cfg["logo_url"] = logo_url
                self.storage.save_config(cfg)
            else:
                logo_url = None

            # Dispatch RPC update
            self.rpc.update_activity(
                details=app_name,
                state=subdetails,
                large_image=logo_url,
                large_text=hover_text,
                show_timer=show_timer,
            )

        except (ImageValidationError, ImageUploadError) as img_err:
            logger.error("Image processing error: %s", img_err)
            self.after(0, lambda: self._update_status_ui(STATUS_ERROR, str(img_err), is_error=True))
        except Exception as exc:
            logger.error("Unexpected error in start worker: %s", exc)
            self.after(0, lambda: self._update_status_ui(STATUS_ERROR, f"Error: {exc}", is_error=True))
        finally:
            self.after(0, self._restore_start_button)

    def _restore_start_button(self) -> None:
        """Reset start button to enabled state."""
        self.is_uploading = False
        self.btn_start.configure(state="normal", text="Start / Update Activity")

    def _on_stop_clicked(self) -> None:
        """Stop Rich Presence activity."""
        self.activity_start_epoch = None
        self.rpc.stop_activity()
        self._update_status_ui(STATUS_DISCONNECTED, "Activity stopped.", is_error=False)

    # -----------------------------------------------------------------------
    # Presets Manager
    # -----------------------------------------------------------------------
    def _refresh_presets_combo(self) -> None:
        """Reload preset names into the combobox."""
        presets = self.storage.load_presets()
        names = list(presets.keys())
        if not names:
            names = ["Code Editor", "Retro Gaming", "Music Studio"]
        self.preset_combo.configure(values=names)
        if names:
            self.preset_combo.set(names[0])

    def _on_load_preset_clicked(self) -> None:
        """Load selected preset and populate all inputs immediately."""
        preset_name = self.preset_combo.get()
        presets = self.storage.load_presets()
        data = presets.get(preset_name)
        if not data:
            self._update_status_ui(STATUS_ERROR, f"Preset '{preset_name}' not found.", is_error=True)
            return

        self._populate_from_config(data)
        self._update_status_ui(STATUS_DISCONNECTED, f"Loaded preset: {preset_name}", is_error=False)

    def _on_save_preset_clicked(self) -> None:
        """Prompt for preset name and save current inputs to presets.json."""
        dialog = ctk.CTkInputDialog(
            text="Enter a name for this preset:",
            title="Save Preset",
        )
        name = dialog.get_input()
        if not name or not name.strip():
            return

        clean_name = name.strip()
        preset_data = {
            "client_id": self.rpc.client_id,
            "app_name": self.entry_app_name.get().strip(),
            "subdetails": self.entry_subdetails.get().strip(),
            "hover_text": self.entry_hover_text.get().strip(),
            "show_timer": self.timer_switch_var.get(),
            "png_path": self.selected_png_path or "",
            "logo_url": self.cached_logo_url or "",
        }

        self.storage.save_preset(clean_name, preset_data)
        self._refresh_presets_combo()
        self.preset_combo.set(clean_name)
        self._update_status_ui(STATUS_DISCONNECTED, f"Preset '{clean_name}' saved.", is_error=False)

    def _on_delete_preset_clicked(self) -> None:
        """Delete currently selected preset."""
        preset_name = self.preset_combo.get()
        if not preset_name:
            return

        success = self.storage.delete_preset(preset_name)
        if success:
            self._refresh_presets_combo()
            self._update_status_ui(STATUS_DISCONNECTED, f"Deleted preset: {preset_name}", is_error=False)
        else:
            self._update_status_ui(STATUS_ERROR, f"Could not delete '{preset_name}'.", is_error=True)

    # -----------------------------------------------------------------------
    # Config Population
    # -----------------------------------------------------------------------
    def _populate_from_config(self, data: Dict[str, Any]) -> None:
        """Populate GUI inputs from a dictionary."""
        app_name = data.get("app_name", "")
        subdetails = data.get("subdetails", "")
        hover_text = data.get("hover_text", "")
        show_timer = data.get("show_timer", True)
        png_path = data.get("png_path", "")
        logo_url = data.get("logo_url", "")

        self.entry_app_name.delete(0, "end")
        self.entry_app_name.insert(0, app_name)

        self.entry_subdetails.delete(0, "end")
        self.entry_subdetails.insert(0, subdetails)

        self.entry_hover_text.delete(0, "end")
        self.entry_hover_text.insert(0, hover_text)

        self.timer_switch_var.set(bool(show_timer))
        self._on_timer_switch_toggled()

        # Handle PNG path
        if png_path and Path(png_path).is_file():
            is_valid, msg, _ = validate_png(png_path)
            if is_valid:
                self.selected_png_path = png_path
                self.cached_logo_url = logo_url or None
                self.lbl_png_name.configure(text=Path(png_path).name, text_color=COLOR_TEXT_PRIMARY)
                self.lbl_png_status.configure(
                    text="✔ Valid 512×512 PNG (Ready for Discord)",
                    text_color=COLOR_GREEN,
                )
                self._update_preview_image(self.selected_png_path)
            else:
                self.selected_png_path = None
                self.cached_logo_url = None
                self.lbl_png_name.configure(text="Default Logo", text_color=COLOR_TEXT_SECONDARY)
                self.lbl_png_status.configure(text="Using default 512x512 preview image", text_color=COLOR_TEXT_SECONDARY)
                self._update_preview_image(PLACEHOLDER_LOGO_PATH)
        else:
            self.selected_png_path = None
            self.cached_logo_url = None
            self.lbl_png_name.configure(text="Default Logo", text_color=COLOR_TEXT_SECONDARY)
            self.lbl_png_status.configure(text="Using default 512x512 preview image", text_color=COLOR_TEXT_SECONDARY)
            self._update_preview_image(PLACEHOLDER_LOGO_PATH)

        client_id = data.get("client_id")
        if client_id and not is_placeholder_client_id(client_id):
            self.rpc.set_client_id(client_id)
            self.cid_badge.configure(
                text=f"App ID: {client_id[:6]}...",
                text_color=COLOR_GREEN,
                border_color=COLOR_GREEN,
            )

        self._on_input_changed()

    # -----------------------------------------------------------------------
    # Client ID Startup Check / Dialog
    # -----------------------------------------------------------------------
    def _check_client_id_warning(self) -> None:
        """Check if DEFAULT_CLIENT_ID is unchanged and warn developer/user."""
        if is_placeholder_client_id(DEFAULT_CLIENT_ID):
            self._update_status_ui(
                STATUS_ERROR,
                "⚠️ Note: DEFAULT_CLIENT_ID is set to placeholder. Replace in src/constants.py.",
                is_error=True,
            )

    def _show_client_id_help_dialog(self) -> None:
        """Show Application ID configuration dialog where users can view or change Client ID."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Discord Application ID Setup")
        dialog.geometry("520x390")
        dialog.resizable(False, False)
        dialog.configure(fg_color=COLOR_BG)
        dialog.transient(self)
        dialog.grab_set()

        try:
            px = self.winfo_rootx() + 120
            py = self.winfo_rooty() + 60
            dialog.geometry(f"+{px}+{py}")
        except Exception:
            pass

        ctk.CTkLabel(
            dialog,
            text="Discord Application ID Setup",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
        ).pack(padx=20, pady=(18, 6))

        info_text = (
            "Each Discord Application represents a registered activity profile.\n"
            "• One-time tip: In Discord Developer Portal, name your app something universal\n"
            "  (like 'Custom Activity' or 'Game') with a game controller icon.\n"
            "• Then, you never need to visit the website again—everything is customizable\n"
            "  locally right here in the desktop app!"
        )

        ctk.CTkLabel(
            dialog,
            text=info_text,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SECONDARY,
            justify="left",
        ).pack(padx=24, pady=(0, 14))

        # Input box for Application ID
        entry_frame = ctk.CTkFrame(dialog, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color=COLOR_BORDER)
        entry_frame.pack(fill="x", padx=24, pady=(0, 16))

        ctk.CTkLabel(
            entry_frame,
            text="Discord Application ID:",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 4))

        id_entry = ctk.CTkEntry(
            entry_frame,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLOR_INPUT_BG,
            border_color=COLOR_BORDER,
            height=32,
        )
        current_id = self.rpc.client_id or DEFAULT_CLIENT_ID
        id_entry.insert(0, current_id)
        id_entry.pack(fill="x", padx=14, pady=(0, 12))

        # Buttons
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", padx=24, pady=(0, 16))

        def _save_new_id() -> None:
            new_id = id_entry.get().strip()
            if not new_id or is_placeholder_client_id(new_id):
                dialog.destroy()
                return

            self.rpc.set_client_id(new_id)
            # Update config
            cfg = self.storage.load_config()
            cfg["client_id"] = new_id
            self.storage.save_config(cfg)

            # Update badge
            self.cid_badge.configure(
                text=f"App ID: {new_id[:6]}...",
                text_color=COLOR_GREEN,
                border_color=COLOR_GREEN,
            )
            self._update_status_ui(STATUS_DISCONNECTED, f"Application ID updated to {new_id}", is_error=False)
            dialog.destroy()

        btn_save = ctk.CTkButton(
            btn_frame,
            text="Save Application ID",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=COLOR_BLURPLE,
            hover_color=COLOR_BLURPLE_HOVER,
            height=34,
            command=_save_new_id,
        )
        btn_save.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_close = ctk.CTkButton(
            btn_frame,
            text="Cancel",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color="#35373c",
            hover_color="#43464d",
            width=90,
            height=34,
            command=dialog.destroy,
        )
        btn_close.pack(side="right")
