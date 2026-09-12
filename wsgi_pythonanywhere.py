# ===========================================================================
# COPY THE CONTENTS OF THIS FILE into your PythonAnywhere WSGI config file.
#
# This file does nothing where it sits. On the Web tab there is a link near
# the top called
#
#     /var/www/YOURUSERNAME_pythonanywhere_com_wsgi.py
#
# Click it, delete everything already in there, paste this in, change
# YOURUSERNAME on the line below, and save. Then hit the green Reload button.
# ===========================================================================

import os
import sys

# --- 1. Where your code lives ---------------------------------------------
project_home = "/home/YOURUSERNAME/gymlog"
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# --- 2. Settings ----------------------------------------------------------
# Setting them here keeps your PIN and secret key out of the code, so they do
# not end up in a git repo. They override the defaults in config.py.
# CHANGE THIS. Digits only, 4-12 of them - the unlock screen is a keypad.
os.environ.setdefault("GYM_PIN", "1234")

# CHANGE THIS TOO. Do not type it by hand; generate one in a Bash console with
#     python3.13 -c "import secrets; print(secrets.token_hex(32))"
# and paste the output between the quotes. A stray " or \ here is a syntax
# error that takes the whole site down.
os.environ.setdefault("GYM_SECRET_KEY", "change-me")

os.environ.setdefault("GYM_TZ", "Europe/London")

# The servers run on UTC. The app already uses zoneinfo for anything that
# matters, but this makes log timestamps read in UK time as well.
os.environ["TZ"] = "Europe/London"
import time
time.tzset()

# --- 3. Hand Flask to the web server --------------------------------------
# uWSGI only looks for a global called `application`, so the rename matters.
from app import app as application  # noqa: E402
