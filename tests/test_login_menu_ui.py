"""Fluxo de login e menu no navegador com servidor Flask e banco de teste."""

import threading
import unittest

from werkzeug.serving import make_server, WSGIRequestHandler

import test_auth_menu as auth_tests
import test_history_ui as browser_tests


class QuietWSGIHandler(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


@unittest.skipIf(browser_tests.sync_playwright is None, "Playwright não instalado")
class LoginMenuUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        auth_tests.AuthMenuTests.setUpClass()
        cls.playwright = browser_tests.sync_playwright().start()
        from pathlib import Path
        if not Path(cls.playwright.chromium.executable_path).exists():
            cls.playwright.stop()
            raise unittest.SkipTest("Chromium não instalado")
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.fixture = auth_tests.AuthMenuTests('test_correct_credentials_create_http_only_session')
        self.fixture.setUp()
        self.server = make_server("127.0.0.1", 0, self.fixture.app_module.app, threaded=True, request_handler=QuietWSGIHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 960})
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.url + '/') else route.abort())

    def tearDown(self):
        self.context.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.fixture.doCleanups()

    def login(self):
        self.page.goto(self.url + '/')
        self.page.locator('#usuario').fill('equipe@example.test')
        self.page.locator('#senha').fill(self.fixture.password)
        self.page.locator('#senha').press('Enter')
        self.page.wait_for_url('**/dashboard.html')
        self.page.wait_for_function("document.querySelector('#menu-user').textContent.includes('Equipe VeriFly')")

    def test_invalid_credentials_password_toggle_and_successful_login(self):
        self.page.goto(self.url + '/')
        self.page.locator('#usuario').fill('equipe@example.test')
        self.page.locator('#senha').fill('senha-errada')
        self.page.locator('.btn-toggle-eye').click()
        self.assertEqual(self.page.locator('#senha').get_attribute('type'), 'text')
        self.page.locator('.btn-submit').click()
        self.page.locator('#login-feedback:not([hidden])').wait_for()
        self.assertIn('E-mail ou senha inválidos', self.page.locator('#login-feedback').inner_text())
        self.assertEqual(self.page.locator('#senha').input_value(), '')
        self.page.locator('#senha').fill(self.fixture.password)
        self.page.locator('.btn-submit').click()
        self.page.wait_for_url('**/dashboard.html')
        self.page.locator('#menu-user').wait_for()
        self.assertEqual(self.errors, [])

    def test_search_where_available_bell_and_logout_on_all_internal_screens(self):
        self.login()
        for screen in ('dashboard', 'history', 'new_reserve'):
            self.page.goto(self.url + f'/{screen}.html')
            search = self.page.locator('[data-menu-search]')
            if screen == 'new_reserve':
                self.assertEqual(search.count(), 0)
            else:
                search.fill('joao')
                self.page.locator('#menu-search-results [role="option"]').wait_for()
                self.assertIn('ABC123', self.page.locator('#menu-search-results').inner_text())
            self.page.locator('#menu-notifications').click()
            self.page.locator('#menu-notification-panel:not([hidden])').wait_for()
            self.assertIn('Você não tem notificações', self.page.locator('#notification-list').inner_text())
            self.page.keyboard.press('Escape')
        self.page.goto(self.url + '/history.html')
        self.page.locator('[data-menu-search]').fill('ABC123')
        self.page.locator('#menu-search-results [role="option"]').click()
        self.page.wait_for_url('**/history.html?reserve=ABC123')
        self.page.locator('[data-toggle="ABC123"][aria-expanded="true"]').wait_for()
        self.page.locator('#menu-logout').click()
        self.page.wait_for_url(self.url + '/')
        self.page.goto(self.url + '/new_reserve.html')
        self.page.locator('#login-form').wait_for()
        self.assertEqual(self.errors, [])

    def test_notification_read_state_survives_reload(self):
        self.login()
        result = self.page.evaluate("""async () => {
            const response = await window.Verifly.fetch('/api/reservas', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name:'Nova passageira', codeReserve:'NEW123', stretches:[{origin:'UDI'}]})
            });
            return response.status;
        }""")
        self.assertEqual(result, 201)
        self.page.locator('#menu-notifications').click()
        self.page.locator('.notification-unread').wait_for()
        self.assertIn('Nova passageira', self.page.locator('#notification-list').inner_text())
        self.page.locator('#notifications-read-all').click()
        self.page.wait_for_function("document.querySelectorAll('.notification-unread').length === 0")
        self.page.reload()
        self.page.locator('#menu-notifications').click()
        self.page.locator('.notification-item').wait_for()
        self.assertEqual(self.page.locator('.notification-unread').count(), 0)
        self.assertTrue(self.page.locator('#notification-count').is_hidden())
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
