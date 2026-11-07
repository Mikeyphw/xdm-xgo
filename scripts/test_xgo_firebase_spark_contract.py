#!/usr/bin/env python3
"""HF14 offline source-contract tests; no Gradle, network, secrets, SDK, or devices."""
from __future__ import annotations
import importlib.util
import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
wf=(ROOT/'.github/workflows/android.yml').read_text()
spec=importlib.util.spec_from_file_location('spark',ROOT/'scripts/xgo_firebase_spark_arm64.py')
mod=importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)

class SparkTests(unittest.TestCase):
    def test_manual_only_and_free_tier_admission(self):
        self.assertIn('workflow_dispatch:',wf)
        self.assertIn('firebase_spark:',wf)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.firebase_spark",wf)
        self.assertIn('pull_request:',wf)  # Existing normal CI remains unchanged
        self.assertIn('  instrumentation:',wf)
        for item in ('confirm_spark','XGO_SPARK_NO_COST_PLAN_NOT_CONFIRMED','cancel-in-progress: false','XGO_SPARK_PROJECT_NOT_CONFIGURED'):
            self.assertIn(item,wf)
    def test_builds_true_native_app_and_instrumentation(self):
        for item in (':app:assembleDebug :app:assembleDebugAndroidTest','scripts/xgo_firebase_spark_arm64.py check-apks','sdkmanager --install','ndk;29.0.14206865'):
            self.assertIn(item,wf)
        self.assertIn('lib/arm64-v8a/libxdmcore.so', (ROOT/'scripts/xgo_firebase_spark_arm64.py').read_text())
    def test_one_single_physical_device_and_no_retry(self):
        for item in ('models describe', 'check-model','--type instrumentation','--no-auto-google-login','--num-flaky-test-attempts=0','--device "model=${XGO_SPARK_MODEL},version=${XGO_SPARK_VERSION},locale=en,orientation=portrait"'):
            self.assertIn(item,wf)
        self.assertEqual(wf.count('--device "model='),1)
        self.assertIn('2>&1 | tee',wf)
    def test_no_paid_or_unverified_green_lane(self):
        for bad in ('developer-device-platform', 'genymotion', '--async', 'continue-on-error: true','credentials_json:','skip-tests'):
            self.assertNotIn(bad,wf)
        self.assertIn('XGO_FIREBASE_SPARK_REAL_ARM64_INSTRUMENTATION_PASS',wf)
        self.assertIn('run-hosted-emulator-instrumentation.sh --device',wf)
        self.assertIn('run-xar16-signed-release-gate.sh --ci',(ROOT/'app/XDM.Android/tools/run-hosted-emulator-instrumentation.sh').read_text())
    def test_model_requires_real_physical_arm64(self):
        d={'id':'shiba','form':'PHYSICAL','supportedVersionIds':['36'],'supportedAbis':['arm64-v8a']}
        mod.check_model(d,'shiba','36')
        for mutation in ({'form':'VIRTUAL'},{'supportedAbis':['x86_64']},{'supportedVersionIds':['35']},{'accessDeniedReasons':['EULA_NOT_ACCEPTED']}):
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):mod.check_model({**d,**mutation},'shiba','36')
    def test_packaged_native_go_elf_and_test_apk(self):
        with tempfile.TemporaryDirectory() as td:
            app,tests=Path(td)/'app.apk',Path(td)/'test.apk'
            elf=bytearray(64);elf[:4]=b'\x7fELF';elf[4]=2;elf[5]=1;struct.pack_into('<H',elf,18,183)
            with zipfile.ZipFile(app,'w') as z:
                for name,data in {'AndroidManifest.xml':b'm','classes.dex':b'd','lib/arm64-v8a/libxdmcore.so':bytes(elf)}.items():z.writestr(name,data)
            with zipfile.ZipFile(tests,'w') as z:
                z.writestr('AndroidManifest.xml',b'm');z.writestr('classes.dex',b'd')
            self.assertTrue(mod.check_apks(app,tests)['arm64_native'])
            with zipfile.ZipFile(app,'w') as z:
                z.writestr('AndroidManifest.xml',b'm');z.writestr('classes.dex',b'd')
            with self.assertRaises(ValueError):mod.check_apks(app,tests)
    def test_gha_credentials_ignored(self):
        self.assertIn('gha-creds-*.json',(ROOT/'.gitignore').read_text())

if __name__=='__main__': unittest.main(verbosity=2)
