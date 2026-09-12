"""
Shretted - a one-person workout tracker built for an iPhone and a free
PythonAnywhere account.

Open it at the gym, it already knows which body part today is. Tap the
exercises your trainer gave you in the order he gave them, hit Start, and tick
them off as you go. Next week it shows you what you did last time.

Run locally:   python app.py      then open http://127.0.0.1:5000
On the server: see DEPLOY.md
"""
import csv
import hmac
import io
import os
import time
from datetime import datetime, timedelta

from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

import db
import stats as stats_mod
from config import (
    BODY_PARTS,
    BODY_PART_COLOURS,
    BRAND_DEEP,
    DB_PATH,
    HTTPS_ONLY,
    EQUIPMENT,
    MAX_UPLOAD_BYTES,
    PIN,
    SECRET_KEY,
    SPLIT,
    UPLOAD_DIR,
    body_part_for,
    now_local,
    today_local,
)
from images import ImageError, delete_image, disk_usage, ensure_upload_dir, save_upload

app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
    PERMANENT_SESSION_LIFETIME=timedelta(days=365),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # PythonAnywhere serves your site over HTTPS, so the login cookie should
    # never travel in clear. Turned off automatically for local development,
    # where there is no certificate.
    SESSION_COOKIE_SECURE=HTTPS_ONLY,
)

ensure_upload_dir()
db.init_db()

# Drop your own artwork at static/img/logo.svg (or .png / .jpg / .webp) and the
# app uses it everywhere in place of the built-in mark. Checked once at start,
# so adding the file needs a Reload.
LOGO_FILE = None
for _name in ("logo.svg", "logo.png", "logo.jpg", "logo.jpeg", "logo.webp"):
    if os.path.exists(os.path.join(app.static_folder, "img", _name)):
        LOGO_FILE = "img/" + _name
        break

MAX_EXERCISES_PER_SESSION = 30

# Crude but effective brute-force guard. A free web app is a single process,
# so a module-level dict is genuinely shared across requests. Nothing here is
# worth a real rate limiter.
_failed_logins = {"count": 0, "locked_until": 0.0}
LOGIN_ATTEMPTS_BEFORE_LOCKOUT = 8
LOGIN_LOCKOUT_SECONDS = 300


# ---------------------------------------------------------------------------
# Request plumbing
# ---------------------------------------------------------------------------

@app.before_request
def require_pin():
    if not PIN:
        return None
    if request.endpoint in {"login", "static", "healthz", "manifest"}:
        return None
    if session.get("unlocked"):
        return None
    return redirect(url_for("login", next=request.full_path))


@app.after_request
def no_store_html(response):
    """Stop iOS Safari showing a stale page when you come back to the tab."""
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


def conn():
    return db.get_conn()


def wants_json():
    return (
        request.headers.get("X-Requested-With") == "fetch"
        or request.accept_mimetypes.best == "application/json"
    )


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _to_date(value):
    return datetime(int(value[0:4]), int(value[5:7]), int(value[8:10]))


@app.template_filter("nice_date")
def nice_date(value):
    """2026-09-10 -> 'Thu 10 Sep', with Today/Yesterday shortcuts."""
    if not value:
        return ""
    value = value[:10]
    today = _to_date(today_local())
    when = _to_date(value)
    delta = (today - when).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    label = DAYS[when.weekday()][:3] + " " + str(when.day) + " " + MONTHS[when.month - 1]
    if when.year != today.year:
        label += " " + str(when.year)
    return label


@app.template_filter("long_date")
def long_date(value):
    if not value:
        return ""
    when = _to_date(value[:10])
    return (
        DAYS[when.weekday()] + " " + str(when.day) + " "
        + MONTHS[when.month - 1] + " " + str(when.year)
    )


@app.template_filter("month_name")
def month_name(value):
    """'2026-09' -> 'September 2026'."""
    if not value or len(value) < 7:
        return ""
    full = ["January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December"]
    return full[int(value[5:7]) - 1] + " " + value[0:4]


@app.template_filter("eq_id")
def eq_id(value):
    """Clamp an equipment value to one we actually have an icon for, so a
    stray database value can never inject an unknown <use> reference."""
    return value if value in EQUIPMENT else "other"


@app.template_filter("clock")
def clock(value):
    """ISO timestamp -> '18:42'."""
    if not value:
        return ""
    return value[11:16]


@app.template_filter("ago")
def ago(days):
    if days is None:
        return "never"
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return str(days) + " days ago"
    if days < 60:
        return str(days // 7) + " weeks ago"
    return str(days // 30) + " months ago"


@app.context_processor
def inject_globals():
    return {
        "BODY_PARTS": BODY_PARTS,
        "EQUIPMENT": EQUIPMENT,
        "COLOURS": BODY_PART_COLOURS,
        "BRAND_DEEP": BRAND_DEEP,
        "LOGO_FILE": LOGO_FILE,
        "today_body_part": body_part_for(),
        "today_name": DAYS[now_local().weekday()],
        "today_iso": today_local(),
        "pin_enabled": bool(PIN),
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _safe_next(target):
    """Only ever redirect to a path on this site.

    "/history" is fine. "//evil.com" is not - it starts with a slash but a
    browser reads it as a protocol-relative URL and leaves the site.
    """
    if not target or not target.startswith("/") or target.startswith("//"):
        return url_for("home")
    if "\\" in target or "\n" in target or "\r" in target:
        return url_for("home")
    return target


@app.route("/login", methods=["GET", "POST"])
def login():
    if not PIN:
        return redirect(url_for("home"))

    error = None
    if request.method == "POST":
        now = time.time()
        if now < _failed_logins["locked_until"]:
            wait = int(_failed_logins["locked_until"] - now) // 60 + 1
            error = "Too many wrong tries. Wait " + str(wait) + " min."
        else:
            entered = (request.form.get("pin") or "").strip()
            # compare_digest refuses non-ASCII str, so compare bytes - otherwise
            # posting any accented character would 500 instead of saying no.
            if len(entered) <= 64 and hmac.compare_digest(
                entered.encode("utf-8"), PIN.encode("utf-8")
            ):
                _failed_logins["count"] = 0
                session.permanent = True
                session["unlocked"] = True
                return redirect(_safe_next(request.form.get("next")))

            _failed_logins["count"] += 1
            if _failed_logins["count"] >= LOGIN_ATTEMPTS_BEFORE_LOCKOUT:
                _failed_logins["locked_until"] = now + LOGIN_LOCKOUT_SECONDS
                _failed_logins["count"] = 0
            error = "Wrong PIN"

    # Keep the destination across a wrong PIN, so a retry still lands where
    # you were heading rather than dumping you on the home screen.
    return render_template(
        "login.html",
        error=error,
        next=request.form.get("next") or request.args.get("next", ""),
    )


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Home - pick today's exercises
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    c = conn()
    try:
        override = request.args.get("bp")
        force_new = request.args.get("new") == "1"

        existing = db.todays_workout(c)
        if existing and not force_new and not override:
            return redirect(url_for("workout", workout_id=existing["id"]))

        scheduled = body_part_for()
        body_part = override if override in BODY_PARTS else scheduled
        is_rest_day = scheduled == "Rest" and not override

        exercises = [] if is_rest_day else db.exercises_for(c, body_part)

        previous = db.previous_workout(c, body_part)
        previous_items = db.workout_items(c, previous["id"]) if previous else []

        return render_template(
            "home.html",
            body_part=body_part,
            scheduled=scheduled,
            is_rest_day=is_rest_day,
            is_override=body_part != scheduled,
            exercises=exercises,
            previous=previous,
            previous_items=previous_items,
            existing=existing,
            edit_workout=None,
            preselected=[],
        )
    finally:
        c.close()


@app.route("/workout", methods=["POST"])
def create_workout():
    order_raw = request.form.get("order", "")
    body_part = request.form.get("body_part", "")
    ids = _parse_order(order_raw)

    if not ids:
        flash("Pick at least one exercise first.", "error")
        return redirect(url_for("home", bp=body_part or None))

    c = conn()
    try:
        ids = _keep_known_exercises(c, ids)
        if not ids:
            flash("Those exercises no longer exist.", "error")
            return redirect(url_for("home"))
        if body_part not in BODY_PARTS:
            body_part = db.get_exercise(c, ids[0])["body_part"]
        workout_id = db.create_workout(c, body_part, ids)
    finally:
        c.close()
    return redirect(url_for("workout", workout_id=workout_id))


def _parse_order(raw):
    """'12,4,9' -> [12, 4, 9], de-duplicated, order preserved, capped."""
    seen, out = set(), []
    for chunk in (raw or "").split(",")[: MAX_EXERCISES_PER_SESSION * 4]:
        chunk = chunk.strip()
        # The length cap matters: SQLite raises OverflowError on an integer
        # too big for 64 bits, so a hand-typed id would 500 rather than be
        # ignored.
        if not chunk.isdigit() or len(chunk) > 12:
            continue
        value = int(chunk)
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
        if len(out) >= MAX_EXERCISES_PER_SESSION:
            break
    return out


def _keep_known_exercises(c, ids):
    placeholders = ",".join("?" for _ in ids)
    known = {
        row[0]
        for row in c.execute(
            "SELECT id FROM exercise WHERE id IN (" + placeholders + ")", ids
        )
    }
    return [i for i in ids if i in known]


# ---------------------------------------------------------------------------
# A single session
# ---------------------------------------------------------------------------

@app.route("/workout/<int:workout_id>")
def workout(workout_id):
    c = conn()
    try:
        w = db.get_workout(c, workout_id)
        if w is None:
            abort(404)
        items = db.workout_items(c, workout_id)
        previous = db.previous_workout(c, w["body_part"], before_id=workout_id)
        previous_items = db.workout_items(c, previous["id"]) if previous else []
        done = sum(1 for i in items if i["done_at"])
        return render_template(
            "workout.html",
            w=w,
            items=items,
            done=done,
            is_today=w["workout_date"] == today_local(),
            previous=previous,
            previous_items=previous_items,
        )
    finally:
        c.close()


@app.route("/workout/<int:workout_id>/item/<int:item_id>/toggle", methods=["POST"])
def toggle_item(workout_id, item_id):
    c = conn()
    try:
        owner = c.execute(
            "SELECT workout_id FROM workout_item WHERE id = ?", (item_id,)
        ).fetchone()
        if owner is None or owner["workout_id"] != workout_id:
            abort(404)
        done_at = db.toggle_item_done(c, item_id)
    finally:
        c.close()
    if wants_json():
        return jsonify({"ok": True, "done_at": done_at, "clock": (done_at or "")[11:16]})
    return redirect(url_for("workout", workout_id=workout_id))


@app.route("/workout/<int:workout_id>/finish", methods=["POST"])
def finish(workout_id):
    c = conn()
    try:
        w = db.get_workout(c, workout_id)
        if w is None:
            abort(404)
        if w["finished_at"]:
            db.reopen_workout(c, workout_id)
        else:
            db.finish_workout(c, workout_id)
    finally:
        c.close()
    return redirect(url_for("workout", workout_id=workout_id))


@app.route("/workout/<int:workout_id>/note", methods=["POST"])
def workout_note(workout_id):
    c = conn()
    try:
        if db.get_workout(c, workout_id) is None:
            abort(404)
        db.set_workout_note(c, workout_id, (request.form.get("note") or "").strip()[:500])
    finally:
        c.close()
    return redirect(url_for("workout", workout_id=workout_id))


@app.route("/workout/<int:workout_id>/edit")
def edit_workout(workout_id):
    c = conn()
    try:
        w = db.get_workout(c, workout_id)
        if w is None:
            abort(404)
        items = db.workout_items(c, workout_id)
        body_part = request.args.get("bp")
        if body_part not in BODY_PARTS:
            body_part = w["body_part"]

        # Show hidden exercises too if this session used them - otherwise the
        # grid could not represent them and saving would quietly drop them.
        grid = list(db.exercises_for(c, body_part))
        shown = {e["id"] for e in grid}
        for item in items:
            if item["exercise_id"] not in shown:
                extra = db.get_exercise(c, item["exercise_id"])
                if extra is not None:
                    grid.append(extra)
                    shown.add(extra["id"])

        return render_template(
            "home.html",
            body_part=body_part,
            scheduled=body_part_for(),
            is_rest_day=False,
            is_override=body_part != w["body_part"],
            exercises=grid,
            previous=None,
            previous_items=[],
            existing=None,
            edit_workout=w,
            preselected=[i["exercise_id"] for i in items],
        )
    finally:
        c.close()


@app.route("/workout/<int:workout_id>/edit", methods=["POST"])
def save_edited_workout(workout_id):
    ids = _parse_order(request.form.get("order", ""))
    c = conn()
    try:
        w = db.get_workout(c, workout_id)
        if w is None:
            abort(404)
        ids = _keep_known_exercises(c, ids) if ids else []
        if not ids:
            flash("A session needs at least one exercise.", "error")
            return redirect(url_for("edit_workout", workout_id=workout_id))
        db.replace_workout_items(c, workout_id, ids)
        body_part = request.form.get("body_part")
        if body_part in BODY_PARTS and body_part != w["body_part"]:
            c.execute(
                "UPDATE workout SET body_part = ? WHERE id = ?", (body_part, workout_id)
            )
            c.commit()
    finally:
        c.close()
    return redirect(url_for("workout", workout_id=workout_id))


@app.route("/workout/<int:workout_id>/delete", methods=["POST"])
def remove_workout(workout_id):
    c = conn()
    try:
        db.delete_workout(c, workout_id)
    finally:
        c.close()
    flash("Session deleted.", "ok")
    return redirect(url_for("history"))


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@app.route("/history")
def history():
    c = conn()
    try:
        workouts = db.recent_workouts(c, limit=120)
        # Attach the exercise names so the list is readable without tapping in.
        summaries = {}
        for w in workouts:
            names = [
                row["name"]
                for row in c.execute(
                    "SELECT e.name FROM workout_item wi JOIN exercise e "
                    "ON e.id = wi.exercise_id WHERE wi.workout_id = ? "
                    "ORDER BY wi.position",
                    (w["id"],),
                )
            ]
            summaries[w["id"]] = names
        return render_template("history.html", workouts=workouts, summaries=summaries)
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@app.route("/stats")
def stats():
    c = conn()
    try:
        selected = request.args.get("bp")
        if selected not in BODY_PARTS:
            selected = None
        return render_template(
            "stats.html",
            head=stats_mod.headline(c),
            parts=stats_mod.by_body_part(c),
            board=stats_mod.exercise_leaderboard(c, body_part=selected),
            top=stats_mod.top_exercise(c),
            grid=stats_mod.activity_grid(c, weeks=12),
            selected=selected,
        )
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Managing the exercise catalogue
# ---------------------------------------------------------------------------

@app.route("/exercises")
def exercises():
    c = conn()
    try:
        selected = request.args.get("bp")
        if selected not in BODY_PARTS:
            selected = body_part_for()
            if selected not in BODY_PARTS:
                selected = BODY_PARTS[0]
        rows = db.exercises_for(c, selected, include_archived=True)
        return render_template("exercises.html", rows=rows, selected=selected)
    finally:
        c.close()


@app.route("/exercises/new", methods=["GET", "POST"])
def new_exercise():
    default_bp = request.args.get("bp")
    if default_bp not in BODY_PARTS:
        default_bp = body_part_for()
        if default_bp not in BODY_PARTS:
            default_bp = BODY_PARTS[0]

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()[:60]
        body_part = request.form.get("body_part")
        note = (request.form.get("note") or "").strip()[:200] or None
        equipment = request.form.get("equipment")
        if equipment not in EQUIPMENT:
            equipment = "other"

        if not name:
            flash("Give the exercise a name.", "error")
            return redirect(url_for("new_exercise", bp=body_part))
        if body_part not in BODY_PARTS:
            flash("Pick a body part.", "error")
            return redirect(url_for("new_exercise"))

        try:
            image = save_upload(request.files.get("photo"))
        except ImageError as exc:
            flash(str(exc), "error")
            return redirect(url_for("new_exercise", bp=body_part))

        c = conn()
        try:
            clash = c.execute(
                "SELECT id FROM exercise WHERE body_part = ? AND name = ? COLLATE NOCASE",
                (body_part, name),
            ).fetchone()
            if clash:
                delete_image(image)
                flash('"' + name + '" is already in ' + body_part + ".", "error")
                return redirect(url_for("exercises", bp=body_part))
            db.add_exercise(c, name, body_part, image=image, note=note,
                            equipment=equipment)
        finally:
            c.close()
        flash("Added " + name + ".", "ok")
        return redirect(url_for("exercises", bp=body_part))

    return render_template("exercise_form.html", row=None, default_bp=default_bp)


@app.route("/exercises/<int:exercise_id>/edit", methods=["GET", "POST"])
def edit_exercise(exercise_id):
    c = conn()
    try:
        row = db.get_exercise(c, exercise_id)
        if row is None:
            abort(404)

        if request.method == "POST":
            name = (request.form.get("name") or "").strip()[:60] or row["name"]
            body_part = request.form.get("body_part")
            if body_part not in BODY_PARTS:
                body_part = row["body_part"]
            note = (request.form.get("note") or "").strip()[:200] or None
            equipment = request.form.get("equipment")
            if equipment not in EQUIPMENT:
                equipment = row["equipment"]

            # There is a UNIQUE index on (body_part, name). Without this check
            # renaming one exercise onto another would raise IntegrityError
            # and show a 500 instead of a message.
            clash = c.execute(
                "SELECT id FROM exercise WHERE body_part = ? AND name = ? COLLATE NOCASE "
                "AND id != ?",
                (body_part, name, exercise_id),
            ).fetchone()
            if clash:
                flash('"' + name + '" is already in ' + body_part + ".", "error")
                return redirect(url_for("edit_exercise", exercise_id=exercise_id))

            fields = {"name": name, "body_part": body_part, "note": note,
                      "equipment": equipment}

            if request.form.get("remove_photo") == "1":
                delete_image(row["image"])
                fields["image"] = None
            else:
                try:
                    new_image = save_upload(request.files.get("photo"))
                except ImageError as exc:
                    flash(str(exc), "error")
                    return redirect(url_for("edit_exercise", exercise_id=exercise_id))
                if new_image:
                    delete_image(row["image"])
                    fields["image"] = new_image

            db.update_exercise(c, exercise_id, **fields)
            flash("Saved.", "ok")
            return redirect(url_for("exercises", bp=body_part))

        return render_template("exercise_form.html", row=row, default_bp=row["body_part"])
    finally:
        c.close()


@app.route("/exercises/<int:exercise_id>/delete", methods=["POST"])
def remove_exercise(exercise_id):
    c = conn()
    try:
        row = db.get_exercise(c, exercise_id)
        if row is None:
            abort(404)
        outcome = db.delete_exercise(c, exercise_id)
        if outcome == "deleted":
            delete_image(row["image"])
            flash("Deleted " + row["name"] + ".", "ok")
        else:
            flash(
                "Hidden " + row["name"] + " - it stays in your past sessions.", "ok"
            )
        return redirect(url_for("exercises", bp=row["body_part"]))
    finally:
        c.close()


@app.route("/exercises/<int:exercise_id>/restore", methods=["POST"])
def restore_exercise(exercise_id):
    c = conn()
    try:
        row = db.get_exercise(c, exercise_id)
        if row is None:
            abort(404)
        db.update_exercise(c, exercise_id, archived=0)
        return redirect(url_for("exercises", bp=row["body_part"]))
    finally:
        c.close()


@app.route("/exercises/<int:exercise_id>/move", methods=["POST"])
def move_exercise(exercise_id):
    """Swap this exercise with its neighbour so the grid order matches how you
    actually train."""
    direction = request.form.get("dir")
    c = conn()
    try:
        row = db.get_exercise(c, exercise_id)
        if row is None:
            abort(404)
        siblings = list(db.exercises_for(c, row["body_part"], include_archived=True))
        index = next((i for i, s in enumerate(siblings) if s["id"] == exercise_id), None)
        if index is not None:
            swap_with = index - 1 if direction == "up" else index + 1
            if 0 <= swap_with < len(siblings):
                siblings[index], siblings[swap_with] = siblings[swap_with], siblings[index]
                for position, item in enumerate(siblings):
                    c.execute(
                        "UPDATE exercise SET sort_order = ? WHERE id = ?",
                        (position, item["id"]),
                    )
                c.commit()
        if wants_json():
            return jsonify({"ok": True})
        return redirect(url_for("exercises", bp=row["body_part"]))
    finally:
        c.close()


@app.route("/exercises/bulk", methods=["GET", "POST"])
def bulk_add():
    """Paste a list of names, one per line, to set up a body part quickly."""
    default_bp = request.args.get("bp")
    if default_bp not in BODY_PARTS:
        default_bp = BODY_PARTS[0]

    if request.method == "POST":
        body_part = request.form.get("body_part")
        if body_part not in BODY_PARTS:
            flash("Pick a body part.", "error")
            return redirect(url_for("bulk_add"))
        names = [
            line.strip()[:60]
            for line in (request.form.get("names") or "").splitlines()
            if line.strip()
        ]
        added = 0
        c = conn()
        try:
            for name in names[:100]:
                clash = c.execute(
                    "SELECT id FROM exercise WHERE body_part = ? AND name = ? COLLATE NOCASE",
                    (body_part, name),
                ).fetchone()
                if clash:
                    continue
                db.add_exercise(c, name, body_part)
                added += 1
        finally:
            c.close()
        flash("Added " + str(added) + " to " + body_part + ".", "ok")
        return redirect(url_for("exercises", bp=body_part))

    return render_template("bulk.html", default_bp=default_bp)


# ---------------------------------------------------------------------------
# Uploaded photos, settings, export
# ---------------------------------------------------------------------------

@app.route("/photo/<filename>")
def photo(filename):
    """Serve an uploaded thumbnail.

    Photos live OUTSIDE static/ on purpose, so the PythonAnywhere static file
    mapping cannot serve them straight off disk to anyone who guesses a name.
    Going through Flask keeps them behind the PIN, and lets us set a long
    cache header - filenames are random and never reused.
    """
    response = send_from_directory(UPLOAD_DIR, filename)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@app.route("/settings")
def settings():
    used_bytes, photo_count = disk_usage()
    db_bytes = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    c = conn()
    try:
        totals = {
            "workouts": c.execute("SELECT COUNT(*) FROM workout").fetchone()[0],
            "exercises": c.execute("SELECT COUNT(*) FROM exercise").fetchone()[0],
        }
    finally:
        c.close()
    return render_template(
        "settings.html",
        split=[(DAYS[i], SPLIT.get(i, "Rest")) for i in range(7)],
        photo_kb=round(used_bytes / 1024),
        photo_count=photo_count,
        db_kb=round(db_bytes / 1024, 1),
        totals=totals,
    )


@app.route("/export.csv")
def export_csv():
    c = conn()
    try:
        rows = c.execute(
            "SELECT w.workout_date, w.body_part, w.started_at, w.finished_at, "
            "  wi.position, e.name, wi.done_at, w.note "
            "FROM workout w JOIN workout_item wi ON wi.workout_id = w.id "
            "JOIN exercise e ON e.id = wi.exercise_id "
            "ORDER BY w.workout_date DESC, w.id DESC, wi.position"
        ).fetchall()
    finally:
        c.close()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["date", "body_part", "started", "finished", "order", "exercise",
         "completed_at", "session_note"]
    )
    for r in rows:
        writer.writerow(
            [r["workout_date"], r["body_part"], r["started_at"], r["finished_at"] or "",
             r["position"] + 1, r["name"], r["done_at"] or "", r["note"] or ""]
        )
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=shretted-"
            + today_local() + ".csv"
        },
    )


@app.route("/backup.sqlite3")
def backup():
    """Download the whole database as one file. Keep a copy somewhere safe.

    Uses SQLite's own backup API rather than handing over the live file, so
    what you download is always a consistent snapshot even if a write lands
    halfway through.
    """
    snapshot = db.snapshot_bytes()
    return Response(
        snapshot,
        mimetype="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename=shretted-"
            + today_local() + ".sqlite3",
            "Content-Length": str(len(snapshot)),
        },
    )


@app.route("/manifest.webmanifest")
def manifest():
    # scope matters: without it, iOS opens every link inside the standalone
    # window with no way back out.
    response = jsonify(
        {
            "name": "Shretted",
            "short_name": "Shretted",
            "id": "/",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "orientation": "portrait",
            "background_color": "#F3F2ED",
            "theme_color": "#F3F2ED",
            "icons": [
                {
                    "src": url_for("static", filename="img/icon-192.png"),
                    "sizes": "192x192",
                    "type": "image/png",
                },
                {
                    "src": url_for("static", filename="img/icon-512.png"),
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
            ],
        }
    )
    response.mimetype = "application/manifest+json"
    return response


@app.route("/healthz")
def healthz():
    return {"ok": True, "today": today_local(), "body_part": body_part_for()}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404,
                           message="That page does not exist."), 404


@app.errorhandler(413)
def too_large(_e):
    flash("That photo is too big. Try a smaller one.", "error")
    return redirect(url_for("exercises"))


@app.errorhandler(500)
def server_error(_e):
    return render_template("error.html", code=500,
                           message="Something broke. Check the server error log."), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
