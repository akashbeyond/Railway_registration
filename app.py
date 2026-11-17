# """Railway Reservation System - a simple and secure Flask web application.

# Features : register / login, search trains, book tickets, view and cancel bookings.
# Security : hashed passwords, parameterised SQL, CSRF protection, secure session
#            cookies, security headers, rate limiting, input validation,
#            per-user access checks and race-free seat booking.
# Run      : python app.py   ->   http://127.0.0.1:5000
# """
# import os
# import re
# import secrets
# import sqlite3
# from datetime import date, datetime, timedelta
# from functools import wraps
# from pathlib import Path
# from zoneinfo import ZoneInfo

# from flask import (Flask, abort, flash, g, redirect, render_template, request,
#                    session, url_for)
# from flask_limiter import Limiter
# from flask_limiter.util import get_remote_address
# from flask_wtf.csrf import CSRFProtect
# from werkzeug.security import check_password_hash, generate_password_hash
# from trains_data import build_trains

# # --------------------------------------------------------------------------
# # Configuration
# # --------------------------------------------------------------------------
# BASE_DIR = Path(__file__).resolve().parent
# INSTANCE_DIR = BASE_DIR / "instance"
# DB_PATH = Path(os.environ.get("DATABASE_PATH", INSTANCE_DIR / "railway.db"))
# MAX_PASSENGERS = 4          # passengers per booking
# TIMEZONE = ZoneInfo("Asia/Kolkata")
# BOOKING_END = date.fromisoformat(os.environ.get("BOOKING_END_DATE", "2027-03-31"))  # last bookable date
# PER_PAGE = 10               # rows per page in the "all trains" list      # how far ahead a ticket can be booked


# def load_secret_key():
#     """Use SECRET_KEY from the environment, else create one once and reuse it."""
#     key = os.environ.get("SECRET_KEY")
#     if key:
#         return key
#     INSTANCE_DIR.mkdir(exist_ok=True)
#     key_file = INSTANCE_DIR / "secret.key"
#     if not key_file.exists():
#         key_file.write_text(secrets.token_hex(32))
#         try:
#             os.chmod(key_file, 0o600)
#         except OSError:
#             pass
#     return key_file.read_text().strip()


# app = Flask(__name__)
# app.config.update(
#     SECRET_KEY=load_secret_key(),
#     SESSION_COOKIE_HTTPONLY=True,                 # JavaScript cannot read the cookie
#     SESSION_COOKIE_SAMESITE="Lax",                # blocks cross-site form posts
#     SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",  # set 1 on HTTPS
#     PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
#     MAX_CONTENT_LENGTH=16 * 1024,                 # reject large request bodies
# )
# csrf = CSRFProtect(app)                           # CSRF token on every POST
# limiter = Limiter(get_remote_address, app=app, default_limits=["200 per hour"],
#                   storage_uri="memory://")        # rate limiting (brute force / DoS)

# # --------------------------------------------------------------------------
# # Database (SQLite, parameterised queries only)
# # --------------------------------------------------------------------------
# SCHEMA = """
# CREATE TABLE IF NOT EXISTS users (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     name TEXT NOT NULL,
#     email TEXT NOT NULL UNIQUE,
#     password_hash TEXT NOT NULL,
#     created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
# );
# CREATE TABLE IF NOT EXISTS trains (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     number TEXT NOT NULL UNIQUE,
#     name TEXT NOT NULL,
#     source TEXT NOT NULL,
#     destination TEXT NOT NULL,
#     departs TEXT NOT NULL,
#     arrives TEXT NOT NULL,
#     fare INTEGER NOT NULL CHECK (fare > 0),
#     total_seats INTEGER NOT NULL CHECK (total_seats > 0)
# );
# CREATE TABLE IF NOT EXISTS bookings (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     pnr TEXT NOT NULL UNIQUE,
#     user_id INTEGER NOT NULL REFERENCES users(id),
#     train_id INTEGER NOT NULL REFERENCES trains(id),
#     travel_date TEXT NOT NULL,
#     seats INTEGER NOT NULL CHECK (seats BETWEEN 1 AND 4),
#     total_fare INTEGER NOT NULL,
#     status TEXT NOT NULL DEFAULT 'CONFIRMED' CHECK (status IN ('CONFIRMED', 'CANCELLED')),
#     booked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
# );
# CREATE TABLE IF NOT EXISTS passengers (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     booking_id INTEGER NOT NULL REFERENCES bookings(id),
#     name TEXT NOT NULL,
#     age INTEGER NOT NULL CHECK (age BETWEEN 1 AND 120)
# );
# CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id);
# CREATE INDEX IF NOT EXISTS idx_bookings_train_date ON bookings(train_id, travel_date);
# """

# def init_db():
#     DB_PATH.parent.mkdir(parents=True, exist_ok=True)
#     con = sqlite3.connect(DB_PATH)
#     con.executescript(SCHEMA)
#     con.executemany(   # INSERT OR IGNORE: safe to run on every start, never duplicates trains
#         "INSERT OR IGNORE INTO trains (number, name, source, destination, departs, arrives, fare, total_seats) "
#         "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", build_trains())
#     con.commit()
#     con.close()

# # Available seats = total seats - confirmed seats for that train and date.
# # Always used with "?" placeholders, never with string formatting.
# AVAILABLE_SQL = """
# SELECT t.*, t.total_seats - COALESCE((
#     SELECT SUM(b.seats) FROM bookings b
#     WHERE b.train_id = t.id AND b.travel_date = ? AND b.status = 'CONFIRMED'), 0) AS available
# FROM trains t
# """


# def init_db():
#     DB_PATH.parent.mkdir(parents=True, exist_ok=True)
#     con = sqlite3.connect(DB_PATH)
#     con.executescript(SCHEMA)
#     if con.execute("SELECT COUNT(*) FROM trains").fetchone()[0] == 0:
#         con.executemany(
#             "INSERT INTO trains (number, name, source, destination, departs, arrives, fare, total_seats) "
#             "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", SAMPLE_TRAINS)
#     con.commit()
#     con.close()


# def get_db():
#     if "db" not in g:
#         # isolation_level=None -> autocommit; booking uses an explicit transaction
#         g.db = sqlite3.connect(DB_PATH, isolation_level=None)
#         g.db.row_factory = sqlite3.Row
#         g.db.execute("PRAGMA foreign_keys = ON")
#     return g.db


# @app.teardown_appcontext
# def close_db(_exc):
#     db = g.pop("db", None)
#     if db is not None:
#         db.close()


# # --------------------------------------------------------------------------
# # Helpers: validation and authentication
# # --------------------------------------------------------------------------
# EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")
# NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,59}$")
# PNR_RE = re.compile(r"^\d{10}$")
# DUMMY_HASH = generate_password_hash("dummy-password")  # keeps login timing similar


# def now_ist():
#     """Current date and time in India (taken from the computer running the app)."""
#     return datetime.now(TIMEZONE)


# def today_ist():
#     return now_ist().date()


# def booking_window(now):
#     """Bookable dates: from today until BOOKING_END."""
#     return now.date(), BOOKING_END


# def has_departed(travel_date, departs, now=None):
#     """True if the train on that date has already left (travel_date 'YYYY-MM-DD', departs 'HH:MM')."""
#     now = now or now_ist()
#     departure = datetime.fromisoformat(f"{travel_date}T{departs}").replace(tzinfo=TIMEZONE)
#     return departure <= now


# def parse_travel_date(value, now=None):
#     """Return an ISO date string if valid and inside the booking window, else None."""
#     try:
#         d = date.fromisoformat(value)
#     except (TypeError, ValueError):
#         return None
#     start, end = booking_window(now or now_ist())
#     return d.isoformat() if start <= d <= end else None


# def upcoming_departures(db, source, destination, now):
#     """Every bookable departure on a route, ordered by date then time (nearest first)."""
#     start, end = booking_window(now)
#     trains = db.execute(
#         "SELECT * FROM trains WHERE source = ? AND destination = ? ORDER BY departs",
#         (source, destination)).fetchall()
#     booked = {(r["train_id"], r["travel_date"]): r["seats"] for r in db.execute(
#         "SELECT b.train_id, b.travel_date, SUM(b.seats) AS seats FROM bookings b "
#         "JOIN trains t ON t.id = b.train_id "
#         "WHERE b.status = 'CONFIRMED' AND t.source = ? AND t.destination = ? "
#         "AND b.travel_date BETWEEN ? AND ? GROUP BY b.train_id, b.travel_date",
#         (source, destination, start.isoformat(), end.isoformat()))}
#     rows, day = [], start
#     while day <= end:
#         iso = day.isoformat()
#         for t in trains:
#             if has_departed(iso, t["departs"], now):
#                 continue
#             rows.append({"train": t, "date": iso, "label": day.strftime("%a %d %b %Y"),
#                          "available": t["total_seats"] - booked.get((t["id"], iso), 0)})
#         day += timedelta(days=1)
#     return rows


# def parse_passengers(names, ages):
#     """Validate passenger rows. Returns (passengers, rows_to_redisplay, errors)."""
#     passengers, rows, errors = [], [], []
#     if len(names) > MAX_PASSENGERS or len(ages) > MAX_PASSENGERS:
#         errors.append(f"A booking can have at most {MAX_PASSENGERS} passengers.")
#     for i in range(MAX_PASSENGERS):
#         name = names[i].strip() if i < len(names) else ""
#         age = ages[i].strip() if i < len(ages) else ""
#         rows.append({"name": name, "age": age})
#         if not name and not age:
#             continue
#         if not NAME_RE.fullmatch(name):
#             errors.append(f"Passenger {i + 1}: enter a valid name (letters, spaces, . ' -).")
#         elif not (age.isascii() and age.isdigit() and 1 <= int(age) <= 120):
#             errors.append(f"Passenger {i + 1}: enter an age between 1 and 120.")
#         else:
#             passengers.append((name, int(age)))
#     if not passengers and not errors:
#         errors.append("Add at least one passenger.")
#     return passengers, rows, errors


# @app.before_request
# def load_user():
#     g.user = None
#     if request.endpoint == "static":
#         return
#     user_id = session.get("user_id")
#     if user_id is not None:
#         g.user = get_db().execute(
#             "SELECT id, name, email FROM users WHERE id = ?", (user_id,)).fetchone()
#         if g.user is None:
#             session.clear()


# def login_required(view):
#     @wraps(view)
#     def wrapped(*args, **kwargs):
#         if g.user is None:
#             flash("Please log in to continue.", "error")
#             return redirect(url_for("login"))
#         return view(*args, **kwargs)
#     return wrapped


# @app.after_request
# def security_headers(resp):
#     resp.headers["Content-Security-Policy"] = (
#         "default-src 'self'; script-src 'self' 'none'; style-src 'self'; img-src 'self' data:; "
#         "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
#     resp.headers["X-Content-Type-Options"] = "nosniff"
#     resp.headers["X-Frame-Options"] = "DENY"
#     resp.headers["Referrer-Policy"] = "same-origin"
#     resp.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
#     if request.endpoint != "static":
#         resp.headers["Cache-Control"] = "no-store"
#     if app.config["SESSION_COOKIE_SECURE"]:
#         resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
#     return resp
# @app.context_processor
# def inject_clock():
#     """Current date/time shown in the page header (templates: now_label, now_epoch)."""
#     n = now_ist()
#     return {"now_label": n.strftime("%a, %d %b %Y, %I:%M:%S %p IST"),
#             "now_epoch": int(n.timestamp() * 1000)}


# # --------------------------------------------------------------------------
# # Routes: accounts
# # --------------------------------------------------------------------------
# @app.route("/register", methods=["GET", "POST"])
# @limiter.limit("10 per hour", methods=["POST"])
# def register():
#     name = email = ""
#     if request.method == "POST":
#         name = request.form.get("name", "").strip()
#         email = request.form.get("email", "").strip().lower()
#         password = request.form.get("password", "")
#         errors = []
#         if not NAME_RE.fullmatch(name):
#             errors.append("Enter a valid name (letters, spaces, . ' -).")
#         if len(email) > 254 or not EMAIL_RE.fullmatch(email):
#             errors.append("Enter a valid email address.")
#         if not (8 <= len(password) <= 128) or password.isalpha() or password.isdigit():
#             errors.append("Password must be 8-128 characters and mix letters with numbers or symbols.")
#         if not errors:
#             try:
#                 get_db().execute(
#                     "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
#                     (name, email, generate_password_hash(password)))
#                 flash("Account created. Please log in.", "success")
#                 return redirect(url_for("login"))
#             except sqlite3.IntegrityError:
#                 errors.append("Registration failed. Try a different email or log in.")
#         for e in errors:
#             flash(e, "error")
#     return render_template("register.html", name=name, email=email)


# @app.route("/login", methods=["GET", "POST"])
# @limiter.limit("10 per minute", methods=["POST"])
# def login():
#     email = ""
#     if request.method == "POST":
#         email = request.form.get("email", "").strip().lower()
#         password = request.form.get("password", "")
#         user = get_db().execute(
#             "SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
#         stored = user["password_hash"] if user else DUMMY_HASH
#         if check_password_hash(stored, password) and user:
#             session.clear()                      # new session on login (prevents fixation)
#             session["user_id"] = user["id"]
#             session.permanent = True
#             return redirect(url_for("index"))
#         flash("Invalid email or password.", "error")  # same message for both cases
#     return render_template("login.html", email=email)


# @app.route("/logout", methods=["POST"])
# def logout():
#     session.clear()
#     flash("You have been logged out.", "success")
#     return redirect(url_for("index"))


# # --------------------------------------------------------------------------
# # Routes: search, booking, journey management
# # --------------------------------------------------------------------------
# @app.route("/")
# def index():
#     db = get_db()
#     now = now_ist()
#     start, end = booking_window(now)
#     stations = [r[0] for r in db.execute(
#         "SELECT source FROM trains UNION SELECT destination FROM trains ORDER BY 1")]
#     source = request.args.get("source", "").strip()
#     destination = request.args.get("destination", "").strip()
#     raw_date = request.args.get("date", "").strip()
#     show_all = request.args.get("all") == "1"      # the "Show all trains" button
#     results = upcoming = None
#     travel_date = None
#     page = total_pages = total = 1
#     if source or destination or raw_date or show_all:
#         if source not in stations or destination not in stations:
#             flash("Please choose valid stations.", "error")
#         elif source == destination:
#             flash("Source and destination must be different.", "error")
#         elif show_all:
#             rows = upcoming_departures(db, source, destination, now)
#             total = len(rows)
#             total_pages = max(1, -(-total // PER_PAGE))
#             page = min(max(request.args.get("page", 1, type=int), 1), total_pages)
#             upcoming = rows[(page - 1) * PER_PAGE: page * PER_PAGE]
#         else:
#             travel_date = parse_travel_date(raw_date, now)
#             if travel_date is None:
#                 flash(f"Choose a date between {start:%d %b %Y} and {end:%d %b %Y}.", "error")
#             else:
#                 found = db.execute(
#                     AVAILABLE_SQL + "WHERE t.source = ? AND t.destination = ? ORDER BY t.departs",
#                     (travel_date, source, destination)).fetchall()
#                 results = [{**dict(r), "departed": has_departed(travel_date, r["departs"], now)}
#                            for r in found]
#     return render_template(
#         "index.html", stations=stations, source=source, destination=destination,
#         travel_date=travel_date, results=results, upcoming=upcoming, page=page,
#         total_pages=total_pages, total=total, min_date=start.isoformat(), max_date=end.isoformat())


# def create_booking(db, user_id, train_id, travel_date, passengers):
#     """Book seats inside one transaction so two users cannot take the same seats.

#     BEGIN IMMEDIATE locks the database for writing, so the seat check and the
#     insert happen together. Returns the PNR, or None if seats are not available.
#     """
#     db.execute("BEGIN IMMEDIATE")
#     try:
#         train = db.execute(AVAILABLE_SQL + "WHERE t.id = ?", (travel_date, train_id)).fetchone()
#         if train is None or len(passengers) > train["available"]:
#             db.execute("ROLLBACK")
#             return None
#         for _ in range(5):                         # retry on the (very rare) PNR clash
#             pnr = str(secrets.randbelow(9_000_000_000) + 1_000_000_000)
#             try:
#                 cur = db.execute(
#                     "INSERT INTO bookings (pnr, user_id, train_id, travel_date, seats, total_fare) "
#                     "VALUES (?, ?, ?, ?, ?, ?)",
#                     (pnr, user_id, train_id, travel_date, len(passengers),
#                      train["fare"] * len(passengers)))
#                 break
#             except sqlite3.IntegrityError:
#                 continue
#         else:
#             raise RuntimeError("Could not generate a PNR")
#         db.executemany("INSERT INTO passengers (booking_id, name, age) VALUES (?, ?, ?)",
#                        [(cur.lastrowid, n, a) for n, a in passengers])
#         db.execute("COMMIT")
#         return pnr
#     except Exception:
#         if db.in_transaction:
#             db.execute("ROLLBACK")
#         raise


# @app.route("/book/<int:train_id>", methods=["GET", "POST"])
# @limiter.limit("20 per hour", methods=["POST"])
# @login_required
# def book(train_id):
#     db = get_db()
#     now = now_ist()
#     travel_date = parse_travel_date(request.values.get("date", ""), now)
#     if travel_date is None:
#         flash("Please search again and choose a valid date.", "error")
#         return redirect(url_for("index"))
#     train = db.execute(AVAILABLE_SQL + "WHERE t.id = ?", (travel_date, train_id)).fetchone()
#     if train is None:
#         abort(404)
#     if has_departed(travel_date, train["departs"], now):
#         flash("This train has already departed. Please choose another.", "error")
#         return redirect(url_for("index"))
#     rows = [{"name": "", "age": ""} for _ in range(MAX_PASSENGERS)]
#     if request.method == "POST":
#         passengers, rows, errors = parse_passengers(
#             request.form.getlist("name"), request.form.getlist("age"))
#         if not errors:
#             pnr = create_booking(db, g.user["id"], train_id, travel_date, passengers)
#             if pnr:
#                 flash("Booking confirmed!", "success")
#                 return redirect(url_for("booking_detail", pnr=pnr))
#             errors.append("Not enough seats left for this train and date.")
#             train = db.execute(AVAILABLE_SQL + "WHERE t.id = ?", (travel_date, train_id)).fetchone()
#         for e in errors:
#             flash(e, "error")
#     return render_template("book.html", train=train, travel_date=travel_date, rows=rows,
#                            max_passengers=MAX_PASSENGERS)


# @app.route("/bookings")
# @login_required
# def my_bookings():
#     bookings = get_db().execute(
#         "SELECT b.pnr, b.travel_date, b.seats, b.total_fare, b.status, "
#         "t.number, t.name AS train_name, t.source, t.destination "
#         "FROM bookings b JOIN trains t ON t.id = b.train_id "
#         "WHERE b.user_id = ? ORDER BY b.travel_date DESC, b.id DESC", (g.user["id"],)).fetchall()
#     return render_template("bookings.html", bookings=bookings)


# def get_own_booking(pnr):
#     """Fetch a booking only if it belongs to the logged-in user (else 404)."""
#     if not PNR_RE.fullmatch(pnr):
#         abort(404)
#     booking = get_db().execute(
#         "SELECT b.*, t.number, t.name AS train_name, t.source, t.destination, t.departs, t.arrives "
#         "FROM bookings b JOIN trains t ON t.id = b.train_id "
#         "WHERE b.pnr = ? AND b.user_id = ?", (pnr, g.user["id"])).fetchone()
#     if booking is None:
#         abort(404)
#     return booking


# @app.route("/bookings/<pnr>")
# @login_required
# def booking_detail(pnr):
#     booking = get_own_booking(pnr)
#     passengers = get_db().execute(
#         "SELECT name, age FROM passengers WHERE booking_id = ? ORDER BY id",
#         (booking["id"],)).fetchall()
#     can_cancel = booking["status"] == "CONFIRMED" and booking["travel_date"] >= date.today().isoformat()
#     return render_template("booking_detail.html", booking=booking, passengers=passengers,
#                            can_cancel=can_cancel)


# @app.route("/bookings/<pnr>/cancel", methods=["POST"])
# @login_required
# def cancel_booking(pnr):
#     booking = get_own_booking(pnr)
#     cur = get_db().execute(
#         "UPDATE bookings SET status = 'CANCELLED' "
#         "WHERE id = ? AND user_id = ? AND status = 'CONFIRMED' AND travel_date >= ?",
#         (booking["id"], g.user["id"], date.today().isoformat()))
#     if cur.rowcount:
#         flash("Booking cancelled. Seats have been released (refund is simulated).", "success")
#     else:
#         flash("This booking cannot be cancelled.", "error")
#     return redirect(url_for("booking_detail", pnr=pnr))


# # --------------------------------------------------------------------------
# # Error pages
# # --------------------------------------------------------------------------
# @app.errorhandler(400)
# @app.errorhandler(404)
# @app.errorhandler(429)
# @app.errorhandler(500)
# def handle_error(err):
#     code = getattr(err, "code", 500)
#     messages = {
#         400: "Bad request, or your form expired. Go back, refresh and try again.",
#         404: "We could not find that page.",
#         429: "Too many requests. Please wait a moment and try again.",
#         500: "Something went wrong on our side.",
#     }
#     return render_template("error.html", code=code, message=messages.get(code, "Error")), code


# init_db()

# if __name__ == "__main__":
#     app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)


"""Railway Reservation System - a simple and secure Flask web application.

Features : register / login, search trains, book tickets, view and cancel bookings.
Security : hashed passwords, parameterised SQL, CSRF protection, secure session
           cookies, security headers, rate limiting, input validation,
           per-user access checks and race-free seat booking.
Run      : python app.py   ->   http://127.0.0.1:5000
"""
import os
import re
import secrets
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash
from trains_data import build_trains

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
DB_PATH = Path(os.environ.get("DATABASE_PATH", INSTANCE_DIR / "railway.db"))
MAX_PASSENGERS = 4          # passengers per booking
TIMEZONE = ZoneInfo("Asia/Kolkata")
BOOKING_END = date.fromisoformat(os.environ.get("BOOKING_END_DATE", "2027-03-31"))  # last bookable date
PER_PAGE = 10               # rows per page in the "all trains" list      # how far ahead a ticket can be booked


def load_secret_key():
    """Use SECRET_KEY from the environment, else create one once and reuse it."""
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    INSTANCE_DIR.mkdir(exist_ok=True)
    key_file = INSTANCE_DIR / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
    return key_file.read_text().strip()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=load_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,                 # JavaScript cannot read the cookie
    SESSION_COOKIE_SAMESITE="Lax",                # blocks cross-site form posts
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",  # set 1 on HTTPS
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    MAX_CONTENT_LENGTH=16 * 1024,                 # reject large request bodies
)
csrf = CSRFProtect(app)                           # CSRF token on every POST
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per hour"],
                  storage_uri="memory://")        # rate limiting (brute force / DoS)

# --------------------------------------------------------------------------
# Database (Neon PostgreSQL via pg8000)
# --------------------------------------------------------------------------
from urllib.parse import unquote, urlparse
from pg8000 import dbapi
from pg8000.dbapi import IntegrityError

class Row(dict):
    """Dictionary-like row that also supports SQLite-style numeric indexing."""
    def __getitem__(self, key):
        if isinstance(key, int):
            key = list(self.keys())[key]
        return super().__getitem__(key)


class Cursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def _row(self, values):
        if values is None:
            return None
        names = [column[0] for column in self._cursor.description]
        return Row(zip(names, values))

    def fetchone(self):
        return self._row(self._cursor.fetchone())

    def fetchall(self):
        return [self._row(row) for row in self._cursor.fetchall()]
    def __iter__(self):
        return iter(self.fetchall())

    @property
    def rowcount(self):
        return self._cursor.rowcount


class Database:
    """Small compatibility layer for the app's existing execute/fetch patterns."""
    def __init__(self):
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL is not set.")
        parsed = urlparse(url)
        self.connection = dbapi.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            database=parsed.path.lstrip("/"),
            user=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            ssl_context=True,
        )
        self.connection.autocommit = True
        self.in_transaction = False

    def execute(self, sql, params=()):
        sql = sql.replace("?", "%s")
        if sql.strip().upper() == "BEGIN IMMEDIATE":
            sql = "BEGIN"
        cur = self.connection.cursor()
        cur.execute(sql, params)
        if sql.strip().upper().startswith("BEGIN"):
            self.in_transaction = True
        elif sql.strip().upper() in ("COMMIT", "ROLLBACK"):
            self.in_transaction = False
        return Cursor(cur)

    def executemany(self, sql, params):
        cur = self.connection.cursor()
        cur.executemany(sql.replace("?", "%s"), params)
        return Cursor(cur)

    def close(self):
        self.connection.close()


def init_db():
    """Create missing PostgreSQL tables and seed train records without duplicates."""
    con = Database()
    statements = [
        """CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS trains (
            id BIGSERIAL PRIMARY KEY, number TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL, source TEXT NOT NULL, destination TEXT NOT NULL,
            departs TEXT NOT NULL, arrives TEXT NOT NULL,
            fare INTEGER NOT NULL CHECK (fare > 0),
            total_seats INTEGER NOT NULL CHECK (total_seats > 0))""",
        """CREATE TABLE IF NOT EXISTS bookings (
            id BIGSERIAL PRIMARY KEY, pnr TEXT NOT NULL UNIQUE,
            user_id BIGINT NOT NULL REFERENCES users(id),
            train_id BIGINT NOT NULL REFERENCES trains(id),
            travel_date TEXT NOT NULL, seats INTEGER NOT NULL CHECK (seats BETWEEN 1 AND 4),
            total_fare INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'CONFIRMED'
                CHECK (status IN ('CONFIRMED', 'CANCELLED')),
            booked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS passengers (
            id BIGSERIAL PRIMARY KEY, booking_id BIGINT NOT NULL REFERENCES bookings(id),
            name TEXT NOT NULL, age INTEGER NOT NULL CHECK (age BETWEEN 1 AND 120))""",
        "CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_bookings_train_date ON bookings(train_id, travel_date)",
    ]
    try:
        for statement in statements:
            con.execute(statement)
        con.executemany(
            """INSERT INTO trains
            (number, name, source, destination, departs, arrives, fare, total_seats)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (number) DO NOTHING""",
            build_trains())
    finally:
        con.close()


AVAILABLE_SQL = """
SELECT t.*, t.total_seats - COALESCE((
    SELECT SUM(b.seats) FROM bookings b
    WHERE b.train_id = t.id AND b.travel_date = ? AND b.status = 'CONFIRMED'), 0) AS available
FROM trains t
"""


def get_db():
    if "db" not in g:
        g.db = Database()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# --------------------------------------------------------------------------
# Helpers: validation and authentication
# --------------------------------------------------------------------------
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,59}$")
PNR_RE = re.compile(r"^\d{10}$")
DUMMY_HASH = generate_password_hash("dummy-password")  # keeps login timing similar


def now_ist():
    """Current date and time in India (taken from the computer running the app)."""
    return datetime.now(TIMEZONE)


def today_ist():
    return now_ist().date()


def booking_window(now):
    """Bookable dates: from today until BOOKING_END."""
    return now.date(), BOOKING_END


def has_departed(travel_date, departs, now=None):
    """True if the train on that date has already left (travel_date 'YYYY-MM-DD', departs 'HH:MM')."""
    now = now or now_ist()
    departure = datetime.fromisoformat(f"{travel_date}T{departs}").replace(tzinfo=TIMEZONE)
    return departure <= now


def parse_travel_date(value, now=None):
    """Return an ISO date string if valid and inside the booking window, else None."""
    try:
        d = date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    start, end = booking_window(now or now_ist())
    return d.isoformat() if start <= d <= end else None


def upcoming_departures(db, source, destination, now):
    """Every bookable departure on a route, ordered by date then time (nearest first)."""
    start, end = booking_window(now)
    trains = db.execute(
        "SELECT * FROM trains WHERE source = ? AND destination = ? ORDER BY departs",
        (source, destination)).fetchall()
    booked = {(r["train_id"], r["travel_date"]): r["seats"] for r in db.execute(
        "SELECT b.train_id, b.travel_date, SUM(b.seats) AS seats FROM bookings b "
        "JOIN trains t ON t.id = b.train_id "
        "WHERE b.status = 'CONFIRMED' AND t.source = ? AND t.destination = ? "
        "AND b.travel_date BETWEEN ? AND ? GROUP BY b.train_id, b.travel_date",
        (source, destination, start.isoformat(), end.isoformat()))}
    rows, day = [], start
    while day <= end:
        iso = day.isoformat()
        for t in trains:
            if has_departed(iso, t["departs"], now):
                continue
            rows.append({"train": t, "date": iso, "label": day.strftime("%a %d %b %Y"),
                         "available": t["total_seats"] - booked.get((t["id"], iso), 0)})
        day += timedelta(days=1)
    return rows


def parse_passengers(names, ages):
    """Validate passenger rows. Returns (passengers, rows_to_redisplay, errors)."""
    passengers, rows, errors = [], [], []
    if len(names) > MAX_PASSENGERS or len(ages) > MAX_PASSENGERS:
        errors.append(f"A booking can have at most {MAX_PASSENGERS} passengers.")
    for i in range(MAX_PASSENGERS):
        name = names[i].strip() if i < len(names) else ""
        age = ages[i].strip() if i < len(ages) else ""
        rows.append({"name": name, "age": age})
        if not name and not age:
            continue
        if not NAME_RE.fullmatch(name):
            errors.append(f"Passenger {i + 1}: enter a valid name (letters, spaces, . ' -).")
        elif not (age.isascii() and age.isdigit() and 1 <= int(age) <= 120):
            errors.append(f"Passenger {i + 1}: enter an age between 1 and 120.")
        else:
            passengers.append((name, int(age)))
    if not passengers and not errors:
        errors.append("Add at least one passenger.")
    return passengers, rows, errors


@app.before_request
def load_user():
    g.user = None
    if request.endpoint == "static":
        return
    user_id = session.get("user_id")
    if user_id is not None:
        g.user = get_db().execute(
            "SELECT id, name, email FROM users WHERE id = ?", (user_id,)).fetchone()
        if g.user is None:
            session.clear()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.after_request
def security_headers(resp):
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'none'; style-src 'self'; img-src 'self' data:; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    if request.endpoint != "static":
        resp.headers["Cache-Control"] = "no-store"
    if app.config["SESSION_COOKIE_SECURE"]:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp
@app.context_processor
def inject_clock():
    """Current date/time shown in the page header (templates: now_label, now_epoch)."""
    n = now_ist()
    return {"now_label": n.strftime("%a, %d %b %Y, %I:%M:%S %p IST"),
            "now_epoch": int(n.timestamp() * 1000)}


# --------------------------------------------------------------------------
# Routes: accounts
# --------------------------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def register():
    name = email = ""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        errors = []
        if not NAME_RE.fullmatch(name):
            errors.append("Enter a valid name (letters, spaces, . ' -).")
        if len(email) > 254 or not EMAIL_RE.fullmatch(email):
            errors.append("Enter a valid email address.")
        if not (8 <= len(password) <= 128) or password.isalpha() or password.isdigit():
            errors.append("Password must be 8-128 characters and mix letters with numbers or symbols.")
        if not errors:
            try:
                get_db().execute(
                    "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                    (name, email, generate_password_hash(password)))
                flash("Account created. Please log in.", "success")
                return redirect(url_for("login"))
            except IntegrityError:
                errors.append("Registration failed. Try a different email or log in.")
        for e in errors:
            flash(e, "error")
    return render_template("register.html", name=name, email=email)


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
        stored = user["password_hash"] if user else DUMMY_HASH
        if check_password_hash(stored, password) and user:
            session.clear()                      # new session on login (prevents fixation)
            session["user_id"] = user["id"]
            session.permanent = True
            return redirect(url_for("index"))
        flash("Invalid email or password.", "error")  # same message for both cases
    return render_template("login.html", email=email)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


# --------------------------------------------------------------------------
# Routes: search, booking, journey management
# --------------------------------------------------------------------------
@app.route("/")
def index():
    db = get_db()
    now = now_ist()
    start, end = booking_window(now)
    stations = [r[0] for r in db.execute(
        "SELECT source FROM trains UNION SELECT destination FROM trains ORDER BY 1")]
    source = request.args.get("source", "").strip()
    destination = request.args.get("destination", "").strip()
    raw_date = request.args.get("date", "").strip()
    show_all = request.args.get("all") == "1"      # the "Show all trains" button
    results = upcoming = None
    travel_date = None
    page = total_pages = total = 1
    if source or destination or raw_date or show_all:
        if source not in stations or destination not in stations:
            flash("Please choose valid stations.", "error")
        elif source == destination:
            flash("Source and destination must be different.", "error")
        elif show_all:
            rows = upcoming_departures(db, source, destination, now)
            total = len(rows)
            total_pages = max(1, -(-total // PER_PAGE))
            page = min(max(request.args.get("page", 1, type=int), 1), total_pages)
            upcoming = rows[(page - 1) * PER_PAGE: page * PER_PAGE]
        else:
            travel_date = parse_travel_date(raw_date, now)
            if travel_date is None:
                flash(f"Choose a date between {start:%d %b %Y} and {end:%d %b %Y}.", "error")
            else:
                found = db.execute(
                    AVAILABLE_SQL + "WHERE t.source = ? AND t.destination = ? ORDER BY t.departs",
                    (travel_date, source, destination)).fetchall()
                results = [{**dict(r), "departed": has_departed(travel_date, r["departs"], now)}
                           for r in found]
    return render_template(
        "index.html", stations=stations, source=source, destination=destination,
        travel_date=travel_date, results=results, upcoming=upcoming, page=page,
        total_pages=total_pages, total=total, min_date=start.isoformat(), max_date=end.isoformat())


def create_booking(db, user_id, train_id, travel_date, passengers):
    """Lock the train row while checking and committing a booking."""
    db.execute("BEGIN")
    try:
        # Serializes bookings for this train, preventing overselling.
        train = db.execute(
            AVAILABLE_SQL + "WHERE t.id = ? FOR UPDATE", (travel_date, train_id)
        ).fetchone()
        if train is None or len(passengers) > train["available"]:
            db.execute("ROLLBACK")
            return None

        pnr = str(secrets.randbelow(9_000_000_000) + 1_000_000_000)
        cur = db.execute(
            "INSERT INTO bookings (pnr, user_id, train_id, travel_date, seats, total_fare) "
            "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (pnr, user_id, train_id, travel_date, len(passengers),
             train["fare"] * len(passengers)))
        booking_id = cur.fetchone()["id"]
        db.executemany(
            "INSERT INTO passengers (booking_id, name, age) VALUES (?, ?, ?)",
            [(booking_id, name, age) for name, age in passengers])
        db.execute("COMMIT")
        return pnr
    except Exception:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise


@app.route("/book/<int:train_id>", methods=["GET", "POST"])
@limiter.limit("20 per hour", methods=["POST"])
@login_required
def book(train_id):
    db = get_db()
    now = now_ist()
    travel_date = parse_travel_date(request.values.get("date", ""), now)
    if travel_date is None:
        flash("Please search again and choose a valid date.", "error")
        return redirect(url_for("index"))
    train = db.execute(AVAILABLE_SQL + "WHERE t.id = ?", (travel_date, train_id)).fetchone()
    if train is None:
        abort(404)
    if has_departed(travel_date, train["departs"], now):
        flash("This train has already departed. Please choose another.", "error")
        return redirect(url_for("index"))
    rows = [{"name": "", "age": ""} for _ in range(MAX_PASSENGERS)]
    if request.method == "POST":
        passengers, rows, errors = parse_passengers(
            request.form.getlist("name"), request.form.getlist("age"))
        if not errors:
            pnr = create_booking(db, g.user["id"], train_id, travel_date, passengers)
            if pnr:
                flash("Booking confirmed!", "success")
                return redirect(url_for("booking_detail", pnr=pnr))
            errors.append("Not enough seats left for this train and date.")
            train = db.execute(AVAILABLE_SQL + "WHERE t.id = ?", (travel_date, train_id)).fetchone()
        for e in errors:
            flash(e, "error")
    return render_template("book.html", train=train, travel_date=travel_date, rows=rows,
                           max_passengers=MAX_PASSENGERS)


@app.route("/bookings")
@login_required
def my_bookings():
    bookings = get_db().execute(
        "SELECT b.pnr, b.travel_date, b.seats, b.total_fare, b.status, "
        "t.number, t.name AS train_name, t.source, t.destination "
        "FROM bookings b JOIN trains t ON t.id = b.train_id "
        "WHERE b.user_id = ? ORDER BY b.travel_date DESC, b.id DESC", (g.user["id"],)).fetchall()
    return render_template("bookings.html", bookings=bookings)


def get_own_booking(pnr):
    """Fetch a booking only if it belongs to the logged-in user (else 404)."""
    if not PNR_RE.fullmatch(pnr):
        abort(404)
    booking = get_db().execute(
        "SELECT b.*, t.number, t.name AS train_name, t.source, t.destination, t.departs, t.arrives "
        "FROM bookings b JOIN trains t ON t.id = b.train_id "
        "WHERE b.pnr = ? AND b.user_id = ?", (pnr, g.user["id"])).fetchone()
    if booking is None:
        abort(404)
    return booking


@app.route("/bookings/<pnr>")
@login_required
def booking_detail(pnr):
    booking = get_own_booking(pnr)
    passengers = get_db().execute(
        "SELECT name, age FROM passengers WHERE booking_id = ? ORDER BY id",
        (booking["id"],)).fetchall()
    can_cancel = booking["status"] == "CONFIRMED" and booking["travel_date"] >= date.today().isoformat()
    return render_template("booking_detail.html", booking=booking, passengers=passengers,
                           can_cancel=can_cancel)


@app.route("/bookings/<pnr>/cancel", methods=["POST"])
@login_required
def cancel_booking(pnr):
    booking = get_own_booking(pnr)
    cur = get_db().execute(
        "UPDATE bookings SET status = 'CANCELLED' "
        "WHERE id = ? AND user_id = ? AND status = 'CONFIRMED' AND travel_date >= ?",
        (booking["id"], g.user["id"], date.today().isoformat()))
    if cur.rowcount:
        flash("Booking cancelled. Seats have been released (refund is simulated).", "success")
    else:
        flash("This booking cannot be cancelled.", "error")
    return redirect(url_for("booking_detail", pnr=pnr))


# --------------------------------------------------------------------------
# Error pages
# --------------------------------------------------------------------------
@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(429)
@app.errorhandler(500)
def handle_error(err):
    code = getattr(err, "code", 500)
    messages = {
        400: "Bad request, or your form expired. Go back, refresh and try again.",
        404: "We could not find that page.",
        429: "Too many requests. Please wait a moment and try again.",
        500: "Something went wrong on our side.",
    }
    return render_template("error.html", code=code, message=messages.get(code, "Error")), code


init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
