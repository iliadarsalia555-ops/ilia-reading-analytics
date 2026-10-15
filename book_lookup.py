import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

OPEN_LIBRARY_SEARCH = "https://openlibrary.org/search.json"
USER_AGENT = "IliaReadingAnalytics/1.0 (educational school project)"

# Open Library often returns many subject labels.  The application maps those
# labels to a smaller, consistent set of genres that is easier to analyse.
# More specific categories are checked before generic "Fiction".
GENRE_RULES = [
    ("Science Fiction", (
        "science fiction", "sci-fi", "space opera", "cyberpunk",
        "dystopian", "dystopia", "time travel", "alien",
    )),
    ("Fantasy", (
        "fantasy", "magic", "magical", "wizards", "witches",
        "dragons", "epic fantasy", "fairy tales",
    )),
    ("Mystery", (
        "mystery", "detective", "crime fiction", "murder mysteries",
        "detective and mystery stories",
    )),
    ("Thriller", ("thriller", "suspense", "psychological thriller")),
    ("Horror", ("horror", "ghost stories", "supernatural fiction", "vampires")),
    ("Romance", ("romance", "love stories", "romantic fiction")),
    ("Historical Fiction", ("historical fiction", "historical novels")),
    ("Adventure", ("adventure", "adventure stories")),
    ("Young Adult", ("young adult", "teen fiction", "juvenile fiction")),
    ("Biography", ("biography", "autobiography", "memoir", "biographies")),
    ("Poetry", ("poetry", "poems")),
    ("Drama", ("drama", "plays", "theater", "theatre")),
    ("Satire", ("satire", "satirical fiction")),
    ("Classic", ("classics", "classic literature", "literary classics")),
    ("Non-fiction", (
        "nonfiction", "non-fiction", "essays", "history", "popular science",
        "self-help", "business", "psychology",
    )),
    ("Fiction", ("fiction", "novels", "literary fiction")),
]


def _normalise_subject(value):
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def infer_genres(subjects, limit=5):
    """Map Open Library subject labels to a small set of app genres."""
    cleaned = [_normalise_subject(subject) for subject in (subjects or []) if subject]
    if not cleaned:
        return []

    found = []
    for genre, keywords in GENRE_RULES:
        for subject in cleaned:
            if any(keyword in subject for keyword in keywords):
                found.append(genre)
                break
        if len(found) >= limit:
            break

    # Keep order, remove duplicates.
    unique = []
    for genre in found:
        if genre not in unique:
            unique.append(genre)
    return unique[:limit]


def _search_open_library(title, limit=6):
    title = (title or "").strip()
    if len(title) < 2:
        return []

    params = urlencode({
        "title": title,
        "limit": max(1, min(int(limit), 12)),
        "fields": (
            "key,title,author_name,first_publish_year,cover_i,"
            "number_of_pages_median,subject"
        ),
    })
    request = Request(
        f"{OPEN_LIBRARY_SEARCH}?{params}",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=6) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []

    return payload.get("docs", [])


def _doc_to_match(doc, fallback_title):
    cover_id = doc.get("cover_i")
    authors = doc.get("author_name") or []
    author = authors[0] if authors else "Unknown author"
    work_key = doc.get("key") or ""
    pages = doc.get("number_of_pages_median")
    try:
        pages = int(pages) if pages else None
    except (TypeError, ValueError):
        pages = None

    genres = infer_genres(doc.get("subject") or [])
    return {
        "title": doc.get("title") or fallback_title,
        "author": author,
        "first_publish_year": doc.get("first_publish_year"),
        "cover_url": (
            f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg?default=false"
            if cover_id else ""
        ),
        "total_pages": pages,
        "genre": genres[0] if genres else "",
        "genres": genres,
        "open_library_url": (
            f"https://openlibrary.org{work_key}"
            if work_key.startswith("/") else "https://openlibrary.org"
        ),
    }


def search_book_covers(title, limit=6):
    """
    Return likely title matches with cover, page and genre metadata.

    The name is kept for backward compatibility with the existing API route.
    """
    docs = _search_open_library(title, limit=max(limit * 2, limit))
    matches = []
    seen = set()
    for doc in docs:
        match = _doc_to_match(doc, title)
        # Cover picker should only show options that actually have a cover.
        if not match["cover_url"]:
            continue
        key = (match["cover_url"], match["title"].lower())
        if key in seen:
            continue
        seen.add(key)
        matches.append(match)
        if len(matches) >= limit:
            break
    return matches


def lookup_book_metadata(title):
    """Return the best Open Library title match for one-click additions."""
    docs = _search_open_library(title, limit=5)
    if not docs:
        return None

    normalized = (title or "").strip().casefold()
    chosen = next(
        (doc for doc in docs if str(doc.get("title", "")).strip().casefold() == normalized),
        docs[0],
    )
    return _doc_to_match(chosen, title)
