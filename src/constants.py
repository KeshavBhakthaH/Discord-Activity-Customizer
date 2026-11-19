"""Application-wide constants, styling configuration, and path helpers for Discord Activity Customizer."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Final, Tuple

# ---------------------------------------------------------------------------
# Application Metadata
# ---------------------------------------------------------------------------
APP_NAME: Final[str] = "Discord Activity Customizer"
APP_VERSION: Final[str] = "1.0.0"
APP_DESCRIPTION: Final[str] = (
    "Production-ready Windows desktop app to customize Discord Rich Presence locally via IPC."
)

# ---------------------------------------------------------------------------
# Discord RPC Configuration
# ---------------------------------------------------------------------------
# IMPORTANT: Replace with your actual Discord Application ID from
# https://discord.com/developers/applications
DEFAULT_CLIENT_ID: Final[str] = "1545379229758394518"
PLACEHOLDER_CLIENT_ID: Final[str] = "YOUR_APPLICATION_ID_HERE"

def is_placeholder_client_id(client_id: str | None) -> bool:
    """Check if the provided client ID is a placeholder or not a valid snowflake ID."""
    if not client_id:
        return True
    cleaned = client_id.strip()
    if cleaned == PLACEHOLDER_CLIENT_ID:
        return True
    if not cleaned.isdigit() or len(cleaned) < 17 or len(cleaned) > 21:
        return True
    return False

# ---------------------------------------------------------------------------
# Validation & Limits
# ---------------------------------------------------------------------------
REQUIRED_PNG_SIZE: Final[Tuple[int, int]] = (512, 512)
MAX_PNG_SIZE_BYTES: Final[int] = 5 * 1024 * 1024  # 5 MB
MAX_DISCORD_URL_LENGTH: Final[int] = 254          # Discord RPC URL length limit
MIN_FIELD_LENGTH: Final[int] = 2                  # Discord RPC minimum string length
MAX_FIELD_LENGTH: Final[int] = 128                # Discord RPC maximum string length

FREEIMAGE_API_URL: Final[str] = "https://freeimage.host/api/1/upload"
FREEIMAGE_API_KEY: Final[str] = "6d207e02198a847aa98d0a2a901485a5"
CATBOX_API_URL: Final[str] = "https://catbox.moe/user/api.php"

# ---------------------------------------------------------------------------
# GUI Colors (Discord Theme)
# ---------------------------------------------------------------------------
COLOR_BG: Final[str] = "#1e1f22"             # Discord app background
COLOR_CARD: Final[str] = "#2b2d31"           # Discord cards/containers
COLOR_CARD_DARK: Final[str] = "#111214"      # Discord profile preview background
COLOR_CARD_HOVER: Final[str] = "#313338"     # Discord element hover
COLOR_BORDER: Final[str] = "#35373c"         # Subtle borders
COLOR_INPUT_BG: Final[str] = "#1e1f22"       # Input box background
COLOR_TEXT_PRIMARY: Final[str] = "#f2f3f5"   # Primary crisp white text
COLOR_TEXT_SECONDARY: Final[str] = "#949ba4" # Secondary muted gray text
COLOR_TEXT_HEADER: Final[str] = "#b5bac1"    # Category/header gray text

COLOR_BLURPLE: Final[str] = "#5865f2"        # Discord blurple primary button
COLOR_BLURPLE_HOVER: Final[str] = "#4752c4"  # Discord blurple hover
COLOR_GREEN: Final[str] = "#23a55a"          # Active / online green
COLOR_GREEN_HOVER: Final[str] = "#1f8b4c"    # Active hover
COLOR_RED: Final[str] = "#da373c"            # Stop / danger red
COLOR_RED_HOVER: Final[str] = "#a1282c"      # Stop hover
COLOR_YELLOW: Final[str] = "#f0b232"         # Idle / warning yellow

# GUI Dimensions
WINDOW_WIDTH: Final[int] = 760
WINDOW_HEIGHT: Final[int] = 560

# ---------------------------------------------------------------------------
# File & Directory Paths
# ---------------------------------------------------------------------------
def get_base_dir() -> Path:
    """Return the base directory for resources (handles PyInstaller bundle)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent

def get_asset_path(relative_path: str) -> Path:
    """Resolve an asset relative path to an absolute path."""
    return get_base_dir() / relative_path

def get_appdata_dir() -> Path:
    """Return the %APPDATA% directory for DiscordActivityCustomizer."""
    roaming = os.getenv("APPDATA")
    if roaming:
        appdata_base = Path(roaming)
    else:
        appdata_base = Path.home() / "AppData" / "Roaming"
    target_dir = appdata_base / "DiscordActivityCustomizer"
    return target_dir

def ensure_appdata_dir() -> Path:
    """Ensure the %APPDATA% directory and subdirectories exist and return it."""
    appdata = get_appdata_dir()
    appdata.mkdir(parents=True, exist_ok=True)
    processed = appdata / "processed_logos"
    processed.mkdir(parents=True, exist_ok=True)
    return appdata

APPDATA_DIR: Final[Path] = get_appdata_dir()
PROCESSED_LOGOS_DIR: Final[Path] = APPDATA_DIR / "processed_logos"
CONFIG_FILE: Final[Path] = APPDATA_DIR / "config.json"
PRESETS_FILE: Final[Path] = APPDATA_DIR / "presets.json"
IMAGE_CACHE_FILE: Final[Path] = APPDATA_DIR / "image_cache.json"

ASSETS_DIR: Final[Path] = get_asset_path("assets")
APP_ICON_PATH: Final[Path] = ASSETS_DIR / "app_icon.ico"
PLACEHOLDER_LOGO_PATH: Final[Path] = ASSETS_DIR / "placeholder_logo.png"

# ---------------------------------------------------------------------------
# Asset Generation Fallback
# ---------------------------------------------------------------------------
def ensure_default_assets() -> None:
    """Ensure default assets (app_icon.ico and placeholder_logo.png) exist."""
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    
    from PIL import Image, ImageDraw

    # 1. placeholder_logo.png (512x512)
    if not PLACEHOLDER_LOGO_PATH.exists():
        img = Image.new("RGBA", REQUIRED_PNG_SIZE, (30, 31, 34, 255))
        draw = ImageDraw.Draw(img)
        # Rounded outer border
        draw.rounded_rectangle(
            [24, 24, 488, 488],
            radius=40,
            fill=(43, 45, 49, 255),
            outline=(88, 101, 242, 255),
            width=6,
        )
        # Center blurple circle
        draw.ellipse([156, 130, 356, 330], fill=(88, 101, 242, 255))
        # White controller body
        draw.rounded_rectangle([196, 205, 316, 275], radius=24, fill=(255, 255, 255, 255))
        # D-pad
        draw.rectangle([216, 230, 236, 250], fill=(43, 45, 49, 255))
        draw.rectangle([222, 224, 230, 256], fill=(43, 45, 49, 255))
        # Buttons
        draw.ellipse([275, 226, 285, 236], fill=(43, 45, 49, 255))
        draw.ellipse([290, 241, 300, 251], fill=(43, 45, 49, 255))
        draw.ellipse([275, 256, 285, 266], fill=(43, 45, 49, 255))
        draw.ellipse([260, 241, 270, 251], fill=(43, 45, 49, 255))
        # Bottom indicator pills
        draw.rounded_rectangle([170, 370, 342, 400], radius=15, fill=(88, 101, 242, 100))
        draw.rounded_rectangle([200, 420, 312, 435], radius=7, fill=(148, 155, 164, 180))
        img.save(PLACEHOLDER_LOGO_PATH, "PNG")

    # 2. app_icon.ico (Multi-size Windows icon)
    if not APP_ICON_PATH.exists():
        icon_img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        draw_ico = ImageDraw.Draw(icon_img)
        draw_ico.ellipse([8, 8, 248, 248], fill=(30, 31, 34, 255), outline=(88, 101, 242, 255), width=8)
        draw_ico.ellipse([36, 36, 220, 220], fill=(88, 101, 242, 255))
        draw_ico.rounded_rectangle([66, 105, 190, 175], radius=24, fill=(255, 255, 255, 255))
        draw_ico.rectangle([88, 132, 112, 148], fill=(43, 45, 49, 255))
        draw_ico.rectangle([96, 124, 104, 156], fill=(43, 45, 49, 255))
        draw_ico.ellipse([150, 126, 162, 138], fill=(43, 45, 49, 255))
        draw_ico.ellipse([166, 142, 178, 154], fill=(43, 45, 49, 255))
        draw_ico.ellipse([150, 158, 162, 170], fill=(43, 45, 49, 255))
        draw_ico.ellipse([134, 142, 146, 154], fill=(43, 45, 49, 255))

        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        icon_img.save(APP_ICON_PATH, format="ICO", sizes=sizes)
