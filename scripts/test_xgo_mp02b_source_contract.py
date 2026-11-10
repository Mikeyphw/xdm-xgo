#!/usr/bin/env python3
"""MP02B fail-closed architecture and targeted routing source checks."""
from __future__ import annotations
from pathlib import Path
import re, unittest
ROOT=Path(__file__).resolve().parents[1]
EXT=ROOT/'app/XDM.Android/browser-extension/src/main/extension/xdm-firefox'
OBS=EXT/'network-observer.js'
STORE=EXT/'candidate-store.js'
POLICY=ROOT/'scripts/ci/xgo_ci_policy.py'

class MP02BSiteMode(unittest.TestCase):
    def test_policy_revoke_and_exact_header_cleanup(self):
        s=OBS.read_text()
        for phrase in ['if (before !== after) revokeAllCaptureState();', 'candidateStore.clearAll()',
                       'capturedHeaders.clear()', 'dispatchTimers.clear()', 'lastDispatchedByTab.clear()',
                       'tabDispatchSessions.clear()', 'diagnosticCounters.clear()', 'forgetTabHeaders(tabId)']:
            self.assertIn(phrase,s)
    def test_no_cdn_site_mode_bypass(self):
        s=OBS.read_text()
        region=s.split('  function tabUrlAllowedForCapture(details)',1)[1].split('\n  function ',1)[0]
        self.assertIn('details.documentUrl || details.originUrl || details.initiator || ""',region)
        self.assertNotIn('details.url',region)
        self.assertIn('if (!source && settings.siteMode !== "all") return false;',region)
        self.assertIn('catch (_) { return false; }',s)
    def test_observations_require_allowed_frame(self):
        s=OBS.read_text()
        for method in ['processPageObservation','processFramePlayback']:
            region=s.split('function '+method+'(',1)[1].split('\n  function ',1)[0]
            self.assertIn('if (!tabAllowed(sender && sender.tab && sender.tab.url',region)
        self.assertIn('const correlated = findPrivilegedEvidence(tabId, extracted.url, frameId)',s)
        self.assertIn('const authoritative = proof && proof.requestFingerprint === selected.requestFingerprint',s)
        self.assertIn('headers: authoritative ? proof.headers : {},',s)
    def test_frame_and_tab_retirement(self):
        s=OBS.read_text()
        self.assertIn('candidateStore.clearFrame(details.tabId, committedFrame)',s)
        self.assertIn('candidateStore.removeTab(details.tabId)',s)
        self.assertIn('forgetTabHeaders(tabId);\n          candidateStore.removeTab(tabId);',s)
        self.assertIn('forgetTabHeaders(tabId);\n      candidateStore.removeTab(tabId);',s)
        st=STORE.read_text()
        self.assertIn('clearAll() {',st)
        for f in ['this.buckets.clear()', 'this.aliases.clear()', 'this.evidence.clear()', 'this.stats.clear()']:
            self.assertIn(f,st)
    def test_targeted_ci_includes_real_node_fixture(self):
        p=POLICY.read_text()
        self.assertIn('app/XDM.Android/browser-extension/tests/test_mp02b_site_mode.js',p)
        self.assertIn('scripts/test_xgo_mp02b_source_contract.py',p)
        self.assertTrue((ROOT/'app/XDM.Android/browser-extension/tests/test_mp02b_site_mode.js').is_file())
        a=(ROOT/'.github/workflows/android.yml').read_text()
        self.assertIn('test_mp02b_site_mode.js',a)
        self.assertIn('test_xgo_mp02b_source_contract.py',a)

if __name__=='__main__': unittest.main(verbosity=2)
