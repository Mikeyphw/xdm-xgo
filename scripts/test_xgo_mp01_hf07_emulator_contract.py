#!/usr/bin/env python3
"""MP01 HF07 fast CI gate: API36 browser Intent test and fail-closed receipt match production."""
from __future__ import annotations
import importlib.util
import pathlib
import re
import tempfile
import unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
INSTR=ROOT/'app/XDM.Android/browser-integration/src/androidTest/kotlin/com/mikeyphw/xdm/android/browser/XdmBrowserIntentFrameworkInstrumentedTest.kt'
PARSER=ROOT/'app/XDM.Android/browser-integration/src/main/kotlin/com/mikeyphw/xdm/android/browser/XdmBrowserDeepLinkParser.kt'
RECEIPT=ROOT/'app/XDM.Android/tools/verify-hosted-emulator-browser-results.py'
WORKFLOW=ROOT/'.github/workflows/android.yml'
LEGACY='v3DirectSessionRetainsBoundedCandidateContext'
CURRENT='v3PlaintextCaptureIsRejectedEvenWithCandidateContext'

def verifier():
    spec=importlib.util.spec_from_file_location('mp01_hf07_browser_verifier',RECEIPT)
    if spec is None or spec.loader is None:raise AssertionError('strict verifier could not be loaded')
    obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj)
    return obj

def make_xml(methods):
    cases=''.join(f'<testcase classname="com.mikeyphw.xdm.android.browser.XdmBrowserIntentFrameworkInstrumentedTest" name="{method}"/>' for method in methods)
    return f'<testsuite tests="{len(methods)}" failures="0" errors="0" skipped="0">{cases}</testsuite>'

class HF07EmulatorContract(unittest.TestCase):
    def test_production_parser_rejects_plaintext_v3_and_accepts_encrypted_v2(self):
        s=PARSER.read_text()
        self.assertRegex(s,r'XdmBrowserDeepLinkContract\.EncryptedCaptureVersion\s*->\s*parseEncryptedCaptureEnvelope')
        self.assertRegex(s,r'XdmBrowserDeepLinkContract\.CurrentVersion\s*->\s*XdmBrowserDeepLinkParseResult\.Rejected\(XdmBrowserDeepLinkRejection\.UnsafeEnvelope\)')
        self.assertIn('allowHeaders = false',s)
    def test_real_framework_intent_exercises_both_build_variants(self):
        t=INSTR.read_text()
        self.assertNotIn(LEGACY,t)
        self.assertEqual(t.count('@Test fun '),10)
        self.assertIn('fun '+CURRENT+'()',t)
        self.assertIn('fun v2EncryptedCaptureHasNoPlaintextUrl()',t)
        self.assertIn('Intent(Intent.ACTION_VIEW, Uri.parse(uri))',t)
        method=t.split('fun '+CURRENT+'()',1)[1].split('@Test fun ',1)[0]
        for token in ('ReleaseScheme','DebugScheme','v=3&url=',
                      'candidates=', 'finalHeaders=', 'token=secret', 'Bearer private',
                      'XdmBrowserDeepLinkRejection.UnsafeEnvelope',
                      'assertNull(XdmBrowserDeepLinkParser.parse(uri, scheme))',
                      'assertNull(XdmBrowserDeepLinkParser.parse(credentialed, scheme))'):
            self.assertIn(token,method,token)
        self.assertNotIn('hasDirectCaptureSession',method)
    def test_strict_receipt_is_updated_not_weakened(self):
        v=verifier(); self.assertEqual(len(v.EXPECTED),10)
        self.assertIn(CURRENT,v.EXPECTED);self.assertNotIn(LEGACY,v.EXPECTED)
        self.assertIn('v2EncryptedCaptureHasNoPlaintextUrl',v.EXPECTED)
        with tempfile.TemporaryDirectory(prefix='mp01-hf07-junit-') as tmp:
            d=pathlib.Path(tmp);p=d/'TEST-browser.xml'
            p.write_text(make_xml(sorted(v.EXPECTED)))
            result=v.inspect(d)
            self.assertEqual(result['test_count'],10)
            self.assertFalse(result['native_arm64_executed'])
            for missing in (CURRENT,'v2EncryptedCaptureHasNoPlaintextUrl'):
                p.write_text(make_xml(sorted(v.EXPECTED-{missing})))
                with self.assertRaisesRegex(ValueError,'MISSING_TESTS'):v.inspect(d)
            p.write_text(make_xml(sorted(v.EXPECTED-{CURRENT}|{LEGACY})))
            with self.assertRaisesRegex(ValueError,'UNEXPECTED_TEST'):v.inspect(d)
            p.write_text(make_xml(sorted(v.EXPECTED)).replace('/>', '><failure/></testcase>',1))
            with self.assertRaisesRegex(ValueError, 'TEST_FAILED'):
                v.inspect(d)
    def test_fast_lane_executes_browser_source_and_receipt_checks(self):
        y=WORKFLOW.read_text()
        fast=y.split('\n  hotfix-fast:\n',1)[1].split('\n  validate:\n',1)[0]
        self.assertIn('python3 -B scripts/test_xgo_xp02b_browser_emulator_ci.py',fast)
        self.assertIn('python3 -B scripts/test_xgo_mp01_hf07_emulator_contract.py',fast)
        self.assertNotRegex(fast,r'(?m)^\s*(?:gradle\s|\./gradlew|sdkmanager\s)')
        self.assertIn('  emulator-compatibility:',y)
        self.assertIn('  android-pr-merge-qualification:',y)
        self.assertIn("contains(github.event.pull_request.labels.*.name, 'xdm-full-ci')",y)

if __name__=='__main__':unittest.main(verbosity=2)
