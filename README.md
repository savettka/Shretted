# Shretted

Shretted is a workout tracker for you and a few friends, built for an iPhone
and a free PythonAnywhere account.

Open it at the gym and it already knows what today is. Tap the exercises your
trainer gave you, **in the order he gave them**, hit Start, and tick each one
off as you finish it. Next week it shows you what you did last time.

Live at `https://shretted.pythonanywhere.com`. Accounts required - see below.

---

## The weekly split

| Day | Body part |
|---|---|
| Monday | Back |
| Tuesday | Shoulders |
| Wednesday | Biceps |
| Thursday | Triceps |
| Friday | Legs |
| Saturday | Chest |
| Sunday | Rest |

The app works out today's body part on its own. To train something else, tap a
different chip at the top — nothing is forced.

To change the split itself, edit `SPLIT` in `config.py` (Monday is `0`) and
reload the web app.

## How it works

**Today** — a grid of exercise tiles for whichever body part is scheduled. Tap
them in training order; each tap stamps a number on the tile. The `3 ▢` button
top-right switches between 3 big tiles per row and 4 small ones, which fits
about fifteen exercises on one screen with no scrolling. Hit **Start workout**
when the list is right.

**During the session** — your exercises in order, largest movements first.
Tap each one as you finish it and the time is recorded. There's a running
elapsed timer and a progress bar, and last week's session for the same body
part is one tap away at the bottom, with a **Repeat this session** button.

**History** — every session you have logged, newest first, grouped by month.

**Stats** — how many times you have done each exercise, which one you repeat
most, your streak, sessions per body part, and a twelve-week activity grid.
Exercises you have never done show a count of zero, so it is as easy to see
what you keep skipping as what you keep repeating.

**Exercises** — rename, reorder, hide, or add your own, with a photo from your
camera roll. There's also a paste-a-list screen for setting up a body part
quickly.

Until you add a photo, each tile shows an equipment icon tinted by body part,
so the grid stays readable from day one.

## Built with

Flask, SQLite and plain Jinja templates. No ORM, no JavaScript framework, no
build step, and nothing loaded from a CDN — the whole thing is served from one
folder, which is what makes it viable on a free account.

The only dependencies are Flask and Pillow, both preinstalled on
PythonAnywhere. **Do not create a virtualenv** — an empty one would use over
half of the 512 MB disk quota.

| File | What it does |
|---|---|
| `app.py` | routes, template filters, error handlers |
| `config.py` | the default split, timezone, paths, limits |
| `auth.py` | passwords and API tokens |
| `api.py` | the JSON API for a native app |
| `selftest.py` | run before deploying an update |
| `db.py` | SQLite schema and every query |
| `stats.py` | the Stats page queries |
| `images.py` | uploads: EXIF rotation, square crop, resize to ~25 KB |
| `seed_data.py` | the 84 starter exercises |
| `make_icons.py` | generates the home-screen icons (run once) |
| `wsgi_pythonanywhere.py` | paste into the PythonAnywhere WSGI file |

## Settings

Configured with environment variables set in the WSGI file on the server,
which override the defaults in `config.py`:

| Variable | Purpose |
|---|---|
| `GYM_INVITE_CODE` | the code friends need to sign up. Empty = sign-ups closed |
| `GYM_SECRET_KEY` | signs the login cookie. Generate with `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `GYM_TZ` | `Europe/London`. PythonAnywhere runs on UTC, so without this the day would roll over an hour early for seven months of the year |
| `GYM_HTTPS_ONLY` | set to `0` only when running locally over plain http |

Photos are stored outside `static/` on purpose and served through the app's
own `/photo/` route, so they stay behind a login rather than being readable by
anyone who guesses a filename.

## Your data

Your training log lives in one file, `gymlog.sqlite3`, which is gitignored —
it never leaves the server. **More → Backup file** downloads a consistent
snapshot; **More → Export CSV** gives you a spreadsheet.

Photos are separate files in `uploads/`, also gitignored, and are *not* in the
database backup. To back those up:

```bash
cd ~/gymlog && zip -r ~/gymlog-photos.zip uploads
```

## Deploying

Full instructions in [DEPLOY.md](DEPLOY.md).

To update a running copy:

```bash
cd ~/gymlog && git pull
```

then hit **Reload** on the PythonAnywhere Web tab. Python changes need the
reload; templates and CSS usually do not.

Run it locally with `python app.py`, then open `http://127.0.0.1:5000`
(set `GYM_HTTPS_ONLY=0` first, or the login cookie will be refused).

## Housekeeping

Free PythonAnywhere web apps **expire after one month**. Nothing is deleted —
the site just stops serving until you log in and click the button on the Web
tab. Worth a repeating monthly reminder in your calendar.

## Using your own logo

The app ships with a built-in sage mark. To use your own artwork instead, drop
a file at `static/img/logo.svg` (or `.png` / `.jpg` / `.webp`) and Reload — it
replaces the mark on the unlock screen and the More page automatically. Square
artwork works best.

The home-screen icon is separate: it is generated by `make_icons.py` into
`static/img/icon-180.png`, `icon-192.png` and `icon-512.png`. Overwrite those
three files with your own square PNGs if you would rather not use the
generated ones.

---

Shretted™ · Sarvpreet Kalra

---

## Accounts

Shretted is multi-user. The **exercise catalogue and photos are shared** by
everyone; **workouts, stats and history are private** to each person, and each
person sets their own weekly split.

- The **first account ever created** becomes the owner. It needs no invite
  code, and it inherits any training logged before accounts existed.
- Everyone after that needs the **invite code** — set `GYM_INVITE_CODE` in the
  WSGI file and give it to the people you want in.
- With no invite code set, sign-ups are closed. That is the default.
- Only the owner can download the database backup, since it contains
  everybody's log.

Manage your split, password and app tokens under **More → Account**.

## JSON API

Versioned at `/api/v1`, for a native app to talk to. Get a token:

```bash
curl -X POST https://shretted.pythonanywhere.com/api/v1/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"..."}'
```

Then pass `Authorization: Bearer <token>` on everything else:

| Method | Path | What it does |
|---|---|---|
| GET | `/api/v1/me` | the logged-in user |
| GET | `/api/v1/today` | body part, exercise grid, existing session — one call for the home screen |
| GET | `/api/v1/exercises` | the shared catalogue |
| POST | `/api/v1/exercises` | add one |
| GET | `/api/v1/workouts` | your sessions, newest first |
| POST | `/api/v1/workouts` | start one: `{"body_part":"Back","exercise_ids":[1,2,3]}` |
| GET | `/api/v1/workouts/<id>` | one session with its ordered items |
| PUT | `/api/v1/workouts/<id>/items` | replace the exercise list |
| POST | `/api/v1/workouts/<id>/items/<item>/toggle` | tick one off |
| POST | `/api/v1/workouts/<id>/finish` | finish or reopen |
| PATCH | `/api/v1/workouts/<id>` | change the note or body part |
| DELETE | `/api/v1/workouts/<id>` | delete a session |
| GET | `/api/v1/stats` | everything the Stats screen shows |

Tokens never expire. Create and revoke them under **More → Account**, or
`POST /api/v1/logout` to revoke the one you are using.

## Before you deploy an update

```bash
python3.13 selftest.py
```

Runs against a throwaway database — it never touches `gymlog.sqlite3`. It
checks the app imports, the migration works, and that one person cannot read
another's workouts. If it fails, do not hit Reload.
