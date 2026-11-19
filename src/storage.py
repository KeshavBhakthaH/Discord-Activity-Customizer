"""JSON persistence for configuration, presets, and SHA-256 image cache."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from src.constants import (
    CONFIG_FILE,
    IMAGE_CACHE_FILE,
    PRESETS_FILE,
    ensure_appdata_dir,
)

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: Dict[str, Any] = {
    "app_name": "Visual Studio Code",
    "subdetails": "Developing Discord Rich Presence",
    "hover_text": "Python 3.13 Pro",
    "png_path": "",
    "logo_url": "",
    "show_timer": True,
}

DEFAULT_PRESETS: Dict[str, Dict[str, Any]] = {
    "Code Editor": {
        "app_name": "Visual Studio Code",
        "subdetails": "Editing main.py (Workspace)",
        "hover_text": "Python 3.13 Development",
        "show_timer": True,
        "png_path": "",
        "logo_url": "",
    },
    "Retro Gaming": {
        "app_name": "Half-Life 3",
        "subdetails": "Chapter 4: Ravenholm",
        "hover_text": "Valve Source Engine",
        "show_timer": True,
        "png_path": "",
        "logo_url": "",
    },
    "Music Studio": {
        "app_name": "FL Studio 21",
        "subdetails": "Mastering New Synthwave Track",
        "hover_text": "High Definition Audio",
        "show_timer": False,
        "png_path": "",
        "logo_url": "",
    },
}


class StorageManager:
    """Manages reading and writing persistent JSON files in %APPDATA%."""

    def __init__(self) -> None:
        self.appdata_dir: Path = ensure_appdata_dir()
        self.config_path: Path = CONFIG_FILE
        self.presets_path: Path = PRESETS_FILE
        self.image_cache_path: Path = IMAGE_CACHE_FILE
        self._ensure_files()

    def _ensure_files(self) -> None:
        """Initialize default files if they do not exist."""
        if not self.config_path.exists():
            self.save_config(DEFAULT_CONFIG)
        if not self.presets_path.exists():
            self.save_presets(DEFAULT_PRESETS)
        if not self.image_cache_path.exists():
            self._save_json_atomic(self.image_cache_path, {})

    @staticmethod
    def _save_json_atomic(target_path: Path, data: Any) -> bool:
        """Atomically write JSON data to file using a temporary file."""
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            temp_file = target_path.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            shutil.move(str(temp_file), str(target_path))
            return True
        except Exception as exc:
            logger.error("Failed to write JSON atomically to %s: %s", target_path, exc)
            return False

    @staticmethod
    def _load_json_safe(target_path: Path, default_val: Any) -> Any:
        """Safely load JSON data from file with fallback on error."""
        if not target_path.exists():
            return default_val
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("Corrupted or unreadable JSON at %s: %s. Using default.", target_path, exc)
            return default_val

    # -----------------------------------------------------------------------
    # Config
    # -----------------------------------------------------------------------
    def load_config(self) -> Dict[str, Any]:
        """Load user configuration from config.json."""
        data = self._load_json_safe(self.config_path, DEFAULT_CONFIG.copy())
        # Ensure all default keys exist
        merged = DEFAULT_CONFIG.copy()
        merged.update(data)
        return merged

    def save_config(self, config_data: Dict[str, Any]) -> bool:
        """Save user configuration to config.json."""
        return self._save_json_atomic(self.config_path, config_data)

    # -----------------------------------------------------------------------
    # Presets
    # -----------------------------------------------------------------------
    def load_presets(self) -> Dict[str, Dict[str, Any]]:
        """Load all presets from presets.json."""
        presets = self._load_json_safe(self.presets_path, DEFAULT_PRESETS.copy())
        if not isinstance(presets, dict):
            return DEFAULT_PRESETS.copy()
        return presets

    def save_presets(self, presets: Dict[str, Dict[str, Any]]) -> bool:
        """Save all presets to presets.json."""
        return self._save_json_atomic(self.presets_path, presets)

    def save_preset(self, name: str, preset_data: Dict[str, Any]) -> bool:
        """Add or update a single preset by name."""
        presets = self.load_presets()
        presets[name.strip()] = preset_data
        return self.save_presets(presets)

    def delete_preset(self, name: str) -> bool:
        """Delete a preset by name."""
        presets = self.load_presets()
        clean_name = name.strip()
        if clean_name in presets:
            del presets[clean_name]
            return self.save_presets(presets)
        return False

    # -----------------------------------------------------------------------
    # Image Cache (SHA-256 -> HTTPS URL)
    # -----------------------------------------------------------------------
    def load_image_cache(self) -> Dict[str, str]:
        """Load image SHA-256 to Catbox URL cache."""
        cache = self._load_json_safe(self.image_cache_path, {})
        if not isinstance(cache, dict):
            return {}
        return cache

    def get_cached_image_url(self, sha256_hash: str) -> Optional[str]:
        """Return cached URL for given SHA-256 hash if it exists."""
        cache = self.load_image_cache()
        url = cache.get(sha256_hash)
        if url and isinstance(url, str) and url.startswith("https://"):
            # Invalidate Catbox URLs due to Discord media proxy 502 Bad Gateway
            if "files.catbox.moe" in url:
                return None
            return url
        return None

    def cache_image_url(self, sha256_hash: str, url: str) -> bool:
        """Associate SHA-256 hash with an uploaded HTTPS URL in the cache."""
        cache = self.load_image_cache()
        cache[sha256_hash] = url
        return self._save_json_atomic(self.image_cache_path, cache)
