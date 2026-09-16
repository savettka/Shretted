"""
Everything the Stats page needs. Read-only, and every query is scoped to one
user - your numbers are yours, even though the exercise catalogue is shared.
"""
from datetime import date, timedelta

from config import BODY_PARTS, today_local


def _parse_date(value):
    return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))


def headline(conn, user_id, split):
    total_sessions = conn.execute(
        "SELECT COUNT(*) FROM workout WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    total_exercises = conn.execute(
        "SELECT COUNT(*) FROM workout_item wi JOIN workout w ON w.id = wi.workout_id "
        "WHERE w.user_id = ?",
        (user_id,),
    ).fetchone()[0]

    this_month = conn.execute(
        "SELECT COUNT(*) FROM workout WHERE user_id = ? AND workout_date LIKE ?",
        (user_id, today_local()[:7] + "%"),
    ).fetchone()[0]

    first = conn.execute(
        "SELECT MIN(workout_date) FROM workout WHERE user_id = ?", (user_id,)
    ).fetchone()[0]

    return {
        "total_sessions": total_sessions,
        "total_exercises": total_exercises,
        "this_month": this_month,
        "streak": current_streak(conn, user_id, split),
        "first_session": first,
        "avg_per_session": round(total_exercises / total_sessions, 1) if total_sessions else 0,
    }


def current_streak(conn, user_id, split):
    """Consecutive scheduled training days not missed.

    Rest days are skipped rather than breaking the run, and today only counts
    against you once it is over.
    """
    trained = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT workout_date FROM workout WHERE user_id = ? "
            "ORDER BY workout_date DESC LIMIT 800",
            (user_id,),
        )
    }
    if not trained:
        return 0

    cursor = _parse_date(today_local())
    if cursor.isoformat() not in trained:
        cursor -= timedelta(days=1)

    streak = 0
    for _ in range(800):
        if split.get(cursor.weekday(), "Rest") == "Rest":
            cursor -= timedelta(days=1)
            continue
        if cursor.isoformat() in trained:
            streak += 1
            cursor -= timedelta(days=1)
        else:
            break
    return streak


def by_body_part(conn, user_id):
    rows = conn.execute(
        "SELECT body_part, COUNT(*) AS sessions, MAX(workout_date) AS last_date "
        "FROM workout WHERE user_id = ? GROUP BY body_part",
        (user_id,),
    ).fetchall()
    found = {r["body_part"]: r for r in rows}

    today = _parse_date(today_local())
    out = []
    for part in BODY_PARTS:
        row = found.get(part)
        last_date = row["last_date"] if row else None
        out.append(
            {
                "body_part": part,
                "sessions": row["sessions"] if row else 0,
                "last_date": last_date,
                "days_ago": (today - _parse_date(last_date)).days if last_date else None,
            }
        )
    return out


def exercise_leaderboard(conn, user_id, body_part=None, limit=None):
    """Every exercise with how many times YOU have logged it, most-used first.

    Exercises you have never done are included with a count of 0, so it is as
    easy to see what you keep skipping as what you keep repeating.
    """
    sql = (
        "SELECT e.id, e.name, e.body_part, e.image, e.equipment, e.archived, "
        "  COUNT(wi.id) AS times_done, MAX(w.workout_date) AS last_date "
        "FROM exercise e "
        "LEFT JOIN workout_item wi ON wi.exercise_id = e.id "
        "LEFT JOIN workout w ON w.id = wi.workout_id AND w.user_id = ? "
        # the join above keeps other people's rows out of the count
        "WHERE (wi.id IS NULL OR w.id IS NOT NULL) "
    )
    params = [user_id]
    if body_part:
        sql += "AND e.body_part = ? "
        params.append(body_part)
    sql += "GROUP BY e.id ORDER BY times_done DESC, e.name COLLATE NOCASE"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    today = _parse_date(today_local())
    out = []
    for row in conn.execute(sql, params):
        item = dict(row)
        item["days_ago"] = (
            (today - _parse_date(row["last_date"])).days if row["last_date"] else None
        )
        out.append(item)
    return out


def top_exercise(conn, user_id):
    board = exercise_leaderboard(conn, user_id, limit=1)
    if board and board[0]["times_done"] > 0:
        return board[0]
    return None


def activity_grid(conn, user_id, split, weeks=12):
    """A Monday-to-Sunday dot grid of the last N weeks, oldest week first."""
    today = _parse_date(today_local())
    start = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)

    logged = {
        row["workout_date"]: row["body_part"]
        for row in conn.execute(
            "SELECT workout_date, body_part FROM workout "
            "WHERE user_id = ? AND workout_date >= ? ORDER BY id",
            (user_id, start.isoformat()),
        )
    }

    grid = []
    for week in range(weeks):
        row = []
        for day in range(7):
            cell = start + timedelta(weeks=week, days=day)
            row.append(
                {
                    "date": cell.isoformat(),
                    "label": cell.strftime("%a %d %b"),
                    "body_part": logged.get(cell.isoformat()),
                    "scheduled": split.get(cell.weekday(), "Rest") != "Rest",
                    "future": cell > today,
                    "today": cell == today,
                }
            )
        grid.append(row)
    return grid
