"""
Shretted - a workout tracker for a small group of people, built for an iPhone
and a free PythonAnywhere account.

Open it at the gym, it already knows which body part today is for you. Tap the
exercises your trainer gave you in the order he gave them, hit Start, and tick
them off as you go. Next week it shows you what you did last time.

Everyone shares one exercise catalogue; every workout belongs to one person.

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
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

import auth
import db
import stats as stats_mod
from config import (
    BODY_PARTS,
    BODY_PART_COLOURS,
    BRAND_DEEP,
    DB_PATH,
    EQUIPMENT,
    HTTPS_ONLY,
    INVITE_CODE,
    MAX_UPLOAD_BYTES,
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
    SESSION_COOKIE_SECURE=HTTPS_ONLY,
    # Cache CSS/JS/icons for a year. Flask's default is no-cache, which makes
    # the phone revalidate every file on every page load - a round trip per
    # file, per screen. Safe because every asset URL carries a ?v= that changes
    # when the file does.
    SEND_FILE_MAX_AGE_DEFAULT=31536000,
)

ensure_upload_dir()
db.init_db()

# Drop your own artwork at static/img/logo.svg (or .png / .jpg / .webp) and the
# app uses it in place of the built-in mark. Checked once at start, so adding
# the file needs a Reload.
LOGO_FILE = None
for _name in ("logo.svg", "logo.png", "logo.jpg", "logo.jpeg", "logo.webp"):
    if os.path.exists(os.path.join(app.static_folder, "img", _name)):
        LOGO_FILE = "img/" + _name
        break

MAX_EXERCISES_PER_SESSION = 30

# Crude but effective brute-force guard, keyed by email. A free web app is a
# single process, so a module-level dict really is shared across requests.
_fail_count = {}
_locked_until = {}
ATTEMPTS_BEFORE_LOCKOUT = 8
LOCKOUT_SECONDS = 300

PUBLIC_ENDPOINTS = {"login", "signup", "static", "healthz", "manifest"}


# ---------------------------------------------------------------------------
# Who is asking
# ---------------------------------------------------------------------------

def load_user():
    """Resolve the caller from the session cookie, or a Bearer token.

    The token path is what the iOS app will use; the cookie path is the web
    app. Both end up at the same place - g.user.
    """
    token = auth.bearer_from(request.headers)
    c = db.get_conn()
    try:
        if token:
            return db.user_for_token_hash(c, auth.token_hash(token))
        user_id = session.get("uid")
        if user_id:
            return db.get_user(c, user_id)
    finally:
        c.close()
    return None


@app.before_request
def require_login():
    g.user = None
    g.split = dict(SPLIT)

    if request.endpoint in PUBLIC_ENDPOINTS or (request.endpoint or "").startswith("api."):
        return None

    user = load_user()
    if user is None:
        session.pop("uid", None)
        return redirect(url_for("login", next=request.full_path))

    g.user = user
    g.split = db.split_of(user)
    return None


def current_user_id():
    return g.user["id"]


@app.after_request
def fresh_html(response):
    """Always revalidate a page, but never forbid storing it.

    "no-store" would also disable Safari's back-forward cache, which is what
    makes the back gesture instant. "no-cache" still guarantees you never see
    a stale workout.
    """
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-cache, private"
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
    return (DAYS[when.weekday()] + " " + str(when.day) + " "
            + MONTHS[when.month - 1] + " " + str(when.year))


@app.template_filter("month_name")
def month_name(value):
    if not value or len(value) < 7:
        return ""
    full = ["January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December"]
    return full[int(value[5:7]) - 1] + " " + value[0:4]


@app.template_filter("eq_id")
def eq_id(value):
    """Clamp equipment to one we have an icon for, so a stray database value
    can never inject an unknown <use> reference."""
    return value if value in EQUIPMENT else "other"


@app.template_filter("clock")
def clock(value):
    return value[11:16] if value else ""


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
    split = getattr(g, "split", SPLIT)
    return {
        "BODY_PARTS": BODY_PARTS,
        "EQUIPMENT": EQUIPMENT,
        "COLOURS": BODY_PART_COLOURS,
        "BRAND_DEEP": BRAND_DEEP,
        "LOGO_FILE": LOGO_FILE,
        "DAYS": DAYS,
        "me": getattr(g, "user", None),
        "today_body_part": body_part_for(split),
        "today_name": DAYS[now_local().weekday()],
        "today_iso": today_local(),
    }


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def _safe_next(target):
    """Only ever redirect to a path on this site. "//evil.com" starts with a
    slash but a browser reads it as protocol-relative and leaves the site."""
    if not target or not target.startswith("/") or target.startswith("//"):
        return url_for("home")
    if "\\" in target or "\n" in target or "\r" in target:
        return url_for("home")
    return target


def _locked_out(email):
    until = _locked_until.get(email)
    return bool(until and time.time() < until)


def _note_failure(email):
    hits = _fail_count.get(email, 0) + 1
    _fail_count[email] = hits
    if hits >= ATTEMPTS_BEFORE_LOCKOUT:
        _locked_until[email] = time.time() + LOCKOUT_SECONDS
        _fail_count[email] = 0


def _clear_failures(email):
    _fail_count.pop(email, None)
    _locked_until.pop(email, None)


@app.route("/login", methods=["GET", "POST"])
def login():
    c = conn()
    try:
        first_run = db.count_users(c) == 0
    finally:
        c.close()
    if first_run:
        return redirect(url_for("signup"))

    error = None
    email = ""
    if request.method == "POST":
        email = auth.clean_email(request.form.get("email"))
        password = request.form.get("password") or ""

        if _locked_out(email):
            error = "Too many attempts. Try again in a few minutes."
        else:
            c = conn()
            try:
                user = db.get_user_by_email(c, email)
                if user and auth.verify_password(user["password_hash"], password):
                    _clear_failures(email)
                    db.touch_user(c, user["id"])
                    session.permanent = True
                    session["uid"] = user["id"]
                    return redirect(_safe_next(request.form.get("next")))
            finally:
                c.close()
            _note_failure(email)
            error = "Wrong email or password."

    return render_template(
        "login.html",
        error=error,
        email=email,
        next=request.form.get("next") or request.args.get("next", ""),
        can_signup=bool(INVITE_CODE),
    )


@app.route("/signup", methods=["GET", "POST"])
def signup():
    c = conn()
    try:
        first_run = db.count_users(c) == 0
    finally:
        c.close()

    # After the owner exists, you need the invite code. With no code set,
    # signup is closed - which is the safe default for a private app.
    if not first_run and not INVITE_CODE:
        return render_template("signup.html", closed=True, first_run=False)

    error = None
    form = {"name": "", "email": ""}
    if request.method == "POST":
        form["name"] = (request.form.get("name") or "").strip()
        form["email"] = auth.clean_email(request.form.get("email"))
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        code = (request.form.get("code") or "").strip()

        try:
            # compare_digest refuses non-ASCII str, so compare bytes - otherwise
            # an accented character in the code field would 500.
            if not first_run and not hmac.compare_digest(
                code.encode("utf-8"), INVITE_CODE.encode("utf-8")
            ):
                raise auth.AuthError("That invite code is not right.")
            name, email = auth.check_signup(form["name"], form["email"], password, confirm)

            c = conn()
            try:
                if db.email_taken(c, email):
                    raise auth.AuthError("There is already an account with that email.")
                user_id = db.create_user(
                    c, name, email, auth.hash_password(password), is_owner=first_run
                )
                if first_run:
                    # A database that already had training history in it from
                    # before accounts existed - hand it all to the owner.
                    claimed = db.claim_orphan_workouts(c, user_id)
                    if claimed:
                        flash(str(claimed) + " earlier sessions are now yours.", "ok")
            finally:
                c.close()

            session.permanent = True
            session["uid"] = user_id
            return redirect(url_for("home"))
        except auth.AuthError as exc:
            error = str(exc)

    return render_template(
        "signup.html", error=error, form=form, first_run=first_run, closed=False
    )


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/account", methods=["GET", "POST"])
def account():
    c = conn()
    try:
        if request.method == "POST":
            action = request.form.get("action")

            if action == "split":
                new_split = {}
                for day in range(7):
                    choice = request.form.get("day" + str(day))
                    new_split[day] = choice if choice in BODY_PARTS else "Rest"
                db.set_split(c, current_user_id(), new_split)
                flash("Split saved.", "ok")

            elif action == "password":
                current = request.form.get("current") or ""
                new = request.form.get("new") or ""
                if not auth.verify_password(g.user["password_hash"], current):
                    flash("That is not your current password.", "error")
                elif len(new) < auth.MIN_PASSWORD:
                    flash("Use at least " + str(auth.MIN_PASSWORD) + " characters.", "error")
                else:
                    db.set_password(c, current_user_id(), auth.hash_password(new))
                    flash("Password changed.", "ok")

            elif action == "token":
                token, hashed = auth.new_token()
                db.add_token(c, current_user_id(), hashed,
                             (request.form.get("label") or "iPhone").strip()[:40])
                # Shown once, never again - only the hash is stored.
                flash("Token: " + token, "ok")

            elif action == "revoke":
                db.delete_token(c, current_user_id(), request.form.get("hash") or "")
                flash("Token revoked.", "ok")

            return redirect(url_for("account"))

        return render_template(
            "account.html",
            split=g.split,
            tokens=db.tokens_for(c, current_user_id()),
            people=db.all_users(c) if g.user["is_owner"] else [],
            invite_code=INVITE_CODE if g.user["is_owner"] else None,
        )
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Home - pick today's exercises
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    c = conn()
    try:
        uid = current_user_id()
        override = request.args.get("bp")
        force_new = request.args.get("new") == "1"

        existing = db.todays_workout(c, uid)
        if existing and not force_new and not override:
            return redirect(url_for("workout", workout_id=existing["id"]))

        scheduled = body_part_for(g.split)
        body_part = override if override in BODY_PARTS else scheduled
        is_rest_day = scheduled == "Rest" and not override

        exercises = [] if is_rest_day else db.exercises_for(c, uid, body_part)
        previous = db.previous_workout(c, uid, body_part)
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


@app.route("/workout", methods=["POST"])
def create_workout():
    ids = _parse_order(request.form.get("order", ""))
    body_part = request.form.get("body_part", "")

    if not ids:
        flash("Pick at least one exercise first.", "error")
        return redirect(url_for("home", bp=body_part or None))

    c = conn()
    try:
        known = db.known_exercise_ids(c, ids)
        ids = [i for i in ids if i in known]
        if not ids:
            flash("Those exercises no longer exist.", "error")
            return redirect(url_for("home"))
        if body_part not in BODY_PARTS:
            body_part = db.get_exercise(c, current_user_id(), ids[0])["body_part"]
        workout_id = db.create_workout(c, current_user_id(), body_part, ids)
    finally:
        c.close()
    return redirect(url_for("workout", workout_id=workout_id))


# ---------------------------------------------------------------------------
# A single session
# ---------------------------------------------------------------------------

@app.route("/workout/<int:workout_id>")
def workout(workout_id):
    c = conn()
    try:
        uid = current_user_id()
        w = db.get_workout(c, uid, workout_id)
        if w is None:
            abort(404)
        items = db.workout_items(c, workout_id)
        previous = db.previous_workout(c, uid, w["body_part"], before_id=workout_id)
        previous_items = db.workout_items(c, previous["id"]) if previous else []
        return render_template(
            "workout.html",
            w=w,
            items=items,
            done=sum(1 for i in items if i["done_at"]),
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
        if not db.item_belongs_to(c, current_user_id(), workout_id, item_id):
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
        w = db.get_workout(c, current_user_id(), workout_id)
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
        if db.get_workout(c, current_user_id(), workout_id) is None:
            abort(404)
        db.set_workout_note(c, workout_id, (request.form.get("note") or "").strip()[:500])
    finally:
        c.close()
    return redirect(url_for("workout", workout_id=workout_id))


@app.route("/workout/<int:workout_id>/edit")
def edit_workout(workout_id):
    c = conn()
    try:
        uid = current_user_id()
        w = db.get_workout(c, uid, workout_id)
        if w is None:
            abort(404)
        items = db.workout_items(c, workout_id)
        body_part = request.args.get("bp")
        if body_part not in BODY_PARTS:
            body_part = w["body_part"]

        # Include hidden exercises this session already uses, otherwise the
        # grid could not represent them and saving would quietly drop them.
        grid = list(db.exercises_for(c, uid, body_part))
        shown = {e["id"] for e in grid}
        for item in items:
            if item["exercise_id"] not in shown:
                extra = db.get_exercise(c, uid, item["exercise_id"])
                if extra is not None:
                    grid.append(extra)
                    shown.add(extra["id"])

        return render_template(
            "home.html",
            body_part=body_part,
            scheduled=body_part_for(g.split),
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
        w = db.get_workout(c, current_user_id(), workout_id)
        if w is None:
            abort(404)
        known = db.known_exercise_ids(c, ids) if ids else set()
        ids = [i for i in ids if i in known]
        if not ids:
            flash("A session needs at least one exercise.", "error")
            return redirect(url_for("edit_workout", workout_id=workout_id))
        db.replace_workout_items(c, workout_id, ids)
        body_part = request.form.get("body_part")
        if body_part in BODY_PARTS and body_part != w["body_part"]:
            db.set_workout_body_part(c, workout_id, body_part)
    finally:
        c.close()
    return redirect(url_for("workout", workout_id=workout_id))


@app.route("/workout/<int:workout_id>/delete", methods=["POST"])
def remove_workout(workout_id):
    c = conn()
    try:
        if db.get_workout(c, current_user_id(), workout_id) is None:
            abort(404)
        db.delete_workout(c, workout_id)
    finally:
        c.close()
    flash("Session deleted.", "ok")
    return redirect(url_for("history"))


# ---------------------------------------------------------------------------
# History and stats
# ---------------------------------------------------------------------------

@app.route("/history")
def history():
    c = conn()
    try:
        workouts = db.recent_workouts(c, current_user_id())
        summaries = {}
        for w in workouts:
            summaries[w["id"]] = [
                row["name"]
                for row in c.execute(
                    "SELECT e.name FROM workout_item wi JOIN exercise e "
                    "ON e.id = wi.exercise_id WHERE wi.workout_id = ? "
                    "ORDER BY wi.position",
                    (w["id"],),
                )
            ]
        return render_template("history.html", workouts=workouts, summaries=summaries)
    finally:
        c.close()


@app.route("/stats")
def stats():
    c = conn()
    try:
        uid = current_user_id()
        selected = request.args.get("bp")
        if selected not in BODY_PARTS:
            selected = None
        return render_template(
            "stats.html",
            head=stats_mod.headline(c, uid, g.split),
            parts=stats_mod.by_body_part(c, uid),
            board=stats_mod.exercise_leaderboard(c, uid, body_part=selected),
            top=stats_mod.top_exercise(c, uid),
            grid=stats_mod.activity_grid(c, uid, g.split, weeks=12),
            selected=selected,
        )
    finally:
        c.close()


# ---------------------------------------------------------------------------
# The shared exercise catalogue
# ---------------------------------------------------------------------------

@app.route("/exercises")
def exercises():
    c = conn()
    try:
        selected = request.args.get("bp")
        if selected not in BODY_PARTS:
            selected = body_part_for(g.split)
            if selected not in BODY_PARTS:
                selected = BODY_PARTS[0]
        rows = db.exercises_for(c, current_user_id(), selected, include_archived=True)
        return render_template("exercises.html", rows=rows, selected=selected)
    finally:
        c.close()


@app.route("/exercises/new", methods=["GET", "POST"])
def new_exercise():
    default_bp = request.args.get("bp")
    if default_bp not in BODY_PARTS:
        default_bp = body_part_for(g.split)
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
            if db.exercise_name_clash(c, body_part, name):
                delete_image(image)
                flash('"' + name + '" is already in ' + body_part + ".", "error")
                return redirect(url_for("exercises", bp=body_part))
            db.add_exercise(c, name, body_part, image=image, note=note,
                            equipment=equipment, created_by=current_user_id())
        finally:
            c.close()
        flash("Added " + name + ".", "ok")
        return redirect(url_for("exercises", bp=body_part))

    return render_template("exercise_form.html", row=None, default_bp=default_bp)


@app.route("/exercises/<int:exercise_id>/edit", methods=["GET", "POST"])
def edit_exercise(exercise_id):
    c = conn()
    try:
        row = db.get_exercise(c, current_user_id(), exercise_id)
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

            if db.exercise_name_clash(c, body_part, name, ignore_id=exercise_id):
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
        row = db.get_exercise(c, current_user_id(), exercise_id)
        if row is None:
            abort(404)
        outcome = db.delete_exercise(c, exercise_id)
        if outcome == "deleted":
            delete_image(row["image"])
            flash("Deleted " + row["name"] + ".", "ok")
        else:
            flash("Hidden " + row["name"] + " - it stays in past sessions.", "ok")
        return redirect(url_for("exercises", bp=row["body_part"]))
    finally:
        c.close()


@app.route("/exercises/<int:exercise_id>/restore", methods=["POST"])
def restore_exercise(exercise_id):
    c = conn()
    try:
        row = db.get_exercise(c, current_user_id(), exercise_id)
        if row is None:
            abort(404)
        db.update_exercise(c, exercise_id, archived=0)
        return redirect(url_for("exercises", bp=row["body_part"]))
    finally:
        c.close()


@app.route("/exercises/<int:exercise_id>/move", methods=["POST"])
def move_exercise(exercise_id):
    """Swap with a neighbour so the grid order matches how you train."""
    direction = request.form.get("dir")
    c = conn()
    try:
        uid = current_user_id()
        row = db.get_exercise(c, uid, exercise_id)
        if row is None:
            abort(404)
        siblings = list(db.exercises_for(c, uid, row["body_part"], include_archived=True))
        index = next((i for i, s in enumerate(siblings) if s["id"] == exercise_id), None)
        if index is not None:
            swap = index - 1 if direction == "up" else index + 1
            if 0 <= swap < len(siblings):
                siblings[index], siblings[swap] = siblings[swap], siblings[index]
                for position, item in enumerate(siblings):
                    c.execute("UPDATE exercise SET sort_order = ? WHERE id = ?",
                              (position, item["id"]))
                c.commit()
        return redirect(url_for("exercises", bp=row["body_part"]))
    finally:
        c.close()


@app.route("/exercises/bulk", methods=["GET", "POST"])
def bulk_add():
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
                if db.exercise_name_clash(c, body_part, name):
                    continue
                db.add_exercise(c, name, body_part, created_by=current_user_id())
                added += 1
        finally:
            c.close()
        flash("Added " + str(added) + " to " + body_part + ".", "ok")
        return redirect(url_for("exercises", bp=body_part))

    return render_template("bulk.html", default_bp=default_bp)


# ---------------------------------------------------------------------------
# Photos, settings, export
# ---------------------------------------------------------------------------

@app.route("/photo/<filename>")
def photo(filename):
    """Serve an uploaded thumbnail.

    Photos live OUTSIDE static/ on purpose, so the PythonAnywhere static file
    mapping cannot serve them straight off disk to anyone who guesses a name.
    Going through Flask keeps them behind a login, and lets us set a long
    cache header - filenames are random and never reused.
    """
    response = send_from_directory(UPLOAD_DIR, filename)
    response.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    return response


@app.route("/settings")
def settings():
    used_bytes, photo_count = disk_usage()
    db_bytes = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    c = conn()
    try:
        uid = current_user_id()
        totals = {
            "workouts": c.execute(
                "SELECT COUNT(*) FROM workout WHERE user_id = ?", (uid,)
            ).fetchone()[0],
            "exercises": c.execute("SELECT COUNT(*) FROM exercise").fetchone()[0],
            "people": db.count_users(c),
        }
    finally:
        c.close()
    return render_template(
        "settings.html",
        split=[(DAYS[i], g.split.get(i, "Rest")) for i in range(7)],
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
            "WHERE w.user_id = ? "
            "ORDER BY w.workout_date DESC, w.id DESC, wi.position",
            (current_user_id(),),
        ).fetchall()
    finally:
        c.close()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["date", "body_part", "started", "finished", "order", "exercise",
                     "completed_at", "session_note"])
    for r in rows:
        writer.writerow([r["workout_date"], r["body_part"], r["started_at"],
                         r["finished_at"] or "", r["position"] + 1, r["name"],
                         r["done_at"] or "", r["note"] or ""])
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=shretted-"
                 + today_local() + ".csv"},
    )


@app.route("/backup.sqlite3")
def backup():
    """The whole database, as a consistent snapshot. Owner only - it contains
    everybody's training log, not just yours."""
    if not g.user["is_owner"]:
        abort(403)
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
    response = jsonify({
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
            {"src": url_for("static", filename="img/icon-192.png"),
             "sizes": "192x192", "type": "image/png"},
            {"src": url_for("static", filename="img/icon-512.png"),
             "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    })
    response.mimetype = "application/manifest+json"
    return response


@app.route("/healthz")
def healthz():
    return {"ok": True, "today": today_local()}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

@app.errorhandler(403)
def forbidden(_e):
    return render_template("error.html", code=403,
                           message="That is not yours to look at."), 403


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


from api import api  # noqa: E402  (imported late so `app` exists first)

app.register_blueprint(api)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
