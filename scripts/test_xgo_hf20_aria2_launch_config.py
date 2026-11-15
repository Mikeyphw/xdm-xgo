#!/usr/bin/env python3
"""HF20: source-level launch-config lifecycle/CI/release safeguards.

This is intentionally a fast static contract, not a substitute for the
instrumented regression on actual ARM64 Android hardware.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "app/XDM.Android/transfer-aria2/src/main/kotlin/com/mikeyphw/xdm/android/transfer/aria2/Aria2SessionStore.kt"
MANAGER = ROOT / "app/XDM.Android/transfer-aria2/src/main/kotlin/com/mikeyphw/xdm/android/transfer/aria2/Aria2ProcessManager.kt"
DEVICE = ROOT / "app/XDM.Android/app/src/androidTest/kotlin/com/mikeyphw/xdm/android/Aria2Rm08PackagedRuntimeInstrumentedTest.kt"
WORKFLOW = ROOT / ".github/workflows/android.yml"
SIGNED_RELEASE_SHA256 = "07f28376b630f5acf9bd6a1b1db873926e0e6e8bd7e2c98883ee37cbeb2836ed"  # Shared HF19 verified seal

class HF20Aria2LaunchConfig(unittest.TestCase):
    def test_prepare_does_not_delete_an_inflight_rpc_secret(self):
        s=STORE.read_text()
        match=re.search(r'override fun prepare\(\) \{(.*?)\n    \}\n\n    override fun cleanupTransientLaunchConfigurations',s,re.S)
        self.assertIsNotNone(match)
        self.assertNotIn('cleanupTransientLaunchConfigurations()',match.group(1))
        self.assertIn('sessionFile.restrictToOwner()',match.group(1))
        self.assertIn('rotateRuntimeLog()',match.group(1))
        self.assertIn('override fun cleanupTransientLaunchConfigurations(): Int',s)
        self.assertIn('it.name.startsWith("launch-")',s)
        self.assertIn('it.extension == "conf"',s)
        self.assertIn('override fun deleteLaunchConfiguration(file: File): Boolean',s)

    def test_explicit_cleanup_precedes_secret_generation_and_repair_keeps_it(self):
        m=MANAGER.read_text()
        start=m.split('suspend fun start(): Aria2StartResult',1)[1].split('suspend fun repair():',1)[0]
        self.assertEqual(start.count('sessionStore.cleanupTransientLaunchConfigurations()'),1)
        self.assertLess(start.index('sessionStore.cleanupTransientLaunchConfigurations()'),start.index('prepareLaunch(report)'))
        repair=m.split('suspend fun repair():',1)[1].split('suspend fun stop():',1)[0]
        self.assertIn('sessionStore.cleanupTransientLaunchConfigurations()',repair)
        self.assertIn('val configurationRemoved = sessionStore.deleteLaunchConfiguration(prepared.configuration)',start)
        self.assertIn('secureAbort(process, prepared.configuration)',start)

    def test_instrumented_regression_asserts_live_and_stale_semantics(self):
        d=DEVICE.read_text()
        name='fun launchConfigurationSurvivesRoutinePreparationUntilExplicitCleanup()'
        self.assertEqual(d.count(name),1)
        body=d.split(name,1)[1].split('\n    @Test',1)[0]
        for text in ('store.writeLaunchConfiguration(', 'store.logFile()', 'store.prepare()',
                     'configuration.isFile', 'store.cleanupTransientLaunchConfigurations()',
                     'assertFalse(configuration.exists())', 'finally {'):
            self.assertIn(text,body)
        self.assertLess(body.index('store.writeLaunchConfiguration('),body.index('store.logFile()'))
        self.assertLess(body.index('store.logFile()'),body.index('store.cleanupTransientLaunchConfigurations()'))
        self.assertIn('fun packagedRuntimeEnforcesTlsAndRecoversSavedOwnedSession()',d)

    def test_workflow_keeps_real_native_payload_tests_and_no_duplicate_pr(self):
        w=WORKFLOW.read_text(encoding='utf-8')
        events=w.split('on:\n',1)[1].split('\npermissions:\n',1)[0]
        self.assertIn('run: python3 -B scripts/test_xgo_hf20_aria2_launch_config.py',w)
        self.assertIn('run: python3 -B scripts/test_xgo_hf19_arm64_runtime_gate.py',w)
        self.assertIn('Verify pinned FFmpeg and FFprobe in the debug APK',w)
        self.assertIn('xdm-android-physical-arm64-apk-pair',w)
        # HF18/HF19 already established: expensive Android CI is tag-only or
        # manually dispatched. The targeted PR/main lanes are separate.
        self.assertIn("  push:\n    tags: ['android-v*']",events)
        self.assertIn('  workflow_dispatch:',events)
        self.assertNotIn('  pull_request:',events)
        self.assertNotIn('branches: [main]',events)
        self.assertIn("if: github.event_name == 'workflow_dispatch' && inputs.arm64_translation_diagnostic",w)

    def test_signed_release_gate_is_byte_for_byte_sealed(self):
        # HF20 must agree with the independently pinned HF19 release baseline,
        # plus HF07's immutable workflow Git blob and semantic protections.
        from test_xgo_hf19_arm64_runtime_gate import SIGNED_RELEASE_SHA256 as HF19_RELEASE_SHA256
        from test_xgo_xpi_v161_parity import (PINNED_ANDROID_WORKFLOW_BLOB,
            git_blob_sha, signed_release_policy_violations)
        raw=WORKFLOW.read_bytes()
        w=raw.decode('utf-8')
        block=w.split('\n  signed-release:\n',1)[1].split('\n  emulator-compatibility:\n',1)[0]
        self.assertEqual(SIGNED_RELEASE_SHA256,HF19_RELEASE_SHA256)
        self.assertEqual(hashlib.sha256(block.encode('utf-8')).hexdigest(),SIGNED_RELEASE_SHA256)
        self.assertEqual(git_blob_sha(raw),PINNED_ANDROID_WORKFLOW_BLOB)
        self.assertEqual(signed_release_policy_violations(w),[])
        self.assertIn('XDM_XAR16_FULL_RELEASE_GATE',block)
        self.assertIn('run-hosted-emulator-instrumentation.sh --signed-release',block)

    def test_release_policy_negative_mutations_rejected(self):
        from test_xgo_xpi_v161_parity import signed_release_policy_violations, release_block
        w=WORKFLOW.read_text(encoding='utf-8')
        self.assertEqual(signed_release_policy_violations(w),[])
        signed=release_block(w)
        for old,new in (
            ("startsWith(github.ref, 'refs/tags/android-v')", "startsWith(github.ref, 'refs/heads/main')"),
            ('&& inputs.signed_release))', '&& true))'),
            ('XDM_XAR16_FULL_RELEASE_GATE: "1"', 'XDM_XAR16_FULL_RELEASE_GATE: "0"'),
            ('name: xdm-android-signed-release', 'name: xdm-android-test-release'),
        ):
            with self.subTest(marker=old):
                self.assertEqual(signed.count(old),1,old)
                mutated=w.replace(signed,signed.replace(old,new,1),1)
                self.assertTrue(signed_release_policy_violations(mutated),old)
        trigger,sep,tail=w.partition('\npermissions:\n')
        self.assertTrue(sep)
        mutated=trigger.replace("tags: ['android-v*']", "branches: ['*']",1)+sep+tail
        self.assertTrue(signed_release_policy_violations(mutated),'tag trigger must fail closed')
        mutated=w.replace('  signed-release:\n','  signed-release:\n    continue-on-error: true\n',1)
        self.assertTrue(signed_release_policy_violations(mutated),'fail-open must be refused')

if __name__ == '__main__':
    unittest.main(verbosity=2)
