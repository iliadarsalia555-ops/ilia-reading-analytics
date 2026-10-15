from datetime import date, datetime
import sqlite3
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request, session

from analytics import analytics_summary, average_speed_for_book
from auth import login_required
from database import get_db
from recommendations import generate_recommendations
from book_lookup import lookup_book_metadata, search_book_covers

bp = Blueprint("api", __name__, url_prefix="/api")

def current_user_id():
    return session["user_id"]

def json_error(message, status=400):
    return jsonify({"error": message}), status



def clean_cover_url(value):
    value = str(value or "").strip()
    if not value:
        return ""
    if len(value) > 1000:
        raise ValueError("Cover URL is too long.")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Cover image must use a valid http or https URL.")
    return value


def valid_date(value):
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False

def recalculate_book_progress(user_id, book_id):
    """
    Rebuild a book's progress from its stored sessions.

    Sessions are processed chronologically so completed_at is the date on
    which cumulative pages first reached the book's total page count.
    """
    db = get_db()
    book = db.execute(
        "SELECT * FROM books WHERE id = ? AND user_id = ?",
        (book_id, user_id),
    ).fetchone()
    if book is None:
        return

    rows = db.execute(
        """SELECT session_date, pages_read
           FROM reading_sessions
           WHERE user_id = ? AND book_id = ?
           ORDER BY session_date ASC, id ASC""",
        (user_id, book_id),
    ).fetchall()

    cumulative_pages = 0
    completed_at = None
    for row in rows:
        cumulative_pages += row["pages_read"]
        if completed_at is None and cumulative_pages >= book["total_pages"]:
            completed_at = row["session_date"]

    current_page = min(cumulative_pages, book["total_pages"])
    if current_page == 0:
        status = "not_started"
        completed_at = None
    elif current_page >= book["total_pages"]:
        status = "completed"
    else:
        status = "reading"
        completed_at = None

    db.execute(
        """UPDATE books
           SET current_page = ?, status = ?, completed_at = ?
           WHERE id = ? AND user_id = ?""",
        (current_page, status, completed_at, book_id, user_id),
    )

@bp.get("/books")
@login_required
def list_books():
    rows = get_db().execute(
        """SELECT id, title, genre, cover_url, total_pages, current_page, status, completed_at
           FROM books
           WHERE user_id = ?
           ORDER BY id DESC""",
        (current_user_id(),),
    ).fetchall()
    return jsonify([dict(row) for row in rows])

@bp.post("/books")
@login_required
def add_book():
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    genre = str(data.get("genre", "")).strip()
    try:
        cover_url = clean_cover_url(data.get("cover_url", ""))
    except ValueError as exc:
        return json_error(str(exc))

    try:
        total_pages = int(data.get("total_pages", 0))
    except (TypeError, ValueError):
        total_pages = 0

    if not title or not genre or total_pages <= 0:
        return json_error("Title, genre and a positive page count are required.")
    if len(title) > 180 or len(genre) > 80:
        return json_error("Title or genre is too long.")

    db = get_db()
    try:
        cursor = db.execute(
            """INSERT INTO books(user_id, title, genre, cover_url, total_pages)
               VALUES (?, ?, ?, ?, ?)""",
            (current_user_id(), title, genre, cover_url, total_pages),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return json_error("That book is already in your library.", 409)

    row = db.execute(
        "SELECT * FROM books WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return jsonify(dict(row)), 201

@bp.put("/books/<int:book_id>")
@login_required
def update_book(book_id):
    user_id = current_user_id()
    db = get_db()
    existing = db.execute(
        "SELECT * FROM books WHERE id = ? AND user_id = ?",
        (book_id, user_id),
    ).fetchone()
    if existing is None:
        return json_error("Book not found.", 404)

    data = request.get_json(silent=True) or {}
    title = str(data.get("title", existing["title"])).strip()
    genre = str(data.get("genre", existing["genre"])).strip()
    try:
        cover_url = clean_cover_url(data.get("cover_url", existing["cover_url"] or ""))
    except ValueError as exc:
        return json_error(str(exc))

    try:
        total_pages = int(data.get("total_pages", existing["total_pages"]))
    except (TypeError, ValueError):
        return json_error("Pages must be a whole number.")

    if not title or not genre or total_pages <= 0:
        return json_error("Enter valid book details.")
    if len(title) > 180 or len(genre) > 80:
        return json_error("Title or genre is too long.")

    # Do not allow page total below progress already logged.
    logged_pages = db.execute(
        """SELECT COALESCE(SUM(pages_read), 0) AS pages
           FROM reading_sessions
           WHERE user_id = ? AND book_id = ?""",
        (user_id, book_id),
    ).fetchone()["pages"]

    if total_pages < logged_pages:
        return json_error(
            f"Total pages cannot be below {logged_pages}, because that many pages are already logged."
        )

    try:
        db.execute(
            """UPDATE books
               SET title = ?, genre = ?, cover_url = ?, total_pages = ?
               WHERE id = ? AND user_id = ?""",
            (title, genre, cover_url, total_pages, book_id, user_id),
        )
        recalculate_book_progress(user_id, book_id)
        db.commit()
    except sqlite3.IntegrityError:
        return json_error("Another book with that title already exists.", 409)

    row = db.execute(
        "SELECT * FROM books WHERE id = ? AND user_id = ?",
        (book_id, user_id),
    ).fetchone()
    return jsonify(dict(row))

@bp.delete("/books/<int:book_id>")
@login_required
def delete_book(book_id):
    db = get_db()
    cursor = db.execute(
        "DELETE FROM books WHERE id = ? AND user_id = ?",
        (book_id, current_user_id()),
    )
    db.commit()
    if cursor.rowcount == 0:
        return json_error("Book not found.", 404)
    return jsonify({"message": "Book and its reading sessions were deleted."})

@bp.get("/book-search")
@login_required
def book_search():
    title = request.args.get("title", "").strip()
    if len(title) < 2:
        return json_error("Enter at least two characters of a book title.")
    matches = search_book_covers(title, limit=6)
    return jsonify({"query": title, "matches": matches})


@bp.get("/sessions")
@login_required
def list_sessions():
    rows = get_db().execute(
        """SELECT s.id, s.book_id, b.title AS book_title,
                  s.session_date, s.duration_minutes, s.pages_read
           FROM reading_sessions s
           JOIN books b ON b.id = s.book_id
           WHERE s.user_id = ?
           ORDER BY s.session_date DESC, s.id DESC""",
        (current_user_id(),),
    ).fetchall()
    return jsonify([dict(row) for row in rows])

@bp.post("/sessions")
@login_required
def add_session():
    data = request.get_json(silent=True) or {}

    try:
        book_id = int(data.get("book_id", 0))
        duration = int(data.get("duration_minutes", 0))
        pages_read = int(data.get("pages_read", 0))
    except (TypeError, ValueError):
        return json_error("Book, duration and pages must be whole numbers.")

    session_date = data.get("session_date")

    if not valid_date(session_date):
        return json_error("Enter a valid session date.")
    if datetime.strptime(session_date, "%Y-%m-%d").date() > date.today():
        return json_error("Reading sessions cannot be logged in the future.")
    if duration <= 0:
        return json_error("Duration must be greater than zero.")
    if pages_read <= 0:
        return json_error("Pages read must be greater than zero.")

    user_id = current_user_id()
    db = get_db()
    book = db.execute(
        "SELECT * FROM books WHERE id = ? AND user_id = ?",
        (book_id, user_id),
    ).fetchone()
    if book is None:
        return json_error("Book not found.", 404)

    already_logged = db.execute(
        """SELECT COALESCE(SUM(pages_read), 0) AS pages
           FROM reading_sessions
           WHERE user_id = ? AND book_id = ?""",
        (user_id, book_id),
    ).fetchone()["pages"]

    remaining = max(book["total_pages"] - already_logged, 0)
    if pages_read > remaining:
        return json_error(
            f"Only {remaining} unlogged pages remain for this book."
        )

    cursor = db.execute(
        """INSERT INTO reading_sessions(
               user_id, book_id, session_date, duration_minutes, pages_read
           ) VALUES (?, ?, ?, ?, ?)""",
        (user_id, book_id, session_date, duration, pages_read),
    )
    recalculate_book_progress(user_id, book_id)
    db.commit()

    return jsonify({"id": cursor.lastrowid, "message": "Reading session logged."}), 201

@bp.delete("/sessions/<int:session_id>")
@login_required
def delete_session(session_id):
    user_id = current_user_id()
    db = get_db()
    row = db.execute(
        """SELECT book_id FROM reading_sessions
           WHERE id = ? AND user_id = ?""",
        (session_id, user_id),
    ).fetchone()
    if row is None:
        return json_error("Session not found.", 404)

    book_id = row["book_id"]
    db.execute(
        "DELETE FROM reading_sessions WHERE id = ? AND user_id = ?",
        (session_id, user_id),
    )
    recalculate_book_progress(user_id, book_id)
    db.commit()
    return jsonify({"message": "Reading session deleted."})

@bp.get("/analytics")
@login_required
def analytics():
    return jsonify(analytics_summary(current_user_id()))

@bp.get("/analytics/speed/<int:book_id>")
@login_required
def speed(book_id):
    user_id = current_user_id()
    book = get_db().execute(
        "SELECT id FROM books WHERE id = ? AND user_id = ?",
        (book_id, user_id),
    ).fetchone()
    if book is None:
        return json_error("Book not found.", 404)

    return jsonify({
        "book_id": book_id,
        "pages_per_hour": average_speed_for_book(user_id, book_id),
    })

@bp.get("/recommendations")
@login_required
def recommendations():
    return jsonify(generate_recommendations(current_user_id()))


@bp.post("/recommendations/add")
@login_required
def add_recommendation_to_library():
    """Add a recommendation directly to the user's reading list.

    The recommendation catalogue intentionally stores only title + genre.
    Open Library is queried at add-time for cover/page metadata. If a page
    count cannot be found, the frontend receives enough information to
    prefill the normal book editor rather than inventing a page count.
    """
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    genre = str(data.get("genre", "")).strip()
    if not title or not genre:
        return json_error("Recommendation title and genre are required.")

    db = get_db()
    catalog_item = db.execute(
        """SELECT title, genre FROM recommendation_catalog
           WHERE title = ? COLLATE NOCASE AND genre = ? COLLATE NOCASE""",
        (title, genre),
    ).fetchone()
    if catalog_item is None:
        return json_error("That recommendation is no longer available.", 404)

    existing = db.execute(
        "SELECT id FROM books WHERE user_id = ? AND title = ? COLLATE NOCASE",
        (current_user_id(), title),
    ).fetchone()
    if existing is not None:
        return json_error("That book is already in your reading list.", 409)

    metadata = lookup_book_metadata(title) or {}
    total_pages = metadata.get("total_pages")
    cover_url = metadata.get("cover_url") or ""

    if not total_pages or total_pages <= 0:
        return jsonify({
            "error": "Page count was not available automatically. Please confirm the pages to finish adding this book.",
            "code": "pages_required",
            "prefill": {
                "title": title,
                "genre": genre,
                "cover_url": cover_url,
                "total_pages": "",
            },
        }), 422

    try:
        cursor = db.execute(
            """INSERT INTO books(user_id, title, genre, cover_url, total_pages)
               VALUES (?, ?, ?, ?, ?)""",
            (current_user_id(), title, genre, cover_url, int(total_pages)),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return json_error("That book is already in your reading list.", 409)

    row = db.execute("SELECT * FROM books WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return jsonify({
        "message": "Book added to your reading list.",
        "book": dict(row),
        "metadata_source": "Open Library",
    }), 201

@bp.get("/goals")
@login_required
def get_goal():
    goal = analytics_summary(current_user_id())["goal"]
    return jsonify(goal)

@bp.post("/goals")
@login_required
def set_goal():
    data = request.get_json(silent=True) or {}
    try:
        target = int(data.get("target_books", 0))
    except (TypeError, ValueError):
        target = 0

    start = data.get("start_date")
    end = data.get("end_date")

    if target <= 0:
        return json_error("Target books must be a positive whole number.")
    if not valid_date(start) or not valid_date(end):
        return json_error("Enter valid start and end dates.")
    if end <= start:
        return json_error("End date must be after start date.")

    db = get_db()
    cursor = db.execute(
        """INSERT INTO goals(user_id, target_books, start_date, end_date)
           VALUES (?, ?, ?, ?)""",
        (current_user_id(), target, start, end),
    )
    db.commit()

    return jsonify({
        "id": cursor.lastrowid,
        "message": "Goal saved.",
        "goal": analytics_summary(current_user_id())["goal"],
    }), 201
