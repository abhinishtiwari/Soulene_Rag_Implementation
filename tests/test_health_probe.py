"""ISSUE-038: liveness vs readiness separation.

A platform probe must never be the thing that builds the application. These
tests pin three properties:

1. `/live` answers from process state alone - no service construction, no
   backend contact, no configuration that can fail.
2. `/health` is readiness: it reports what explicit initialization already
   achieved, and never triggers initialization itself.
3. Readiness is bounded - a hung storage backend cannot hang the probe - and
   its body carries coarse dependency states without exception detail.
"""

from __future__ import annotations

import time
import unittest
from contextlib import contextmanager

from app.config.settings import Settings
from app.security import ApiAuth
from tests.fake_llm import FakeLLMClient


def _import_main():
    import main
    main.app.config.update(TESTING=True)
    return main


def _build_service(main):
    from app.chatbot import build_chatbot
    return build_chatbot(Settings.from_env(), client=FakeLLMClient(),
                         build_client=False)


class ProbeIsolationTests(unittest.TestCase):
    """Probes must be observers, not initializers."""

    def setUp(self):
        self.main = _import_main()
        self.client = self.main.app.test_client()
        self._service = self.main._service
        self._started = self.main._PROCESS_STARTED_AT
        self._init_state = dict(self.main._INIT_STATE)
        self._auth = self.main._auth

    def tearDown(self):
        self.main._service = self._service
        self.main._PROCESS_STARTED_AT = self._started
        self.main._INIT_STATE.clear()
        self.main._INIT_STATE.update(self._init_state)
        self.main._auth = self._auth

    @contextmanager
    def _spy_get_service(self):
        calls = []
        original = self.main.get_service

        def spy():
            calls.append(1)
            return original()

        self.main.get_service = spy
        try:
            yield calls
        finally:
            self.main.get_service = original

    def _reset_uninitialized(self):
        self.main._service = None
        self.main._INIT_STATE.update(attempts=0, failures=0, last_failure_at=0.0)

    # --- liveness ---------------------------------------------------------
    def test_live_endpoint_exists(self):
        r = self.client.get("/live")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["status"], "alive")
        self.assertIn("uptime_seconds", body)

    def test_live_never_constructs_the_service(self):
        self._reset_uninitialized()
        with self._spy_get_service() as calls:
            r = self.client.get("/live")
        self.assertEqual(r.status_code, 200,
                         "liveness must answer even before initialization")
        self.assertEqual(calls, [], "liveness must not construct the service")
        self.assertIsNone(self.main._service)

    def test_live_stays_up_when_storage_is_broken(self):
        service = _build_service(self.main)
        self.main._service = service

        def explode():
            raise RuntimeError("backend down")

        original = service.archive.healthcheck
        service.archive.healthcheck = explode
        try:
            self.assertEqual(self.client.get("/live").status_code, 200)
        finally:
            service.archive.healthcheck = original

    def test_live_is_open_when_auth_enabled(self):
        self.main._auth = ApiAuth("k")
        self.assertEqual(self.client.get("/live").status_code, 200)

    # --- readiness --------------------------------------------------------
    def test_readiness_never_constructs_the_service(self):
        self._reset_uninitialized()
        with self._spy_get_service() as calls:
            r = self.client.get("/health")
        self.assertEqual(calls, [],
                         "readiness probe must not trigger service construction")
        self.assertIsNone(self.main._service,
                          "a probe must not leave a constructed service behind")
        self.assertEqual(r.status_code, 503)

    def test_readiness_reports_initializing_inside_grace(self):
        self._reset_uninitialized()
        self.main._PROCESS_STARTED_AT = time.time()
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.get_json()["status"], "initializing")

    def test_readiness_reports_unavailable_past_startup_deadline(self):
        self._reset_uninitialized()
        self.main._PROCESS_STARTED_AT = time.time() - 100000
        body = self.client.get("/health").get_json()
        self.assertEqual(body["status"], "unavailable")
        self.assertEqual(body["reason"], "startup_deadline_exceeded")

    def test_readiness_reports_failed_initialization_immediately(self):
        self._reset_uninitialized()
        self.main._PROCESS_STARTED_AT = time.time()
        self.main._INIT_STATE.update(attempts=1, failures=1,
                                     last_failure_at=time.time())
        body = self.client.get("/health").get_json()
        self.assertEqual(body["status"], "unavailable")
        self.assertEqual(body["reason"], "initialization_failed")

    def test_readiness_ok_reports_dependency_states(self):
        self.main._service = _build_service(self.main)
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["dependencies"]["storage"], "ok")
        self.assertEqual(body["dependencies"]["service"], "ok")

    def test_readiness_hides_exception_detail_on_failure(self):
        service = _build_service(self.main)
        self.main._service = service

        def explode():
            raise RuntimeError("mongo://user:pw@host refused")

        service.archive.healthcheck = explode
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 503)
        raw = r.get_data(as_text=True)
        self.assertNotIn("mongo://", raw)
        self.assertNotIn("RuntimeError", raw)
        body = r.get_json()
        self.assertEqual(body["status"], "unavailable")
        self.assertEqual(body["dependencies"]["storage"], "failed")

    def test_readiness_is_bounded_when_storage_hangs(self):
        service = _build_service(self.main)
        self.main._service = service
        budget = self.main._settings.readiness_probe_timeout_seconds

        def hang():
            time.sleep(budget + 30)

        service.archive.healthcheck = hang
        t0 = time.time()
        r = self.client.get("/health")
        elapsed = time.time() - t0
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.get_json()["dependencies"]["storage"], "timeout")
        self.assertLess(elapsed, budget + 5,
                        "readiness must not block on a hung backend")


class ExplicitInitializationTests(unittest.TestCase):
    """Startup owns initialization; failures are recorded, not swallowed."""

    def setUp(self):
        self.main = _import_main()
        self._service = self.main._service
        self._init_state = dict(self.main._INIT_STATE)

    def tearDown(self):
        self.main._service = self._service
        self.main._INIT_STATE.clear()
        self.main._INIT_STATE.update(self._init_state)

    def test_initialize_service_reports_failure_without_raising(self):
        self.main._service = None
        self.main._INIT_STATE.update(attempts=0, failures=0, last_failure_at=0.0)
        original = self.main.build_chatbot

        def explode(*args, **kwargs):
            raise RuntimeError("no backend")

        self.main.build_chatbot = explode
        try:
            self.assertFalse(self.main.initialize_service())
        finally:
            self.main.build_chatbot = original
        self.assertEqual(self.main._INIT_STATE["failures"], 1)
        self.assertGreater(self.main._INIT_STATE["last_failure_at"], 0)

    def test_successful_initialization_is_recorded(self):
        self.main._service = _build_service(self.main)
        self.main._INIT_STATE.update(attempts=0, failures=0, last_failure_at=0.0)
        self.assertTrue(self.main.initialize_service())
        self.assertEqual(self.main._INIT_STATE["failures"], 0)


class ProbeConfigurationTests(unittest.TestCase):
    """The deployment manifest must point the platform at readiness."""

    def test_render_manifest_documents_both_probes(self):
        from pathlib import Path
        manifest = (Path(__file__).resolve().parents[1] / "render.yaml").read_text(
            encoding="utf-8")
        self.assertIn("healthCheckPath: /health", manifest)
        self.assertIn("/live", manifest,
                      "the manifest must document the liveness path")
        self.assertIn("READINESS_STARTUP_GRACE_SECONDS", manifest)

    def test_probe_paths_bypass_identity_and_rate_limiting(self):
        main = _import_main()
        self.assertIn("/live", main._PROBE_PATHS)
        self.assertIn("/health", main._PROBE_PATHS)
        self.assertTrue(main._PROBE_PATHS <= main._OPEN_PATHS)


if __name__ == "__main__":
    unittest.main()
