"""
The exercise list the app starts with, so the grid is not empty on day one.

This is only a starting point. Add, rename, reorder and delete freely in the
app - nothing here is re-applied once the database exists.

Each entry is (name, equipment, note).
  - name      kept short on purpose: it has to stay readable under a small
              square tile on a phone
  - equipment picks the icon a tile shows before you add your own photo
              (barbell, dumbbell, ezbar, machine, cable, bodyweight, other)
  - note      one line shown under the exercise during a session

Order runs big compound lifts first, isolation last, which is roughly how a
session gets programmed.
"""

CATALOGUE = {
    "Back": [
        ("Deadlift",            "barbell",    "Heavy, low reps, first while you are fresh"),
        ("Pull-Up",             "bodyweight", "Add weight once you clear 10 clean reps"),
        ("Barbell Row",         "barbell",    "Flat back, pull to the belly button"),
        ("T-Bar Row",           "machine",    "Chest supported if the gym has the pad"),
        ("Lat Pulldown",        "cable",      "Wide grip, drive the elbows down not back"),
        ("Seated Cable Row",    "cable",      "Squeeze the shoulder blades, no torso swing"),
        ("Chest Supported Row", "machine",    "Takes the lower back out of it"),
        ("Dumbbell Row",        "dumbbell",   "One arm at a time, full stretch at the bottom"),
        ("Close Grip Pulldown", "cable",      "Hits the lats lower down"),
        ("Machine Row",         "machine",    "Good finisher when your grip has gone"),
        ("Straight-Arm Pull",   "cable",      "Arms locked, pure lat isolation"),
        ("Face Pull",           "cable",      "Rear delts and upper back, high reps"),
        ("Shrugs",              "dumbbell",   "Traps, hold the top for a second"),
        ("Back Extension",      "bodyweight", "Lower back and glutes, controlled"),
    ],
    "Shoulders": [
        ("Overhead Press",      "barbell",    "Brace the core, press slightly back"),
        ("Dumbbell Press",      "dumbbell",   "Seated, elbows just in front of the body"),
        ("Arnold Press",        "dumbbell",   "Rotate as you press for the front delt"),
        ("Machine Press",       "machine",    "Push heavy without needing a spotter"),
        ("Lateral Raise",       "dumbbell",   "Light weight, lead with the elbows"),
        ("Cable Lateral Raise", "cable",      "Constant tension the whole way up"),
        ("Rear Delt Fly",       "dumbbell",   "Bent over, thumbs down"),
        ("Reverse Pec Deck",    "machine",    "Machine version of the rear delt fly"),
        ("Front Raise",         "dumbbell",   "Plate or dumbbell, stop at eye level"),
        ("Upright Row",         "ezbar",      "Wide grip is kinder on the shoulder"),
        ("Face Pull",           "cable",      "Rear delts and rotator cuff health"),
        ("Landmine Press",      "barbell",    "Shoulder-friendly pressing angle"),
        ("Shrugs",              "barbell",    "Traps finisher"),
        ("Cable Y-Raise",       "cable",      "Upper traps and rear delts together"),
    ],
    "Biceps": [
        ("Barbell Curl",        "barbell",    "The heaviest curl you have, strict form"),
        ("EZ Bar Curl",         "ezbar",      "Easier on the wrists than a straight bar"),
        ("Dumbbell Curl",       "dumbbell",   "Turn the palm up hard at the top"),
        ("Incline DB Curl",     "dumbbell",   "Long head stretch, big range"),
        ("Hammer Curl",         "dumbbell",   "Neutral grip, hits the brachialis"),
        ("Preacher Curl",       "ezbar",      "No swinging, full stretch at the bottom"),
        ("Machine Preacher",    "machine",    "Steady resistance, good for drop sets"),
        ("Cable Curl",          "cable",      "Tension never drops off"),
        ("Rope Hammer Curl",    "cable",      "Forearms and brachialis"),
        ("Concentration Curl",  "dumbbell",   "Slow, one arm, squeeze at the top"),
        ("Spider Curl",         "ezbar",      "Chest on an incline bench, arms hanging"),
        ("High Cable Curl",     "cable",      "Both arms, cables at head height"),
        ("Reverse Curl",        "ezbar",      "Overhand grip, builds the forearms"),
        ("Chin-Up",             "bodyweight", "Underhand, biceps plus back"),
    ],
    "Triceps": [
        ("Close Grip Bench",    "barbell",    "Elbows tucked, main pressing movement"),
        ("Dips",                "bodyweight", "Upright torso keeps it on the triceps"),
        ("Skull Crusher",       "ezbar",      "To the forehead, elbows still"),
        ("Overhead Rope Ext",   "cable",      "Long head stretch, do not flare out"),
        ("Rope Pushdown",       "cable",      "Spread the rope apart at the bottom"),
        ("Bar Pushdown",        "cable",      "Straight or V-bar, elbows pinned"),
        ("Single-Arm Pushdown", "cable",      "Evens out side-to-side differences"),
        ("DB Overhead Ext",     "dumbbell",   "One heavy dumbbell, both hands"),
        ("Machine Tricep Press", "machine",   "Easy to overload safely"),
        ("Bench Dips",          "bodyweight", "Feet further out to make it harder"),
        ("Kickback",            "dumbbell",   "Light, squeeze and hold at lockout"),
        ("JM Press",            "barbell",    "Half press half skull crusher, heavy"),
        ("Diamond Push-Up",     "bodyweight", "No equipment needed, high reps"),
        ("Reverse Pushdown",    "cable",      "Underhand grip, hits the medial head"),
    ],
    "Legs": [
        ("Back Squat",          "barbell",    "The main lift - depth over weight"),
        ("Front Squat",         "barbell",    "More quad, more upright"),
        ("Leg Press",           "machine",    "Load up safely, control the negative"),
        ("Hack Squat",          "machine",    "Quad focused, deep range"),
        ("Romanian Deadlift",   "barbell",    "Hamstrings - push the hips back"),
        ("Bulgarian Split Sq",  "dumbbell",   "Brutal single leg work, go light first"),
        ("Walking Lunge",       "dumbbell",   "Long strides for the glutes"),
        ("Goblet Squat",        "dumbbell",   "Great warm-up, one dumbbell"),
        ("Leg Extension",       "machine",    "Quads, pause at the top"),
        ("Lying Leg Curl",      "machine",    "Hamstrings, full range"),
        ("Seated Leg Curl",     "machine",    "A different hamstring angle to lying"),
        ("Hip Thrust",          "barbell",    "Glutes, squeeze hard at lockout"),
        ("Standing Calf Raise", "machine",    "Slow, pause in the bottom stretch"),
        ("Seated Calf Raise",   "machine",    "Hits the soleus"),
    ],
    "Chest": [
        ("Barbell Bench",       "barbell",    "The main lift, controlled to the chest"),
        ("Incline Barbell",     "barbell",    "Upper chest, bench around 30 degrees"),
        ("Dumbbell Bench",      "dumbbell",   "Bigger range than the barbell"),
        ("Incline DB Press",    "dumbbell",   "Best upper chest mass builder"),
        ("Machine Chest Press", "machine",    "Safe to push near failure alone"),
        ("Chest Dips",          "bodyweight", "Lean forward to take it off the triceps"),
        ("Pec Deck",            "machine",    "Pure isolation, squeeze in the middle"),
        ("Cable Fly",           "cable",      "Pulleys high for the lower chest"),
        ("Low to High Fly",     "cable",      "Upper chest, cables from the bottom"),
        ("Cable Crossover",     "cable",      "Cross the hands over for the squeeze"),
        ("Incline DB Fly",      "dumbbell",   "Big stretch, keep a soft elbow"),
        ("Smith Machine Press", "machine",    "Fixed path, good for drop sets"),
        ("Decline Bench",       "barbell",    "Lower chest, easier on the shoulder"),
        ("Push-Up",             "bodyweight", "Finisher, go to failure"),
    ],
}
