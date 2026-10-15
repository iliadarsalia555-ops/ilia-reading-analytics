PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL COLLATE NOCASE,
    genre TEXT NOT NULL,
    cover_url TEXT NOT NULL DEFAULT '',
    total_pages INTEGER NOT NULL CHECK(total_pages > 0),
    current_page INTEGER NOT NULL DEFAULT 0
        CHECK(current_page >= 0 AND current_page <= total_pages),
    status TEXT NOT NULL DEFAULT 'not_started'
        CHECK(status IN ('not_started', 'reading', 'completed')),
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(user_id, title)
);

CREATE TABLE IF NOT EXISTS reading_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    book_id INTEGER NOT NULL,
    session_date TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL CHECK(duration_minutes > 0),
    pages_read INTEGER NOT NULL CHECK(pages_read > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    target_books INTEGER NOT NULL CHECK(target_books > 0),
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS recommendation_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL UNIQUE COLLATE NOCASE,
    genre TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_books_user ON books(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON reading_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_book ON reading_sessions(book_id);
CREATE INDEX IF NOT EXISTS idx_sessions_date ON reading_sessions(session_date);
CREATE INDEX IF NOT EXISTS idx_goals_user ON goals(user_id);
