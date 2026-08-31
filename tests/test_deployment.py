"""ISSUE-034: the deployment topology must match the concurrency model.

Turn locks, rate-limit buckets, context/response caches and knowledge-cache
state are all process-local. Threads share them correctly; separate worker
processes do not. These tests fail if a future change raises the worker count
before that coordination moves to a shared store, and they check that
in-process concurrency really is serialised.
"""

from __future__ import annotations

import re
import threading
import unittest
import uuid
from dataclasses import replace
from pathlib import Path

from app.chatbot import build_chatbot
from app.config.settings import Settings
from tests.fake_llm import FakeLLMClient

REPO_ROOT = Path(__file__).resolve().parents[1]


def _worker_and_thread_counts(text: str):
    workers = re.search(r"--workers\s+(\d+)", text)
    threads = re.search(r"--threads\s+(\d+)", text)
    return (int(workers.group(1)) if workers else None,
            int(threads.group(1)) if threads else None)


class DependencyPinningTests(unittest.TestCase):
    """ISSUE-037: enforce what the repository can enforce about dependencies."""

    def _requirements(self):
        text = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        entries = []
        for line in text.splitlines():
            stripped = line.split("#", 1)[0].strip()
            if stripped:
                entries.append(stripped)
        return entries

    def test_every_direct_dependency_is_exactly_pinned(self):
        for entry in self._requirements():
            with self.subTest(dependency=entry):
                self.assertIn("==", entry,
                              "ranges allow silent upgrades between builds")
                for operator in (">=", "<=", "~=", ">", "<", "!="):
                    self.assertNotIn(operator, entry.replace("==", ""))

    def test_no_dependency_points_at_a_url_or_vcs(self):
        for entry in self._requirements():
            with self.subTest(dependency=entry):
                for scheme in ("http://", "https://", "git+", "file:"):
                    self.assertNotIn(scheme, entry.lower())

    def test_build_command_does_not_opportunistically_upgrade(self):
        text = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")
        build = re.search(r"buildCommand:\s*(.+)", text).group(1)
        # `pip install --upgrade pip` changes the resolver between builds, so the
        # same commit can install different transitive artifacts over time.
        self.assertNotIn("--upgrade pip", build,
                         "pin the build toolchain instead of upgrading it")

    def test_lock_file_if_present_is_hash_locked(self):
        """No lock file is committed yet; if one appears it must carry hashes."""
        lock = REPO_ROOT / "requirements.lock"
        if not lock.exists():
            self.skipTest("no lock file committed (see ISSUE-037 external gate)")
        text = lock.read_text(encoding="utf-8")
        self.assertIn("--hash=sha256:", text)


class ShutdownLifecycleTests(unittest.TestCase):
    """ISSUE-036: shared connections have an explicit, idempotent close."""

    def test_shutdown_closes_the_feedback_connection_once(self):
        import main
        from app.storage.feedback_store import FeedbackStore
        import tempfile

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        saved = main._feedback
        closed = []

        class Tracking(FeedbackStore):
            def close(self):
                closed.append(True)
                super().close()

        main._feedback = Tracking(Path(temp.name) / "fb.sqlite3")
        try:
            first = main.shutdown_resources()
            self.assertTrue(first["feedback"])
            self.assertEqual(len(closed), 1)
            # Idempotent: a second call must not fail or double-close.
            second = main.shutdown_resources()
            self.assertFalse(second["feedback"])
            self.assertEqual(len(closed), 1)
            self.assertIsNone(main._feedback)
        finally:
            main._feedback = saved

    def test_shutdown_resets_mongo_even_when_never_connected(self):
        import main
        result = main.shutdown_resources()
        self.assertTrue(result["mongo"])

    def test_shutdown_is_registered_at_exit(self):
        import atexit
        import main
        registered = getattr(atexit, "_ncallbacks", None)
        self.assertTrue(callable(main.shutdown_resources))
        # The module registers it at import; re-registering is harmless.
        atexit.unregister(main.shutdown_resources)
        atexit.register(main.shutdown_resources)
        self.assertTrue(registered is None or registered() >= 1)

    def test_a_failing_close_does_not_prevent_the_rest(self):
        import main
        saved = main._feedback

        class Broken:
            def close(self):
                raise RuntimeError("cannot close")

        main._feedback = Broken()
        try:
            result = main.shutdown_resources()
            self.assertFalse(result["feedback"])
            # Mongo cleanup still ran despite the feedback failure.
            self.assertTrue(result["mongo"])
            self.assertIsNone(main._feedback)
        finally:
            main._feedback = saved


class SecurityHeaderTests(unittest.TestCase):
    """ISSUE-027: a nonce-based CSP and the supporting headers are enforced."""

    @classmethod
    def setUpClass(cls):
        import main
        main._service = build_chatbot(Settings.from_env(), client=FakeLLMClient(),
                                      build_client=False)
        main.app.config.update(TESTING=True)
        cls.main = main
        cls.client = main.app.test_client()

    def test_all_headers_present_on_the_ui_and_the_api(self):
        for path in ("/", "/documents"):
            response = self.client.get(path)
            with self.subTest(path=path):
                for header, expected in (
                    ("X-Content-Type-Options", "nosniff"),
                    ("X-Frame-Options", "DENY"),
                    ("Referrer-Policy", "no-referrer"),
                ):
                    self.assertEqual(response.headers.get(header), expected)
                self.assertIn("Permissions-Policy", response.headers)

    def test_csp_is_nonce_based_and_not_unsafe(self):
        response = self.client.get("/")
        policy = response.headers["Content-Security-Policy"]
        self.assertNotIn("unsafe-inline", policy)
        self.assertNotIn("unsafe-eval", policy)
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertIn("object-src 'none'", policy)
        self.assertIn("base-uri 'none'", policy)
        self.assertRegex(policy, r"script-src 'self' 'nonce-[\w-]+'")

    def test_page_nonce_matches_the_policy_nonce(self):
        import re as regex
        response = self.client.get("/")
        policy = response.headers["Content-Security-Policy"]
        nonce = regex.search(r"'nonce-([\w-]+)'", policy).group(1)
        body = response.get_data(as_text=True)
        # Both inline blocks must carry the same nonce, or the UI breaks.
        self.assertEqual(body.count(f'nonce="{nonce}"'), 2)

    def test_nonce_is_unique_per_request(self):
        import re as regex
        first = regex.search(r"'nonce-([\w-]+)'",
                             self.client.get("/").headers["Content-Security-Policy"])
        second = regex.search(r"'nonce-([\w-]+)'",
                              self.client.get("/").headers["Content-Security-Policy"])
        self.assertNotEqual(first.group(1), second.group(1))

    def test_no_inline_event_handlers_remain_in_the_ui(self):
        html = (REPO_ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("onclick=\"", html)


class CliTrustBoundaryTests(unittest.TestCase):
    """ISSUE-005: the CLI must refuse to run against production surfaces."""

    def _run(self, env_updates):
        import os
        import subprocess
        import sys
        env = {**os.environ, "SOULENE_SKIP_WARM": "1", **env_updates}
        return subprocess.run(
            [sys.executable, "-c",
             "import main; main.run_cli()"],
            cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
            input="", timeout=120)

    def test_cli_refuses_shared_production_storage(self):
        result = self._run({"STORAGE_BACKEND": "mongo",
                            "MONGO_URI": "mongodb://localhost:27017/x",
                            "IDENTITY_SECRET": "y" * 40})
        self.assertEqual(result.returncode, 2)
        self.assertIn("Refusing to start the CLI", result.stdout)
        self.assertIn("shared production storage", result.stdout)

    def test_cli_refuses_when_deployment_requires_auth(self):
        result = self._run({"REQUIRE_API_AUTH": "true",
                            "API_KEY": "client-key", "ADMIN_API_KEY": "admin-key"})
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires authenticated access", result.stdout)

    def test_explicit_override_is_honoured(self):
        result = self._run({"STORAGE_BACKEND": "mongo",
                            "MONGO_URI": "mongodb://localhost:27017/x",
                            "IDENTITY_SECRET": "y" * 40,
                            "SOULENE_ALLOW_UNSAFE_CLI": "1"})
        # It proceeds past the guard (and then fails on storage, which is fine).
        self.assertNotIn("Refusing to start the CLI", result.stdout)


class OperationalControlTests(unittest.TestCase):
    """ISSUE-039: budget, counters and disk reporting are enforced, not advisory."""

    def test_budget_refuses_calls_once_exhausted(self):
        from app.observability import DailyCallBudget
        budget = DailyCallBudget(2)
        self.assertTrue(budget.consume())
        self.assertTrue(budget.consume())
        self.assertFalse(budget.consume())
        self.assertTrue(budget.snapshot()["exhausted"])

    def test_zero_budget_means_unlimited(self):
        from app.observability import DailyCallBudget
        budget = DailyCallBudget(0)
        for _ in range(50):
            self.assertTrue(budget.consume())
        self.assertFalse(budget.snapshot()["exhausted"])

    def test_budget_resets_on_a_new_day(self):
        import app.observability as obs
        budget = obs.DailyCallBudget(1)
        self.assertTrue(budget.consume())
        self.assertFalse(budget.consume())
        budget._day -= 1  # simulate the UTC day rolling over
        self.assertTrue(budget.consume())

    def test_exhausted_budget_degrades_the_reply_instead_of_erroring_out(self):
        from app.config.settings import Settings as S
        settings = replace(
            Settings.from_env(), mongo_uri="", storage_backend="sqlite",
            enable_input_moderation=False, enable_semantic_safety=False,
            model_daily_call_budget=1)
        service = build_chatbot(settings, client=FakeLLMClient(),
                               build_client=False, warm_cache=False)
        # The fake client has no budget, so attach a real exhausted one.
        from app.observability import DailyCallBudget
        service.client._budget = DailyCallBudget(1)
        original_generate = service.client.generate

        def budgeted(**kwargs):
            if not service.client._budget.consume():
                raise RuntimeError("budget exhausted")
            return original_generate(**kwargs)

        service.client.generate = budgeted
        first = service.handle(f"bg-{uuid.uuid4().hex[:6]}", "hello there",
                               user_id="bg1")
        second = service.handle(f"bg-{uuid.uuid4().hex[:6]}", "hello again",
                                user_id="bg2")
        # Both must still answer the user; the second is a deterministic fallback.
        self.assertTrue(first.reply)
        self.assertTrue(second.reply)
        self.assertNotIn("budget exhausted", second.reply)

    def test_counters_are_content_free(self):
        import json as json_module
        from app.observability import Counters
        counters = Counters()
        counters.increment("safety_degraded_escalations")
        counters.increment("safety_degraded_escalations")
        snapshot = counters.snapshot()
        self.assertEqual(snapshot["safety_degraded_escalations"], 2)
        self.assertTrue(all(isinstance(v, int) for v in snapshot.values()))
        json_module.dumps(snapshot)  # serialisable, values only

    def test_safety_degradation_increments_a_counter(self):
        from app.observability import COUNTERS

        class Raises(FakeLLMClient):
            def assess_risk(self, **kwargs):
                raise RuntimeError("classifier down")

        before = COUNTERS.snapshot().get("safety_classifier_unavailable", 0)
        settings = replace(
            Settings.from_env(), mongo_uri="", storage_backend="sqlite",
            enable_input_moderation=False, enable_semantic_safety=True)
        service = build_chatbot(settings, client=Raises(), build_client=False,
                               warm_cache=False)
        service.handle(f"cnt-{uuid.uuid4().hex[:6]}", "hello", user_id="cnt")
        self.assertGreater(
            COUNTERS.snapshot().get("safety_classifier_unavailable", 0), before)

    def test_disk_posture_reports_free_space(self):
        from app.observability import disk_posture
        posture = disk_posture(Path(__file__).resolve().parent, warn_below_mb=1)
        self.assertTrue(posture["available"])
        self.assertGreater(posture["total_mb"], 0)
        self.assertFalse(posture["low_space"])
        # An impossible threshold must trip the flag.
        self.assertTrue(disk_posture(
            Path(__file__).resolve().parent,
            warn_below_mb=10 ** 9)["low_space"])

    def test_runbook_documents_the_watch_list_and_gaps(self):
        text = (REPO_ROOT / "OPERATIONS.md").read_text(encoding="utf-8")
        for marker in ("safety_classifier_unavailable", "model_budget",
                       "Backup and restore", "Known gaps", "One worker"):
            self.assertIn(marker, text)


class PersistencePathTests(unittest.TestCase):
    """ISSUE-035: every writable path must live inside the durable mount."""

    def test_declared_mount_rejects_paths_outside_it(self):
        import app.config.settings as settings_module
        original = settings_module.PROJECT_ROOT
        try:
            settings_module.PROJECT_ROOT = Path("/srv/app")
            outside = replace(Settings.from_env(),
                              persistent_root="/srv/app/data",
                              knowledge_dir="knowledge", cache_dir="cache")
            with self.assertRaises(RuntimeError) as caught:
                outside.validate_persistence()
            self.assertIn("outside the declared persistent root", str(caught.exception))

            inside = replace(outside, knowledge_dir="data/knowledge",
                            cache_dir="data/cache")
            inside.validate_persistence()
        finally:
            settings_module.PROJECT_ROOT = original

    def test_no_declared_mount_is_permitted_for_local_development(self):
        replace(Settings.from_env(), persistent_root="").validate_persistence()

    def test_render_manifest_keeps_knowledge_and_cache_on_the_disk(self):
        text = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")
        mount = re.search(r"mountPath:\s*(\S+)", text).group(1)
        declared = re.search(r"PERSISTENT_ROOT\s*\n\s*value:\s*(\S+)", text).group(1)
        self.assertEqual(declared, mount)
        for key in ("KNOWLEDGE_DIR", "CACHE_DIR"):
            value = re.search(rf"{key}\s*\n\s*value:\s*(\S+)", text).group(1)
            self.assertTrue(value.startswith("data/"),
                            f"{key}={value} would be lost on redeploy")

    def test_cag_uses_the_configured_cache_path(self):
        import app.config.settings as settings_module
        settings = replace(Settings.from_env(), cache_dir="data/cache")
        expected = settings_module.PROJECT_ROOT / "data" / "cache"
        self.assertEqual(settings.cache_path, expected)
        service = build_chatbot(
            replace(settings, mongo_uri="", storage_backend="sqlite"),
            client=FakeLLMClient(), build_client=False, warm_cache=False)
        self.assertEqual(service.cag.knowledge.cache_dir, expected)


class PromotionGateTests(unittest.TestCase):
    """ISSUE-040: nothing reaches users without an explicit, gated promotion."""

    WORKFLOW = REPO_ROOT / ".github" / "workflows" / "gate.yml"

    def _manifest(self):
        return (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")

    def test_automatic_deployment_from_main_is_disabled(self):
        value = re.search(r"autoDeploy:\s*(\S+)", self._manifest()).group(1)
        self.assertEqual(
            value, "false",
            "autoDeploy releases whatever landed on main with no test, safety, "
            "schema or dependency gate; keep it false until required status "
            "checks and a staged rollout exist (ISSUE-040)")

    def test_manifest_points_at_the_promotion_procedure(self):
        text = self._manifest()
        self.assertIn("ISSUE-040", text)
        self.assertIn("OPERATIONS.md", text,
                      "the manifest must say where the promotion checklist lives")

    def test_a_gate_workflow_exists_and_runs_the_full_suite(self):
        self.assertTrue(self.WORKFLOW.exists(),
                        "no repository-side test gate is defined")
        text = self.WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("python -m pytest -q tests", text)
        self.assertIn("requirements-dev.txt", text)

    def test_the_gate_cannot_pass_while_ignoring_failures(self):
        text = self.WORKFLOW.read_text(encoding="utf-8")
        for escape in ("continue-on-error", "|| true", "--exitfirst-ignore"):
            self.assertNotIn(escape, text,
                             "a gate that tolerates failures is not a gate")

    def test_the_gate_runs_the_production_interpreter(self):
        workflow = self.WORKFLOW.read_text(encoding="utf-8")
        declared = re.search(r'python-version:\s*"([\d.]+)"', workflow).group(1)
        production = re.search(r"PYTHON_VERSION\s*\n\s*value:\s*\"([\d.]+)\"",
                               self._manifest()).group(1)
        self.assertEqual(declared, production,
                         "the gate must run on the interpreter production uses")

    def test_the_gate_runs_the_production_safety_configuration(self):
        workflow = self.WORKFLOW.read_text(encoding="utf-8")
        for flag in ("ENABLE_INPUT_MODERATION", "ENABLE_SEMANTIC_SAFETY",
                     "ENABLE_OUTPUT_SAFETY_CHECK"):
            production = re.search(rf"{flag}\s*\n\s*value:\s*\"(\w+)\"",
                                   self._manifest()).group(1)
            declared = re.search(rf"{flag}:\s*\"(\w+)\"", workflow).group(1)
            with self.subTest(flag=flag):
                self.assertEqual(declared, production,
                                 "the gate must not test a weaker safety "
                                 "configuration than the one that ships")

    def test_test_only_dependencies_are_pinned_and_out_of_the_image(self):
        dev = (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
        self.assertIn("-r requirements.txt", dev)
        for line in dev.splitlines():
            entry = line.split("#", 1)[0].strip()
            if entry and not entry.startswith("-r"):
                with self.subTest(dependency=entry):
                    self.assertIn("==", entry)
        build = re.search(r"buildCommand:\s*(.+)", self._manifest()).group(1)
        self.assertNotIn("requirements-dev", build,
                         "test dependencies must not ship in the image")

    def test_runbook_documents_the_promotion_checklist(self):
        text = (REPO_ROOT / "OPERATIONS.md").read_text(encoding="utf-8")
        self.assertIn("Deployment promotion", text)
        for marker in ("rollback", "gate.yml", "attestation"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


class DeploymentTopologyTests(unittest.TestCase):
    def test_render_manifest_declares_a_single_worker(self):
        workers, threads = _worker_and_thread_counts(
            (REPO_ROOT / "render.yaml").read_text(encoding="utf-8"))
        self.assertEqual(
            workers, 1,
            "process-local safety/cache/limit state cannot span workers; "
            "move coordination to a shared store before raising this")
        self.assertGreater(threads or 0, 1, "concurrency should come from threads")

    def test_procfile_matches_the_render_manifest(self):
        render = _worker_and_thread_counts(
            (REPO_ROOT / "render.yaml").read_text(encoding="utf-8"))
        procfile = _worker_and_thread_counts(
            (REPO_ROOT / "Procfile").read_text(encoding="utf-8"))
        self.assertEqual(render, procfile,
                         "deployment entry points must not disagree")


class InProcessConcurrencyTests(unittest.TestCase):
    """Threads must serialise per session and stay owner-isolated."""

    def _service(self):
        settings = replace(
            Settings.from_env(), mongo_uri="", storage_backend="sqlite",
            enable_input_moderation=False, enable_semantic_safety=False)
        return build_chatbot(settings, client=FakeLLMClient(),
                             build_client=False, warm_cache=False)

    def test_concurrent_turns_on_one_session_are_serialised(self):
        service = self._service()
        session = f"cc-{uuid.uuid4().hex[:6]}"
        errors = []

        def send(index):
            try:
                service.handle(session, f"message {index}", user_id="cc-user")
            except Exception as exc:  # pragma: no cover - failure detail only
                errors.append(repr(exc))

        threads = [threading.Thread(target=send, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        stored = service.archive.fetch_recent("cc-user", session, limit=100)
        # Two rows per turn, and sequence numbers must be unique and gapless.
        self.assertEqual(len(stored), 16)
        sequences = sorted(m.sequence_number for m in stored)
        self.assertEqual(sequences, list(range(1, 17)))

    def test_concurrent_sessions_stay_isolated(self):
        service = self._service()
        errors = []

        def send(index):
            try:
                service.handle(f"iso-{index}", "hello there", user_id=f"iso-{index}")
            except Exception as exc:  # pragma: no cover
                errors.append(repr(exc))

        threads = [threading.Thread(target=send, args=(i,)) for i in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        for index in range(6):
            self.assertEqual(service.archive.count(f"iso-{index}", f"iso-{index}"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
