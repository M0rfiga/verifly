"""Autenticação real contra banco simulado, controle de sessão e APIs do menu."""

import re
import time
import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash, check_password_hash

import test_local_verification as verification_tests


class AuthMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        verification_tests.LocalVerificationTests.setUpClass()
        cls.app_module = verification_tests.LocalVerificationTests.app_module
        cls.queue = verification_tests.LocalVerificationTests.queue
        cls.comparator = verification_tests.LocalVerificationTests.comparator
        from python_modules.authentication import digest
        cls.user_id = digest("equipe@example.test")
        cls.password = "Senha-forte-12345"
        cls.password_hash = generate_password_hash(cls.password)

    def setUp(self):
        self.db = verification_tests.Database()
        self.db.store["usuarios", self.user_id] = {
            "email": "equipe@example.test", "name": "Equipe VeriFly", "enabled": True,
            "passwordHash": self.password_hash, "passwordVersion": "version-1",
        }
        self.db.store["reservas", "ABC123"] = {"name": "João Carlos", "codeReserve": "ABC123", "folder": "4039", "status": "pending", "stretches": []}
        for target in (self.app_module, self.queue, self.comparator):
            patcher = patch.object(target, "db", self.db)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(self.queue.firestore, "transactional", lambda fn: fn)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.dict(self.app_module.app.config, {"TESTING": True, "TURNSTILE_SITE_KEY": "", "TURNSTILE_SECRET_KEY": "", "SESSION_COOKIE_SECURE": False})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = self.app_module.app.test_client()

    def login(self, password=None, email="equipe@example.test", client=None, next_page=None):
        client = client or self.client
        response = client.get("/")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', response.text)[1]
        payload = {"email": email, "password": password if password is not None else self.password, "csrf_token": csrf}
        if next_page is not None:
            payload["next"] = next_page
        response = client.post("/api/auth/login", json=payload)
        if response.status_code == 200:
            session = client.get("/api/auth/me").json
            client.environ_base["HTTP_X_CSRF_TOKEN"] = session["csrfToken"]
        return response

    def test_all_private_pages_and_apis_require_login(self):
        for url in ("/dashboard.html", "/history.html", "/new_reserve.html"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("next=", response.location)
        for url in ("/api/reservas", "/api/reservas/ABC123/historico", "/api/pesquisa?q=Joao", "/api/notificacoes", "/api/auth/me"):
            self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.post("/api/reservas", json={}).status_code, 401)

    def test_correct_credentials_create_http_only_session(self):
        response = self.login(email=" EQUIPE@example.test ")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["redirect"], "/dashboard.html")
        self.assertIn("HttpOnly", response.headers.getlist("Set-Cookie")[0])
        self.assertIn("SameSite=Lax", response.headers.getlist("Set-Cookie")[0])
        user = self.client.get("/api/auth/me").json["user"]
        self.assertEqual(user["name"], "Equipe VeriFly")
        self.assertNotIn("passwordHash", user)
        self.assertEqual(self.client.get("/dashboard.html").status_code, 200)
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_wrong_password_and_unknown_user_are_rejected(self):
        first = self.login(password="senha-errada")
        second = self.login(email="desconhecido@example.test")
        self.assertEqual(first.status_code, 401)
        self.assertEqual(first.json, second.json)
        self.assertEqual(self.client.get("/api/reservas").status_code, 401)

    def test_disabled_user_is_rejected(self):
        self.db.store["usuarios", self.user_id]["enabled"] = False
        self.assertEqual(self.login().status_code, 401)

    def test_login_and_writes_require_csrf(self):
        self.assertEqual(self.client.post("/api/auth/login", json={"email": "equipe@example.test", "password": self.password}).status_code, 403)
        self.login()
        self.client.environ_base.pop("HTTP_X_CSRF_TOKEN")
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 403)
        self.assertEqual(self.client.post("/api/reservas/ABC123/comparar").status_code, 403)

    def test_logout_revokes_the_cookie_even_when_replayed(self):
        from python_modules.authentication import SESSION_COOKIE
        self.login()
        token = self.client.get_cookie(SESSION_COOKIE).value
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.assertIsNone(self.client.get_cookie(SESSION_COOKIE))
        self.client.set_cookie(SESSION_COOKIE, token)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_expired_and_disabled_sessions_stop_working(self):
        from python_modules.authentication import SESSION_COOKIE, digest
        self.login()
        token = self.client.get_cookie(SESSION_COOKIE).value
        record = self.db.store["sessoes", digest(token)]
        record["expiresAt"] = time.time() - 1
        self.assertEqual(self.client.get("/api/reservas").status_code, 401)
        record["expiresAt"] = time.time() + 3600
        self.db.store["usuarios", self.user_id]["enabled"] = False
        self.assertEqual(self.client.get("/api/reservas").status_code, 401)

    def test_attempt_limit_expires(self):
        from python_modules.authentication import digest, ATTEMPT_WINDOW
        for _ in range(5):
            self.assertEqual(self.login(password="errada").status_code, 401)
        self.assertEqual(self.login().status_code, 429)
        self.db.store["tentativas_login", digest("equipe@example.test|127.0.0.1")]["windowStart"] -= ATTEMPT_WINDOW + 1
        self.assertEqual(self.login().status_code, 200)

    def test_user_creation_and_reset_use_hashes_and_revoke_old_sessions(self):
        from python_modules.authentication import create_user, digest
        created = create_user(self.db, "novo@example.test", "Novo", "Outra-senha-forte-12")
        stored = self.db.store["usuarios", created["id"]]
        self.assertNotEqual(stored["passwordHash"], "Outra-senha-forte-12")
        self.assertTrue(check_password_hash(stored["passwordHash"], "Outra-senha-forte-12"))
        with self.assertRaises(ValueError):
            create_user(self.db, "novo@example.test", "Novo", "Outra-senha-forte-12")
        with self.assertRaises(ValueError):
            create_user(self.db, "fraco@example.test", "Novo", "123")
        self.login()
        create_user(self.db, "equipe@example.test", "Equipe", "Nova-senha-forte-123", reset=True)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.login(password="Nova-senha-forte-123").status_code, 200)

    def test_redirect_only_accepts_internal_pages(self):
        self.assertEqual(self.login(next_page="https://example.test").json["redirect"], "/dashboard.html")

    def test_search_is_accent_insensitive_and_returns_only_display_fields(self):
        self.login()
        for query in ("joao", "abc123", "4039"):
            response = self.client.get("/api/pesquisa", query_string={"q": query})
            self.assertEqual(response.json["results"][0]["id"], "ABC123")
            self.assertNotIn("stretches", response.json["results"][0])
        self.assertEqual(self.client.get("/api/pesquisa?q=ausente").json["results"], [])
        self.assertEqual(self.client.get("/api/pesquisa?q=").json["results"], [])

    def test_notifications_are_created_with_history_and_read_state_is_per_user(self):
        self.login()
        data = {"name": "Maria", "codeReserve": "NEW123", "stretches": [{"origin": "UDI"}]}
        self.assertEqual(self.client.post("/api/reservas", json=data).status_code, 201)
        response = self.client.get("/api/notificacoes").json
        notification = response["notifications"][0]
        self.assertEqual(notification["title"], "Reserva cadastrada")
        self.assertEqual(response["unreadCount"], 1)
        self.assertEqual(self.client.post("/api/notificacoes/lidas", json={"ids": [notification["id"]]}).status_code, 200)
        self.assertEqual(self.client.get("/api/notificacoes").json["unreadCount"], 0)
        self.client.post("/api/auth/logout")
        self.login()
        self.assertEqual(self.client.get("/api/notificacoes").json["unreadCount"], 0)
        from python_modules.menu_services import list_notifications
        self.assertEqual(list_notifications(self.db, "outro-usuario")["unreadCount"], 1)

    def test_existing_alerts_are_visible_and_repeated_results_do_not_duplicate(self):
        self.login()
        reserve = self.db.store["reservas", "ABC123"]
        reserve.update(status="high_priority", lastCheck="2026-11-02T12:00:00")
        self.assertEqual(self.client.get("/api/notificacoes").json["unreadCount"], 1)
        from python_modules.reservation_history import append_event
        ref = self.db.collection("reservas").document("ABC123")
        after = {**reserve, "segmentResults": [{"newDeparture": "2027-05-23T15:00"}]}
        append_event(self.db, self.db.transaction(), ref, "checked", reserve, after)
        append_event(self.db, self.db.transaction(), ref, "checked", after, dict(after))
        self.assertEqual(len([key for key in self.db.store if key[0] == "notificacoes"]), 1)
        self.assertEqual(len(self.client.get("/api/notificacoes").json["notifications"]), 1)

    def test_turnstile_is_verified_on_server_when_enabled(self):
        self.app_module.app.config.update(TURNSTILE_SITE_KEY="test-site", TURNSTILE_SECRET_KEY="test-secret")
        with patch.object(self.app_module, "verify_turnstile", return_value=False) as verify:
            self.assertEqual(self.login().status_code, 400)
            verify.assert_called_once()
        with patch.object(self.app_module, "verify_turnstile", return_value=True):
            self.assertEqual(self.login().status_code, 200)


if __name__ == "__main__":
    unittest.main()
