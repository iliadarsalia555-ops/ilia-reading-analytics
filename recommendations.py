from database import get_db


def selection_sort_desc(items):
    """
    Manual descending selection sort.
    Each item is a dict with a numeric 'score' key.
    """
    ranked = items[:]
    for i in range(len(ranked)):
        largest = i
        for j in range(i + 1, len(ranked)):
            if ranked[j]["score"] > ranked[largest]["score"]:
                largest = j
        if largest != i:
            ranked[i], ranked[largest] = ranked[largest], ranked[i]
    return ranked


def generate_recommendations(user_id, limit=3):
    db = get_db()

    # Reading behaviour by genre.  Speed is calculated as total pages divided
    # by total hours, which avoids giving a short session the same weight as a
    # long session.
    behaviour_rows = db.execute(
        """SELECT
               b.genre,
               COALESCE(SUM(s.duration_minutes), 0) AS minutes,
               COALESCE(SUM(s.pages_read), 0) AS pages,
               COUNT(s.id) AS sessions
           FROM reading_sessions s
           JOIN books b ON b.id = s.book_id
           WHERE s.user_id = ?
           GROUP BY b.genre
           HAVING SUM(s.duration_minutes) > 0""",
        (user_id,),
    ).fetchall()

    if not behaviour_rows:
        return {
            "message": "Log reading sessions to generate personalised recommendations.",
            "recommendations": [],
            "genre_ranking": [],
        }

    total_minutes = sum(row["minutes"] for row in behaviour_rows) or 1

    completed_rows = db.execute(
        """SELECT genre, COUNT(*) AS completed
           FROM books
           WHERE user_id = ? AND status = 'completed'
           GROUP BY genre""",
        (user_id,),
    ).fetchall()
    completed_by_genre = {row["genre"]: row["completed"] for row in completed_rows}
    total_completed = sum(completed_by_genre.values())

    raw_stats = []
    for row in behaviour_rows:
        minutes = row["minutes"] or 0
        pages = row["pages"] or 0
        speed = pages / (minutes / 60) if minutes > 0 else 0.0
        raw_stats.append({
            "genre": row["genre"],
            "minutes": minutes,
            "pages": pages,
            "sessions": row["sessions"] or 0,
            "speed_pages_per_hour": speed,
        })

    max_speed = max((item["speed_pages_per_hour"] for item in raw_stats), default=1) or 1

    # Recommendation model:
    #   70% reading speed by genre
    #   20% share of reading time
    #   10% share of completed books
    #
    # Speed has the strongest influence, matching the intended behaviour:
    # genres the user reads more fluently are recommended most strongly.
    scored = []
    for item in raw_stats:
        speed_score = item["speed_pages_per_hour"] / max_speed
        time_share = item["minutes"] / total_minutes
        completion_share = (
            completed_by_genre.get(item["genre"], 0) / total_completed
            if total_completed > 0 else 0
        )

        score = round(
            (0.70 * speed_score)
            + (0.20 * time_share)
            + (0.10 * completion_share),
            4,
        )
        scored.append({
            **item,
            "speed_pages_per_hour": round(item["speed_pages_per_hour"], 2),
            "speed_score": round(speed_score, 4),
            "time_share": round(time_share, 4),
            "completion_share": round(completion_share, 4),
            "completed": completed_by_genre.get(item["genre"], 0),
            "score": score,
        })

    ranked = selection_sort_desc(scored)

    owned_rows = db.execute(
        "SELECT LOWER(TRIM(title)) AS title FROM books WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    owned = {row["title"] for row in owned_rows}

    recommendations = []
    for genre_info in ranked:
        candidates = db.execute(
            """SELECT title, genre
               FROM recommendation_catalog
               WHERE genre = ?
               ORDER BY title""",
            (genre_info["genre"],),
        ).fetchall()

        for candidate in candidates:
            if candidate["title"].strip().lower() in owned:
                continue

            speed = genre_info["speed_pages_per_hour"]
            recommendations.append({
                "title": candidate["title"],
                "genre": candidate["genre"],
                "score": genre_info["score"],
                "speed_pages_per_hour": speed,
                "minutes_in_genre": genre_info["minutes"],
                "reason": (
                    f"You read {genre_info['genre']} at about {speed:g} pages/hour. "
                    "Reading speed has the highest weight in your recommendation score."
                ),
            })
            if len(recommendations) >= limit:
                break

        if len(recommendations) >= limit:
            break

    return {
        "message": (
            "Recommendations are ranked mainly by the genres you read fastest."
            if recommendations
            else "No unread catalog titles were available for your strongest genres."
        ),
        "recommendations": recommendations,
        "genre_ranking": ranked,
        "scoring_model": {
            "reading_speed": 0.70,
            "reading_time": 0.20,
            "completed_books": 0.10,
        },
    }
