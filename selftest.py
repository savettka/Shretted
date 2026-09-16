"""
Check the app works before you reload the live site.

    python3.13 selftest.py

Runs against a throwaway database in a temp folder - it never opens, reads or
writes gymlog.sqlite3, so it cannot touch your training history.

It covers the things that would actually hurt: the app importing at all, the
migration from the old single-user database, and whether one person can see
another person's workouts.
"""
import os
import shutil
import sqlite3
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="shretted-selftest-")

# Must be set BEFORE config is imported - it reads the environment on import.
os.environ["GYM_DB_PATH"] = os.path.join(TMP, "test.sqlite3")
os.environ["GYM_UPLOAD_DIR"] = os.path.join(TMP, "uploads")
os.environ["GYM_SECRET_KEY"] = "selftest-only"
os.environ["GYM_INVITE_CODE"] = "LETMEIN"
os.environ["GYM_HTTPS_ONLY"] = "0"

PASS, FAIL = [], []


def check(label, condition, detail=""):
    if condition:
        PASS.append(label)
        print("  ok    " + label)
    else:
        FAIL.append(label + (" - " + detail if detail else ""))
        print("  FAIL  " + label + (("  (" + detail + ")") if detail else ""))


# ---------------------------------------------------------------------------
print("\n1. Imports")
# ---------------------------------------------------------------------------
try:
    import app as app_module
    import api          # noqa: F401
    import auth
    import db
    import stats        # noqa: F401
    check("every module imports", True)
except Exception as exc:                                  # noqa: BLE001
    print("  FAIL  import blew up: " + repr(exc))
    import traceback
    traceback.print_exc()
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1)

flask_app = app_module.app
flask_app.config["WTF_CSRF_ENABLED"] = False
client = flask_app.test_client()


# ---------------------------------------------------------------------------
print("\n2. First run and the owner account")
# ---------------------------------------------------------------------------
r = client.get("/", follow_redirects=False)
check("logged out is redirected", r.status_code == 302, "got " + str(r.status_code))

r = client.get("/login", follow_redirects=False)
check("no accounts yet sends you to signup",
      r.status_code == 302 and "/signup" in r.headers.get("Location", ""),
      r.headers.get("Location", ""))

r = client.post("/signup", data={
    "name": "Owner", "email": "owner@example.com",
    "password": "correct horse", "confirm": "correct horse",
}, follow_redirects=False)
check("owner account is created", r.status_code == 302, "got " + str(r.status_code))

r = client.get("/")
check("home loads once logged in", r.status_code == 200, "got " + str(r.status_code))

for path in ("/history", "/stats", "/exercises", "/settings", "/account"):
    r = client.get(path)
    check("GET " + path, r.status_code == 200, "got " + str(r.status_code))


# ---------------------------------------------------------------------------
print("\n3. Logging a workout")
# ---------------------------------------------------------------------------
c = db.get_conn()
owner = db.get_user_by_email(c, "owner@example.com")
some = c.execute("SELECT id FROM exercise LIMIT 3").fetchall()
c.close()
check("starter exercises were seeded", len(some) == 3, str(len(some)) + " found")

ids = ",".join(str(row["id"]) for row in some)
r = client.post("/workout", data={"order": ids, "body_part": "Back"},
                follow_redirects=False)
check("workout is created", r.status_code == 302, "got " + str(r.status_code))
owner_workout = r.headers.get("Location", "").rstrip("/").split("/")[-1]

r = client.get("/workout/" + owner_workout)
check("owner can open their workout", r.status_code == 200, "got " + str(r.status_code))


# ---------------------------------------------------------------------------
print("\n4. A second person, and whether they can snoop")
# ---------------------------------------------------------------------------
client.post("/logout")
friend = flask_app.test_client()

r = friend.post("/signup", data={
    "name": "Friend", "email": "friend@example.com",
    "password": "another pass", "confirm": "another pass", "code": "WRONG",
}, follow_redirects=True)
check("wrong invite code is rejected", b"invite code" in r.data.lower())

r = friend.post("/signup", data={
    "name": "Friend", "email": "friend@example.com",
    "password": "another pass", "confirm": "another pass", "code": "LETMEIN",
}, follow_redirects=False)
check("right invite code is accepted", r.status_code == 302, "got " + str(r.status_code))

r = friend.get("/workout/" + owner_workout)
check("FRIEND CANNOT OPEN THE OWNER'S WORKOUT", r.status_code == 404,
      "got " + str(r.status_code) + " - this one matters")

r = friend.post("/workout/" + owner_workout + "/delete", follow_redirects=False)
check("friend cannot delete the owner's workout",
      r.status_code in (403, 404), "got " + str(r.status_code))

r = friend.get("/history")
check("friend's history is empty", r.status_code == 200 and b"Back" not in r.data)

r = friend.get("/backup.sqlite3")
check("friend cannot download the database", r.status_code == 403,
      "got " + str(r.status_code))

c = db.get_conn()
check("two accounts exist", db.count_users(c) == 2, str(db.count_users(c)))
c.close()


# ---------------------------------------------------------------------------
print("\n5. The JSON API")
# ---------------------------------------------------------------------------
r = client.post("/api/v1/login", json={"email": "owner@example.com",
                                       "password": "correct horse"})
check("api login returns a token", r.status_code == 200 and "token" in r.get_json(),
      str(r.status_code))
token = (r.get_json() or {}).get("token", "")
head = {"Authorization": "Bearer " + token}

r = client.post("/api/v1/login", json={"email": "owner@example.com",
                                       "password": "wrong"})
check("api rejects a bad password", r.status_code == 401, "got " + str(r.status_code))

r = client.get("/api/v1/today", headers=head)
check("api /today works", r.status_code == 200, "got " + str(r.status_code))

r = client.get("/api/v1/today")
check("api refuses a missing token", r.status_code == 401, "got " + str(r.status_code))

r = client.get("/api/v1/today", headers={"Authorization": "Bearer not-a-real-token"})
check("api refuses a junk token", r.status_code == 401, "got " + str(r.status_code))

r = client.get("/api/v1/workouts", headers=head)
check("api lists the owner's workouts",
      r.status_code == 200 and len(r.get_json()["workouts"]) == 1,
      str(r.status_code))

r = client.get("/api/v1/workouts/" + owner_workout, headers=head)
check("api returns a workout with its items",
      r.status_code == 200 and len(r.get_json().get("items", [])) == 3)

r = client.get("/api/v1/stats", headers=head)
check("api /stats works", r.status_code == 200, "got " + str(r.status_code))


# ---------------------------------------------------------------------------
print("\n6. Migrating an old single-user database")
# ---------------------------------------------------------------------------
old_path = os.path.join(TMP, "old.sqlite3")
old = sqlite3.connect(old_path)
old.executescript("""
CREATE TABLE exercise (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
    body_part TEXT NOT NULL, image TEXT, note TEXT,
    equipment TEXT NOT NULL DEFAULT 'other', archived INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE workout (
    id INTEGER PRIMARY KEY AUTOINCREMENT, workout_date TEXT NOT NULL,
    body_part TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, note TEXT);
CREATE TABLE workout_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT, workout_id INTEGER NOT NULL,
    exercise_id INTEGER NOT NULL, position INTEGER NOT NULL, done_at TEXT);
INSERT INTO exercise (name, body_part, created_at) VALUES ('Deadlift','Back','2026-01-01');
INSERT INTO workout (workout_date, body_part, started_at)
       VALUES ('2026-01-02','Back','2026-01-02T18:00:00+00:00');
INSERT INTO workout_item (workout_id, exercise_id, position) VALUES (1, 1, 0);
PRAGMA user_version = 1;
""")
old.commit()
old.close()

import importlib

import config
os.environ["GYM_DB_PATH"] = old_path
importlib.reload(config)
importlib.reload(db)
db.init_db()

c = db.get_conn()
cols = {row["name"] for row in c.execute("PRAGMA table_info(workout)")}
check("migration adds user_id to workout", "user_id" in cols, str(sorted(cols)))
check("the old workout survived",
      c.execute("SELECT COUNT(*) FROM workout").fetchone()[0] == 1)
check("the old exercise survived",
      c.execute("SELECT COUNT(*) FROM exercise").fetchone()[0] == 1)
check("the old workout is unclaimed until someone signs up",
      c.execute("SELECT user_id FROM workout WHERE id = 1").fetchone()[0] is None)

uid = db.create_user(c, "Owner", "o@e.com", auth.hash_password("x" * 10), is_owner=True)
claimed = db.claim_orphan_workouts(c, uid)
check("the first account inherits the old sessions", claimed == 1, str(claimed))
check("and can now read it", db.get_workout(c, uid, 1) is not None)
c.close()


# ---------------------------------------------------------------------------
shutil.rmtree(TMP, ignore_errors=True)
print("\n" + "=" * 58)
print(str(len(PASS)) + " passed, " + str(len(FAIL)) + " failed")
if FAIL:
    print("\nFailures:")
    for item in FAIL:
        print("  - " + item)
    print("\nDo NOT reload the web app until these are fixed.")
    sys.exit(1)
print("\nAll good. Safe to hit Reload.")
