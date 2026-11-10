#!/usr/bin/env python3
"""XP02B source/CI contracts and fail-closed JUnit verifier regressions (no Gradle)."""
from __future__ import annotations
import importlib.util
import pathlib
import re
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEST_PATH = 'app/XDM.Android/browser-integration/src/androidTest/kotlin/com/mikeyphw/xdm/android/browser/XdmBrowserIntentFrameworkInstrumentedTest.kt'
VERIFY_PATH = 'app/XDM.Android/tools/verify-hosted-emulator-browser-results.py'


def verifier():
    spec = importlib.util.spec_from_file_location('xgo_xp02b_verify', ROOT / VERIFY_PATH)
    assert spec is not None and spec.loader is not None
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def xml(methods, *, fail='', attrs=''):
    parts = []
    for method in methods:
        value = '<failure/>' if method == fail else ''
        parts.append(f'<testcase classname="com.mikeyphw.xdm.android.browser.XdmBrowserIntentFrameworkInstrumentedTest" name="{method}">{value}</testcase>')
    return f'<testsuite tests="{len(methods)}" {attrs}>' + ''.join(parts) + '</testsuite>'


class BrowserEmulatorGateTests(unittest.TestCase):
    def test_instrumented_production_parser_cases_are_complete(self):
        obj = verifier()
        kotlin = (ROOT / TEST_PATH).read_text()
        methods = set(re.findall(r'@Test\s+fun\s+(\w+)\s*\(', kotlin))
        self.assertEqual(methods, obj.EXPECTED)
        self.assertEqual(len(methods), 10)
        self.assertIn('XdmBrowserDeepLinkParser.parseDetailed', kotlin)
        self.assertIn('Intent(Intent.ACTION_VIEW, Uri.parse(uri))', kotlin)
        self.assertIn('VariantMismatch', kotlin)
        self.assertNotIn('hasDirectCaptureSession', kotlin)
        self.assertIn('v3PlaintextCaptureIsRejectedEvenWithCandidateContext', kotlin)
        self.assertIn('XdmBrowserDeepLinkRejection.UnsafeEnvelope', kotlin)
        self.assertIn('assertNull(XdmBrowserDeepLinkParser.parse(uri, scheme))', kotlin)
        self.assertIn('assertNull(XdmBrowserDeepLinkParser.parse(credentialed, scheme))', kotlin)
        parser = (ROOT / 'app/XDM.Android/browser-integration/src/main/kotlin/com/mikeyphw/xdm/android/browser/XdmBrowserDeepLinkParser.kt').read_text()
        self.assertIn('XdmBrowserDeepLinkContract.EncryptedCaptureVersion -> parseEncryptedCaptureEnvelope', parser)
        self.assertRegex(parser, r'XdmBrowserDeepLinkContract\.CurrentVersion\s*->\s*XdmBrowserDeepLinkParseResult\.Rejected\(XdmBrowserDeepLinkRejection\.UnsafeEnvelope\)')
        self.assertNotIn('v3DirectSessionRetainsBoundedCandidateContext', kotlin)
        self.assertNotIn('v3DirectSessionRetainsBoundedCandidateContext', obj.EXPECTED)
        self.assertIn('hasEncryptedCaptureEnvelope', kotlin)

    def test_emulator_lane_is_native_free_and_original_room_lane_retained(self):
        workflow = (ROOT / '.github/workflows/android.yml').read_text()
        runner = (ROOT / 'app/XDM.Android/tools/run-hosted-emulator-persistence-tests.sh').read_text()
        gradle = (ROOT / 'app/XDM.Android/browser-integration/build.gradle.kts').read_text()
        # CI05: ordinary PRs use targeted CI; original Android/Room/emulator
        # qualification stays on manual dispatch and Android release tags.
        self.assertNotIn('  pull_request:', workflow)
        self.assertIn("  push:\n    tags: ['android-v*']", workflow)
        self.assertIn('  workflow_dispatch:', workflow)
        targeted = (ROOT / '.github/workflows/xgo-targeted.yml').read_text()
        policy = (ROOT / 'scripts/ci/xgo_ci_policy.py').read_text()
        self.assertIn('scripts/ci/xgo_ci_policy.py', targeted)
        self.assertIn('scripts/test_xgo_xp02b_browser_emulator_ci.py', policy)
        self.assertIn('python3 -B scripts/test_xgo_xp02b_browser_emulator_ci.py', workflow)
        self.assertIn('xdm-emulator-browser-intake-test-results', workflow)
        self.assertIn('xdm-emulator-persistence-test-results', workflow)
        self.assertIn('androidx.test.runner.AndroidJUnitRunner', gradle)
        self.assertIn('androidTestImplementation(libs.androidx.test.runner)', gradle)
        self.assertIn('androidTestImplementation(libs.androidx.test.ext.junit)', gradle)
        self.assertIn(':persistence:connectedDebugAndroidTest', runner)
        self.assertIn(':browser-integration:connectedDebugAndroidTest', runner)
        self.assertIn('verify-hosted-emulator-browser-results.py', runner)
        self.assertIn('verify-hosted-emulator-persistence-results.py', runner)
        self.assertNotIn(':app:connectedDebugAndroidTest', runner)
        self.assertNotIn('buildXgoNativeCore', runner)
        self.assertNotIn('libxdmcore', runner)
        self.assertNotIn('project(":app")', gradle)
        self.assertNotIn('project(":transfer-native")', gradle)
        self.assertNotIn('project(":transfer-aria2")', gradle)
        self.assertNotIn('project(":media-ffmpeg")', gradle)

    def test_accepts_only_expected_real_junit_methods(self):
        obj = verifier()
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td)
            (path / 'TEST-browser.xml').write_text(xml(sorted(obj.EXPECTED)))
            receipt = obj.inspect(path)
            self.assertEqual(receipt['test_count'], 10)
            self.assertEqual(receipt['status'], 'EMULATOR_X86_64_BROWSER_INTAKE_PASS')
            self.assertFalse(receipt['native_arm64_executed'])
            self.assertFalse(receipt['app_composition_executed'])
            self.assertEqual(len(receipt['xml_sha256']), 1)

    def test_verifier_rejects_missing_results_and_method(self):
        obj = verifier()
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td)
            with self.assertRaisesRegex(ValueError, 'JUNIT_XML_MISSING'):
                obj.inspect(path)
            (path / 'TEST-browser.xml').write_text(xml(sorted(obj.EXPECTED)[:-1]))
            with self.assertRaisesRegex(ValueError, 'MISSING_TESTS'):
                obj.inspect(path)

    def test_verifier_rejects_failures_skips_and_bad_counts(self):
        obj = verifier()
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td)
            file = path / 'TEST-browser.xml'
            methods = sorted(obj.EXPECTED)
            file.write_text(xml(methods, fail=methods[0]))
            with self.assertRaisesRegex(ValueError, 'TEST_FAILED'):
                obj.inspect(path)
            file.write_text(xml(methods, attrs='skipped="1"'))
            with self.assertRaisesRegex(ValueError, 'SUITE_SKIPPED'):
                obj.inspect(path)
            file.write_text(xml(methods).replace('tests="10"', 'tests="11"'))
            with self.assertRaisesRegex(ValueError, 'SUITE_COUNT_MISMATCH'):
                obj.inspect(path)

    def test_verifier_rejects_extra_duplicate_or_unexpected_tests(self):
        obj = verifier()
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td)
            file = path / 'TEST-browser.xml'
            methods = sorted(obj.EXPECTED)
            file.write_text(xml(methods + ['unknownMethod']))
            with self.assertRaisesRegex(ValueError, 'UNEXPECTED_TEST'):
                obj.inspect(path)
            file.write_text(xml(methods + [methods[0]]))
            with self.assertRaisesRegex(ValueError, 'DUPLICATE_TEST'):
                obj.inspect(path)
            file.write_text(xml(methods).replace('XdmBrowserIntentFrameworkInstrumentedTest', 'FakeTest'))
            with self.assertRaisesRegex(ValueError, 'UNEXPECTED_TEST'):
                obj.inspect(path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
