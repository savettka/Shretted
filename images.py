"""
Turning a photo straight off an iPhone into a small square thumbnail.

Every upload is re-encoded rather than stored as-is. That does three jobs at
once: it strips EXIF (including GPS), it guarantees the file really is an
image, and it keeps each tile at roughly 20-40 KB so a few hundred photos
still barely dent a free PythonAnywhere disk quota.
"""
import io
import os
import secrets

from config import ALLOWED_EXTENSIONS, JPEG_QUALITY, THUMB_PX, UPLOAD_DIR

try:
    from PIL import Image, ImageOps, UnidentifiedImageError

    PILLOW_AVAILABLE = True
except ImportError:  # pragma: no cover - only hit if Pillow is missing
    PILLOW_AVAILABLE = False
    Image = ImageOps = None

    class UnidentifiedImageError(Exception):
        pass


# iOS Safari normally transcodes HEIC to JPEG on upload, but Android browsers,
# some third-party keyboards and "share to browser" flows do not. If the
# pillow-heif plugin is installed we can read HEIC directly; if not, we fail
# with a clear message rather than saving a file the browser cannot display.
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIC_SUPPORTED = True
except ImportError:
    HEIC_SUPPORTED = False


# Roughly 60 megapixels - far above any phone camera (an iPhone 15 is 48 MP at
# most, and 12 MP by default) but low enough to stop a decompression bomb.
MAX_PIXELS = 60_000_000

if PILLOW_AVAILABLE:
    # Pillow's own bomb guard; ours above gives a friendlier message first.
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class ImageError(Exception):
    """Raised with a message that is safe to show to the user."""


def ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def _extension(filename):
    return os.path.splitext(filename or "")[1].lower()


def save_upload(file_storage):
    """Validate, square-crop, shrink and store an uploaded photo.

    Returns the stored filename (not a path), or None if no file was supplied.
    Raises ImageError with a human-readable message on anything invalid.
    """
    if file_storage is None or not file_storage.filename:
        return None

    ext = _extension(file_storage.filename)
    if ext and ext not in ALLOWED_EXTENSIONS:
        raise ImageError(
            "That file type is not supported. Use a JPEG, PNG or HEIC photo."
        )

    if not PILLOW_AVAILABLE:
        raise ImageError(
            "Image support is not installed on the server. "
            "Run: pip install --user Pillow"
        )

    raw = file_storage.read()
    if not raw:
        raise ImageError("That photo came through empty. Try picking it again.")

    try:
        img = Image.open(io.BytesIO(raw))
        # Check the declared size BEFORE decoding. A 12 MB PNG can expand to
        # hundreds of MB in memory, which on a free tier means the worker gets
        # killed and the whole site goes down for a moment.
        width, height = img.size
        if width * height > MAX_PIXELS:
            raise ImageError(
                "That photo is too large to process ("
                + str(width) + "x" + str(height) + "). Try a smaller one."
            )
        img.load()
    except ImageError:
        raise
    except UnidentifiedImageError:
        if ext in {".heic", ".heif"} and not HEIC_SUPPORTED:
            raise ImageError(
                "This is a HEIC photo and the server cannot read HEIC yet. "
                "Either run 'pip install --user pillow-heif' on the server, or "
                "set iPhone Settings > Camera > Formats to 'Most Compatible'."
            )
        raise ImageError("That file does not look like an image.")
    except Exception:
        raise ImageError("That photo could not be read. Try a different one.")

    # Honour the EXIF orientation flag, otherwise portrait photos come out
    # rotated 90 degrees.
    img = ImageOps.exif_transpose(img)

    # Flatten transparency onto white so PNGs with alpha do not go black.
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        canvas = Image.new("RGB", img.size, (255, 255, 255))
        canvas.paste(img, mask=img.split()[-1])
        img = canvas
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Centre-crop to a square, then resize. Tiles are square, so doing the crop
    # server-side means the grid never has to letterbox anything.
    img = ImageOps.fit(img, (THUMB_PX, THUMB_PX), method=Image.LANCZOS, centering=(0.5, 0.4))

    ensure_upload_dir()
    filename = secrets.token_hex(8) + ".jpg"
    path = os.path.join(UPLOAD_DIR, filename)
    img.save(path, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    return filename


def delete_image(filename):
    """Remove a stored thumbnail. Silently ignores anything odd."""
    if not filename:
        return
    # Defensive: never let a stored name escape the uploads directory.
    safe = os.path.basename(filename)
    path = os.path.join(UPLOAD_DIR, safe)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def disk_usage():
    """Total bytes used by uploaded photos, for the Settings page."""
    total = 0
    count = 0
    if not os.path.isdir(UPLOAD_DIR):
        return 0, 0
    for name in os.listdir(UPLOAD_DIR):
        if name.startswith("."):
            continue  # .gitkeep and friends are not photos
        path = os.path.join(UPLOAD_DIR, name)
        if os.path.isfile(path):
            total += os.path.getsize(path)
            count += 1
    return total, count
