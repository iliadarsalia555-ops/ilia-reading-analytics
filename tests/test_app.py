import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app import create_app


class ReadingAnalyticsSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = str(Path(self.temp_dir.name) / "test.db")
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": db_path,
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def register(self, username="ilia", email="ilia@example.com", password="password123"):
        return self.client.post(
            "/register",
            data={"username": username, "email": email, "password": password},
            follow_redirects=True,
        )

    def test_registration_book_progress_analytics_and_recommendations(self):
        response = self.register()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Reading dashboard", response.data)

        # Add a Fiction book.
        response = self.client.post("/api/books", json={
            "title": "My Fiction Book",
            "genre": "Fiction",
            "total_pages": 100,
            "cover_url": "https://covers.openlibrary.org/b/id/123-M.jpg",
        })
        self.assertEqual(response.status_code, 201)
        book_id = response.get_json()["id"]
        self.assertEqual(response.get_json()["cover_url"], "https://covers.openlibrary.org/b/id/123-M.jpg")

        # Edit must persist title/genre/pages/cover changes.
        updated = self.client.put(f"/api/books/{book_id}", json={
            "title": "My Updated Fiction Book",
            "genre": "Fiction",
            "total_pages": 100,
            "cover_url": "https://covers.openlibrary.org/b/id/456-M.jpg",
        })
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["title"], "My Updated Fiction Book")
        self.assertEqual(updated.get_json()["cover_url"], "https://covers.openlibrary.org/b/id/456-M.jpg")

        # Duplicate titles for the same user must be rejected.
        duplicate = self.client.post("/api/books", json={
            "title": "my updated fiction book",
            "genre": "Fiction",
            "total_pages": 100,
        })
        self.assertEqual(duplicate.status_code, 409)

        # First session: book is in progress.
        response = self.client.post("/api/sessions", json={
            "book_id": book_id,
            "session_date": "2026-09-01",
            "duration_minutes": 60,
            "pages_read": 40,
        })
        self.assertEqual(response.status_code, 201)

        books = self.client.get("/api/books").get_json()
        self.assertEqual(books[0]["current_page"], 40)
        self.assertEqual(books[0]["status"], "reading")

        # Second session completes the book.
        response = self.client.post("/api/sessions", json={
            "book_id": book_id,
            "session_date": "2026-09-02",
            "duration_minutes": 90,
            "pages_read": 60,
        })
        self.assertEqual(response.status_code, 201)

        books = self.client.get("/api/books").get_json()
        self.assertEqual(books[0]["current_page"], 100)
        self.assertEqual(books[0]["status"], "completed")
        self.assertEqual(books[0]["completed_at"], "2026-09-02")

        # 100 pages / 2.5 hours = 40 pages/hour.
        speed = self.client.get(f"/api/analytics/speed/{book_id}").get_json()
        self.assertEqual(speed["pages_per_hour"], 40.0)

        analytics = self.client.get("/api/analytics").get_json()
        self.assertEqual(analytics["total_minutes"], 150)
        self.assertEqual(analytics["genre_distribution"][0]["genre"], "Fiction")

        recs = self.client.get("/api/recommendations").get_json()
        self.assertGreaterEqual(len(recs["recommendations"]), 1)
        self.assertTrue(all(r["genre"] == "Fiction" for r in recs["recommendations"]))
        self.assertTrue(all(r["title"].lower() != "my updated fiction book" for r in recs["recommendations"]))

    def test_book_update_and_delete_endpoints(self):
        self.register()
        created = self.client.post("/api/books", json={
            "title": "Editable Book",
            "genre": "Classic",
            "total_pages": 200,
            "cover_url": "https://example.com/one.jpg",
        }).get_json()
        book_id = created["id"]

        response = self.client.put(f"/api/books/{book_id}", json={
            "title": "Edited Book",
            "genre": "Drama",
            "total_pages": 220,
            "cover_url": "https://example.com/two.jpg",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["title"], "Edited Book")
        self.assertEqual(response.get_json()["cover_url"], "https://example.com/two.jpg")

        deleted = self.client.delete(f"/api/books/{book_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/books").get_json(), [])

    def test_invalid_cover_url_is_rejected(self):
        self.register()
        response = self.client.post("/api/books", json={
            "title": "Unsafe Cover",
            "genre": "Classic",
            "total_pages": 100,
            "cover_url": "javascript:alert(1)",
        })
        self.assertEqual(response.status_code, 400)

    def test_users_cannot_see_each_others_books(self):
        self.register("userone", "one@example.com")
        self.client.post("/api/books", json={
            "title": "Private Book",
            "genre": "Classic",
            "total_pages": 200,
        })
        self.client.post("/logout")

        self.register("usertwo", "two@example.com")
        books = self.client.get("/api/books").get_json()
        self.assertEqual(books, [])


    def test_recommendation_can_be_added_directly_to_library(self):
        self.register()
        created = self.client.post("/api/books", json={
            "title": "Preference Seed",
            "genre": "Fiction",
            "total_pages": 100,
        }).get_json()
        self.client.post("/api/sessions", json={
            "book_id": created["id"],
            "session_date": date.today().isoformat(),
            "duration_minutes": 45,
            "pages_read": 30,
        })

        recommendation = self.client.get("/api/recommendations").get_json()["recommendations"][0]
        with patch("api.lookup_book_metadata", return_value={
            "title": recommendation["title"],
            "cover_url": "https://covers.openlibrary.org/b/id/999-M.jpg",
            "total_pages": 240,
        }):
            response = self.client.post("/api/recommendations/add", json={
                "title": recommendation["title"],
                "genre": recommendation["genre"],
            })

        self.assertEqual(response.status_code, 201)
        added = response.get_json()["book"]
        self.assertEqual(added["title"], recommendation["title"])
        self.assertEqual(added["total_pages"], 240)
        self.assertEqual(added["status"], "not_started")

        titles = [b["title"] for b in self.client.get("/api/books").get_json()]
        self.assertIn(recommendation["title"], titles)

    def test_recommendation_without_page_metadata_prefills_editor(self):
        self.register()
        created = self.client.post("/api/books", json={
            "title": "Preference Seed",
            "genre": "Fiction",
            "total_pages": 100,
        }).get_json()
        self.client.post("/api/sessions", json={
            "book_id": created["id"],
            "session_date": date.today().isoformat(),
            "duration_minutes": 30,
            "pages_read": 20,
        })
        recommendation = self.client.get("/api/recommendations").get_json()["recommendations"][0]

        with patch("api.lookup_book_metadata", return_value={
            "title": recommendation["title"],
            "cover_url": "https://covers.openlibrary.org/b/id/123-M.jpg",
            "total_pages": None,
        }):
            response = self.client.post("/api/recommendations/add", json={
                "title": recommendation["title"],
                "genre": recommendation["genre"],
            })

        self.assertEqual(response.status_code, 422)
        payload = response.get_json()
        self.assertEqual(payload["code"], "pages_required")
        self.assertEqual(payload["prefill"]["title"], recommendation["title"])

    def test_analytics_contains_continuous_dynamic_series(self):
        self.register()
        response = self.client.get("/api/analytics")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["daily_trends"]), 30)
        self.assertEqual(len(data["weekly_trends"]), 12)
        self.assertEqual(len(data["monthly_trends"]), 12)
        self.assertIn("activity", data)
        self.assertIn("library_status", data)
        self.assertIn("book_speeds", data)
        self.assertIn("genre_speeds", data)
        self.assertTrue(all("minutes" in row and "pages" in row for row in data["daily_trends"]))

    def test_analytics_reports_speed_for_all_books_and_genres(self):
        self.register()

        fast = self.client.post("/api/books", json={
            "title": "Fast Mystery",
            "genre": "Mystery",
            "total_pages": 200,
        }).get_json()
        slow = self.client.post("/api/books", json={
            "title": "Slow Fiction",
            "genre": "Fiction",
            "total_pages": 200,
        }).get_json()
        no_sessions = self.client.post("/api/books", json={
            "title": "Unread Fantasy",
            "genre": "Fantasy",
            "total_pages": 300,
        }).get_json()

        today = date.today().isoformat()
        self.client.post("/api/sessions", json={
            "book_id": fast["id"],
            "session_date": today,
            "duration_minutes": 60,
            "pages_read": 80,
        })
        self.client.post("/api/sessions", json={
            "book_id": slow["id"],
            "session_date": today,
            "duration_minutes": 60,
            "pages_read": 30,
        })

        data = self.client.get("/api/analytics").get_json()
        by_title = {row["title"]: row for row in data["book_speeds"]}
        self.assertEqual(by_title["Fast Mystery"]["pages_per_hour"], 80.0)
        self.assertEqual(by_title["Slow Fiction"]["pages_per_hour"], 30.0)
        self.assertIsNone(by_title["Unread Fantasy"]["pages_per_hour"])

        self.assertEqual(data["genre_speeds"][0]["genre"], "Mystery")
        self.assertEqual(data["genre_speeds"][0]["pages_per_hour"], 80.0)

    def test_recommendations_prioritise_faster_genre(self):
        self.register()
        today = date.today().isoformat()

        mystery = self.client.post("/api/books", json={
            "title": "Mystery Seed",
            "genre": "Mystery",
            "total_pages": 150,
        }).get_json()
        fiction = self.client.post("/api/books", json={
            "title": "Fiction Seed",
            "genre": "Fiction",
            "total_pages": 150,
        }).get_json()

        # Same time in each genre, but Mystery is read much faster.
        self.client.post("/api/sessions", json={
            "book_id": mystery["id"],
            "session_date": today,
            "duration_minutes": 60,
            "pages_read": 90,
        })
        self.client.post("/api/sessions", json={
            "book_id": fiction["id"],
            "session_date": today,
            "duration_minutes": 60,
            "pages_read": 30,
        })

        payload = self.client.get("/api/recommendations").get_json()
        self.assertGreater(len(payload["genre_ranking"]), 1)
        self.assertEqual(payload["genre_ranking"][0]["genre"], "Mystery")
        self.assertGreater(
            payload["genre_ranking"][0]["score"],
            payload["genre_ranking"][1]["score"],
        )
        self.assertEqual(payload["scoring_model"]["reading_speed"], 0.70)

    def test_password_reset_flow_changes_password_and_invalidates_token(self):
        self.register(password="oldpassword123")
        self.client.post("/logout")

        with self.app.app_context():
            from auth import create_password_reset_token
            from database import get_db
            user = get_db().execute(
                "SELECT * FROM users WHERE email = ?",
                ("ilia@example.com",),
            ).fetchone()
            token = create_password_reset_token(user)

        response = self.client.get(f"/reset-password/{token}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Choose a new password", response.data)

        response = self.client.post(
            f"/reset-password/{token}",
            data={
                "password": "newpassword456",
                "confirm_password": "newpassword456",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Password updated", response.data)

        # Old token is invalid after the password hash changes.
        old_token_response = self.client.get(f"/reset-password/{token}")
        self.assertEqual(old_token_response.status_code, 400)

        # Old password no longer logs in.
        old_login = self.client.post(
            "/login",
            data={"identity": "ilia@example.com", "password": "oldpassword123"},
            follow_redirects=True,
        )
        self.assertIn(b"Incorrect username/email or password", old_login.data)

        # New password works.
        new_login = self.client.post(
            "/login",
            data={"identity": "ilia@example.com", "password": "newpassword456"},
            follow_redirects=True,
        )
        self.assertIn(b"Reading dashboard", new_login.data)

    def test_forgot_password_does_not_reveal_account_existence(self):
        self.register()
        self.client.post("/logout")

        existing = self.client.post(
            "/forgot-password",
            data={"email": "ilia@example.com"},
        )
        missing = self.client.post(
            "/forgot-password",
            data={"email": "nobody@example.com"},
        )

        expected = b"If an account exists for that email address"
        self.assertIn(expected, existing.data)
        self.assertIn(expected, missing.data)

    def test_unauthenticated_api_returns_401_json(self):
        response = self.client.get("/api/books")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "Authentication required.")


if __name__ == "__main__":
    unittest.main()
