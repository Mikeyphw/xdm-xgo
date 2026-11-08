#!/usr/bin/env python3
"""XP02: fail-closed source topology and report-parser regression tests."""
from __future__ import annotations
import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class EmulatorPersistenceContract(unittest.TestCase):
    def test_ci_invokes_safe_module_and_preserves_arm64_gates(self):
        w = (ROOT / '.github/workflows/android.yml').read_text()
        emulator = w.split('\n  emulator-compatibility:\n', 1)[1]
        signed = w.split('\n  signed-release:\n', 1)[1].split('\n  emulator-compatibility:\n', 1)[0]
        diagnostic = w.split('\n  instrumentation:\n', 1)[1].split('\n  signed-release:\n', 1)[0]
        compat = (ROOT / 'app/XDM.Android/tools/run-hosted-emulator-compatibility.sh').read_text()
        runner = (ROOT / 'app/XDM.Android/tools/run-hosted-emulator-persistence-tests.sh').read_text()
        library = (ROOT / 'app/XDM.Android/persistence/build.gradle.kts').read_text()
        self.assertIn('run-hosted-emulator-compatibility.sh', emulator)
        self.assertIn('gradle-version: \'9.7.1\'', emulator)
        self.assertIn('xdm-emulator-persistence-test-results', emulator)
        self.assertEqual(w.count("      - 'scripts/test_xgo_emulator_persistence_ci.py'"), 2)
        self.assertIn('XP02 emulator-persistence CI source and receipt regressions', w)
        self.assertIn('run-hosted-emulator-persistence-tests.sh', compat)
        self.assertIn(':persistence:connectedDebugAndroidTest', runner)
        self.assertIn('verify-hosted-emulator-persistence-results.py', runner)
        self.assertNotIn(':app:connectedDebugAndroidTest', runner)
        self.assertNotIn('libxdmcore.so', runner)
        self.assertNotIn('project(":app")', library)
        self.assertIn("if: github.event_name == 'workflow_dispatch' && inputs.arm64_translation_diagnostic", diagnostic)
        self.assertIn('run-hosted-emulator-instrumentation.sh --device', diagnostic)
        self.assertIn('run-hosted-emulator-instrumentation.sh --signed-release', signed)
        self.assertIn('XDM_XAR16_PREVIOUS_RELEASE_APK', signed)
        self.assertIn('xdm-android-signed-release', signed)
        self.assertIn('scripts/run_physical_arm64_instrumentation.sh', (ROOT / '.github/workflows/android.yml').read_text())
        self.assertIn('XGO_REAL_ARM64_DEVICE_INSTRUMENTATION_PASS', (ROOT / 'scripts/run_physical_arm64_instrumentation.sh').read_text())

    def test_all_seven_persistence_classes_present(self):
        source = ROOT / 'app/XDM.Android/persistence/src/androidTest/kotlin/com/mikeyphw/xdm/android/persistence'
        spec = importlib.util.spec_from_file_location('xgo_xp02_verify', ROOT / 'app/XDM.Android/tools/verify-hosted-emulator-persistence-results.py')
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(module)
        self.assertEqual(len(module.EXPECTED), 7)
        for cls in module.EXPECTED:
            self.assertTrue((source / (cls + '.kt')).is_file(), cls)

    def test_report_parser_rejects_missing_failing_skipped_unexpected_and_duplicate_cases(self):
        spec = importlib.util.spec_from_file_location('xgo_xp02_verify', ROOT / 'app/XDM.Android/tools/verify-hosted-emulator-persistence-results.py')
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(module)
        def xml(case, cls='AppDatabaseMigrationTest', extra=''):
            return f'<testsuite><testcase classname="com.mikeyphw.xdm.android.persistence.{cls}" name="{case}">{extra}</testcase></testsuite>'
        with tempfile.TemporaryDirectory() as td:
            dirpath = pathlib.Path(td)
            with self.assertRaisesRegex(ValueError, 'JUNIT_XML_MISSING'):
                module.inspect(dirpath)
            for index, cls in enumerate(sorted(module.EXPECTED)):
                (dirpath / f'TEST-{index}.xml').write_text(xml(f'test{index}', cls))
            result = module.inspect(dirpath)
            self.assertEqual(result['test_count'], 7)
            self.assertFalse(result['native_arm64_executed'])
            self.assertEqual(len(result['xml_sha256']), 7)
            original = (dirpath / 'TEST-0.xml').read_text()
            for extra, error in [('<failure/>', 'TEST_FAILED'), ('<skipped/>', 'TEST_SKIPPED')]:
                (dirpath / 'TEST-0.xml').write_text(xml('test0', sorted(module.EXPECTED)[0], extra))
                with self.assertRaisesRegex(ValueError, error):
                    module.inspect(dirpath)
            (dirpath / 'TEST-0.xml').write_text(original)
            (dirpath / 'TEST-7.xml').write_text(xml('duplicate', 'OtherTest'))
            with self.assertRaisesRegex(ValueError, 'UNEXPECTED_CLASS'):
                module.inspect(dirpath)
            (dirpath / 'TEST-7.xml').write_text(original)
            with self.assertRaisesRegex(ValueError, 'DUPLICATE_TEST'):
                module.inspect(dirpath)
            (dirpath / 'TEST-7.xml').unlink()
            (dirpath / 'TEST-0.xml').write_text(
                '<testsuite tests="2" failures="0" errors="0" skipped="0">'
                '<testcase classname="com.mikeyphw.xdm.android.persistence.'
                + sorted(module.EXPECTED)[0] + '" name="test0"/>'
                '</testsuite>'
            )
            with self.assertRaisesRegex(ValueError, 'SUITE_COUNT_MISMATCH'):
                module.inspect(dirpath)
            (dirpath / 'TEST-0.xml').write_text(original)
            (dirpath / 'TEST-0.xml').write_text(original.replace('<testsuite>', '<testsuite errors="1">'))
            with self.assertRaisesRegex(ValueError, 'SUITE_ERRORS'):
                module.inspect(dirpath)
            (dirpath / 'TEST-0.xml').write_text(original)
            (dirpath / 'TEST-0.xml').unlink()
            with self.assertRaisesRegex(ValueError, 'MISSING_CLASSES'):
                module.inspect(dirpath)

if __name__ == '__main__':
    unittest.main(verbosity=2)
