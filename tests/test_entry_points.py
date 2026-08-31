"""ISSUE-033: one manifest accounts for every test/diagnostic entry point.

These tests fail if a root-level script appears without being classified, if the
CI gate and the manifest disagree about which lanes gate a release, if a lane
declared hermetic can still write the working repository, or if a historical
report stops declaring itself stale.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from tests.lanes import (AUTHORITATIVE_COMMAND, HISTORICAL_REPORTS, LANES,
                         REPO_ROOT, STALENESS_MARKER, discovered_root_entries,
                         root_scripts_excluded_from_collection)

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "gate.yml"


def _run(args, env_updates=None, timeout=300):
    env = {**os.environ, **(env_updates or {})}
    return subprocess.run([sys.executable, *args], cwd=str(REPO_ROOT), env=env,
                          capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")


class ManifestCompletenessTests(unittest.TestCase):
    def test_every_root_entry_point_is_classified(self):
        classified = {lane.entry for lane in LANES}
        for name in discovered_root_entries():
            with self.subTest(entry=name):
                self.assertIn(name, classified,
                              f"{name} looks like an entry point but is not in "
                              "tests/lanes.py; classify it or rename it")

    def test_every_declared_entry_exists(self):
        for lane in LANES:
            with self.subTest(lane=lane.name):
                self.assertTrue((REPO_ROOT / lane.entry).exists(),
                                f"{lane.entry} is declared but missing")

    def test_every_lane_states_why_it_is_or_is_not_a_gate(self):
        for lane in LANES:
            with self.subTest(lane=lane.name):
                self.assertTrue(lane.note.strip(), "a lane without a reason is "
                                                   "a lane nobody can act on")
                self.assertIn(lane.kind, {"suite", "diagnostic", "operator"})

    def test_exactly_one_authoritative_suite_lane_gates(self):
        gating = [lane for lane in LANES if lane.in_gate]
        self.assertEqual([lane.name for lane in gating], ["suite"])
        self.assertEqual(gating[0].command, AUTHORITATIVE_COMMAND)


class GateAgreementTests(unittest.TestCase):
    """The CI workflow and the manifest must not drift apart."""

    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_gate_runs_every_lane_marked_in_gate(self):
        for lane in LANES:
            if lane.in_gate:
                with self.subTest(lane=lane.name):
                    self.assertIn(lane.command, self.workflow)

    def test_gate_runs_nothing_marked_out_of_gate(self):
        for lane in LANES:
            if not lane.in_gate:
                with self.subTest(lane=lane.name):
                    self.assertNotIn(lane.command, self.workflow)

    def test_non_hermetic_lanes_are_never_in_the_gate(self):
        for lane in LANES:
            if not lane.hermetic:
                with self.subTest(lane=lane.name):
                    self.assertFalse(lane.in_gate,
                                     "a lane that can write outside a temporary "
                                     "tree must not run in CI")


class CollectionSafetyTests(unittest.TestCase):
    """`pytest .` must not execute a root script at import time."""

    def test_root_conftest_ignores_the_declared_scripts(self):
        import conftest as root_conftest

        self.assertEqual(sorted(root_conftest.collect_ignore),
                         sorted(root_scripts_excluded_from_collection()))
        self.assertIn("test_all.py", root_conftest.collect_ignore)

    def test_collecting_the_whole_repository_succeeds(self):
        result = _run(["-m", "pytest", "--collect-only", "-q", "."])
        self.assertNotIn("INTERNALERROR", result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout[-2000:])
        collected = re.search(r"(\d+) tests collected", result.stdout)
        self.assertIsNotNone(collected, result.stdout[-2000:])
        self.assertGreater(int(collected.group(1)), 400)

    def test_pytest_ini_still_scopes_the_default_run(self):
        text = (REPO_ROOT / "pytest.ini").read_text(encoding="utf-8")
        self.assertIn("testpaths = tests", text)


class DiagnosticLaneBehaviourTests(unittest.TestCase):
    """A lane declared hermetic must actually be hermetic."""

    def _repo_data_state(self):
        data = REPO_ROOT / "data"
        return {p.name: p.stat().st_mtime_ns
                for p in sorted(data.glob("*")) if p.is_file()}

    def _assert_hermetic(self, args):
        before = self._repo_data_state()
        result = _run(args)
        self.assertEqual(before, self._repo_data_state(),
                         f"{args} mutated the working repository's data/")
        return result

    # Running the full diagnostics costs ~15s of subprocess startup, so they
    # are opt-in: skipped by default to keep the everyday run fast, and turned
    # on in CI (gate.yml sets SOULENE_RUN_DIAGNOSTIC_LANES=1) so the hermeticity
    # proof still executes before a release. The cheap refusal/manifest checks
    # below always run.
    _RUN_DIAGNOSTICS = os.getenv(
        "SOULENE_RUN_DIAGNOSTIC_LANES", "").lower() in {"1", "true", "yes"}
    _SKIP_REASON = ("set SOULENE_RUN_DIAGNOSTIC_LANES=1 to run the full "
                    "diagnostic lanes (slow: spawns subprocesses)")

    @unittest.skipUnless(_RUN_DIAGNOSTICS, _SKIP_REASON)
    def test_safety_diagnostic_passes_without_touching_the_repository(self):
        result = self._assert_hermetic(["test_all.py"])
        self.assertEqual(result.returncode, 0, result.stdout[-2000:])
        self.assertIn("0 failed", result.stdout)

    @unittest.skipUnless(_RUN_DIAGNOSTICS, _SKIP_REASON)
    def test_pipeline_diagnostic_passes_without_touching_the_repository(self):
        result = self._assert_hermetic(["test_audit.py"])
        self.assertEqual(result.returncode, 0, result.stdout[-2000:])
        self.assertIn("0 FAIL", result.stdout)

    def test_live_audit_refuses_to_run_without_an_explicit_opt_in(self):
        results = REPO_ROOT / "context_audit_results.json"
        before = results.stat().st_mtime_ns if results.exists() else None
        result = _run(["context_audit.py"], {"SOULENE_ALLOW_LIVE_AUDIT": ""})
        after = results.stat().st_mtime_ns if results.exists() else None
        self.assertEqual(before, after,
                         "the refused run must not write a results file")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Refusing to run the live context audit", result.stdout)
        # The guard must run before any traffic is possible.
        self.assertNotIn("Traceback", result.stderr)

    def test_live_smoke_lanes_refuse_without_an_explicit_opt_in(self):
        for module in ("tests.smoke_live", "tests.smoke_staging"):
            with self.subTest(lane=module):
                before = self._repo_data_state()
                result = _run(["-m", module], {"SOULENE_ALLOW_LIVE_SMOKE": ""})
                self.assertEqual(result.returncode, 2, result.stdout[-1000:])
                self.assertIn("Refusing to run", result.stdout)
                self.assertEqual(before, self._repo_data_state(),
                                 "a refused live lane must not write data/")

    def test_uncollected_lanes_cannot_be_picked_up_by_pytest(self):
        from tests.lanes import uncollected_lanes

        for lane in uncollected_lanes():
            name = Path(lane.entry).name
            with self.subTest(lane=lane.name):
                if lane.entry.startswith("tests/"):
                    # Inside the discovered directory, only the filename keeps
                    # pytest away, so that must stay true.
                    self.assertFalse(name.startswith("test_"),
                                     f"{lane.entry} would be collected and "
                                     "executed by the default suite")
                else:
                    self.assertIn(name, root_scripts_excluded_from_collection())


class HistoricalReportTests(unittest.TestCase):
    def test_historical_reports_declare_themselves_stale(self):
        """Historical reports are untracked local artifacts, so absence is fine.

        Presence is not: a report sitting in the tree without a staleness header
        is exactly what gets quoted as current evidence.
        """
        for name in HISTORICAL_REPORTS:
            path = REPO_ROOT / name
            with self.subTest(report=name):
                if not path.exists():
                    continue
                head = path.read_text(encoding="utf-8")[:1200]
                self.assertIn(STALENESS_MARKER, head)
                self.assertIn(AUTHORITATIVE_COMMAND, head,
                              "a stale report must point at the current command")

    def test_developer_guide_documents_the_lanes(self):
        text = (REPO_ROOT / "DEVELOPER_GUIDE.md").read_text(encoding="utf-8")
        self.assertIn(AUTHORITATIVE_COMMAND, text)
        self.assertIn("tests/lanes.py", text)
        for lane in LANES:
            with self.subTest(lane=lane.name):
                self.assertIn(lane.entry, text)


if __name__ == "__main__":
    unittest.main()
