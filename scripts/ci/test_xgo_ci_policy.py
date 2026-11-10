#!/usr/bin/env python3
"""Offline adversarial qualification of XGO source-targeting and five-merge gates."""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xgo_ci_policy as policy


class TargetTests(unittest.TestCase):
    def test_document_only(self):
        plan = policy.classify(["docs/phase.md"])
        self.assertFalse(plan["needs_android_compile"])
        self.assertFalse(plan["needs_go"])
        self.assertEqual(plan["groups"], ["docs"])
        self.assertIn("scripts/ci/test_xgo_ci_policy.py", plan["tests"])

    def test_media_detector_has_real_privacy_tests(self):
        plan = policy.classify(["app/XDM.Android/browser-extension/src/main/extension/xdm-firefox/candidate-store.js"])
        self.assertIn("app/XDM.Android/browser-extension/tests/test_secure_handoff.js", plan["tests"])
        self.assertIn("app/XDM.Android/browser-extension/tests/test_mp02_discovery.js", plan["tests"])
        self.assertIn("app/XDM.Android/tools/validate-xar10-browser-capture-evidence.py", plan["tests"])
        self.assertFalse(plan["needs_android_compile"])

    def test_android_kotlin_requests_focused_compile(self):
        plan = policy.classify(["app/XDM.Android/app/src/main/kotlin/SomeFile.kt"])
        self.assertTrue(plan["needs_android_compile"])
        self.assertIn("scripts/test_xgo_mp01_hf07_emulator_contract.py", plan["tests"])

    def test_go_not_desktop_or_android(self):
        plan = policy.classify(["engine/media/graph.go"])
        self.assertTrue(plan["needs_go"])
        self.assertFalse(plan["needs_android_compile"])

    def test_workflow_changes_require_all_source_checks(self):
        plan = policy.classify([".github/workflows/android.yml"])
        self.assertTrue(plan["ci_sensitive"])
        self.assertTrue(plan["high_risk"])
        self.assertIn("app/XDM/eng/validate-xfe01-single-firefox-extension.py", plan["tests"])

    def test_unknown_file_fails_closed(self):
        plan = policy.classify(["custom/src/Mystery.kt"])
        self.assertIn("ci", plan["groups"])
        self.assertIn("extension", plan["groups"])

    def test_high_risk_and_nonrisk(self):
        self.assertTrue(policy.is_risk("app/XDM.Android/browser-extension/src/main/extension/xdm-firefox/handoff.js"))
        self.assertTrue(policy.is_risk("app/XDM.Android/app/src/main/AndroidManifest.xml"))
        self.assertTrue(policy.is_risk("engine/runtime/runtime.go"))
        self.assertFalse(policy.is_risk("app/XDM.Android/browser-extension/src/main/extension/xdm-firefox/fab.js"))
        self.assertFalse(policy.is_risk("docs/ROADMAP.md"))

    def test_mandatory_jobs_not_weakened(self):
        self.assertEqual(set(policy.WORKFLOWS), {"android.yml", "modern-ci.yml", "media-parity.yml", "devtool-xgo-engine.yml"})
        self.assertEqual(sum(map(len, policy.WORKFLOWS.values())), 13)
        self.assertIn("emulator-compatibility", policy.WORKFLOWS["android.yml"])
        self.assertIn("native-windows-arm64", policy.WORKFLOWS["modern-ci.yml"])
        self.assertIn("MP00 existing Android media JVM regressions", policy.WORKFLOWS["media-parity.yml"])

    def test_run_verification_requires_real_success(self):
        records = [{"name": name, "status": "completed", "conclusion": "success"} for name in policy.WORKFLOWS["android.yml"]]
        with patch.object(policy, "api", return_value={"jobs": records, "total_count": len(records)}):
            policy.verify_run("android.yml", {"id": 22, "status": "completed", "conclusion": "success", "head_sha": "a" * 40}, "a" * 40)
        records[-1]["conclusion"] = "skipped"
        with patch.object(policy, "api", return_value={"jobs": records, "total_count": len(records)}):
            with self.assertRaisesRegex(RuntimeError, "mandatory job failed"):
                policy.verify_run("android.yml", {"id": 22, "status": "completed", "conclusion": "success", "head_sha": "a" * 40}, "a" * 40)


class GitPlanTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="xgo-ci05-test-")
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        self.g("init", "-q", "-b", "main")
        self.g("config", "user.email", "unit@example.invalid")
        self.g("config", "user.name", "XGO CI Tests")
        self.add("README.md", "base\n")
        self.base = self.g("rev-parse", "HEAD")
        self.patcher = patch.object(policy, "INITIAL_ACCOUNTING_SHA", self.base)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def g(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True).strip()

    def add(self, path, contents):
        dest = self.repo / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(contents)
        self.g("add", "--", path)
        self.g("commit", "--quiet", "-m", "overlay")
        return self.g("rev-parse", "HEAD")

    def plan(self, interval=5, force=False):
        return policy.gate_plan(self.g("rev-parse", "HEAD"), interval, cwd=self.repo, force=force)

    def test_first_four_commits_not_due_then_fifth_due(self):
        for n in range(4):
            self.add(f"docs/{n}.txt", str(n))
        p = self.plan()
        self.assertEqual(p["integrations_since_gate"], 4)
        self.assertFalse(p["due"])
        self.assertFalse(p["gate_qualified"])
        self.add("docs/fifth.txt", "five")
        self.assertTrue(self.plan()["due"])
        self.assertIn("cadence", self.plan()["reason"])

    def test_security_and_workflow_changes_force_gate(self):
        self.add("app/XDM.Android/browser-extension/src/main/extension/xdm-firefox/handoff.js", "change")
        self.assertIn("high-risk", self.plan()["reason"])

    def test_genuine_tag_resets_unit_counter(self):
        for i in range(3):
            self.add(f"docs/{i}.txt", str(i))
        head = self.g("rev-parse", "HEAD")
        self.g("tag", "xgo-full-gate/1234", head)
        p = self.plan()
        self.assertTrue(p["gate_qualified"])
        self.assertEqual(p["integrations_since_gate"], 0)
        self.add("docs/after.txt", "next")
        self.assertEqual(self.plan()["integrations_since_gate"], 1)

    def test_side_branch_tag_does_not_reset(self):
        self.g("checkout", "-q", "-b", "side")
        side = self.add("docs/side.txt", "side")
        self.g("tag", "xgo-full-gate/7", side)
        self.g("checkout", "-q", "main")
        self.add("docs/main.txt", "main")
        self.assertEqual(self.plan()["integrations_since_gate"], 1)

    def test_force_gate_and_invalid_interval(self):
        self.assertTrue(self.plan(force=True)["due"])
        for interval in (0, -2, 26):
            with self.assertRaises(ValueError):
                self.plan(interval)

    def test_short_sha_refused(self):
        with self.assertRaises(ValueError):
            policy.paths_between("abc", "def", cwd=self.repo)

    def test_missing_baseline_refused(self):
        with patch.object(policy, "INITIAL_ACCOUNTING_SHA", "f" * 40):
            with self.assertRaises(RuntimeError):
                self.plan()


if __name__ == "__main__":
    unittest.main(verbosity=2)
