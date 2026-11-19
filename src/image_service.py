"""PNG validation, Pillow thumbnail generation, SHA-256 caching, and high-reliability CDN hosting."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Callable, Optional, Tuple

from PIL import Image, ImageDraw

from src.constants import (
    CATBOX_API_URL,
    FREEIMAGE_API_KEY,
    FREEIMAGE_API_URL,
    MAX_DISCORD_URL_LENGTH,
    MAX_PNG_SIZE_BYTES,
    PLACEHOLDER_LOGO_PATH,
    PROCESSED_LOGOS_DIR,
    REQUIRED_PNG_SIZE,
    ensure_default_assets,
)
from src.storage import StorageManager

logger = logging.getLogger(__name__)


class ImageValidationError(Exception):
    """Raised when an image fails strict validation requirements."""


class ImageUploadError(Exception):
    """Raised when an image upload fails or returns an invalid URL."""


def validate_png(file_path: str | Path) -> Tuple[bool, str, Optional[Tuple[int, int]]]:
    """Validate a PNG file for Discord Rich Presence usage.

    Enforces:
    1. File existence and valid path.
    2. Case-insensitive .png extension.
    3. File size <= 5 MB.
    4. Format is verified as genuine PNG via Pillow.
    5. Exact dimensions: 512 x 512 pixels.

    Returns:
        Tuple of (is_valid, status_message, dimensions_tuple)
    """
    path = Path(file_path)
    if not path.is_file():
        return False, f"File does not exist: {path.name}", None

    # Check extension
    if path.suffix.lower() != ".png":
        return False, f"Invalid extension '{path.suffix}'. Please select a .png file.", None

    # Check file size (5MB limit)
    try:
        size_bytes = path.stat().st_size
    except OSError as err:
        return False, f"Cannot read file size: {err}", None

    if size_bytes > MAX_PNG_SIZE_BYTES:
        size_mb = size_bytes / (1024 * 1024)
        return False, f"File size ({size_mb:.2f} MB) exceeds maximum allowed size (5.0 MB).", None

    # Verify image integrity, format and dimensions with Pillow
    try:
        with Image.open(path) as img:
            format_name = img.format
            dimensions = img.size

            if format_name != "PNG":
                return (
                    False,
                    f"Invalid image format '{format_name}'. File must be a genuine PNG image.",
                    dimensions,
                )

            if dimensions != REQUIRED_PNG_SIZE:
                w, h = dimensions
                return (
                    False,
                    f"Invalid dimensions: {w}x{h} px. Please select a 512x512 px PNG.",
                    dimensions,
                )

            return True, "Valid 512x512 PNG", dimensions
    except Exception as exc:
        return False, f"Unable to read image file: {exc}", None


def calculate_sha256(file_path: str | Path) -> str:
    """Compute the SHA-256 hash of a file efficiently in 64KB blocks."""
    sha256_hash = hashlib.sha256()
    path = Path(file_path)
    with open(path, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def upload_to_freeimage(file_path: str | Path) -> str:
    """Upload a PNG to FreeImage.host and return the direct public HTTPS URL (iili.io).

    Discord-friendly CDN with zero 502/proxy drops.

    Args:
        file_path: Path to the validated 512x512 PNG file.

    Returns:
        Clean direct HTTPS URL string (< 254 characters).

    Raises:
        ImageUploadError: If upload fails or returns an invalid URL.
    """
    path = Path(file_path)
    try:
        import requests

        with open(path, "rb") as f:
            files = {"source": (path.name, f, "image/png")}
            data = {
                "key": FREEIMAGE_API_KEY,
                "action": "upload",
                "format": "json",
            }
            response = requests.post(
                FREEIMAGE_API_URL,
                data=data,
                files=files,
                timeout=25,
            )

        if response.status_code != 200:
            raise ImageUploadError(
                f"FreeImage API returned HTTP status {response.status_code}: {response.text[:200]}"
            )

        res_json = response.json()
        raw_url = res_json.get("image", {}).get("url", "")
        if not raw_url:
            raise ImageUploadError(
                f"FreeImage did not return image URL in response: {response.text[:200]}"
            )

        raw_url = raw_url.strip()
        if not raw_url.startswith("https://"):
            raise ImageUploadError(f"FreeImage returned non-HTTPS URL: '{raw_url}'")

        if len(raw_url) >= MAX_DISCORD_URL_LENGTH:
            raise ImageUploadError(
                f"Generated URL is too long ({len(raw_url)} chars) for Discord RPC (limit {MAX_DISCORD_URL_LENGTH})."
            )

        logger.info("Successfully uploaded image to FreeImage: %s", raw_url)
        return raw_url

    except Exception as exc:
        if isinstance(exc, ImageUploadError):
            raise
        # Catch requests exceptions or others gracefully
        raise ImageUploadError(f"Network error during upload to FreeImage: {exc}") from exc


def upload_to_catbox(file_path: str | Path) -> str:
    """Upload a PNG to Catbox and return the public HTTPS URL (fallback).

    Args:
        file_path: Path to the validated 512x512 PNG file.

    Returns:
        Clean HTTPS URL string (< 254 characters).

    Raises:
        ImageUploadError: If upload fails or returns an invalid URL.
    """
    path = Path(file_path)
    try:
        import requests

        with open(path, "rb") as f:
            files = {"fileToUpload": (path.name, f, "image/png")}
            data = {"reqtype": "fileupload"}
            response = requests.post(
                CATBOX_API_URL,
                data=data,
                files=files,
                timeout=30,
            )

        if response.status_code != 200:
            raise ImageUploadError(
                f"Catbox API returned HTTP status {response.status_code}: {response.text.strip()}"
            )

        raw_url = response.text.strip()
        if not raw_url.startswith("https://"):
            raise ImageUploadError(f"Catbox returned non-HTTPS URL: '{raw_url}'")

        if len(raw_url) >= MAX_DISCORD_URL_LENGTH:
            raise ImageUploadError(
                f"Generated URL is too long ({len(raw_url)} chars) for Discord RPC (limit {MAX_DISCORD_URL_LENGTH})."
            )

        logger.info("Successfully uploaded image to Catbox: %s", raw_url)
        return raw_url

    except Exception as exc:
        if isinstance(exc, ImageUploadError):
            raise
        raise ImageUploadError(f"Network error during upload to Catbox: {exc}") from exc


def upload_image(file_path: str | Path) -> str:
    """Upload image using FreeImage.host as primary and Catbox as fallback.

    FreeImage.host (iili.io) provides high-performance direct CDN URLs
    that are fully trusted and rendered by Discord's media proxy.
    """
    try:
        return upload_to_freeimage(file_path)
    except ImageUploadError as fie_err:
        logger.warning("FreeImage upload failed (%s). Falling back to Catbox...", fie_err)
        try:
            return upload_to_catbox(file_path)
        except ImageUploadError as cb_err:
            raise ImageUploadError(
                f"Image upload failed across all providers:\n• FreeImage: {fie_err}\n• Catbox: {cb_err}"
            ) from cb_err


def get_or_upload_image(
    file_path: str | Path,
    storage: StorageManager,
    status_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[str, bool]:
    """Retrieve cached HTTPS URL or upload the PNG to high-reliability image CDN.

    Args:
        file_path: Path to local PNG file.
        storage: StorageManager instance for SHA-256 caching.
        status_callback: Optional callback for status text updates.

    Returns:
        Tuple of (https_url, was_cached)

    Raises:
        ImageValidationError: If file fails PNG validation.
        ImageUploadError: If file fails uploading.
    """
    is_valid, msg, _ = validate_png(file_path)
    if not is_valid:
        raise ImageValidationError(msg)

    # 1. Compute SHA-256
    file_hash = calculate_sha256(file_path)

    # 2. Check cache (Reject old Catbox URLs since Discord proxy 502s them)
    cached_url = storage.get_cached_image_url(file_hash)
    if cached_url and not cached_url.startswith("https://files.catbox.moe/"):
        if status_callback:
            status_callback("Using cached logo URL...")
        logger.info("Found cached URL for SHA-256 %s: %s", file_hash[:12], cached_url)
        return cached_url, True

    # 3. Upload to high-reliability CDN
    if status_callback:
        status_callback("Uploading 512x512 PNG to image CDN...")
    uploaded_url = upload_image(file_path)

    # 4. Save to cache
    storage.cache_image_url(file_hash, uploaded_url)
    return uploaded_url, False


def process_image_to_512(
    img: Image.Image,
    mode: str = "crop",
    bg_color: Tuple[int, int, int, int] = (0, 0, 0, 0),
) -> Image.Image:
    """Transform an image to exact 512x512 dimensions.

    Args:
        img: Source PIL Image.
        mode: Transformation mode - 'crop' (center crop 1:1), 'fit' (aspect fit with padding),
              or 'stretch' (direct resize).
        bg_color: Background fill color for 'fit' mode (RGBA tuple).

    Returns:
        Exact 512x512 RGBA Image.
    """
    img_rgba = img.convert("RGBA")
    w, h = img_rgba.size

    if mode == "fit":
        # Aspect fit inside 512x512 with padding
        ratio = min(REQUIRED_PNG_SIZE[0] / w, REQUIRED_PNG_SIZE[1] / h)
        new_w = max(1, int(w * ratio))
        new_h = max(1, int(h * ratio))
        resized = img_rgba.resize((new_w, new_h), Image.Resampling.LANCZOS)
        out = Image.new("RGBA", REQUIRED_PNG_SIZE, bg_color)
        pad_x = (REQUIRED_PNG_SIZE[0] - new_w) // 2
        pad_y = (REQUIRED_PNG_SIZE[1] - new_h) // 2
        out.paste(resized, (pad_x, pad_y), mask=resized)
        return out
    elif mode == "stretch":
        # Direct resize to 512x512
        return img_rgba.resize(REQUIRED_PNG_SIZE, Image.Resampling.LANCZOS)
    else:
        # Default: Center Crop (Fill 1:1)
        min_dim = min(w, h)
        left = (w - min_dim) // 2
        top = (h - min_dim) // 2
        cropped = img_rgba.crop((left, top, left + min_dim, top + min_dim))
        return cropped.resize(REQUIRED_PNG_SIZE, Image.Resampling.LANCZOS)


def save_processed_logo(img: Image.Image, original_filename: str) -> Path:
    """Save a processed 512x512 image into %APPDATA% processed_logos folder."""
    PROCESSED_LOGOS_DIR.mkdir(parents=True, exist_ok=True)
    base_stem = Path(original_filename).stem
    # Use image data hash to deduplicate
    img_bytes = img.tobytes()
    hash_prefix = hashlib.sha256(img_bytes).hexdigest()[:10]
    target_path = PROCESSED_LOGOS_DIR / f"{base_stem}_512x512_{hash_prefix}.png"
    img.save(target_path, "PNG", optimize=True, compress_level=7)
    logger.info("Saved 512x512 processed logo to: %s", target_path)
    return target_path


def create_rounded_preview(
    image_source: Optional[str | Path | Image.Image] = None,
    size: Tuple[int, int] = (80, 80),
    radius: int = 14,
) -> Image.Image:
    """Create an antialiased rounded-corner preview thumbnail.

    Args:
        image_source: Path to image, PIL Image object, or None (uses placeholder).
        size: Target dimensions (width, height), default (80, 80).
        radius: Corner rounding radius in pixels, default 14.

    Returns:
        RGBA PIL Image with transparent rounded corners.
    """
    ensure_default_assets()

    base_img: Optional[Image.Image] = None
    try:
        if isinstance(image_source, Image.Image):
            base_img = image_source.copy()
        elif image_source and Path(image_source).is_file():
            base_img = Image.open(image_source)
        else:
            base_img = Image.open(PLACEHOLDER_LOGO_PATH)
    except Exception as exc:
        logger.warning("Could not load image source %s: %s. Using placeholder.", image_source, exc)
        base_img = Image.open(PLACEHOLDER_LOGO_PATH)

    # Supersample mask for smooth antialiased corners
    scale = 4
    high_size = (size[0] * scale, size[1] * scale)
    high_mask = Image.new("L", high_size, 0)
    draw_mask = ImageDraw.Draw(high_mask)
    draw_mask.rounded_rectangle(
        [0, 0, high_size[0], high_size[1]],
        radius=radius * scale,
        fill=255,
    )
    mask = high_mask.resize(size, Image.Resampling.LANCZOS)

    # Resize source image with Lanczos
    resized_img = base_img.resize(size, Image.Resampling.LANCZOS).convert("RGBA")

    # Apply mask
    rounded = Image.new("RGBA", size, (0, 0, 0, 0))
    rounded.paste(resized_img, (0, 0), mask=mask)
    return rounded
