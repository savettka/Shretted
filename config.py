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

# Who may create an account.
#
# The very first account is always allowed - that one becomes the owner, and
# inherits any training history from before accounts existed. After that,
# signing up requires this code, which you give to the friends you want in.
#
# Leave it empty and signup closes completely once the owner account exists.
# Set it in the WSGI file as GYM_INVITE_CODE; that wins over this default.
INVITE_CODE = os.environ.get("GYM_INVITE_CODE", "")

# Used to sign the login cookie. CHANGE THIS to any long random string.
# Generate one with:  python3 -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY = os.environ.get("GYM_SECRET_KEY", "change-me-to-a-long-random-string")

# Only send the login cookie over HTTPS. PythonAnywhere is always HTTPS, so
# this stays on there; set GYM_HTTPS_ONLY=0 if you run the app locally over
# plain http, otherwise the browser will discard your login cookie.
HTTPS_ONLY = os.environ.get("GYM_HTTPS_ONLY", "1") != "0"

# The default weekly split handed to each NEW account. Everyone can change
# their own afterwards under More - changing this does not change theirs.
# Key = weekday number (Mon=0 ... Sun=6).
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

# A colour per body part. Deliberately desaturated and close in tone so the
# grid reads as one family next to the sage mark - six bright hues would fight
# the logo and make the whole thing look like a toy.
# Each one is dark enough to carry white text at small sizes AND to be read as
# text on the pale background - both happen, so they all clear about 4.5:1.
BODY_PART_COLOURS = {
    "Back":      "#5F7D5B",   # moss
    "Shoulders": "#5C7288",   # dusty blue
    "Biceps":    "#91664A",   # clay
    "Triceps":   "#77597E",   # plum
    "Legs":      "#6F7D45",   # olive
    "Chest":     "#9E5F57",   # terracotta
    "Rest":      "#6E736C",   # stone
}

# The mark's own green. BRAND is the light logo sage; BRAND_DEEP is the darker
# version used wherever it has to carry white text or be read as text.
BRAND = "#9CB295"
BRAND_DEEP = "#5A7755"

# --------------------------------------------------------------------------
# Paths and limits
# --------------------------------------------------------------------------

DB_PATH = os.environ.get("GYM_DB_PATH", os.path.join(BASE_DIR, "gymlog.sqlite3"))

# Deliberately NOT inside static/. On PythonAnywhere you map /static/ straight
# to the filesystem, which bypasses Flask entirely - anything in there is
# public and guessable. Your photos go through the /photo/ route instead, which
# behind your login. Both paths are absolute because a web worker's working
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


def body_part_for(split=None, date_obj=None):
    """The body part scheduled for a given date, for a given person's split.

    Pass the user's own split; SPLIT is only the default for new accounts.
    """
    split = split or SPLIT
    date_obj = date_obj or now_local()
    return split.get(date_obj.weekday(), "Rest")
