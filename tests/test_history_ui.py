"""Integração no Chromium com API simulada e sem acesso ao banco real."""

import copy
import threading
import unittest
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from jinja2 import Environment, FileSystemLoader

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


class QuietHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/templates/") and path.endswith(".html"):
            environment = Environment(loader=FileSystemLoader(Path(self.directory) / "templates"), autoescape=True)
            html = environment.get_template(Path(path).name).render().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html)
        else:
            super().do_GET()

    def log_message(self, *args):
        pass


@unittest.skipIf(sync_playwright is None, "Playwright disponível apenas nas dependências locais")
class HistoryUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        if not Path(cls.playwright.chromium.executable_path).exists():
            cls.playwright.stop()
            raise unittest.SkipTest("Chromium não instalado")
        cls.browser = cls.playwright.chromium.launch(headless=True)
        root = str(Path(__file__).resolve().parents[1])
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=root))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page_errors = []
        self.page.on("pageerror", lambda error: self.page_errors.append(str(error)))
        self.addCleanup(self.context.close)
        now = datetime.now(timezone.utc).isoformat()
        self.reserve = {
            "id": "ABC123", "name": 'João <img src=x onerror="window.injected=1">', "codeReserve": "ABC123",
            "status": "high_priority", "historyLastAt": now, "historyLastType": "checked",
            "lastCheck": now, "stretches": [{"order": 1, "company": "azul", "origin": "UDI", "destination": "MCZ",
                                          "departureOriginal": "2027-05-23T12:55", "arrivalOriginal": "2027-05-23T15:30"}],
        }
        self.reserves = [self.reserve, {"id": "OLD123", "name": "Reserva antiga", "codeReserve": "OLD123", "status": "completed", "createdAt": "2020-01-01T12:00:00Z"}]
        before = {**copy.deepcopy(self.reserve), "segmentResults": [{"order": 1, "newDeparture": "2027-05-23T14:00"}]}
        after = {**copy.deepcopy(self.reserve), "segmentResults": [{"order": 1, "newDeparture": "2027-05-23T15:00", "status": "changed"}]}
        self.events = [{"id": "evt1", "type": "checked", "occurredAt": now, "before": before, "after": after}]
        self.fail_list = False
        self.fail_history = False
        self.page.route("**/*", self.route_request)

    def route_request(self, route):
        url = urlparse(route.request.url)
        if url.path == "/api/auth/me":
            route.fulfill(json={"user": {"name": "Equipe", "email": "equipe@example.test"}, "csrfToken": "test-csrf"})
        elif url.path == "/api/notificacoes":
            route.fulfill(json={"notifications": [], "unreadCount": 0})
        elif url.path == "/api/pesquisa":
            route.fulfill(json={"results": []})
        elif url.path == "/api/reservas":
            route.fulfill(status=503 if self.fail_list else 200, json=self.reserves)
        elif url.path.endswith("/historico"):
            cursor = parse_qs(url.query).get("cursor", [None])[0]
            offset = next((i + 1 for i, event in enumerate(self.events) if event["id"] == cursor), 0)
            page = self.events[offset:offset + 25]
            route.fulfill(status=503 if self.fail_history else 200, json={
                "reserve": self.reserve, "events": page,
                "nextCursor": page[-1]["id"] if offset + 25 < len(self.events) else None,
            })
        elif url.hostname == "127.0.0.1":
            route.continue_()
        else:
            route.abort()

    def open_page(self):
        self.page.goto(f"{self.base_url}/templates/history.html")
        self.page.locator(".booking").first.wait_for()

    def test_search_filters_timeline_and_escaped_content(self):
        self.open_page()
        self.assertEqual(self.page.locator(".booking").count(), 2)
        self.assertEqual(self.page.locator("#history-list img").count(), 0)
        self.page.locator('[data-toggle="ABC123"]').click()
        self.page.locator(".verification").wait_for()
        self.assertIn("14:00", self.page.locator(".flight-change").inner_text())
        self.assertIn("15:00", self.page.locator(".flight-change").inner_text())
        self.page.locator('[data-days="30"]').click()
        self.assertEqual(self.page.locator(".booking").count(), 1)
        self.page.locator('[data-days=""]').click()
        self.page.locator("#history-search").fill("joao")
        self.assertEqual(self.page.locator(".booking").count(), 1)
        self.page.locator("#history-search").fill("inexistente")
        self.assertIn("Nenhuma reserva", self.page.locator("#history-list").inner_text())
        self.assertIsNone(self.page.evaluate("window.injected"))
        self.assertEqual(self.page_errors, [])

    def test_automatic_refresh_preserves_expansion_and_existing_rows_on_error(self):
        self.open_page()
        self.page.locator('[data-toggle="ABC123"]').click()
        self.page.locator(".verification").wait_for()
        self.reserves.append({"id": "NEW123", "name": "Nova reserva", "status": "pending", "createdAt": self.reserve["historyLastAt"]})
        self.page.locator('[data-toggle="NEW123"]').wait_for(timeout=8000)
        self.assertEqual(self.page.locator('[data-toggle="ABC123"]').get_attribute("aria-expanded"), "true")
        self.fail_list = True
        self.page.evaluate("loadReserves()")
        self.assertEqual(self.page.locator(".booking").count(), 3)
        self.assertIn("Não foi possível", self.page.locator("#history-feedback").inner_text())
        self.assertEqual(self.page_errors, [])

    def test_pagination_and_retry(self):
        self.events = [{**self.events[0], "id": f"event-{i}"} for i in range(26)]
        self.open_page()
        self.fail_history = True
        self.page.locator('[data-toggle="ABC123"]').click()
        self.page.locator('[data-retry="ABC123"]').wait_for()
        self.fail_history = False
        self.page.locator('[data-retry="ABC123"]').click()
        self.page.locator('[data-more="ABC123"]').wait_for()
        self.assertEqual(self.page.locator(".verification").count(), 25)
        self.page.locator('[data-more="ABC123"]').click()
        self.page.wait_for_function("document.querySelectorAll('.verification').length === 26")
        self.assertEqual(self.page.locator('[data-more="ABC123"]').count(), 0)
        self.assertEqual(self.page_errors, [])


if __name__ == "__main__":
    unittest.main()
