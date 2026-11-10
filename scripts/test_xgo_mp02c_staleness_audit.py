#!/usr/bin/env python3
"""Fail-closed MP02C audit of stale source tests, active XPI and CI05 routing."""
from __future__ import annotations
import hashlib, json, os, subprocess, unittest
from pathlib import Path
ROOT=Path(os.environ.get('XGO_MP02C_STAGED_ROOT') or Path(__file__).resolve().parents[1]).resolve()
ORIG=Path(os.environ.get('XGO_MP02C_ORIGINAL_ROOT') or ROOT).resolve()
EXT=ROOT/'app/XDM.Android/browser-extension/src/main/extension/xdm-firefox'
def get(path):
 p=ROOT/path
 if not p.exists(): p=ORIG/path
 return p.read_text(encoding='utf-8')
class StalenessAudit(unittest.TestCase):
 def test_hls_body_fixture_no_longer_promotes_page_mime(self):
  t=get('app/XDM.Android/browser-extension/tests/test_background.js')
  self.assertNotIn('verified HLS body promotes retained privileged evidence',t)
  self.assertIn('Untrusted HLS body cannot promote suffix-only HTTP response evidence',t)
  contract=get('scripts/test_xgo_mp02a_source_contract.py')
  self.assertNotIn('contentType: evidence.contentType || observation.contentType',contract)
  self.assertIn('analysis.manifestBody && CORE.isManifest',contract)
 def test_other_existing_security_contracts_not_silently_removed(self):
  a=get('scripts/test_xgo_mp02b_source_contract.py')
  self.assertIn('candidateStore.clearFrame(details.tabId, committedFrame)',a)
  self.assertIn('finalHeaders',get('app/XDM.Android/tools/validate-xar10-browser-capture-evidence.py'))
  xp=get('scripts/test_xgo_xp02b_browser_emulator_ci.py')
  self.assertIn("self.assertNotIn('  pull_request:', workflow)",xp)
  self.assertIn("self.assertIn('  workflow_dispatch:', workflow)",xp)
 def test_ext04_fixture_checks_real_logical_grouping_not_mere_proof_count(self):
  fixture=get('app/XDM.Android/browser-extension/tests/test_mp02c_playback.js')
  self.assertIn('segment flood must not evict strong HLS manifest proof',fixture)
  self.assertIn('master and child must share one frame-scoped logical proof',fixture)
  self.assertIn('the authoritative master is selected over its child variant',fixture)
  self.assertIn('unrelated manifests stay ambiguous for MSE playback',fixture)
  builder=get('app/XDM.Android/browser-extension/src/main/extension/xdm-firefox/candidate-store.js')
  self.assertIn('this.rootIdentity(Number(tabId), scopedMediaId(rawId, frame))',builder)
 def test_ext10_race_fixture_uses_bounded_entry_signal(self):
  fixture=get('app/XDM.Android/browser-extension/tests/test_mp02c_observer.js')
  self.assertIn('async function awaitPairedHandoffStarted(',fixture)
  self.assertIn('running.then(result=>({state:\'exited\',result})',fixture)
  self.assertIn('await awaitPairedHandoffStarted(pairingStarted,running);',fixture)
  self.assertIn("assert.ok(/changed during review/i.test(failed.error))",fixture)
  self.assertNotIn('const running=send(7,pending); await Promise.resolve();await Promise.resolve();',fixture)
 def test_complete_digest_tables_preserve_historical_xpi(self):
  ref=json.loads(get('docs/xgo/XGO_XPI_V161_REFERENCE_DIGESTS.json'))
  self.assertEqual(len(ref['adoptedAssetSha256'])+len(ref['unchangedAssetSha256']),13)
  self.assertEqual(ref['schema'],1)
  # Historical XPI provenance is immutable. Read the ORIGINAL reference from
  # the exact pinned Git tree instead of introducing a second hand-copied SHA
  # that can become a stale/incorrect test contract (the HF03 failure).
  parent='24e4ac3056a63b2185a7825b43e893cb1f0ba749'
  original=subprocess.run(
   ['git','show',f'{parent}:docs/xgo/XGO_XPI_V161_REFERENCE_DIGESTS.json'],
   cwd=ORIG,check=True,capture_output=True,text=True)
  baseline=json.loads(original.stdout)
  self.assertEqual(ref['referenceSnapshotBeforeMp01Sha256'],baseline['referenceSnapshotBeforeMp01Sha256'])
  self.assertEqual(ref['originalXpiSha256'],baseline['originalXpiSha256'])
  self.assertEqual(ref['reference'],baseline['reference'])
  xfe=get('app/XDM/eng/validate-xfe01-single-firefox-extension.py')
  for section in ('adoptedAssetSha256','unchangedAssetSha256'):
   for name,digest in ref[section].items():
    self.assertEqual(hashlib.sha256((EXT/name).read_bytes()).hexdigest(),digest,name)
    self.assertIn(f'"{name}": "{digest}"',xfe,name)
 def test_targeted_and_full_do_not_diverge_or_regress_ci05(self):
  policy=get('scripts/ci/xgo_ci_policy.py')
  full=get('.github/workflows/android.yml')
  router=get('.github/workflows/xgo-full-gate-router.yml')
  for item in ('test_mp02c_playback.js','test_mp02c_observer.js',
               'test_xgo_mp02c_source_contract.py','test_xgo_mp02c_staleness_audit.py'):
   self.assertIn(item,policy);self.assertIn(item,full)
  self.assertIn('DEFAULT_INTERVAL = 5',policy)
  self.assertIn("'5'",router)
  self.assertNotIn('  pull_request:',full)
  self.assertIn('  workflow_dispatch:',full)
  self.assertIn('  pull_request:',get('.github/workflows/xgo-targeted.yml'))
if __name__=='__main__':unittest.main(verbosity=2)
