#!/usr/bin/env python3
"""MP02C source/security + CI routing contract; run with -B to avoid pycache files."""
from __future__ import annotations
import hashlib, json, os, re, subprocess, unittest
from pathlib import Path
ROOT=Path(os.environ.get('XGO_MP02C_STAGED_ROOT') or Path(__file__).resolve().parents[1]).resolve()
EXT=ROOT/'app/XDM.Android/browser-extension/src/main/extension/xdm-firefox'
DOC=ROOT/'docs/xgo/XGO_XPI_V161_REFERENCE_DIGESTS.json'
XFE=ROOT/'app/XDM/eng/validate-xfe01-single-firefox-extension.py'
POLICY=ROOT/'scripts/ci/xgo_ci_policy.py'
ANDROID=ROOT/'.github/workflows/android.yml'
BASE='24e4ac3056a63b2185a7825b43e893cb1f0ba749'

def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()

class MP02CSecurityContract(unittest.TestCase):
    def test_mime_and_page_world_boundary(self):
        core=(EXT/'detector-core.js').read_text()
        obs=(EXT/'network-observer.js').read_text()
        self.assertIn('const hardNonMedia = HARD_NON_MEDIA_MIME_RE.test(contentType)',core)
        self.assertIn('analysis.manifestBody && CORE.isManifest("", evidence.contentType)',obs)
        self.assertNotIn('contentType: evidence.contentType || observation.contentType',obs)
        self.assertIn('requestProof = sameHop ? captured : null',obs)
        self.assertIn('finalHeadersForExecution(requestProof)',obs)
        self.assertIn('lastRequestGeneration = Math.max(Date.now(), lastRequestGeneration + 1)',obs)
        self.assertIn('confirmedChild = item => Boolean',obs)
        self.assertIn('variantInfo: (selected.variantInfo || []).filter(confirmedChild)',obs)
    def test_mse_is_tentative_and_not_a_blob_download(self):
        bridge=(EXT/'frame-bridge.js').read_text()
        store=(EXT/'candidate-store.js').read_text()
        obs=(EXT/'network-observer.js').read_text()
        self.assertIn('blobPlayback: true',bridge)
        self.assertIn('lastBlobObservationAt',bridge)
        self.assertIn('recentManifestEvidence(tabId, frameId',store)
        self.assertIn('proof.source !== "webRequest"',store)
        self.assertIn('this.rootIdentity(Number(tabId), scopedMediaId(rawId, frame))',store)
        self.assertIn('const rootMatch = CORE.stableMediaIdentity(logical.url) === rawId',store)
        self.assertIn('if (!logical) continue',store)
        self.assertIn('playbackCorrelation: "tentative-same-frame-network"',obs)
        self.assertIn('playbackObserved: false',obs)
    def test_send_once_and_navigation_fail_closed(self):
        obs=(EXT/'network-observer.js').read_text()
        fab=(EXT/'fab.js').read_text()
        popup=(EXT/'popup.js').read_text()
        self.assertIn('sendExactlyOnce(tabId, message.logicalMediaIds, "xdm")',obs)
        self.assertIn('manualDispatches.clear()',obs)
        self.assertIn('freshTab.url !== tab.url',obs)
        self.assertIn('pickerSendInFlight',fab)
        self.assertIn('logicalSendInFlight',popup)
        self.assertIn('buildCaptureSession',obs)
        self.assertIn('Signed URL expired or replaced',obs)
        self.assertIn('Signed media URLs require XDM encrypted capture',obs)
        self.assertIn('url: selected.url',obs)
        self.assertIn('if (externalUrl.search || CORE.logicalMediaUrl',obs)
        self.assertIn('1DM+ cannot safely receive authenticated request headers',obs)
    def test_observer_async_race_fixture_reports_pre_handoff_failures(self):
        fixture=(ROOT/'app/XDM.Android/browser-extension/tests/test_mp02c_observer.js').read_text()
        self.assertIn('async function awaitPairedHandoffStarted(',fixture)
        self.assertIn('running.then(result=>({state:\'exited\',result})',fixture)
        self.assertIn('entered.then(()=>({state:\'started\'}))',fixture)
        self.assertIn('await awaitPairedHandoffStarted(pairingStarted,running);',fixture)
        self.assertNotIn('const running=send(7,pending); await Promise.resolve();await Promise.resolve();',fixture)
        self.assertIn('freshTab.url !== tab.url',(EXT/'network-observer.js').read_text())
    def test_limits_and_original_security(self):
        store=(EXT/'candidate-store.js').read_text()
        self.assertIn('MAX_ALIASES_PER_TAB = 512',store)
        self.assertIn('delete record.manifestText',store)
        self.assertIn('at: prior ? prior.at : Date.now()',store)
        self.assertIn('if (CORE.isLikelySegment(url))',store)
        self.assertTrue((EXT/'handoff.js').is_file())
    def test_xpi_active_digests_and_immutable_original_reference(self):
        doc=json.loads(DOC.read_text())
        self.assertEqual(len(doc['adoptedAssetSha256']),7)
        self.assertEqual(len(doc['unchangedAssetSha256']),6)
        for group in ('adoptedAssetSha256','unchangedAssetSha256'):
            for name,digest in doc[group].items():
                self.assertEqual(sha(EXT/name),digest,name)
                self.assertIn(f'"{name}": "{digest}"',XFE.read_text())
        self.assertIn('referenceSnapshotBeforeMp01Sha256',doc)
        # Original historic digests must NEVER be recomputed or swapped to active assets.
        original=subprocess.run(['git','show',f'{BASE}:docs/xgo/XGO_XPI_V161_REFERENCE_DIGESTS.json'],
                                cwd=Path(os.environ.get('XGO_MP02C_ORIGINAL_ROOT') or ROOT),text=True,capture_output=True,check=True)
        history=json.loads(original.stdout)
        self.assertEqual(doc['referenceSnapshotBeforeMp01Sha256'],history['referenceSnapshotBeforeMp01Sha256'])
    def test_actual_ci_routing(self):
        policy=POLICY.read_text()
        android=ANDROID.read_text()
        for test in ('test_mp02c_playback.js','test_mp02c_observer.js'):
            self.assertIn(test,policy)
            self.assertIn(test,android)
            self.assertTrue((ROOT/'app/XDM.Android/browser-extension/tests'/test).is_file())
        self.assertIn('scripts/test_xgo_mp02c_source_contract.py',policy)
        self.assertIn('scripts/test_xgo_mp02c_source_contract.py',android)
        self.assertIn('workflow_dispatch',android)
        self.assertTrue((ROOT/'.github/workflows/xgo-targeted.yml').is_file())
        self.assertTrue((ROOT/'.github/workflows/xgo-full-gate-router.yml').is_file())

if __name__=='__main__':
    unittest.main(verbosity=1)
