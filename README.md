# RailBook - Railway Reservation System

A small, secure web app: register, search trains, book tickets, view and cancel bookings.
Built with **Python (Flask) + SQLite**. Trains and payment are demo only.

## Run it

Needs Python 3.10 or newer.

```bash
# 1. (optional) create a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS / Linux

# 2. install requirements
pip install -r requirements.txt

# 3. start the app
python app.py
```

Open **http://127.0.0.1:5000**. The database and sample trains are created automatically on first run
(`instance/railway.db`). Delete the `instance` folder to reset everything.

**Try it:** Register -> Login -> search `Bengaluru` to `Davanagere` (any date in the next 60 days) ->
Book -> My bookings -> open a booking -> Cancel.

## Project structure

```
app.py              all backend code (routes, database, security)
requirements.txt    Flask, Flask-WTF (CSRF), Flask-Limiter (rate limiting)
templates/          HTML pages (base, index, register, login, book, bookings, booking_detail, error)
static/style.css    styling (no JavaScript is used)
instance/           created at runtime: railway.db + secret.key (do not share or commit)
```

## How the code works (app.py, top to bottom)

| Part | What it does |
|---|---|
| Configuration | Loads the secret key, sets secure cookie options, turns on CSRF protection and rate limiting. |
| `SCHEMA`, `init_db()` | 4 tables: `users`, `trains`, `bookings`, `passengers`. Adds 9 sample trains if empty. |
| `AVAILABLE_SQL` | Seats left = total seats - confirmed seats for that train and date. |
| Helpers | `parse_travel_date`, `parse_passengers` validate input. `login_required` guards pages. |
| `security_headers` | Adds CSP, X-Frame-Options, nosniff and other headers to every response. |
| `register`, `login`, `logout` | Account handling with hashed passwords. |
| `index` | Search page: validates stations and date, then lists trains with seats left. |
| `create_booking` | Checks seats and saves the booking in **one transaction** (no double booking). |
| `book`, `my_bookings`, `booking_detail`, `cancel_booking` | Booking and journey management; each checks the booking belongs to the logged-in user. |
| Error handlers | Friendly 400 / 404 / 429 / 500 pages. |

## Security measures

| Threat | Protection in this app |
|---|---|
| SQL injection | Every query uses `?` placeholders. User input is never joined into SQL. |
| Stolen passwords | Passwords are hashed with salt (Werkzeug scrypt). Plain passwords are never stored. |
| Brute force / bots / DoS | Rate limits: login 10/min, register 10/hour, booking 20/hour, 200 requests/hour overall. |
| Phishing-style form attacks (CSRF) | Every POST form carries a CSRF token; requests without it get 400. |
| XSS | Jinja2 escapes all output, names are validated, and CSP blocks all scripts. |
| Session theft / fixation | Cookie is HttpOnly + SameSite=Lax (+ Secure on HTTPS); session is reset on login; 30 min timeout. |
| Unauthorized access to records (IDOR) | A booking is only returned if `user_id` matches the logged-in user; otherwise 404. |
| Overbooking (race condition) | `BEGIN IMMEDIATE` transaction around the seat check and insert. |
| Account guessing | Same message for wrong email or wrong password; timing kept similar; PNRs are random. |
| Clickjacking, MIME sniffing | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, CSP `frame-ancestors 'none'`. |
| Data exposure | No card data collected. Pages are `no-store` cached. Secret key kept outside the code. |

## Settings (environment variables, all optional)

| Variable | Meaning | Default |
|---|---|---|
| `SECRET_KEY` | Signs session cookies | auto-generated in `instance/secret.key` |
| `COOKIE_SECURE` | Set `1` when served over HTTPS | `0` |
| `DATABASE_PATH` | SQLite file location | `instance/railway.db` |
| `PORT` | Port to listen on | `5000` |

## Before using it for real

This is a learning project. For production you would also: serve it over HTTPS behind a proper
server (for example gunicorn + nginx) with `COOKIE_SECURE=1`, use Redis for rate limiting
(`storage_uri` in `app.py`), use a real database, add email verification and password reset,
add a real payment gateway (never store card data yourself), and take regular encrypted backups.
