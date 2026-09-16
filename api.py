"""
JSON API, versioned at /api/v1.

This is what a native iOS app talks to. The web app does not use it - both sit
on the same database, so you can run them side by side and the data matches.

Auth is a bearer token:

    POST /api/v1/login  {"email": "...", "password": "..."}
      -> {"token": "..."}

    Then send it on every other call:
      Authorization: Bearer <token>

Tokens do not expire. Revoke one from More -> Account on the web app.
"""
from functools import wraps

from flask import Blueprint, g, jsonify, request

import auth
import db
import stats as stats_mod
from config import BODY_PARTS, EQUIPMENT, body_part_for, today_local

api = Blueprint("api", __name__, url_prefix="/api/v1")

MAX_ITEMS = 30


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------

def fail(message, status=400):
    return jsonify({"error": message}), status


def need_auth(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        token = auth.bearer_from(request.headers)
        if not token:
            return fail("Missing Authorization: Bearer <token>", 401)
        c = db.get_conn()
        try:
            user = db.user_for_token_hash(c, auth.token_hash(token))
        finally:
            c.close()
        if user is None:
            return fail("That token is not valid.", 401)
        g.user = user
        g.split = db.split_of(user)
        return view(*args, **kwargs)

    return wrapper


def body():
    return request.get_json(silent=True) or {}


def user_json(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "is_owner": bool(row["is_owner"]),
        "split": {str(k): v for k, v in db.split_of(row).items()},
    }


def exercise_json(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "body_part": row["body_part"],
        "equipment": row["equipment"],
        "note": row["note"],
        "photo_url": ("/photo/" + row["image"]) if row["image"] else None,
        "archived": bool(row["archived"]),
        "times_done": row["times_done"] if "times_done" in row.keys() else None,
    }


def workout_json(row, items=None):
    out = {
        "id": row["id"],
        "date": row["workout_date"],
        "body_part": row["body_part"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "note": row["note"],
    }
    if items is not None:
        out["items"] = [
            {
                "id": i["id"],
                "exercise_id": i["exercise_id"],
                "name": i["name"],
                "equipment": i["equipment"],
                "photo_url": ("/photo/" + i["image"]) if i["image"] else None,
                "position": i["position"],
                "done_at": i["done_at"],
            }
            for i in items
        ]
    return out


def parse_ids(raw):
    """Accepts [1,2,3] or "1,2,3". De-duplicated, order preserved, capped."""
    if isinstance(raw, str):
        raw = [chunk.strip() for chunk in raw.split(",")]
    if not isinstance(raw, list):
        return []
    seen, out = set(), []
    for value in raw[: MAX_ITEMS * 4]:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number <= 0 or number > 2 ** 53 or number in seen:
            continue
        seen.add(number)
        out.append(number)
        if len(out) >= MAX_ITEMS:
            break
    return out


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@api.post("/login")
def login():
    data = body()
    email = auth.clean_email(data.get("email"))
    password = data.get("password") or ""

    c = db.get_conn()
    try:
        user = db.get_user_by_email(c, email)
        if user is None or not auth.verify_password(user["password_hash"], password):
            # Same message either way - do not confirm which emails exist.
            return fail("Wrong email or password.", 401)
        token, hashed = auth.new_token()
        db.add_token(c, user["id"], hashed, (data.get("label") or "iOS")[:40])
        db.touch_user(c, user["id"])
        return jsonify({"token": token, "user": user_json(user)})
    finally:
        c.close()


@api.post("/logout")
@need_auth
def logout():
    token = auth.bearer_from(request.headers)
    c = db.get_conn()
    try:
        db.delete_token(c, g.user["id"], auth.token_hash(token))
    finally:
        c.close()
    return jsonify({"ok": True})


@api.get("/me")
@need_auth
def me():
    return jsonify(user_json(g.user))


# ---------------------------------------------------------------------------
# Today
# ---------------------------------------------------------------------------

@api.get("/today")
@need_auth
def today():
    """One call for the whole home screen: what is scheduled, the exercises to
    choose from, and whether a session already exists."""
    c = db.get_conn()
    try:
        uid = g.user["id"]
        requested = request.args.get("body_part")
        scheduled = body_part_for(g.split)
        body_part = requested if requested in BODY_PARTS else scheduled
        existing = db.todays_workout(c, uid)

        exercises = (
            [] if body_part not in BODY_PARTS
            else [exercise_json(e) for e in db.exercises_for(c, uid, body_part)]
        )
        previous = db.previous_workout(c, uid, body_part)

        return jsonify({
            "date": today_local(),
            "scheduled_body_part": scheduled,
            "body_part": body_part,
            "is_rest_day": scheduled == "Rest",
            "exercises": exercises,
            "existing_workout": workout_json(existing) if existing else None,
            "previous_workout": (
                workout_json(previous, db.workout_items(c, previous["id"]))
                if previous else None
            ),
        })
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Exercises (shared catalogue)
# ---------------------------------------------------------------------------

@api.get("/exercises")
@need_auth
def list_exercises():
    c = db.get_conn()
    try:
        uid = g.user["id"]
        part = request.args.get("body_part")
        include_archived = request.args.get("archived") == "1"
        parts = [part] if part in BODY_PARTS else BODY_PARTS
        out = []
        for p in parts:
            out.extend(
                exercise_json(e)
                for e in db.exercises_for(c, uid, p, include_archived=include_archived)
            )
        return jsonify({"exercises": out})
    finally:
        c.close()


@api.post("/exercises")
@need_auth
def create_exercise():
    data = body()
    name = (data.get("name") or "").strip()[:60]
    part = data.get("body_part")
    equipment = data.get("equipment")
    note = (data.get("note") or "").strip()[:200] or None

    if not name:
        return fail("name is required")
    if part not in BODY_PARTS:
        return fail("body_part must be one of " + ", ".join(BODY_PARTS))
    if equipment not in EQUIPMENT:
        equipment = "other"

    c = db.get_conn()
    try:
        if db.exercise_name_clash(c, part, name):
            return fail("That exercise already exists in " + part, 409)
        new_id = db.add_exercise(c, name, part, note=note, equipment=equipment,
                                 created_by=g.user["id"])
        return jsonify(exercise_json(db.get_exercise(c, g.user["id"], new_id))), 201
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Workouts (private)
# ---------------------------------------------------------------------------

@api.get("/workouts")
@need_auth
def list_workouts():
    try:
        limit = min(int(request.args.get("limit", 60)), 500)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        return fail("limit and offset must be numbers")

    c = db.get_conn()
    try:
        rows = db.recent_workouts(c, g.user["id"], limit=limit, offset=offset)
        return jsonify({
            "workouts": [
                dict(workout_json(w),
                     exercise_count=w["exercise_count"],
                     done_count=w["done_count"] or 0)
                for w in rows
            ]
        })
    finally:
        c.close()


@api.get("/workouts/<int:workout_id>")
@need_auth
def get_workout(workout_id):
    c = db.get_conn()
    try:
        w = db.get_workout(c, g.user["id"], workout_id)
        if w is None:
            return fail("No such workout.", 404)
        return jsonify(workout_json(w, db.workout_items(c, workout_id)))
    finally:
        c.close()


@api.post("/workouts")
@need_auth
def create_workout():
    data = body()
    ids = parse_ids(data.get("exercise_ids"))
    part = data.get("body_part")

    if not ids:
        return fail("exercise_ids must have at least one id")

    c = db.get_conn()
    try:
        known = db.known_exercise_ids(c, ids)
        ids = [i for i in ids if i in known]
        if not ids:
            return fail("None of those exercise ids exist.")
        if part not in BODY_PARTS:
            part = db.get_exercise(c, g.user["id"], ids[0])["body_part"]
        workout_id = db.create_workout(c, g.user["id"], part, ids)
        w = db.get_workout(c, g.user["id"], workout_id)
        return jsonify(workout_json(w, db.workout_items(c, workout_id))), 201
    finally:
        c.close()


@api.put("/workouts/<int:workout_id>/items")
@need_auth
def replace_items(workout_id):
    ids = parse_ids(body().get("exercise_ids"))
    c = db.get_conn()
    try:
        if db.get_workout(c, g.user["id"], workout_id) is None:
            return fail("No such workout.", 404)
        known = db.known_exercise_ids(c, ids)
        ids = [i for i in ids if i in known]
        if not ids:
            return fail("A session needs at least one exercise.")
        db.replace_workout_items(c, workout_id, ids)
        w = db.get_workout(c, g.user["id"], workout_id)
        return jsonify(workout_json(w, db.workout_items(c, workout_id)))
    finally:
        c.close()


@api.post("/workouts/<int:workout_id>/items/<int:item_id>/toggle")
@need_auth
def toggle(workout_id, item_id):
    c = db.get_conn()
    try:
        if not db.item_belongs_to(c, g.user["id"], workout_id, item_id):
            return fail("No such item.", 404)
        done_at = db.toggle_item_done(c, item_id)
        return jsonify({"id": item_id, "done_at": done_at})
    finally:
        c.close()


@api.post("/workouts/<int:workout_id>/finish")
@need_auth
def finish(workout_id):
    c = db.get_conn()
    try:
        w = db.get_workout(c, g.user["id"], workout_id)
        if w is None:
            return fail("No such workout.", 404)
        if w["finished_at"]:
            db.reopen_workout(c, workout_id)
        else:
            db.finish_workout(c, workout_id)
        return jsonify(workout_json(db.get_workout(c, g.user["id"], workout_id)))
    finally:
        c.close()


@api.patch("/workouts/<int:workout_id>")
@need_auth
def update_workout(workout_id):
    data = body()
    c = db.get_conn()
    try:
        if db.get_workout(c, g.user["id"], workout_id) is None:
            return fail("No such workout.", 404)
        if "note" in data:
            db.set_workout_note(c, workout_id, (data.get("note") or "").strip()[:500])
        if data.get("body_part") in BODY_PARTS:
            db.set_workout_body_part(c, workout_id, data["body_part"])
        return jsonify(workout_json(db.get_workout(c, g.user["id"], workout_id)))
    finally:
        c.close()


@api.delete("/workouts/<int:workout_id>")
@need_auth
def delete_workout(workout_id):
    c = db.get_conn()
    try:
        if db.get_workout(c, g.user["id"], workout_id) is None:
            return fail("No such workout.", 404)
        db.delete_workout(c, workout_id)
        return jsonify({"ok": True})
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@api.get("/stats")
@need_auth
def stats():
    c = db.get_conn()
    try:
        uid = g.user["id"]
        return jsonify({
            "headline": stats_mod.headline(c, uid, g.split),
            "by_body_part": stats_mod.by_body_part(c, uid),
            "leaderboard": stats_mod.exercise_leaderboard(c, uid),
            "activity": stats_mod.activity_grid(c, uid, g.split, weeks=12),
        })
    finally:
        c.close()
