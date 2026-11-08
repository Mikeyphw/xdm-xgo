#!/usr/bin/env python3
"""HF11 regression: preserve source-bound ARM64 emulator & release safety gates."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def src(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')


class HF11Contracts(unittest.TestCase):
    def test_three_jobs_use_the_same_pinned_android_setup_action(self):
        workflow = src('.github/workflows/android.yml')
        action = 'android-actions/setup-android@be39fa834029ff78f1a44aa3bb0819b8fc2bd8fd'
        for name in ('validate', 'instrumentation', 'signed-release'):
            match = re.search(rf'(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-zA-Z][\w-]*:\n|\Z)', workflow)
            self.assertIsNotNone(match, name)
            job = match.group(1)
            self.assertEqual(job.count(action), 1, name)
            self.assertIn("packages: 'platform-tools'", job, name)

    def test_signed_release_retains_tag_signing_and_real_gate(self):
        workflow = src('.github/workflows/android.yml')
        self.assertIn("startsWith(github.ref, 'refs/tags/android-v')", workflow)
        release = workflow.split('\n  signed-release:\n', 1)
        self.assertEqual(len(release), 2)
        self.assertIn('script: bash app/XDM.Android/tools/run-hosted-emulator-instrumentation.sh --signed-release', release[1])
        wrapper = src('app/XDM.Android/tools/run-hosted-emulator-instrumentation.sh')
        self.assertIn('bash tools/run-xar16-signed-release-gate.sh --ci', wrapper)
        self.assertIn('./gradlew :app:connectedDebugAndroidTest', wrapper)

    def test_emulator_fails_closed_on_arm64_translation(self):
        workflow = src('.github/workflows/android.yml')
        wrapper = src('app/XDM.Android/tools/run-hosted-emulator-instrumentation.sh')
        self.assertIn('api-level: 36', workflow)
        self.assertIn('target: google_apis', workflow)
        self.assertIn('arch: x86_64', workflow)
        self.assertIn('ubuntu-24.04', workflow)
        self.assertIn('XDM_ARM64_TRANSLATION_UNAVAILABLE', wrapper)
        self.assertIn('arm64-v8a', wrapper)
        self.assertIn('ro.kernel.qemu', wrapper)
        self.assertIn('ro.build.version.sdk', wrapper)
        self.assertIn('XDM_HOST_KVM_UNAVAILABLE', wrapper)
        self.assertIn('run-bug-hunt-phase11-validation-matrix.sh --device-only', wrapper)

    def test_phase10_xar16_validators_recognize_real_delegation(self):
        p10 = src('app/XDM.Android/tools/validate-bug-hunt-phase10-release-upgrade-packaging.py')
        xar16 = src('app/XDM.Android/tools/validate-xar16-release-evidence-seal.py')
        self.assertIn('run-hosted-emulator-instrumentation.sh --signed-release', p10)
        self.assertIn('run-hosted-emulator-instrumentation.sh --signed-release', xar16)
        self.assertIn("'bash tools/run-xar16-signed-release-gate.sh --ci' in hosted_runner", p10)
        self.assertIn("'bash tools/run-xar16-signed-release-gate.sh --ci'", xar16)

    def test_windows_arm64_llvm_mingw_provisioning_retained(self):
        workflow = src('.github/workflows/modern-ci.yml')
        provision = src('app/XDM/eng/setup-windows-arm64-cgo.ps1')
        self.assertIn('setup-windows-arm64-cgo.ps1', workflow)
        self.assertIn('archiveSha256', provision)
        self.assertIn('GOARCH', provision)


if __name__ == '__main__':
    unittest.main(verbosity=2)
