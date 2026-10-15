# Book Reading Analytics — Flask + SQLite

This version converts Ilia's original single-file HTML/JavaScript visual prototype into a real multi-user web application while preserving its four-tab interface and main features.

## Architecture

```text
Browser (HTML/CSS/JavaScript)
        ↓ fetch / forms
Flask routes and JSON API
        ↓
Python analytics + recommendation algorithms
        ↓
SQLite database
```

## VS Code structure

```text
ilia_reading_analytics/
├── app.py
├── auth.py
├── api.py
├── analytics.py
├── recommendations.py
├── database.py
├── schema.sql
├── requirements.txt
├── Procfile
├── .env.example
├── .gitignore
├── instance/
│   └── reading.db             # created automatically; do not commit
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── register.html
│   └── dashboard.html
└── static/
    ├── style.css
    └── dashboard.js
```

## Functional features

- Registration, login and logout
- Password hashing using Werkzeug
- User-specific books, sessions and goals
- SQLite permanent storage
- Add, edit and delete books
- Log reading duration and pages read
- Automatic reading-progress and completion status
- Total reading time
- Average reading speed in pages/hour
- Genre distribution
- Weekly and monthly reading trends
- Reading goals
- Goal-completion prediction
- Personalised recommendations
- Duplicate and invalid-input validation
- Foreign-key relationships and cascade deletion

## Recommendation algorithm

The recommendation module uses actual user history rather than a random book:

1. Sum reading minutes per genre.
2. Count completed books per genre.
3. Calculate a weighted preference score:
   - 70% reading-time share
   - 30% completed-book share
4. Rank genres with a manually implemented selection sort.
5. Search the recommendation catalogue from the highest ranked genre downward.
6. Exclude books already present in the user's library.
7. Return up to three unread suggestions.

The 70/30 weighting is a design choice and should be justified/evaluated by the student in the IA.

## Run locally in VS Code

### Windows PowerShell

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SECRET_KEY="replace-with-a-long-random-secret"
flask --app app run --debug
```

Open `http://127.0.0.1:5000`.

The database is created automatically at `instance/reading.db`.

## Run the smoke tests

After installing the requirements:

```powershell
python -m unittest discover -s tests -v
```

The tests cover registration, database persistence, duplicate validation, reading-progress recalculation, completion status, analytics, recommendation generation, API authentication and user-data isolation.

## Run online

### Production command

```text
gunicorn app:app
```

Do not use Flask's development server as the public production server.

### PythonAnywhere

PythonAnywhere is suitable for this school project because an SQLite file can remain in the account's persistent home directory. Upload or clone the project, install `requirements.txt` in a virtual environment, configure the Flask web app/WSGI file, set a strong `SECRET_KEY`, and reload the web app.

### Render or another container host

The app also supports an external database path through the `DATABASE_PATH` environment variable. For a host whose normal filesystem is temporary, attach persistent storage and point `DATABASE_PATH` to the mounted disk, for example:

```text
DATABASE_PATH=/var/data/reading.db
SECRET_KEY=<long-random-secret>
COOKIE_SECURE=1
```

Without persistent storage, SQLite data may disappear when that type of service restarts/redeploys.

## About the extra trial files

The downloaded `index-*.js`, `s.js`, shared CSS files and `saved_resource.html` supplied alongside the project are browser/Claude platform assets rather than Ilia's reading-app source code, so they are intentionally not included in the application. The uploaded decomposition table is useful for IA planning because its components map closely to this implementation: book input, session input, storage, processing, analytics, goals, prediction, recommendations, validation and UI.

## IA authenticity

Use this as a development scaffold/reference. The student should type/adapt, test and be able to explain the significant code and decisions themselves, especially:

- database relationships and SQL queries
- password hashing and login sessions
- progress recalculation
- analytics queries/algorithms
- goal prediction
- recommendation scoring and selection sort
- input validation and testing

## Book covers (V3 addition)

When a user types a book title, the dashboard performs a low-volume Open Library title lookup through the Flask backend. The first likely cover is selected automatically, and alternative matches are displayed below the form. The selected `cover_url` is stored in SQLite with the book.

The user can always:
- choose a different search result;
- paste/edit any valid `http` or `https` cover image URL;
- remove the cover;
- search again while editing an existing book.

Existing databases are migrated automatically: if an older `books` table does not contain `cover_url`, the app adds that column at startup.

Book Edit/Delete buttons use delegated JavaScript click handling and the existing authenticated `PUT /api/books/<id>` and `DELETE /api/books/<id>` routes.

## V4 additions

### Add recommendations directly to the reading list
Recommendation cards now have an **Add to reading list** button. The backend validates that the title exists in the recommendation catalogue, tries to retrieve cover/page metadata, and inserts the book as `not_started`. If a page count cannot be found, the normal Books editor opens prefilled so the user can confirm the page count rather than the application inventing one.

### Reading progress bars
The Books table now shows a progress bar calculated from:

```text
current_page / total_pages * 100
```

Progress is rebuilt from stored reading sessions, so deleting a session also updates the bar.

### Improved analytics dynamics
Analytics now contains continuous time series that include zero-activity periods:

- daily: last 30 days
- weekly: last 12 weeks
- monthly: last 12 months

The chart can switch between **Minutes** and **Pages**. Summary cards also show:

- total reading time and pages
- last 7 days of reading time
- percentage change versus the previous 7 days
- pages read in the last 7 days
- active reading days in the last 30 days
- average minutes per active day
- books completed/currently reading

### Updating an existing V3 installation
Keep your existing `instance/reading.db`. Replace the application code/templates/static files with the V4 files, then restart Flask and hard-refresh the browser (`Ctrl + Shift + R`). No new database migration is required for V4.


## V5 additions

- Reading speed is calculated automatically for every book that has sessions.
- Analytics includes a reading-speed-by-genre comparison.
- Recommendations now weight:
  - 70% reading speed by genre
  - 20% share of reading time
  - 10% completed books
- Open Library title lookup now requests subject metadata as well as covers/pages.
- Open Library subjects are mapped into a consistent app genre list.
- Genre suggestions are automatic but remain editable by the user.


## V6 — password recovery

The login page now includes **Forgot password?**

Flow:

1. User submits their registered email address.
2. The application creates a signed, time-limited reset token.
3. A reset link is sent through the SendGrid HTTP API.
4. The link expires after 30 minutes.
5. The user chooses a new password.
6. The new password is hashed before storage.
7. Changing the password automatically invalidates all previously issued reset links.

The forgot-password page deliberately displays the same response for registered
and unregistered email addresses so it does not reveal which users exist.

### Local password-recovery testing

For local testing without SendGrid:

Windows PowerShell:

```powershell
$env:PASSWORD_RESET_DEBUG="1"
flask --app app run --debug
```

Submit the Forgot Password form. The reset URL will be printed in the Flask
terminal. Open that URL in the browser.

Do not enable `PASSWORD_RESET_DEBUG=1` on a public deployment.

### SendGrid setup

Set these environment variables on the host:

```text
SENDGRID_API_KEY=<your SendGrid API key>
RESET_FROM_EMAIL=<a sender address verified in SendGrid>
RESET_FROM_NAME=Book Reading Analytics
PUBLIC_BASE_URL=https://YOUR_USERNAME.pythonanywhere.com
SECRET_KEY=<long random secret>
COOKIE_SECURE=1
```

A stable `SECRET_KEY` is essential. If it changes, existing login sessions and
password-reset links become invalid.

## Recommended free deployment: PythonAnywhere

This project is a good fit for PythonAnywhere because it uses Flask + SQLite.
Keep the SQLite database inside the project/instance directory so it remains on
the account filesystem.

Typical deployment steps:

1. Create a PythonAnywhere free account.
2. Upload this project ZIP and extract it in your home directory.
3. Open a Bash console.
4. Create a virtual environment:
   `python -m venv ~/.virtualenvs/readinganalytics`
5. Activate it:
   `source ~/.virtualenvs/readinganalytics/bin/activate`
6. Install requirements:
   `pip install -r ~/ilia_reading_analytics/requirements.txt`
7. Create a Flask web app from the **Web** tab using manual configuration.
8. Set the source code directory to your project directory.
9. Configure the WSGI file so it imports `app` from `app.py`.
10. Add the environment variables listed above to the WSGI configuration
    before importing the Flask application.
11. Reload the web app.

Example WSGI environment configuration:

```python
import os
import sys

project_home = "/home/YOUR_USERNAME/ilia_reading_analytics"
if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.environ["SECRET_KEY"] = "REPLACE_WITH_A_LONG_RANDOM_SECRET"
os.environ["COOKIE_SECURE"] = "1"
os.environ["SENDGRID_API_KEY"] = "REPLACE_WITH_SENDGRID_KEY"
os.environ["RESET_FROM_EMAIL"] = "YOUR_VERIFIED_SENDER_EMAIL"
os.environ["RESET_FROM_NAME"] = "Book Reading Analytics"
os.environ["PUBLIC_BASE_URL"] = "https://YOUR_USERNAME.pythonanywhere.com"
os.environ["DATABASE_PATH"] = (
    "/home/YOUR_USERNAME/ilia_reading_analytics/instance/reading.db"
)

from app import app as application
```

Never commit real API keys or the production SECRET_KEY to GitHub.
