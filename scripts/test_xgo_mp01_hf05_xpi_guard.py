#!/usr/bin/env python3
"""MP01 HF05: active canonical XPI attestation with immutable XP01 provenance.

Runs without Android SDK, Gradle, Node, network, or GitHub credentials.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'app/XDM.Android/browser-extension/src/main/extension/xdm-firefox'
REF=ROOT/'docs/xgo/XGO_XPI_V161_REFERENCE_DIGESTS.json'
DESKTOP=ROOT/'app/XDM/eng/validate-xfe01-single-firefox-extension.py'
XAR10=ROOT/'app/XDM.Android/tools/validate-xar10-browser-capture-evidence.py'
WORKFLOW=ROOT/'.github/workflows/android.yml'
OLD={
 'handoff.js':'19dd11fba950c20725b6860ed5def908f4e38da7fb179cb458ad70ca066572a2',
 'network-observer.js':'7988d45e1810f750adbe2f5443143cbe0f43ec9d826a4b2b16a6f67611224274',
 'generated-config.js':'e7c0adc1cf7e6e33e3f6ca6ed72008d83ea1b79923e98fed63681a1c7a02ccff',
}

def digest(data:bytes)->str:return hashlib.sha256(data).hexdigest()

class CanonicalXpiGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref=json.loads(REF.read_text(encoding='utf-8'))
    def test_user_snapshot_is_preserved_not_reclassified_as_new_xpi(self):
        self.assertEqual(self.ref['referenceSnapshotBeforeMp01Sha256'],OLD)
        self.assertEqual(self.ref['schema'],1)
        self.assertEqual(self.ref['referenceGeneratedConfigVersion'],'1.6.0')
        self.assertEqual(self.ref['referenceManifestVersion'],'1.6.1')
        self.assertIn('MP01 encrypted browser capture v2',self.ref['activeCanonicalContract'])
        self.assertNotEqual(self.ref['adoptedAssetSha256']['handoff.js'],OLD['handoff.js'])
    def test_active_xpi_and_desktop_shared_source_are_byte_attested(self):
        xfe=DESKTOP.read_text(encoding='utf-8')
        mapping=dict(re.findall(r'^\s+"([^"]+)": "([0-9a-f]{64})",?$',xfe,re.M))
        self.assertEqual(len(mapping),16,'XFE01 must attest all sixteen assets')
        for name,expected in self.ref['adoptedAssetSha256'].items():
            with self.subTest(name=name):
                self.assertEqual(digest((SRC/name).read_bytes()),expected,'current canonical digest')
                self.assertEqual(mapping[name],expected,'desktop consumed a different digest')
        for name,expected in self.ref['unchangedAssetSha256'].items():
            with self.subTest(name=name):
                self.assertEqual(digest((SRC/name).read_bytes()),expected)
                self.assertEqual(mapping[name],expected)
        self.assertIn('|| action == "capture"',xfe)
        self.assertIn('Encrypted browser captures require the paired Android app',xfe)
    def test_encrypted_v2_guards_and_single_selection(self):
        handoff=(SRC/'handoff.js').read_text(encoding='utf-8')
        network=(SRC/'network-observer.js').read_text(encoding='utf-8')
        gate=XAR10.read_text(encoding='utf-8')
        for marker in ('async function buildCaptureSession(', 'const pairing = pairedCaptureConfig()',
                       'subtle.encrypt({ name: "AES-GCM"', 'subtle.encrypt({ name: "RSA-OAEP"',
                       'const uri = `${scheme}://capture?v=2&sid=',
                       'if (hasCredentialHeader(input)) return ""'):
            self.assertIn(marker,handoff)
        for forbidden in ('params.set("headers"','params.set("finalHeaders"','params.set("proposedHeaders"'):
            self.assertNotIn(forbidden,handoff)
        for marker in (
             'const authoritative = proof && proof.requestFingerprint === selected.requestFingerprint',
             'Number(proof.requestGeneration || 0) === Number(selected.requestGeneration || 0)',
             'const candidate = Object.assign({}, selected, {',
             'streamKind: candidateStreamKind(selected),',
             'browserHandoff: Object.assign({}, selected.browserHandoff || {}, {',
             'finalHeaders: authoritative ? proof.browserHandoff.finalHeaders : null,',
             'headers: authoritative ? proof.headers : {},',
             'await handoff.buildCaptureSession({',
             'candidates: [candidate]','totalCandidateCount: 1','truncated: false',
        ):
            self.assertIn(marker,network)
            self.assertIn(marker,gate)
    def test_fast_ci_runs_full_xp01_without_gradle(self):
        y=WORKFLOW.read_text(encoding='utf-8')
        fast=y.split('\n  hotfix-fast:\n',1)[1].split('\n  validate:\n',1)[0]
        self.assertIn('python3 -B scripts/test_xgo_xpi_v161_parity.py',fast)
        self.assertIn('python3 -B scripts/test_xgo_mp01_hf05_xpi_guard.py',fast)
        self.assertNotIn('sdkmanager',fast)
        self.assertNotRegex(fast, r'(?m)^\s*(?:\./gradlew|gradle\s|sdkmanager\s)')
        self.assertIn('  android-pr-merge-qualification:',y)
        self.assertIn("contains(github.event.pull_request.labels.*.name, 'xdm-full-ci')",y)
        self.assertIn('needs: [hotfix-fast, validate, emulator-compatibility]',y)
    def test_negative_drift_is_detectable(self):
        good=(SRC/'handoff.js').read_bytes()
        expected=self.ref['adoptedAssetSha256']['handoff.js']
        self.assertEqual(digest(good),expected)
        self.assertNotEqual(digest(good+b'\n// injected drift'),expected)
        self.assertNotEqual(digest(good),OLD['handoff.js'])

if __name__=='__main__':
    unittest.main(verbosity=2)
