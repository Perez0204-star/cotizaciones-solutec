import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import create_user, init_db
from app.main import app
from app.services.auth import hash_password


class AuthTests(unittest.TestCase):
    def test_protected_pages_require_login_and_accept_valid_credentials(self) -> None:
        init_db()
        username = f"user_{uuid4().hex[:8]}"
        password = "Segura123!"
        create_user(username, hash_password(password))

        client = TestClient(app)

        response = client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/login", response.headers["location"])

        login_response = client.post(
            "/login",
            data={"username": username, "password": password, "next": "/"},
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 303)
        self.assertEqual(login_response.headers["location"], "/")

        dashboard_response = client.get("/")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn("Dashboard", dashboard_response.text)


if __name__ == "__main__":
    unittest.main()
