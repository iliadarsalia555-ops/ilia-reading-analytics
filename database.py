import sqlite3
from pathlib import Path

from flask import current_app, g

# Small built-in catalogue used by the recommendation algorithm.
# It is deliberately separate from the user's own library.
CATALOG = [
    ("The Great Gatsby", "Classic"),
    ("To Kill a Mockingbird", "Classic"),
    ("Crime and Punishment", "Classic"),
    ("The Book Thief", "Historical Fiction"),
    ("All the Light We Cannot See", "Historical Fiction"),
    ("Hamlet", "Drama"),
    ("King Lear", "Drama"),
    ("The Cherry Orchard", "Drama"),
    ("1984", "Fiction"),
    ("The Little Prince", "Fiction"),
    ("The Kite Runner", "Fiction"),
    ("Gulliver's Travels", "Satire"),
    ("Animal Farm", "Satire"),
    ("Catch-22", "Satire"),
    ("Antigone", "Tragedy"),
    ("Oedipus Rex", "Tragedy"),
    ("Macbeth", "Tragedy"),
    ("Dracula", "Horror"),
    ("Frankenstein", "Horror"),
    ("The Haunting of Hill House", "Horror"),
    ("And Then There Were None", "Mystery"),
    ("The Hound of the Baskervilles", "Mystery"),
    ("Murder on the Orient Express", "Mystery"),
    ("The Hobbit", "Fantasy"),
    ("The Fellowship of the Ring", "Fantasy"),
    ("The Name of the Wind", "Fantasy"),
    ("Dune", "Sci-Fi"),
    ("The Martian", "Sci-Fi"),
    ("Brave New World", "Sci-Fi"),
    ("Pride and Prejudice", "Romance"),
    ("Jane Eyre", "Romance"),
    ("Anna Karenina", "Romance"),
    ("Sapiens", "Non-fiction"),
    ("A Short History of Nearly Everything", "Non-fiction"),
    ("Educated", "Biography"),
    ("Steve Jobs", "Biography"),
]


def get_db():
    if "db" not in g:
        db_path = current_app.config["DATABASE"]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(db_path, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 5000")
        # WAL improves reliability when the deployed app performs overlapping reads/writes.
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _ensure_schema_migrations(db):
    """Apply tiny backwards-compatible migrations for existing local databases."""
    columns = {row["name"] for row in db.execute("PRAGMA table_info(books)").fetchall()}
    if "cover_url" not in columns:
        db.execute("ALTER TABLE books ADD COLUMN cover_url TEXT NOT NULL DEFAULT ''")


def init_db():
    db = get_db()
    schema_path = Path(current_app.root_path) / "schema.sql"
    db.executescript(schema_path.read_text(encoding="utf-8"))
    _ensure_schema_migrations(db)
    db.executemany(
        "INSERT OR IGNORE INTO recommendation_catalog(title, genre) VALUES (?, ?)",
        CATALOG,
    )
    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
