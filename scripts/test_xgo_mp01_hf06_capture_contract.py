#!/usr/bin/env python3
"""HF06 Android/JVM capture contract preflight (Python only, no SDK/NDK/Gradle).

Checks the same post-MP01 invariants that the JVM Phase59-61 source test
exercises, plus app-generated XPI key pairing and fail-closed behavior.
"""
from __future__ import annotations
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
KOTLIN=ROOT/'app/XDM.Android/app/src/test/kotlin/com/mikeyphw/xdm/android/BrowserCapturePhases59_61ContractTest.kt'
VIEW=ROOT/'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/MainViewModel.kt'
GEN=ROOT/'app/XDM.Android/browser-extension/src/main/kotlin/com/mikeyphw/xdm/android/browserextension/BrowserExtensionPackageGenerator.kt'
CONFIG=ROOT/'app/XDM.Android/browser-extension/src/main/kotlin/com/mikeyphw/xdm/android/browserextension/BrowserExtensionBuildConfig.kt'
JS=ROOT/'app/XDM.Android/browser-extension/src/main/extension/xdm-firefox/handoff.js'
NET=ROOT/'app/XDM.Android/browser-extension/src/main/extension/xdm-firefox/network-observer.js'
SECURE=ROOT/'app/XDM.Android/browser-extension/tests/test_secure_handoff.js'
PARSER=ROOT/'app/XDM.Android/browser-integration/src/main/kotlin/com/mikeyphw/xdm/android/browser/XdmBrowserDeepLinkParser.kt'
WORKFLOW=ROOT/'.github/workflows/android.yml'


def check_model(jvm:str,app:str,gen:str,config:str,js:str,net:str,secure:str,parser:str)->list[str]:
    errors=[]
    def need(src:str,token:str,where:str):
        if token not in src:errors.append(f'{where}: required {token}')
    def forbid(src:str,token:str,where:str):
        if token in src:errors.append(f'{where}: obsolete/unsafe {token}')
    if jvm.count('    @Test\n')!=4:errors.append('Phase59-61 should retain exactly 4 unit tests')
    for token in ('fun firefoxCaptureUsesPairedEncryptedV2AndRejectsPlaintextV3()',
                  'fun firefoxTransfersOnlyOneExplicitlySelectedEvidenceBackedCandidatePerReviewHandoff()',
                  'fun exportedXpiUsesAppPublicPairingAndKeylessFallbackIsPublicOnly()',
                  'captureSessionsRemainFirstClassAndNonSecretInMediaInbox',
                  'EncryptedCaptureVersion -> parseEncryptedCaptureEnvelope',
                  '@@CAPTURE_PAIRING_CONFIG@@',
                  'captureKeyId = browserCaptureEnvelopeManager.keyId',
                  'candidates: sourceCandidates.slice(0, count)',
                  'finalHeaders: authoritative ? proof.browserHandoff.finalHeaders : null,',
                  'subtle.encrypt({ name: \\"AES-GCM\\"',
                  'assertFalse(handoff.contains("uri.searchParams.set(\\"candidates\\""))'):
        need(jvm,token,'Phase59-61 JVM tests')
    for token in ('currentFirefoxHandoffIsDirectV3WhileEncryptedV2RemainsReaderOnlyMigrationSupport',
                  'exportedXpiIsKeylessAndStalesOnlyForPackageAffectingChanges',
                  'uri.searchParams.set(\\"truncated\\"',
                  'stable capture payload must not depend on Android app version/key lifecycle',
                  'sender-bound direct v3 lifecycle test passed'):
        forbid(jvm,token,'Phase59-61 JVM tests')
    for token in ('captureKeyId = browserCaptureEnvelopeManager.keyId',
                  'capturePublicKeySpkiBase64Url = browserCaptureEnvelopeManager.publicKeySpkiBase64Url',
                  'captureOaepHash = browserCaptureEnvelopeManager.captureOaepHash',
                  'val config = runCatching {', '}.getOrElse { failure ->',
                  'Unable to prepare the app-paired Firefox capture key.',
                  'phase = BrowserExtensionExportPhase.Failed',
                  'return@launch'):
        need(app,token,'app XPI export')
    for token in ('@@CAPTURE_PAIRING_CONFIG@@','captureKeyId:', 'capturePublicKeySpkiBase64Url:', 'captureOaepHash:'):
        need(gen,token,'XPI package generator')
    for token in ('require(paired == 0 || paired == 3)', 'captureKeyId: String = ""',
                  'capturePublicKeySpkiBase64Url: String = ""','captureOaepHash: String = ""'):
        need(config,token,'XPI build config')
    for token in ('const pairing = pairedCaptureConfig()', 'subtle.encrypt({ name: "RSA-OAEP"',
                  'subtle.encrypt({ name: "AES-GCM"', '://capture?v=2&sid=',
                  '&kid=','&ek=','&iv=','&ct=',
                  'if (hasCredentialHeader(input)) return ""', 'return buildXdmAdd(input)'):
        need(js,token,'Firefox encrypted XPI')
    for token in ('params.set("headers"', 'params.set("finalHeaders"',
                  'params.set("proposedHeaders"', 'params.set("candidates"'):
        forbid(js,token,'Firefox plaintext navigation')
    for token in ('const authoritative = proof && proof.requestFingerprint === selected.requestFingerprint',
                  'Number(proof.requestGeneration || 0) === Number(selected.requestGeneration || 0)',
                  'finalHeaders: authoritative ? proof.browserHandoff.finalHeaders : null,',
                  'headers: authoritative ? proof.headers : {},','candidates: [candidate]',
                  'totalCandidateCount: 1','truncated: false'):
        need(net,token,'exact request background capture')
    for token in ('webcrypto.subtle.decrypt','json.candidates[0].finalHeaders.authorization',
                  'json.candidates[0].durationMs,630000',
                  'json.candidates[0].thumbnailUrl,"https://img.example/poster.jpg"',
                  'xdm-capture-v2|forged|'):
        need(secure,token,'AES-GCM tamper and media fidelity test')
    for token in ('EncryptedCaptureVersion -> parseEncryptedCaptureEnvelope',
                  'XdmBrowserDeepLinkContract.CurrentVersion ->',
                  'XdmBrowserDeepLinkParseResult.Rejected(XdmBrowserDeepLinkRejection.UnsafeEnvelope)'):
        need(parser,token,'Android browser link parser')
    return errors


class MP01HF06Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources=[f.read_text(encoding='utf-8') for f in
             (KOTLIN,VIEW,GEN,CONFIG,JS,NET,SECURE,PARSER)]
    def test_runtime_and_jvm_contracts(self):
        self.assertEqual(check_model(*self.sources),[])
    def test_fast_lane_before_gradle_and_full_gate_preserved(self):
        y=WORKFLOW.read_text(encoding='utf-8')
        fast=y.split('\n  hotfix-fast:\n',1)[1].split('\n  validate:\n',1)[0]
        self.assertIn('python3 -B scripts/test_xgo_mp01_hf06_capture_contract.py',fast)
        self.assertNotIn('sdkmanager',fast)
        self.assertNotIn('./gradlew',fast)
        self.assertIn('  android-pr-merge-qualification:',y)
        self.assertIn("contains(github.event.pull_request.labels.*.name, 'xdm-full-ci')",y)
    def test_mutation_missing_pairing_fails(self):
        parts=self.sources[:]
        parts[1]=parts[1].replace('captureKeyId = browserCaptureEnvelopeManager.keyId',
                                   'captureKeyId = ""')
        self.assertTrue(any('app XPI export' in e for e in check_model(*parts)))
    def test_mutation_failed_closed_export_fails(self):
        parts=self.sources[:]
        parts[1]=parts[1].replace('}.getOrElse { failure ->','}.getOrNull()?.let { config ->')
        self.assertTrue(any('app XPI export' in e for e in check_model(*parts)))
    def test_mutation_plaintext_handoff_fails(self):
        parts=self.sources[:]
        parts[4]=parts[4]+'\nparams.set("headers", data);\n'
        self.assertTrue(any('plaintext navigation' in e for e in check_model(*parts)))
    def test_mutation_final_header_scope_fails(self):
        parts=self.sources[:]
        parts[5]=parts[5].replace('headers: authoritative ? proof.headers : {},','headers: selected.headers,')
        self.assertTrue(any('background capture' in e for e in check_model(*parts)))
    def test_mutation_stale_jvm_tests_fails(self):
        parts=self.sources[:]
        parts[0]=parts[0].replace('fun firefoxCaptureUsesPairedEncryptedV2AndRejectsPlaintextV3()',
                                     'fun currentFirefoxHandoffIsDirectV3WhileEncryptedV2RemainsReaderOnlyMigrationSupport()')
        self.assertTrue(check_model(*parts))

if __name__=='__main__':
    unittest.main(verbosity=2)
