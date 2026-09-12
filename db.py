"""
SQLite storage layer. Standard library only - no ORM, no extra packages.

Why SQLite and not MySQL: a free PythonAnywhere web app runs in a single
worker process, and this app has exactly one user, so there is never more than
one writer. SQLite in that setting is simpler, needs no credentials, and the
whole database is one file you can download as a backup.

Note: PythonAnywhere stores your files on a network filesystem, where SQLite's
WAL mode is unreliable. We deliberately stay on the default rollback journal
and set a generous busy timeout instead.
"""
import os
import sqlite3

from config import DB_PATH, now_local, today_local

SCHEMA = """
CREATE TABLE IF NOT EXISTS exercise (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    body_part   TEXT    NOT NULL,
    image       TEXT,
    note        TEXT,
    equipment   TEXT    NOT NULL DEFAULT 'other',
    archived    INTEGER NOT NULL DEFAULT 0,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_exercise_name
    ON exercise (body_part, name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS workout (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_date TEXT    NOT NULL,
    body_part    TEXT    NOT NULL,
    started_at   TEXT    NOT NULL,
    finished_at  TEXT,
    note         TEXT
);

CREATE INDEX IF NOT EXISTS ix_workout_date ON workout (workout_date DESC);

CREATE TABLE IF NOT EXISTS workout_item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id  INTEGER NOT NULL REFERENCES workout(id) ON DELETE CASCADE,
    exercise_id INTEGER NOT NULL REFERENCES exercise(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    done_at     TEXT
);

CREATE INDEX IF NOT EXISTS ix_item_workout  ON workout_item (workout_id, position);
CREATE INDEX IF NOT EXISTS ix_item_exercise ON workout_item (exercise_id);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create the tables if they are missing, then seed the exercise list.

    The seed runs once, ever. PRAGMA user_version records that it has happened,
    so deleting every exercise on purpose does not cause all 84 starter
    exercises to reappear the next time the app restarts.
    """
    first_run = not os.path.exists(DB_PATH)
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        seeded = conn.execute("PRAGMA user_version").fetchone()[0]
        if not seeded:
            if conn.execute("SELECT COUNT(*) FROM exercise").fetchone()[0] == 0:
                seed_exercises(conn)
            conn.execute("PRAGMA user_version = 1")
            conn.commit()
    finally:
        conn.close()
    return first_run


def snapshot_bytes():
    """A consistent copy of the whole database, as bytes, for the backup link."""
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
    """Fill an empty exercise table with a starter catalogue."""
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
# Exercises
# ---------------------------------------------------------------------------

def exercises_for(conn, body_part, include_archived=False):
    sql = (
        "SELECT e.*, "
        "  (SELECT COUNT(*) FROM workout_item wi WHERE wi.exercise_id = e.id) AS times_done "
        "FROM exercise e WHERE e.body_part = ?"
    )
    if not include_archived:
        sql += " AND e.archived = 0"
    sql += " ORDER BY e.sort_order, e.name COLLATE NOCASE"
    return conn.execute(sql, (body_part,)).fetchall()


def all_exercises(conn, include_archived=True):
    sql = (
        "SELECT e.*, "
        "  (SELECT COUNT(*) FROM workout_item wi WHERE wi.exercise_id = e.id) AS times_done "
        "FROM exercise e"
    )
    if not include_archived:
        sql += " WHERE e.archived = 0"
    sql += " ORDER BY e.body_part, e.sort_order, e.name COLLATE NOCASE"
    return conn.execute(sql).fetchall()


def get_exercise(conn, exercise_id):
    # times_done is selected here too, so a row from this function can be
    # dropped straight into the exercise grid alongside exercises_for() rows.
    return conn.execute(
        "SELECT e.*, "
        "  (SELECT COUNT(*) FROM workout_item wi WHERE wi.exercise_id = e.id) AS times_done "
        "FROM exercise e WHERE e.id = ?",
        (exercise_id,),
    ).fetchone()


def add_exercise(conn, name, body_part, image=None, note=None, equipment="other"):
    next_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM exercise WHERE body_part = ?",
        (body_part,),
    ).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO exercise (name, body_part, image, note, equipment, archived, sort_order, created_at) "
        "VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
        (name, body_part, image, note, equipment, next_order,
         now_local().isoformat(timespec="seconds")),
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
    row = conn.execute(
        "SELECT 1 FROM workout_item WHERE exercise_id = ? LIMIT 1", (exercise_id,)
    ).fetchone()
    return row is not None


def delete_exercise(conn, exercise_id):
    """Hard-delete if it has never been used, otherwise archive it so past
    workouts keep their history. Returns 'deleted' or 'archived'."""
    if exercise_is_used(conn, exercise_id):
        conn.execute("UPDATE exercise SET archived = 1 WHERE id = ?", (exercise_id,))
        conn.commit()
        return "archived"
    conn.execute("DELETE FROM exercise WHERE id = ?", (exercise_id,))
    conn.commit()
    return "deleted"


# ---------------------------------------------------------------------------
# Workouts
# ---------------------------------------------------------------------------

def create_workout(conn, body_part, exercise_ids):
    """exercise_ids must already be in the order you intend to train them."""
    now = now_local().isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO workout (workout_date, body_part, started_at) VALUES (?, ?, ?)",
        (today_local(), body_part, now),
    )
    workout_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO workout_item (workout_id, exercise_id, position) VALUES (?, ?, ?)",
        [(workout_id, ex_id, i) for i, ex_id in enumerate(exercise_ids)],
    )
    conn.commit()
    return workout_id


def get_workout(conn, workout_id):
    return conn.execute("SELECT * FROM workout WHERE id = ?", (workout_id,)).fetchone()


def workout_items(conn, workout_id):
    return conn.execute(
        "SELECT wi.*, e.name, e.image, e.note AS exercise_note, e.body_part, e.equipment "
        "FROM workout_item wi JOIN exercise e ON e.id = wi.exercise_id "
        "WHERE wi.workout_id = ? ORDER BY wi.position",
        (workout_id,),
    ).fetchall()


def todays_workout(conn):
    return conn.execute(
        "SELECT * FROM workout WHERE workout_date = ? ORDER BY id DESC LIMIT 1",
        (today_local(),),
    ).fetchone()


def previous_workout(conn, body_part, before_id=None):
    """The most recent session for this body part, ignoring today's."""
    sql = "SELECT * FROM workout WHERE body_part = ?"
    params = [body_part]
    if before_id is not None:
        sql += " AND id < ?"
        params.append(before_id)
    else:
        sql += " AND workout_date < ?"
        params.append(today_local())
    sql += " ORDER BY id DESC LIMIT 1"
    return conn.execute(sql, params).fetchone()


def recent_workouts(conn, limit=60, offset=0):
    return conn.execute(
        "SELECT w.*, COUNT(wi.id) AS exercise_count, "
        "  SUM(CASE WHEN wi.done_at IS NOT NULL THEN 1 ELSE 0 END) AS done_count "
        "FROM workout w LEFT JOIN workout_item wi ON wi.workout_id = w.id "
        "GROUP BY w.id ORDER BY w.workout_date DESC, w.id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()


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


def delete_workout(conn, workout_id):
    conn.execute("DELETE FROM workout WHERE id = ?", (workout_id,))
    conn.commit()


def replace_workout_items(conn, workout_id, exercise_ids):
    """Swap the whole exercise list of an existing session, keeping any
    done_at timestamps for exercises that survive the edit."""
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
