"""
SQLite storage layer. Standard library only - no ORM, no extra packages.

Shape of the data:
  user          one row per person
  exercise      SHARED catalogue - everyone sees the same exercises and photos
  workout       PRIVATE to one user, always scoped by user_id
  workout_item  the ordered exercises inside one workout
  api_token     long-lived tokens for the iOS app

Why SQLite: a free PythonAnywhere web app runs a single worker, so writes are
serialised anyway. Fine for a handful of people. If this ever grows past that,
the move is MySQL on a paid tier - every query here is plain SQL, so it ports.

Note: PythonAnywhere stores files on a network filesystem where SQLite's WAL
mode is unreliable, so we stay on the default rollback journal with a generous
busy timeout.
"""
import json
import os
import sqlite3

from config import DB_PATH, SPLIT, now_local, today_local

# Tables and indexes are kept apart on purpose, and run in three steps:
# tables -> add any missing columns -> indexes. An index on a column that an
# older database has not got yet would fail, and CREATE TABLE IF NOT EXISTS
# will not add the column for us because the table already exists.
TABLES = """
CREATE TABLE IF NOT EXISTS user (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    email         TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    split         TEXT    NOT NULL,
    is_owner      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL,
    last_seen     TEXT
);

CREATE TABLE IF NOT EXISTS api_token (
    token_hash TEXT    PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    label      TEXT,
    created_at TEXT    NOT NULL,
    last_used  TEXT
);

CREATE TABLE IF NOT EXISTS exercise (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    body_part   TEXT    NOT NULL,
    image       TEXT,
    note        TEXT,
    equipment   TEXT    NOT NULL DEFAULT 'other',
    archived    INTEGER NOT NULL DEFAULT 0,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL,
    created_by  INTEGER REFERENCES user(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS workout (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER REFERENCES user(id) ON DELETE CASCADE,
    workout_date TEXT    NOT NULL,
    body_part    TEXT    NOT NULL,
    started_at   TEXT    NOT NULL,
    finished_at  TEXT,
    note         TEXT
);

CREATE TABLE IF NOT EXISTS workout_item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id  INTEGER NOT NULL REFERENCES workout(id) ON DELETE CASCADE,
    exercise_id INTEGER NOT NULL REFERENCES exercise(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    done_at     TEXT
);
"""

# Columns added after the first release. Each one is (table, column, definition)
# and is only applied when missing, so this is safe to run on every start.
ADDED_COLUMNS = [
    ("workout", "user_id", "INTEGER REFERENCES user(id)"),
    ("exercise", "created_by", "INTEGER REFERENCES user(id)"),
]

INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS ux_user_email ON user (email COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS ix_token_user ON api_token (user_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_exercise_name
    ON exercise (body_part, name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS ix_workout_user ON workout (user_id, workout_date DESC);
CREATE INDEX IF NOT EXISTS ix_workout_date ON workout (workout_date DESC);
CREATE INDEX IF NOT EXISTS ix_item_workout  ON workout_item (workout_id, position);
CREATE INDEX IF NOT EXISTS ix_item_exercise ON workout_item (exercise_id);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _columns(conn, table):
    return {row["name"] for row in conn.execute("PRAGMA table_info(" + table + ")")}


def init_db():
    """Create or migrate the database. Safe to run on every start."""
    conn = get_conn()
    try:
        # 1. Tables. Existing ones are left exactly as they are.
        conn.executescript(TABLES)
        conn.commit()

        # 2. Columns added since the first release. A database written by the
        #    single-user version has no user_id on workout and no created_by
        #    on exercise. Adding a nullable column is non-destructive - the
        #    old workouts stay unclaimed until the first account takes them.
        for table, column, definition in ADDED_COLUMNS:
            if column not in _columns(conn, table):
                conn.execute(
                    "ALTER TABLE " + table + " ADD COLUMN " + column + " " + definition
                )
        conn.commit()

        # 3. Indexes, now that every column they mention definitely exists.
        conn.executescript(INDEXES)
        conn.commit()

        # Seed the starter catalogue exactly once, ever - so deliberately
        # deleting everything does not bring all 84 back on the next restart.
        if not conn.execute("PRAGMA user_version").fetchone()[0]:
            if conn.execute("SELECT COUNT(*) FROM exercise").fetchone()[0] == 0:
                seed_exercises(conn)
            conn.execute("PRAGMA user_version = 1")
            conn.commit()
    finally:
        conn.close()


def snapshot_bytes():
    """A consistent copy of the whole database, for the backup link."""
    import tempfile

    source = get_conn()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "snapshot.sqlite3")
            target = sqlite3.connect(path)
            try:
                source.backup(target)
            finally:
                target.close()
            with open(path, "rb") as handle:
                return handle.read()
    finally:
        source.close()


def seed_exercises(conn):
    from seed_data import CATALOGUE

    now = now_local().isoformat(timespec="seconds")
    rows = []
    for body_part, exercises in CATALOGUE.items():
        for i, (name, equipment, note) in enumerate(exercises):
            rows.append((name, body_part, None, note, equipment, 0, i, now))
    conn.executemany(
        "INSERT OR IGNORE INTO exercise "
        "(name, body_part, image, note, equipment, archived, sort_order, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def default_split_json():
    return json.dumps({str(k): v for k, v in SPLIT.items()})


def split_of(user_row):
    """The user's weekly split as {weekday_int: body_part}."""
    try:
        raw = json.loads(user_row["split"])
        return {int(k): v for k, v in raw.items()}
    except (ValueError, TypeError, KeyError):
        return dict(SPLIT)


def count_users(conn):
    return conn.execute("SELECT COUNT(*) FROM user").fetchone()[0]


def create_user(conn, name, email, password_hash, is_owner=False):
    cur = conn.execute(
        "INSERT INTO user (name, email, password_hash, split, is_owner, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, email, password_hash, default_split_json(), 1 if is_owner else 0,
         now_local().isoformat(timespec="seconds")),
    )
    conn.commit()
    return cur.lastrowid


def get_user(conn, user_id):
    return conn.execute("SELECT * FROM user WHERE id = ?", (user_id,)).fetchone()


def get_user_by_email(conn, email):
    return conn.execute(
        "SELECT * FROM user WHERE email = ? COLLATE NOCASE", (email,)
    ).fetchone()


def email_taken(conn, email):
    return get_user_by_email(conn, email) is not None


def all_users(conn):
    return conn.execute(
        "SELECT u.*, "
        "  (SELECT COUNT(*) FROM workout w WHERE w.user_id = u.id) AS sessions "
        "FROM user u ORDER BY u.created_at"
    ).fetchall()


def touch_user(conn, user_id):
    conn.execute(
        "UPDATE user SET last_seen = ? WHERE id = ?",
        (now_local().isoformat(timespec="seconds"), user_id),
    )
    conn.commit()


def set_split(conn, user_id, split_map):
    conn.execute(
        "UPDATE user SET split = ? WHERE id = ?",
        (json.dumps({str(k): v for k, v in split_map.items()}), user_id),
    )
    conn.commit()


def set_password(conn, user_id, password_hash):
    conn.execute(
        "UPDATE user SET password_hash = ? WHERE id = ?", (password_hash, user_id)
    )
    conn.commit()


def claim_orphan_workouts(conn, user_id):
    """Hand any pre-accounts workouts to the first person who signs up.

    Run once, when the first account is created on a database that already had
    training history in it.
    """
    cur = conn.execute(
        "UPDATE workout SET user_id = ? WHERE user_id IS NULL", (user_id,)
    )
    conn.commit()
    return cur.rowcount


# ---------------------------------------------------------------------------
# API tokens
# ---------------------------------------------------------------------------

def add_token(conn, user_id, token_hash_value, label=None):
    conn.execute(
        "INSERT INTO api_token (token_hash, user_id, label, created_at) "
        "VALUES (?, ?, ?, ?)",
        (token_hash_value, user_id, label, now_local().isoformat(timespec="seconds")),
    )
    conn.commit()


def user_for_token_hash(conn, token_hash_value):
    row = conn.execute(
        "SELECT u.* FROM api_token t JOIN user u ON u.id = t.user_id "
        "WHERE t.token_hash = ?",
        (token_hash_value,),
    ).fetchone()
    if row is not None:
        conn.execute(
            "UPDATE api_token SET last_used = ? WHERE token_hash = ?",
            (now_local().isoformat(timespec="seconds"), token_hash_value),
        )
        conn.commit()
    return row


def tokens_for(conn, user_id):
    return conn.execute(
        "SELECT token_hash, label, created_at, last_used FROM api_token "
        "WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()


def delete_token(conn, user_id, token_hash_value):
    conn.execute(
        "DELETE FROM api_token WHERE user_id = ? AND token_hash = ?",
        (user_id, token_hash_value),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Exercises - shared catalogue, but "times done" is always yours
# ---------------------------------------------------------------------------

_TIMES_DONE = (
    "(SELECT COUNT(*) FROM workout_item wi JOIN workout w ON w.id = wi.workout_id "
    " WHERE wi.exercise_id = e.id AND w.user_id = ?) AS times_done"
)


def exercises_for(conn, user_id, body_part, include_archived=False):
    sql = "SELECT e.*, " + _TIMES_DONE + " FROM exercise e WHERE e.body_part = ?"
    if not include_archived:
        sql += " AND e.archived = 0"
    sql += " ORDER BY e.sort_order, e.name COLLATE NOCASE"
    return conn.execute(sql, (user_id, body_part)).fetchall()


def get_exercise(conn, user_id, exercise_id):
    return conn.execute(
        "SELECT e.*, " + _TIMES_DONE + " FROM exercise e WHERE e.id = ?",
        (user_id, exercise_id),
    ).fetchone()


def add_exercise(conn, name, body_part, image=None, note=None, equipment="other",
                 created_by=None):
    next_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM exercise WHERE body_part = ?",
        (body_part,),
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO exercise "
        "(name, body_part, image, note, equipment, archived, sort_order, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)",
        (name, body_part, image, note, equipment, next_order,
         now_local().isoformat(timespec="seconds"), created_by),
    )
    conn.commit()
    return cur.lastrowid


def update_exercise(conn, exercise_id, **fields):
    allowed = {"name", "body_part", "image", "note", "equipment", "archived", "sort_order"}
    sets, values = [], []
    for key, value in fields.items():
        if key in allowed:
            sets.append(key + " = ?")
            values.append(value)
    if not sets:
        return
    values.append(exercise_id)
    conn.execute("UPDATE exercise SET " + ", ".join(sets) + " WHERE id = ?", values)
    conn.commit()


def exercise_is_used(conn, exercise_id):
    return conn.execute(
        "SELECT 1 FROM workout_item WHERE exercise_id = ? LIMIT 1", (exercise_id,)
    ).fetchone() is not None


def delete_exercise(conn, exercise_id):
    """Hard-delete only if nobody has ever used it, otherwise archive so other
    people's history stays intact. Returns 'deleted' or 'archived'."""
    if exercise_is_used(conn, exercise_id):
        conn.execute("UPDATE exercise SET archived = 1 WHERE id = ?", (exercise_id,))
        conn.commit()
        return "archived"
    conn.execute("DELETE FROM exercise WHERE id = ?", (exercise_id,))
    conn.commit()
    return "deleted"


def exercise_name_clash(conn, body_part, name, ignore_id=None):
    sql = "SELECT id FROM exercise WHERE body_part = ? AND name = ? COLLATE NOCASE"
    params = [body_part, name]
    if ignore_id is not None:
        sql += " AND id != ?"
        params.append(ignore_id)
    return conn.execute(sql, params).fetchone() is not None


# ---------------------------------------------------------------------------
# Workouts - always scoped to one user
# ---------------------------------------------------------------------------

def create_workout(conn, user_id, body_part, exercise_ids):
    now = now_local().isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO workout (user_id, workout_date, body_part, started_at) "
        "VALUES (?, ?, ?, ?)",
        (user_id, today_local(), body_part, now),
    )
    workout_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO workout_item (workout_id, exercise_id, position) VALUES (?, ?, ?)",
        [(workout_id, ex_id, i) for i, ex_id in enumerate(exercise_ids)],
    )
    conn.commit()
    return workout_id


def get_workout(conn, user_id, workout_id):
    """Returns None if the workout does not exist OR belongs to someone else -
    which is what stops anyone reading another person's log by guessing ids."""
    return conn.execute(
        "SELECT * FROM workout WHERE id = ? AND user_id = ?", (workout_id, user_id)
    ).fetchone()


def workout_items(conn, workout_id):
    return conn.execute(
        "SELECT wi.*, e.name, e.image, e.note AS exercise_note, e.body_part, e.equipment "
        "FROM workout_item wi JOIN exercise e ON e.id = wi.exercise_id "
        "WHERE wi.workout_id = ? ORDER BY wi.position",
        (workout_id,),
    ).fetchall()


def todays_workout(conn, user_id):
    return conn.execute(
        "SELECT * FROM workout WHERE user_id = ? AND workout_date = ? "
        "ORDER BY id DESC LIMIT 1",
        (user_id, today_local()),
    ).fetchone()


def previous_workout(conn, user_id, body_part, before_id=None):
    sql = "SELECT * FROM workout WHERE user_id = ? AND body_part = ?"
    params = [user_id, body_part]
    if before_id is not None:
        sql += " AND id < ?"
        params.append(before_id)
    else:
        sql += " AND workout_date < ?"
        params.append(today_local())
    sql += " ORDER BY id DESC LIMIT 1"
    return conn.execute(sql, params).fetchone()


def recent_workouts(conn, user_id, limit=120, offset=0):
    return conn.execute(
        "SELECT w.*, COUNT(wi.id) AS exercise_count, "
        "  SUM(CASE WHEN wi.done_at IS NOT NULL THEN 1 ELSE 0 END) AS done_count "
        "FROM workout w LEFT JOIN workout_item wi ON wi.workout_id = w.id "
        "WHERE w.user_id = ? "
        "GROUP BY w.id ORDER BY w.workout_date DESC, w.id DESC LIMIT ? OFFSET ?",
        (user_id, limit, offset),
    ).fetchall()


def item_belongs_to(conn, user_id, workout_id, item_id):
    return conn.execute(
        "SELECT 1 FROM workout_item wi JOIN workout w ON w.id = wi.workout_id "
        "WHERE wi.id = ? AND wi.workout_id = ? AND w.user_id = ? LIMIT 1",
        (item_id, workout_id, user_id),
    ).fetchone() is not None


def toggle_item_done(conn, item_id):
    row = conn.execute("SELECT done_at FROM workout_item WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        return None
    new_value = None if row["done_at"] else now_local().isoformat(timespec="seconds")
    conn.execute("UPDATE workout_item SET done_at = ? WHERE id = ?", (new_value, item_id))
    conn.commit()
    return new_value


def finish_workout(conn, workout_id):
    conn.execute(
        "UPDATE workout SET finished_at = ? WHERE id = ?",
        (now_local().isoformat(timespec="seconds"), workout_id),
    )
    conn.commit()


def reopen_workout(conn, workout_id):
    conn.execute("UPDATE workout SET finished_at = NULL WHERE id = ?", (workout_id,))
    conn.commit()


def set_workout_note(conn, workout_id, note):
    conn.execute("UPDATE workout SET note = ? WHERE id = ?", (note or None, workout_id))
    conn.commit()


def set_workout_body_part(conn, workout_id, body_part):
    conn.execute("UPDATE workout SET body_part = ? WHERE id = ?", (body_part, workout_id))
    conn.commit()


def delete_workout(conn, workout_id):
    conn.execute("DELETE FROM workout WHERE id = ?", (workout_id,))
    conn.commit()


def replace_workout_items(conn, workout_id, exercise_ids):
    """Swap the whole exercise list, keeping done_at for anything that stays."""
    existing = {
        row["exercise_id"]: row["done_at"]
        for row in conn.execute(
            "SELECT exercise_id, done_at FROM workout_item WHERE workout_id = ?",
            (workout_id,),
        )
    }
    conn.execute("DELETE FROM workout_item WHERE workout_id = ?", (workout_id,))
    conn.executemany(
        "INSERT INTO workout_item (workout_id, exercise_id, position, done_at) "
        "VALUES (?, ?, ?, ?)",
        [(workout_id, ex_id, i, existing.get(ex_id)) for i, ex_id in enumerate(exercise_ids)],
    )
    conn.commit()


def known_exercise_ids(conn, ids):
    if not ids:
        return set()
    placeholders = ",".join("?" for _ in ids)
    return {
        row[0]
        for row in conn.execute(
            "SELECT id FROM exercise WHERE id IN (" + placeholders + ")", ids
        )
    }
