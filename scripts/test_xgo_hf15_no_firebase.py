#!/usr/bin/env python3
"""Firebase removal + CI boundaries: release unchanged, test APKs downloadable."""
from __future__ import annotations
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = '4e5a736080d57bd2124364413507fb1326e0abed'
DELETED = ('docs/xgo/XGO_FIREBASE_SPARK_ARM64.md',
           'scripts/test_xgo_firebase_spark_contract.py',
           'scripts/xgo_firebase_spark_arm64.py')

def previous(rel: str) -> bytes:
    return subprocess.check_output(['git', '-C', str(ROOT), 'show', f'{PARENT}:{rel}'])

class NoFirebaseContracts(unittest.TestCase):
    def test_no_firebase_remains(self):
        for rel in DELETED:
            self.assertFalse((ROOT / rel).exists(), rel)
        wf = (ROOT / '.github/workflows/android.yml').read_text()
        for forbidden in ('firebase_spark', 'firebase-spark-arm64:', 'google-github-actions/auth@',
                          'google-github-actions/setup-gcloud@', 'gcloud firebase test'):
            self.assertNotIn(forbidden, wf)
        self.assertEqual((ROOT / '.gitignore').read_bytes(), previous('.gitignore'))

    def test_release_gate_byte_identical_to_hf14_parent(self):
        current = (ROOT / '.github/workflows/android.yml').read_text()
        before = previous('.github/workflows/android.yml').decode()
        self.assertIn('\n  signed-release:\n', current)
        self.assertEqual(current.split('\n  signed-release:\n', 1)[1].split('\n  emulator-compatibility:\n', 1)[0],
                         before.split('\n  signed-release:\n', 1)[1])
        self.assertIn('XDM_XAR16_FULL_RELEASE_GATE', current)
        self.assertIn('XDM_RELEASE_SIGNER_SHA256', current)
        self.assertIn('run-hosted-emulator-instrumentation.sh --signed-release', current)

    def test_native_instrumentation_kept_as_explicit_unresolved_gate(self):
        wf = (ROOT / '.github/workflows/android.yml').read_text()
        job = wf.split('\n  instrumentation:\n', 1)[1].split('\n  signed-release:\n', 1)[0]
        self.assertIn('run-hosted-emulator-instrumentation.sh --device', job)
        self.assertIn('xdm-hosted-instrumentation-evidence', job)
        self.assertIn('if: always()', job)

    def test_apks_are_paired_in_separate_hosted_artifact(self):
        wf = (ROOT / '.github/workflows/android.yml').read_text()
        validate = wf.split('\n  validate:\n', 1)[1].split('\n  instrumentation:\n', 1)[0]
        self.assertIn('scripts/xgo_hf16_apk_pair.py', validate)
        self.assertIn('xdm-android-physical-arm64-apk-pair', validate)
        self.assertIn('if-no-files-found: error', validate)
        self.assertIn('app-debug-androidTest.apk', validate)
        self.assertIn('app-debug.apk', validate)
        self.assertIn('xdm-android-debug-artifacts', validate)

    def test_separate_emulator_compatibility_lane_is_not_arm64_acceptance(self):
        wf = (ROOT / '.github/workflows/android.yml').read_text()
        job = wf.split('\n  emulator-compatibility:\n', 1)[1]
        self.assertIn('run-hosted-emulator-compatibility.sh', job)
        self.assertNotIn('connectedDebugAndroidTest', job)
        shell = (ROOT / 'app/XDM.Android/tools/run-hosted-emulator-compatibility.sh').read_text()
        self.assertIn('ABI_MISMATCH', shell)
        self.assertIn('NOT executed', shell)

if __name__ == '__main__':
    unittest.main(verbosity=2)
