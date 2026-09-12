"""
Configuration for the gym log app.

Everything you might want to change lives in this file. On PythonAnywhere you
can also override any of these with environment variables set in the WSGI file.
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------
# Things you may want to change
# --------------------------------------------------------------------------

# Your local timezone. PythonAnywhere servers run on UTC, so without this the
# app would roll over to the next day at midnight UTC instead of midnight here.
TIMEZONE = os.environ.get("GYM_TZ", "Europe/London")

# The PIN that guards the app. The site sits on a public URL, so leave one set.
#
# DIGITS ONLY, 4 to 12 of them - the unlock screen is a numeric keypad, so a
# PIN containing letters could never be typed in. Set to "" to remove the lock
# entirely (only sensible if you are running this on your own machine).
#
# Setting it here works, but on the server set GYM_PIN in the WSGI file
# instead: that value wins over this one.
PIN = os.environ.get("GYM_PIN", "1234")

# Used to sign the login cookie. CHANGE THIS to any long random string.
# Generate one with:  python3 -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY = os.environ.get("GYM_SECRET_KEY", "change-me-to-a-long-random-string")

# Only send the login cookie over HTTPS. PythonAnywhere is always HTTPS, so
# this stays on there; set GYM_HTTPS_ONLY=0 if you run the app locally over
# plain http, otherwise the browser will discard your login cookie.
HTTPS_ONLY = os.environ.get("GYM_HTTPS_ONLY", "1") != "0"

# Your weekly split. Key = weekday number (Mon=0 ... Sun=6).
SPLIT = {
    0: "Back",
    1: "Shoulders",
    2: "Biceps",
    3: "Triceps",
    4: "Legs",
    5: "Chest",
    6: "Rest",
}

# Order body parts appear in dropdowns / stats.
BODY_PARTS = ["Back", "Shoulders", "Biceps", "Triceps", "Legs", "Chest"]

# A colour per body part, used for the tile placeholders and headers.
BODY_PART_COLOURS = {
    "Back":      "#2563eb",
    "Shoulders": "#7c3aed",
    "Biceps":    "#db2777",
    "Triceps":   "#ea580c",
    "Legs":      "#16a34a",
    "Chest":     "#dc2626",
    "Rest":      "#475569",
}

# --------------------------------------------------------------------------
# Paths and limits
# --------------------------------------------------------------------------

DB_PATH = os.environ.get("GYM_DB_PATH", os.path.join(BASE_DIR, "gymlog.sqlite3"))

# Deliberately NOT inside static/. On PythonAnywhere you map /static/ straight
# to the filesystem, which bypasses Flask entirely - anything in there is
# public and guessable. Your photos go through the /photo/ route instead, which
# is behind the PIN. Both paths are absolute because a web worker's working
# directory is not reliably your project folder.
UPLOAD_DIR = os.environ.get("GYM_UPLOAD_DIR", os.path.join(BASE_DIR, "uploads"))

# Equipment types, used to pick the icon shown on a tile before you add a
# photo. Keys must match the symbol ids in templates/icons/equipment.svg.
EQUIPMENT = ["barbell", "dumbbell", "ezbar", "machine", "cable", "bodyweight", "other"]

# Reject uploads larger than this before we even read them (raw phone photos
# from an iPhone 15 are ~2-5 MB, HEIC or JPEG).
MAX_UPLOAD_BYTES = 12 * 1024 * 1024

# Every uploaded photo is cropped square and shrunk to this many pixels, then
# saved as an optimised JPEG. Keeps the free-tier disk quota comfortable.
THUMB_PX = 400
JPEG_QUALITY = 80

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif", ".bmp"}


# --------------------------------------------------------------------------
# Time helpers - always go through these, never call datetime.now() directly
# --------------------------------------------------------------------------

def tz():
    return ZoneInfo(TIMEZONE)


def now_local():
    """Current wall-clock time where you are, timezone-aware."""
    return datetime.now(tz())


def today_local():
    """Today's date where you are, as a YYYY-MM-DD string."""
    return now_local().strftime("%Y-%m-%d")


def body_part_for(date_obj=None):
    """The body part scheduled for a given date (defaults to today)."""
    date_obj = date_obj or now_local()
    return SPLIT.get(date_obj.weekday(), "Rest")
