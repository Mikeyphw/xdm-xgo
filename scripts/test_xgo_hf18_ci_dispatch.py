#!/usr/bin/env python3
"""HF18 static CI topology regression: no Gradle, ADB, network or Github token."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / '.github/workflows/android.yml'
DEVTOOL = ROOT / '.github/workflows/devtool-xgo-engine.yml'
MODERN = ROOT / '.github/workflows/modern-ci.yml'


def event_block(source):
    return source.split('on:\n', 1)[1].split('\npermissions:\n', 1)[0]


def section(source, name, end):
    return source.split(f'\n  {name}:\n', 1)[1].split(f'\n  {end}:\n', 1)[0]


class HF18CiTopology(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.android = ANDROID.read_text()
        cls.devtool = DEVTOOL.read_text()
        cls.modern = MODERN.read_text()

    def test_pr_once_and_release_tags_not_filtered(self):
        events = event_block(self.android)
        self.assertIn("  push:\n    tags: ['android-v*']", events)
        self.assertIn('  workflow_dispatch:', events)
        self.assertNotIn('  pull_request:', events)
        self.assertNotIn('    branches: [main]', events)
        job = section(self.android, 'signed-release', 'emulator-compatibility')
        self.assertIn("if: startsWith(github.ref, 'refs/tags/android-v')", job)
        self.assertIn('XDM_XAR16_FULL_RELEASE_GATE', job)

    def test_engine_push_main_only_and_pr_retained(self):
        # The former all-in-one PR/main jobs were intentionally replaced by
        # the dedicated CI05 targeted PR/main and MP08B3 source/media lanes.
        for workflow in (self.devtool, self.modern):
            events = event_block(workflow)
            self.assertIn('  workflow_dispatch:', events)
            self.assertNotIn('  pull_request:', events)
            self.assertNotIn('  push:', events)
        targeted = (ROOT / '.github/workflows/xgo-targeted.yml').read_text()
        media = (ROOT / '.github/workflows/xgo-mp08b3-acceptance.yml').read_text()
        self.assertIn('  pull_request:', event_block(targeted))
        self.assertIn("  push:\n    branches: [main]", event_block(targeted))
        self.assertIn('XGO targeted checks passed (NOT full qualification)', targeted)
        self.assertIn('  pull_request:', event_block(media))
        self.assertIn('Source contracts and real Linux FFmpeg golden', media)
        self.assertIn('x86_64_media_test:', media)
        self.assertIn('default: false', media)

    def test_native_emulator_only_opt_in_diagnostics(self):
        job = section(self.android, 'instrumentation', 'signed-release')
        self.assertIn("if: github.event_name == 'workflow_dispatch' && inputs.arm64_translation_diagnostic", job)
        self.assertIn('script: bash app/XDM.Android/tools/run-hosted-emulator-instrumentation.sh --device', job)
        self.assertIn('xdm-hosted-instrumentation-evidence', job)
        self.assertNotIn('continue-on-error: true', job)
        self.assertIn('arm64_translation_diagnostic:\n', event_block(self.android))
        self.assertIn('default: false', event_block(self.android))

    def test_release_gate_not_weakened(self):
        job = section(self.android, 'signed-release', 'emulator-compatibility')
        self.assertIn("if: startsWith(github.ref, 'refs/tags/android-v')", job)
        for needle in ('XDM_XAR16_FULL_RELEASE_GATE', 'XDM_RELEASE_SIGNER_SHA256',
                       'XDM_RELEASE_KEYSTORE_BASE64',
                       'run-hosted-emulator-instrumentation.sh --signed-release',
                       'xdm-android-signed-release',
                       'XDM_XAR16_PREVIOUS_RELEASE_APK'):
            self.assertIn(needle, job)
        self.assertNotIn('continue-on-error: true', job)
        self.assertNotIn('|| true', job)

    def test_artifact_emulator_and_native_local_are_separate(self):
        wf = self.android
        validate = section(wf, 'validate', 'instrumentation')
        self.assertIn('xdm-android-physical-arm64-apk-pair', validate)
        self.assertIn('scripts/test_xgo_hf18_ci_dispatch.py', validate)
        self.assertIn('scripts/xgo_hf16_apk_pair.py', validate)
        self.assertIn('if-no-files-found: error', validate)
        emulator = wf.split('\n  emulator-compatibility:\n', 1)[1]
        self.assertIn('run-hosted-emulator-compatibility.sh', emulator)
        self.assertNotIn('connectedDebugAndroidTest', emulator)
        physical = (ROOT / 'scripts/run_physical_arm64_instrumentation.sh').read_text()
        self.assertIn('XGO_ADB_NATIVE_ARM64_REQUIRED', physical)
        self.assertIn('XGO_ADB_EMULATOR_REFUSED', physical)
        self.assertIn('XGO_REAL_ARM64_DEVICE_INSTRUMENTATION_PASS', physical)


if __name__ == '__main__':
    unittest.main(verbosity=2)
