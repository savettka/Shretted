# Putting Gym Log on PythonAnywhere (free account)

Start to finish this takes about 20 minutes. You do not need to install
anything on your laptop and you do not need to know Python.

Everywhere below, replace `YOURUSERNAME` with your actual PythonAnywhere
username.

---

## Before you start: what a free account actually gives you

These are the limits the app was designed around, so nothing here should
surprise you later.

| | Free "Beginner" account |
|---|---|
| Your web address | `https://YOURUSERNAME.pythonanywhere.com` (HTTPS already set up) |
| Disk space | **512 MB total** — code, database and photos all count |
| Web app expiry | **1 month.** You must click a button to keep it alive (see step 10) |
| Database | **No MySQL for accounts created from Jan 2026.** This app uses SQLite instead, which is just a file — nothing to set up |
| Web workers | 1, so the site handles one request at a time. Fine for one person |
| Support | Forums only |

The 512 MB is the one to watch, and it is the reason the app shrinks every
photo you upload to a 400x400 JPEG of roughly 25 KB. At that size you could
store several thousand photos before space became a problem.

---

## Step 1 — Create the account

Go to <https://www.pythonanywhere.com/registration/register/beginner/> and
sign up for the free Beginner plan.

**Pick your username carefully — it becomes your public web address and it
cannot be changed later.** Something like `sarvpreetgym` gives you
`https://sarvpreetgym.pythonanywhere.com`.

Use an email address you actually read. That is where the monthly "your web
app is about to expire" reminder goes.

---

## Step 2 — Upload the code

You have the `gymlog` folder. Zip it up on your laptop first: right-click the
`gymlog` folder → **Send to → Compressed (zipped) folder**. You will get
`gymlog.zip`, about 60 KB.

On PythonAnywhere:

1. Go to the **Files** tab.
2. You should be in `/home/YOURUSERNAME/`. Under "Upload a file", choose
   `gymlog.zip`.
3. Now open a console: **Consoles** tab → **$ Bash**.
4. Type these two lines, pressing Enter after each:

```bash
cd ~
unzip gymlog.zip
```

You should now have `/home/YOURUSERNAME/gymlog/` containing `app.py` and the
rest. Check with:

```bash
ls ~/gymlog
```

> **Alternative if you use GitHub:** push the folder to a repo and run
> `git clone https://github.com/YOU/YOURREPO.git ~/gymlog` instead. GitHub is
> reachable from free accounts over HTTPS. SSH (`git@github.com:...`) is not.

---

## Step 3 — Set it up (still in the Bash console)

```bash
cd ~/gymlog
mkdir -p uploads
chmod u+rwx uploads
python3.13 make_icons.py
python3.13 -c "import db; db.init_db(); print('database ready')"
```

You should see three "wrote ..." lines and then `database ready`.

**Do not create a virtualenv.** Flask and Pillow are already installed for
every Python version on PythonAnywhere, and an empty virtualenv would eat
over half of your 512 MB. This app needs nothing else.

If `python3.13` is not found, your account may be on an older system image —
try `python3.10` instead, and use the same version everywhere below.

---

## Step 4 — Create the web app

1. Go to the **Web** tab.
2. Click **Add a new web app** → **Next**.
3. Choose **Manual configuration** — *not* the Flask option. The Flask
   quickstart writes its own files over the top of yours.
4. Choose **Python 3.13** (or whichever version worked in step 3).
5. Click Next. It will churn for a moment and then show you the config page.

Leave the **Virtualenv** section completely empty.

---

## Step 5 — Point it at your code

Still on the Web tab, in the **Code** section:

- **Source code:** `/home/YOURUSERNAME/gymlog`
- **Working directory:** `/home/YOURUSERNAME/gymlog`

---

## Step 6 — The WSGI file

In that same Code section there is a link like

```
/var/www/YOURUSERNAME_pythonanywhere_com_wsgi.py
```

Click it. An editor opens with a lot of commented-out example code.

**Select all of it and delete it.** Then open `wsgi_pythonanywhere.py` from
this project (Files tab → `gymlog` → click the file), copy its contents, and
paste them in.

Change three things in what you pasted:

```python
project_home = "/home/YOURUSERNAME/gymlog"          # your username
os.environ.setdefault("GYM_PIN", "1234")            # your own PIN
os.environ.setdefault("GYM_SECRET_KEY", "change-me")  # see below
```

**The PIN must be digits only, 4 to 12 of them.** The unlock screen is a
numeric keypad, so a PIN with letters in it could never be typed. It is what
stops a stranger who guesses your URL from reading your training log — don't
leave it as `1234`.

**Do not invent the secret key by hand.** A stray `"` or `\` would break the
file and take the whole site down. Generate a safe one in a Bash console:

```bash
python3.13 -c "import secrets; print(secrets.token_hex(32))"
```

Copy the 64-character output and paste it between the quotes.

> Note: this value in the WSGI file **overrides** whatever is in `config.py`.
> Changing the PIN in `config.py` later will appear to do nothing — change it
> here instead, then Reload.

Click **Save**.

---

## Step 7 — Serve the CSS and images efficiently

On the Web tab, scroll to **Static files** and add one row:

| URL | Directory |
|---|---|
| `/static/` | `/home/YOURUSERNAME/gymlog/static` |

This hands the stylesheet and icons to PythonAnywhere's own web server so your
single worker is free to render pages.

**Do not add a mapping for `uploads`.** A static mapping bypasses Flask
entirely, which would make every exercise photo public to anyone who guesses
the filename. The app serves photos through its own `/photo/` route, behind
your PIN. That is deliberate.

---

## Step 7b — Force HTTPS

Still on the Web tab, in the **Security** section, switch **Force HTTPS** on.

The app refuses to send your login cookie over an unencrypted connection, so
without this a visit to the `http://` version of your address would leave you
stuck at the PIN screen in a loop.

---

## Step 8 — Reload and open it

Click the big green **Reload** button at the top of the Web tab. Wait for the
spinner to finish, then visit:

```
https://YOURUSERNAME.pythonanywhere.com
```

Enter your PIN. You should land on today's body part with a grid of exercises.

**If you get an error page:** on the Web tab click the **Error log** link and
read the *bottom* of the file. That is where the actual problem is. See
Troubleshooting below.

---

## Step 9 — Put it on your iPhone home screen

1. Open the site in **Safari** on your iPhone (it must be Safari, not Chrome).
2. Tap the **Share** button (square with an arrow).
3. Scroll down and tap **Add to Home Screen**.
4. Tap **Add**.

You now get a Gym Log icon that opens full screen with no address bar. Log in
with your PIN once and it stays logged in for a year.

---

## Step 10 — The one bit of ongoing maintenance

**Free web apps expire after one month.** PythonAnywhere emails you a link
before it happens; clicking it resets the clock. You can also just log in and
click the button on the Web tab.

Nothing is deleted if you miss it — the site simply stops serving until you
log in and re-enable it. But set a **monthly repeating reminder** in your
phone calendar anyway. Free accounts cannot automate this.

---

## Optional: HEIC photos

iPhones shoot in HEIC. When you pick a photo from your camera roll, Safari
normally converts it to JPEG on the way up, so this usually does not matter.
But if you ever pick a photo through **Browse / Files** instead of the photo
library, the raw `.heic` file reaches the server and the app will tell you it
cannot read it.

Two fixes — either is fine:

**A. Teach the server to read HEIC** (uses ~20 MB of your quota):

```bash
pip3.13 install --user --no-cache-dir pillow-heif
rm -rf ~/.cache/pip
```

Then hit Reload on the Web tab.

**B. Change your phone instead** (free): iPhone **Settings → Camera →
Formats → Most Compatible**. New photos are taken as JPEG.

---

## Making changes later

After editing any `.py` file you **must** click **Reload** on the Web tab.
Template and CSS changes usually appear without it, but reloading never hurts.

To change your training split, edit `config.py` and change the `SPLIT`
dictionary (Monday is `0`), then Reload.

---

## Backups

Your training log — every session, every exercise, every timestamp — lives in
one file: `gymlog.sqlite3`.

The easy way: open the app, go to **More → Backup file**, and it downloads.
Do that once a month when you renew the web app. Keep it somewhere off the
server. You can also export a spreadsheet-friendly copy with
**More → Export CSV**.

**The photos are not in that file.** The database stores only their filenames;
the images themselves are separate files in `~/gymlog/uploads/`. To back those
up as well, run this in a Bash console, then download the zip from the Files
tab:

```bash
cd ~/gymlog && zip -r ~/gymlog-photos.zip uploads
```

---

## Troubleshooting

**"Something went wrong :-(" / error page**
Web tab → Error log → read the bottom. Almost always one of: a typo in
`project_home`, the wrong Python version, or a virtualenv left configured.

**`ModuleNotFoundError: No module named 'app'`**
`project_home` in the WSGI file does not match where the code actually is.
Run `ls ~/gymlog/app.py` in a Bash console to confirm the path.

**`ModuleNotFoundError: No module named 'flask'`**
You have something in the Virtualenv box on the Web tab. Clear it and Reload.

**The page loads but has no styling, or the PIN pad does nothing**
Both are the same cause: the static files mapping is wrong, so the stylesheet
and the script are not being served. Both the URL and the directory are
case-sensitive, and you must Reload after changing them. (You can still get in
meanwhile — the PIN box works as a plain text field without the script.)

**The PIN screen keeps coming back even though the PIN is right**
Force HTTPS is off (Step 7b). The login cookie is refused over plain http.

**Photos will not upload**
Check the uploads folder exists and is writable:
```bash
ls -ld ~/gymlog/uploads
chmod u+rwx ~/gymlog/uploads
```

**The wrong day's body part is showing**
Only possible if `GYM_TZ` is wrong. It should be `Europe/London`.

**"Disk quota exceeded"**
See what is using it:
```bash
du -hs /tmp ~/.[!.]* ~/* | sort -h
```
The usual culprits are `~/.cache` (safe to delete) and a virtualenv you
created by accident.
