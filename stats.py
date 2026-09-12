"""
Everything the Stats page needs. Read-only queries over the same SQLite file.
"""
from datetime import date, timedelta

from config import BODY_PARTS, SPLIT, today_local


def _parse_date(value):
    return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))


def headline(conn):
    """The four numbers across the top of the Stats page."""
    total_sessions = conn.execute("SELECT COUNT(*) FROM workout").fetchone()[0]
    total_exercises = conn.execute("SELECT COUNT(*) FROM workout_item").fetchone()[0]

    month_prefix = today_local()[:7]
    this_month = conn.execute(
        "SELECT COUNT(*) FROM workout WHERE workout_date LIKE ?", (month_prefix + "%",)
    ).fetchone()[0]

    first = conn.execute("SELECT MIN(workout_date) FROM workout").fetchone()[0]

    return {
        "total_sessions": total_sessions,
        "total_exercises": total_exercises,
        "this_month": this_month,
        "streak": current_streak(conn),
        "first_session": first,
        "avg_per_session": round(total_exercises / total_sessions, 1) if total_sessions else 0,
    }


def current_streak(conn):
    """Consecutive scheduled training days you have not missed.

    Rest days (Sunday, by default) are skipped rather than breaking the run.
    Today only breaks the streak once it is over - if you have not trained yet
    today we start counting from yesterday.
    """
    trained = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT workout_date FROM workout ORDER BY workout_date DESC LIMIT 800"
        )
    }
    if not trained:
        return 0

    cursor = _parse_date(today_local())
    if cursor.isoformat() not in trained:
        cursor -= timedelta(days=1)

    streak = 0
    # 800 days back is a generous ceiling; the loop always terminates.
    for _ in range(800):
        if SPLIT.get(cursor.weekday(), "Rest") == "Rest":
            cursor -= timedelta(days=1)
            continue
        if cursor.isoformat() in trained:
            streak += 1
            cursor -= timedelta(days=1)
        else:
            break
    return streak


def by_body_part(conn):
    """Sessions per body part, plus when you last trained it."""
    rows = conn.execute(
        "SELECT body_part, COUNT(*) AS sessions, MAX(workout_date) AS last_date "
        "FROM workout GROUP BY body_part"
    ).fetchall()
    found = {r["body_part"]: r for r in rows}

    today = _parse_date(today_local())
    out = []
    for part in BODY_PARTS:
        row = found.get(part)
        last_date = row["last_date"] if row else None
        days_ago = (today - _parse_date(last_date)).days if last_date else None
        out.append(
            {
                "body_part": part,
                "sessions": row["sessions"] if row else 0,
                "last_date": last_date,
                "days_ago": days_ago,
            }
        )
    return out


def exercise_leaderboard(conn, body_part=None, limit=None):
    """Every exercise with how many times you have logged it, most-used first.

    Exercises you have never done are included with a count of 0, so you can
    see what you keep skipping as easily as what you keep repeating.
    """
    sql = (
        "SELECT e.id, e.name, e.body_part, e.image, e.equipment, e.archived, "
        "  COUNT(wi.id) AS times_done, MAX(w.workout_date) AS last_date "
        "FROM exercise e "
        "LEFT JOIN workout_item wi ON wi.exercise_id = e.id "
        "LEFT JOIN workout w ON w.id = wi.workout_id "
    )
    params = []
    if body_part:
        sql += "WHERE e.body_part = ? "
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


def top_exercise(conn):
    board = exercise_leaderboard(conn, limit=1)
    if board and board[0]["times_done"] > 0:
        return board[0]
    return None


def activity_grid(conn, weeks=12):
    """A Monday-to-Sunday dot grid of the last N weeks, oldest week first.

    Each cell is: {'date', 'body_part' (or None), 'scheduled', 'future'}
    """
    today = _parse_date(today_local())
    # Start on the Monday of the week that is `weeks - 1` weeks back.
    start = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)

    logged = {
        row["workout_date"]: row["body_part"]
        for row in conn.execute(
            "SELECT workout_date, body_part FROM workout WHERE workout_date >= ? "
            "ORDER BY id",
            (start.isoformat(),),
        )
    }

    grid = []
    for week in range(weeks):
        row = []
        for day in range(7):
            cell_date = start + timedelta(weeks=week, days=day)
            scheduled = SPLIT.get(cell_date.weekday(), "Rest") != "Rest"
            row.append(
                {
                    "date": cell_date.isoformat(),
                    "label": cell_date.strftime("%a %d %b"),
                    "body_part": logged.get(cell_date.isoformat()),
                    "scheduled": scheduled,
                    "future": cell_date > today,
                    "today": cell_date == today,
                }
            )
        grid.append(row)
    return grid


def month_summary(conn, months=6):
    """Sessions per calendar month, newest first."""
    return [
        dict(row)
        for row in conn.execute(
            "SELECT substr(workout_date, 1, 7) AS month, COUNT(*) AS sessions "
            "FROM workout GROUP BY month ORDER BY month DESC LIMIT ?",
            (months,),
        )
    ]
