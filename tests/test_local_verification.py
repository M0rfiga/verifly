"""Testes do fluxo sem credenciais, navegador ou chamadas ao Firestore real."""

import copy
import importlib
import sys
import types
import unittest
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4
import time
from pathlib import Path


class Snapshot:
    def __init__(self, ref):
        self.reference = ref
        self.id = ref.id
        self.data = copy.deepcopy(ref.store.get(ref.key))
        self.exists = self.data is not None

    def to_dict(self):
        return copy.deepcopy(self.data)


class Reference:
    def __init__(self, store, collection, doc_id):
        self.store, self.id = store, doc_id
        self.key = collection, doc_id

    def get(self, transaction=None):
        return Snapshot(self)

    def update(self, data):
        self.store[self.key].update(copy.deepcopy(data))

    def set(self, data):
        self.store[self.key] = copy.deepcopy(data)

    def delete(self):
        self.store.pop(self.key, None)

    def collection(self, name):
        return Collection(self.store, f"{self.key[0]}/{self.id}/{name}")


class Collection:
    def __init__(self, store, name):
        self.store, self.name = store, name
        self.filter = None
        self.order = None
        self.cap = None
        self.cursor = None

    def document(self, doc_id=None):
        return Reference(self.store, self.name, doc_id or uuid4().hex)

    def order_by(self, field, direction=None):
        self.order = field, direction
        return self

    def limit(self, count):
        self.cap = count
        return self

    def start_after(self, snapshot):
        self.cursor = snapshot.id
        return self

    def where(self, *, filter):
        self.filter = filter
        return self

    def stream(self):
        snapshots = []
        for collection, doc_id in list(self.store):
            if collection == self.name:
                snapshot = self.document(doc_id).get()
                if self.filter is None or snapshot.data.get(self.filter.field_path) == self.filter.value:
                    snapshots.append(snapshot)
        if self.order:
            field, direction = self.order
            snapshots.sort(key=lambda snapshot: (snapshot.data[field], snapshot.id), reverse=direction == "DESCENDING")
        if self.cursor:
            position = next(i for i, snapshot in enumerate(snapshots) if snapshot.id == self.cursor)
            snapshots = snapshots[position + 1:]
        yield from snapshots[:self.cap]


class Transaction:
    def set(self, ref, data):
        ref.store[ref.key] = copy.deepcopy(data)

    def update(self, ref, data):
        ref.update(data)


class Database:
    def __init__(self):
        self.store = {}

    def collection(self, name):
        return Collection(self.store, name)

    def transaction(self):
        return Transaction()

    def get_all(self, refs):
        return [ref.get() for ref in refs]


def authorize_client(db, client):
    from python_modules.authentication import SESSION_COOKIE, digest
    db.store["usuarios", "test-user"] = {"email": "equipe@example.test", "name": "Equipe", "enabled": True, "passwordVersion": "v1"}
    db.store["sessoes", digest("test-session")] = {
        "userId": "test-user", "csrfToken": "test-csrf", "passwordVersion": "v1", "expiresAt": time.time() + 3600,
    }
    client.set_cookie(SESSION_COOKIE, "test-session")
    client.environ_base["HTTP_X_CSRF_TOKEN"] = "test-csrf"


class LocalVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Importar o servidor também deve funcionar sem o Playwright instalado.
        firebase_stub = types.ModuleType("python_modules.firebase_db")
        firebase_stub.db = Database()
        previous_firebase = sys.modules.get("python_modules.firebase_db")
        previous_playwright = sys.modules.get("playwright")
        sys.modules["python_modules.firebase_db"] = firebase_stub
        sys.modules["playwright"] = None
        try:
            cls.queue = importlib.import_module("python_modules.verification_queue")
            cls.app_module = importlib.import_module("python_modules.web")
            cls.comparator = importlib.import_module("python_modules.comparator")
        finally:
            for name, previous in (("python_modules.firebase_db", previous_firebase), ("playwright", previous_playwright)):
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous

    def setUp(self):
        self.db = Database()
        self.db.store["reservas", "ABC123"] = {
            "name": "Teste", "status": "pending", "codeReserve": "ABC123",
            "stretches": [{"company": "azul", "origin": "UDI", "destination": "MCZ",
                           "departureOriginal": "2027-05-23T12:55", "urlReserve": "https://example.test/reserva"}],
        }
        for target in (self.queue, self.app_module, self.comparator):
            patcher = patch.object(target, "db", self.db)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(self.queue.firestore, "transactional", lambda fn: fn)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = self.app_module.app.test_client()
        authorize_client(self.db, self.client)

    def start_check(self):
        self.queue.request_check("ABC123")
        claim = self.queue.claim_next()
        return claim[1], copy.deepcopy(self.db.store["reservas", "ABC123"])

    def test_entrypoint_keeps_deployment_and_asset_paths(self):
        entrypoint = importlib.import_module("app")
        self.assertIs(entrypoint.app, self.app_module.app)
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(Path(entrypoint.app.template_folder), root / "templates")
        self.assertEqual(Path(entrypoint.app.static_folder), root / "static")
        with self.client.get("/static/css/variables.css") as response:
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/dashboard.html").status_code, 200)

    def test_api_enqueues_without_importing_or_running_playwright(self):
        with patch.dict(sys.modules, {"playwright": None, "python_modules.flight_search": None}):
            response = self.client.post("/api/reservas/ABC123/comparar")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json["verification"]["state"], "queued")
        self.assertNotIn("lastCheck", self.db.store["reservas", "ABC123"])

    def test_missing_reserve_returns_404(self):
        self.assertEqual(self.client.post("/api/reservas/missing/comparar").status_code, 404)
        self.assertNotIn(("verificacoes", "missing"), self.db.store)

    def test_duplicate_request_preserves_running_job(self):
        token, _ = self.start_check()
        self.queue.request_check("ABC123")
        self.assertEqual(self.db.store["verificacoes", "ABC123"]["token"], token)
        self.assertIsNone(self.queue.claim_next())

    def test_expired_job_reclaimed_and_old_worker_rejected(self):
        old_token, reserve = self.start_check()
        self.db.store["verificacoes", "ABC123"]["leaseUntil"] = self.queue.now() - timedelta(seconds=1)
        _, new_token = self.queue.claim_next()
        self.assertNotEqual(old_token, new_token)
        self.assertFalse(self.queue.finish_check("ABC123", old_token, reserve, {"status": "confirmed"}))
        self.assertEqual(self.db.store["reservas", "ABC123"]["status"], "pending")
        self.assertTrue(self.queue.renew_lease("ABC123", new_token))
        self.assertFalse(self.queue.renew_lease("ABC123", old_token))

    def test_result_published_and_visible_on_dashboard(self):
        token, reserve = self.start_check()
        self.queue.finish_check("ABC123", token, reserve, {"status": "confirmed", "lastCheckError": None})
        response = self.client.get("/api/reservas")
        self.assertEqual(response.json[0]["status"], "confirmed")
        self.assertEqual(response.json[0]["verification"]["state"], "done")
        self.assertNotIn("token", response.json[0]["verification"])
        self.queue.request_check("ABC123")
        self.assertEqual(self.db.store["verificacoes", "ABC123"]["state"], "queued")

    def test_manual_status_wins_over_late_result(self):
        for status in ("solved", "completed"):
            with self.subTest(status=status):
                self.db.store["reservas", "ABC123"]["status"] = "pending"
                token, reserve = self.start_check()
                self.db.store["reservas", "ABC123"]["status"] = status
                self.queue.finish_check("ABC123", token, reserve, {"status": "confirmed"})
                self.assertEqual(self.db.store["reservas", "ABC123"]["status"], status)
                self.assertEqual(self.db.store["verificacoes", "ABC123"]["state"], "skipped")

    def test_edited_stretches_trigger_new_search(self):
        token, reserve = self.start_check()
        self.db.store["reservas", "ABC123"]["stretches"][0]["departureOriginal"] = "2027-05-24T12:55"
        self.assertFalse(self.queue.finish_check("ABC123", token, reserve, {"status": "confirmed"}))
        self.assertEqual(self.db.store["verificacoes", "ABC123"]["state"], "queued")
        self.assertEqual(self.db.store["reservas", "ABC123"]["status"], "pending")

    def test_failed_search_preserves_reserve_status(self):
        token, reserve = self.start_check()
        search = types.ModuleType("python_modules.flight_search")
        search.search_flight = lambda *args: {"outbound_flight_infos": {"origin": {"date": None}}}
        with patch.dict(sys.modules, {"python_modules.flight_search": search}):
            update = self.comparator.build_comparison_update(reserve)
        self.queue.finish_check("ABC123", token, reserve, update)
        self.assertEqual(self.db.store["reservas", "ABC123"]["status"], "pending")
        self.assertEqual(self.db.store["verificacoes", "ABC123"]["state"], "failed")
        self.assertIn("não retornou", self.db.store["reservas", "ABC123"]["lastCheckError"])

    def test_local_worker_searches_and_publishes(self):
        token, _ = self.start_check()
        search = types.ModuleType("python_modules.flight_search")
        search.search_flight = lambda *args: {"outbound_flight_infos": {
            "origin": {"airport": "UDI", "date": "23/05/2027", "hour": "12:55"},
            "destiny": {"airport": "MCZ", "date": "23/05/2027", "hour": "15:30"},
        }}
        firebase_stub = types.ModuleType("python_modules.firebase_db")
        firebase_stub.db = self.db
        with patch.dict(sys.modules, {"python_modules.firebase_db": firebase_stub, "python_modules.flight_search": search}):
            from python_modules import local_worker
            local_worker.process_check("ABC123", token)
        self.assertEqual(self.db.store["reservas", "ABC123"]["status"], "confirmed")
        self.assertEqual(self.db.store["verificacoes", "ABC123"]["state"], "done")

    def test_completed_reserve_is_not_enqueued(self):
        self.db.store["reservas", "ABC123"]["status"] = "completed"
        response = self.client.post("/api/reservas/ABC123/comparar")
        self.assertEqual(response.status_code, 202)
        self.assertNotIn(("verificacoes", "ABC123"), self.db.store)

    def history_events(self):
        return self.client.get("/api/reservas/ABC123/historico").json["events"]

    def test_creation_is_listed_and_has_permanent_history(self):
        data = copy.deepcopy(self.db.store["reservas", "ABC123"])
        del self.db.store["reservas", "ABC123"]
        response = self.client.post("/api/reservas", json=data)
        self.assertEqual(response.status_code, 201)
        listing = self.client.get("/api/reservas").json
        self.assertEqual(listing[0]["historyLastType"], "created")
        event = self.history_events()[0]
        self.assertEqual(event["type"], "created")
        self.assertIsNone(event["before"])
        self.assertEqual(event["after"]["name"], data["name"])
        self.assertNotIn("urlReserve", event["after"]["stretches"][0])

    def test_recadastro_preserves_creation_date_and_old_snapshots(self):
        data = copy.deepcopy(self.db.store["reservas", "ABC123"])
        del self.db.store["reservas", "ABC123"]
        self.client.post("/api/reservas", json=data)
        created_at = self.db.store["reservas", "ABC123"]["createdAt"]
        data["name"] = "Nome atualizado"
        data["stretches"][0]["departureOriginal"] = "2027-05-24T18:00"
        data["historyLastType"] = "forged"
        self.client.post("/api/reservas", json=data)
        events = self.history_events()
        self.assertEqual([e["type"] for e in events], ["updated", "created"])
        self.assertEqual(events[0]["before"]["name"], "Teste")
        self.assertEqual(events[0]["after"]["name"], "Nome atualizado")
        self.assertEqual(events[1]["after"]["stretches"][0]["departureOriginal"], "2027-05-23T12:55")
        self.assertEqual(self.db.store["reservas", "ABC123"]["createdAt"], created_at)

    def test_repeated_checks_preserve_each_flight_result(self):
        token, reserve = self.start_check()
        first = {"status": "high_priority", "segmentResults": [{"order": 1, "newDeparture": "2027-05-23T14:00"}], "lastCheckError": None}
        self.queue.finish_check("ABC123", token, reserve, first)
        token, reserve = self.start_check()
        second = {**first, "segmentResults": [{"order": 1, "newDeparture": "2027-05-23T15:00"}]}
        self.queue.finish_check("ABC123", token, reserve, second)
        checks = [e for e in self.history_events() if e["type"] == "checked"]
        self.assertEqual(len(checks), 2)
        self.assertEqual(checks[0]["before"]["segmentResults"][0]["newDeparture"], "2027-05-23T14:00")
        self.assertEqual(checks[0]["after"]["segmentResults"][0]["newDeparture"], "2027-05-23T15:00")
        self.assertEqual(checks[1]["after"]["segmentResults"][0]["newDeparture"], "2027-05-23T14:00")

    def test_manual_action_records_before_and_after_without_duplicates(self):
        self.db.store["reservas", "ABC123"]["status"] = "high_priority"
        self.assertEqual(self.client.patch("/api/reservas/ABC123/status", json={"status": "solved"}).status_code, 200)
        self.assertEqual(self.client.patch("/api/reservas/ABC123/status", json={"status": "solved"}).status_code, 400)
        self.assertEqual(self.client.patch("/api/reservas/ABC123/status", json={"status": "completed"}).status_code, 200)
        events = self.history_events()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["before"]["status"], "solved")
        self.assertEqual(events[0]["after"]["status"], "completed")
        self.assertEqual(events[1]["before"]["status"], "high_priority")

    def test_queue_clicks_and_stale_workers_do_not_duplicate_events(self):
        token, reserve = self.start_check()
        self.queue.request_check("ABC123")
        self.assertEqual(len(self.history_events()), 1)
        self.queue.finish_check("ABC123", token, reserve, {"status": "confirmed"})
        self.queue.finish_check("ABC123", token, reserve, {"status": "high_priority"})
        self.assertEqual([e["type"] for e in self.history_events()], ["checked", "check_requested"])

    def test_failures_have_a_separate_history_event(self):
        token, reserve = self.start_check()
        self.queue.finish_check("ABC123", token, reserve, {"lastCheckError": "Companhia indisponível"})
        event = self.history_events()[0]
        self.assertEqual(event["type"], "check_failed")
        self.assertEqual(event["before"]["status"], event["after"]["status"])
        self.assertEqual(event["after"]["lastCheckError"], "Companhia indisponível")

    def test_history_pagination_and_invalid_requests(self):
        for _ in range(3):
            token, reserve = self.start_check()
            self.queue.finish_check("ABC123", token, reserve, {"status": "confirmed"})
        first = self.client.get("/api/reservas/ABC123/historico?limit=2").json
        self.assertEqual(len(first["events"]), 2)
        second = self.client.get(f'/api/reservas/ABC123/historico?limit=2&cursor={first["nextCursor"]}').json
        self.assertFalse(set(e["id"] for e in first["events"]) & set(e["id"] for e in second["events"]))
        self.assertGreater(first["events"][-1]["occurredAt"], second["events"][0]["occurredAt"])
        for query in ("limit=0", "limit=101", "limit=oops", "cursor=missing", "cursor=a/b"):
            self.assertEqual(self.client.get(f"/api/reservas/ABC123/historico?{query}").status_code, 400)
        self.assertEqual(self.client.get("/api/reservas/missing/historico").status_code, 404)

    def test_existing_reservation_has_no_invented_history(self):
        response = self.client.get("/api/reservas/ABC123/historico")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["events"], [])
        self.assertIsNone(response.json["nextCursor"])
        self.assertEqual(response.json["reserve"]["name"], "Teste")


if __name__ == "__main__":
    unittest.main()
