from collections import defaultdict
from datetime import date, datetime, timedelta

from database import get_db


def total_reading_time(user_id):
    row = get_db().execute(
        "SELECT COALESCE(SUM(duration_minutes), 0) AS total FROM reading_sessions WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return row["total"]


def total_pages_read(user_id):
    row = get_db().execute(
        "SELECT COALESCE(SUM(pages_read), 0) AS total FROM reading_sessions WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return row["total"]


def average_speed_for_book(user_id, book_id):
    row = get_db().execute(
        """SELECT
               COALESCE(SUM(pages_read), 0) AS pages,
               COALESCE(SUM(duration_minutes), 0) AS minutes
           FROM reading_sessions
           WHERE user_id = ? AND book_id = ?""",
        (user_id, book_id),
    ).fetchone()

    if row["minutes"] == 0:
        return 0.0
    return round(row["pages"] / (row["minutes"] / 60), 2)


def book_speed_stats(user_id):
    """Return reading speed for every book in the user's library."""
    rows = get_db().execute(
        """SELECT
               b.id,
               b.title,
               b.genre,
               b.status,
               b.current_page,
               b.total_pages,
               COALESCE(SUM(s.pages_read), 0) AS pages_read,
               COALESCE(SUM(s.duration_minutes), 0) AS minutes,
               COUNT(s.id) AS session_count
           FROM books b
           LEFT JOIN reading_sessions s
             ON s.book_id = b.id AND s.user_id = b.user_id
           WHERE b.user_id = ?
           GROUP BY b.id
           ORDER BY
             CASE b.status
               WHEN 'reading' THEN 0
               WHEN 'completed' THEN 1
               ELSE 2
             END,
             b.title COLLATE NOCASE""",
        (user_id,),
    ).fetchall()

    results = []
    for row in rows:
        minutes = row["minutes"] or 0
        pages = row["pages_read"] or 0
        speed = round(pages / (minutes / 60), 2) if minutes > 0 else None
        results.append({
            "book_id": row["id"],
            "title": row["title"],
            "genre": row["genre"],
            "status": row["status"],
            "current_page": row["current_page"],
            "total_pages": row["total_pages"],
            "pages_read": pages,
            "minutes": minutes,
            "session_count": row["session_count"] or 0,
            "pages_per_hour": speed,
        })
    return results


def genre_speed_stats(user_id):
    """
    Return aggregate reading speed per genre.

    Aggregate pages / aggregate hours is used instead of averaging individual
    session speeds so long and short sessions are weighted naturally.
    """
    rows = get_db().execute(
        """SELECT
               b.genre,
               COALESCE(SUM(s.pages_read), 0) AS pages_read,
               COALESCE(SUM(s.duration_minutes), 0) AS minutes,
               COUNT(s.id) AS session_count,
               COUNT(DISTINCT b.id) AS book_count
           FROM books b
           JOIN reading_sessions s
             ON s.book_id = b.id AND s.user_id = b.user_id
           WHERE b.user_id = ?
           GROUP BY b.genre
           HAVING SUM(s.duration_minutes) > 0
           ORDER BY b.genre COLLATE NOCASE""",
        (user_id,),
    ).fetchall()

    results = []
    for row in rows:
        minutes = row["minutes"] or 0
        pages = row["pages_read"] or 0
        speed = round(pages / (minutes / 60), 2) if minutes > 0 else 0.0
        results.append({
            "genre": row["genre"],
            "pages_read": pages,
            "minutes": minutes,
            "session_count": row["session_count"] or 0,
            "book_count": row["book_count"] or 0,
            "pages_per_hour": speed,
        })

    return sorted(results, key=lambda item: item["pages_per_hour"], reverse=True)


def genre_distribution(user_id):
    rows = get_db().execute(
        """SELECT genre, COUNT(*) AS count
           FROM books
           WHERE user_id = ?
           GROUP BY genre
           ORDER BY count DESC, genre""",
        (user_id,),
    ).fetchall()
    return [{"genre": row["genre"], "count": row["count"]} for row in rows]


def _session_rows(user_id, start_date, end_date):
    return get_db().execute(
        """SELECT session_date, duration_minutes, pages_read
           FROM reading_sessions
           WHERE user_id = ? AND session_date BETWEEN ? AND ?
           ORDER BY session_date""",
        (user_id, start_date.isoformat(), end_date.isoformat()),
    ).fetchall()


def daily_trends(user_id, days=30):
    """Return every day in the requested window, including zero-activity days."""
    days = max(7, min(int(days), 90))
    end = date.today()
    start = end - timedelta(days=days - 1)
    totals = {
        (start + timedelta(days=i)).isoformat(): {"minutes": 0, "pages": 0}
        for i in range(days)
    }

    for row in _session_rows(user_id, start, end):
        if row["session_date"] in totals:
            totals[row["session_date"]]["minutes"] += row["duration_minutes"]
            totals[row["session_date"]]["pages"] += row["pages_read"]

    return [
        {
            "period": key,
            "label": datetime.strptime(key, "%Y-%m-%d").strftime("%b %d"),
            **totals[key],
        }
        for key in sorted(totals)
    ]


def weekly_trends(user_id, weeks=12):
    """Return complete Monday-based weeks, including weeks with no sessions."""
    weeks = max(4, min(int(weeks), 26))
    today = date.today()
    current_monday = today - timedelta(days=today.weekday())
    start_monday = current_monday - timedelta(weeks=weeks - 1)
    end = today

    totals = {}
    for i in range(weeks):
        week_start = start_monday + timedelta(weeks=i)
        totals[week_start] = {"minutes": 0, "pages": 0}

    for row in _session_rows(user_id, start_monday, end):
        d = datetime.strptime(row["session_date"], "%Y-%m-%d").date()
        week_start = d - timedelta(days=d.weekday())
        if week_start in totals:
            totals[week_start]["minutes"] += row["duration_minutes"]
            totals[week_start]["pages"] += row["pages_read"]

    return [
        {
            "period": week_start.isoformat(),
            "label": week_start.strftime("%b %d"),
            **totals[week_start],
        }
        for week_start in sorted(totals)
    ]


def _month_start(d):
    return d.replace(day=1)


def _add_months(d, delta):
    month_index = d.year * 12 + (d.month - 1) + delta
    return date(month_index // 12, month_index % 12 + 1, 1)


def monthly_trends(user_id, months=12):
    """Return complete calendar months, including months with no sessions."""
    months = max(3, min(int(months), 24))
    current_month = _month_start(date.today())
    start_month = _add_months(current_month, -(months - 1))
    end = date.today()

    totals = {}
    for i in range(months):
        month_start = _add_months(start_month, i)
        totals[month_start] = {"minutes": 0, "pages": 0}

    for row in _session_rows(user_id, start_month, end):
        d = datetime.strptime(row["session_date"], "%Y-%m-%d").date()
        month_start = d.replace(day=1)
        if month_start in totals:
            totals[month_start]["minutes"] += row["duration_minutes"]
            totals[month_start]["pages"] += row["pages_read"]

    return [
        {
            "period": month_start.strftime("%Y-%m"),
            "label": month_start.strftime("%b %Y"),
            **totals[month_start],
        }
        for month_start in sorted(totals)
    ]


def _sum_window(user_id, start, end):
    row = get_db().execute(
        """SELECT
               COALESCE(SUM(duration_minutes), 0) AS minutes,
               COALESCE(SUM(pages_read), 0) AS pages,
               COUNT(DISTINCT session_date) AS active_days
           FROM reading_sessions
           WHERE user_id = ? AND session_date BETWEEN ? AND ?""",
        (user_id, start.isoformat(), end.isoformat()),
    ).fetchone()
    return {
        "minutes": row["minutes"],
        "pages": row["pages"],
        "active_days": row["active_days"],
    }


def activity_snapshot(user_id):
    today = date.today()
    current_start = today - timedelta(days=6)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=6)
    last_30_start = today - timedelta(days=29)

    current = _sum_window(user_id, current_start, today)
    previous = _sum_window(user_id, previous_start, previous_end)
    last_30 = _sum_window(user_id, last_30_start, today)

    if previous["minutes"] > 0:
        change_percent = round(
            ((current["minutes"] - previous["minutes"]) / previous["minutes"]) * 100,
            1,
        )
    elif current["minutes"] > 0:
        change_percent = None  # New activity; no meaningful percentage baseline.
    else:
        change_percent = 0.0

    avg_active_day = (
        round(last_30["minutes"] / last_30["active_days"], 1)
        if last_30["active_days"] else 0.0
    )

    return {
        "last_7_minutes": current["minutes"],
        "previous_7_minutes": previous["minutes"],
        "last_7_pages": current["pages"],
        "change_percent": change_percent,
        "active_days_30": last_30["active_days"],
        "average_minutes_per_active_day_30": avg_active_day,
    }


def library_status(user_id):
    row = get_db().execute(
        """SELECT
               SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
               SUM(CASE WHEN status = 'reading' THEN 1 ELSE 0 END) AS reading,
               COUNT(*) AS total
           FROM books
           WHERE user_id = ?""",
        (user_id,),
    ).fetchone()
    return {
        "completed": row["completed"] or 0,
        "reading": row["reading"] or 0,
        "total": row["total"] or 0,
    }


def latest_goal(user_id):
    return get_db().execute(
        """SELECT * FROM goals
           WHERE user_id = ?
           ORDER BY id DESC
           LIMIT 1""",
        (user_id,),
    ).fetchone()


def goal_progress(user_id):
    goal = latest_goal(user_id)
    if goal is None:
        return None

    completed = get_db().execute(
        """SELECT COUNT(*) AS count
           FROM books
           WHERE user_id = ?
             AND status = 'completed'
             AND completed_at IS NOT NULL
             AND completed_at BETWEEN ? AND ?""",
        (user_id, goal["start_date"], goal["end_date"]),
    ).fetchone()["count"]

    percentage = min(round((completed / goal["target_books"]) * 100, 1), 100.0)

    start = datetime.strptime(goal["start_date"], "%Y-%m-%d").date()
    end = datetime.strptime(goal["end_date"], "%Y-%m-%d").date()
    today = date.today()

    if completed >= goal["target_books"]:
        prediction = "Goal already achieved."
        on_track = True
        projected_date = None
    elif today < start:
        prediction = "Goal period has not started yet."
        on_track = None
        projected_date = None
    elif today > end:
        prediction = "Goal deadline has passed."
        on_track = False
        projected_date = None
    else:
        elapsed_days = max((today - start).days + 1, 1)
        if completed == 0:
            prediction = "Not enough completed-book data to predict a finish date yet."
            on_track = False
            projected_date = None
        else:
            pace = completed / elapsed_days
            remaining = goal["target_books"] - completed
            days_needed = remaining / pace
            projected = today + timedelta(days=days_needed)
            projected_date = projected.isoformat()
            on_track = projected <= end
            if on_track:
                prediction = f"On track: projected completion {projected_date}."
            else:
                prediction = f"At the current pace, projected completion is {projected_date}."

    return {
        "goal_id": goal["id"],
        "target": goal["target_books"],
        "completed": completed,
        "percentage": percentage,
        "start": goal["start_date"],
        "end": goal["end_date"],
        "prediction": prediction,
        "on_track": on_track,
        "projected_date": projected_date,
    }


def analytics_summary(user_id):
    return {
        "total_minutes": total_reading_time(user_id),
        "total_pages": total_pages_read(user_id),
        "library_status": library_status(user_id),
        "activity": activity_snapshot(user_id),
        "genre_distribution": genre_distribution(user_id),
        "book_speeds": book_speed_stats(user_id),
        "genre_speeds": genre_speed_stats(user_id),
        "daily_trends": daily_trends(user_id, 30),
        "weekly_trends": weekly_trends(user_id, 12),
        "monthly_trends": monthly_trends(user_id, 12),
        "goal": goal_progress(user_id),
    }
