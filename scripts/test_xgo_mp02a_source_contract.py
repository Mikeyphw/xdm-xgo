#!/usr/bin/env python3
"""MP02A fast checks for code paths that cannot be fully executed under Node."""
from pathlib import Path
import unittest
# Test lives in repo at scripts/test_xgo_mp02a_source_contract.py
REPO=Path(__file__).resolve().parents[1]
EXT=REPO/'app/XDM.Android/browser-extension/src/main/extension/xdm-firefox'
WORKFLOW=REPO/'.github/workflows/android.yml'
class MP02SourceContract(unittest.TestCase):
    def test_webrequest_only_promotes_page_body(self):
        s=(EXT/'network-observer.js').read_text()
        self.assertIn('if (bodyExcerpt && responseUrl && evidence)',s)
        self.assertIn('const correlated = findPrivilegedEvidence(tabId, extracted.url, frameId)',s)
        self.assertIn('contentType: evidence.contentType || observation.contentType || ""',s)
        self.assertIn('parentManifestUrl: analysis.hlsBody || analysis.dashBody ? responseUrl : ""',s)
        self.assertIn('delete payload.headers;',s)
        self.assertIn('delete payload.browserHandoff;',s)
    def test_navigation_retires_rows(self):
        s=(EXT/'network-observer.js').read_text()
        self.assertIn('candidateStore.clearFrame(details.tabId, committedFrame)',s)
        self.assertIn('candidateStore.removeTab(details.tabId)',s)
        self.assertIn('candidateStore.removeTab(tabId)',s)
    def test_picker_requires_exact_one(self):
        s=(EXT/'network-observer.js').read_text()
        self.assertIn('if (ids.length !== 1) throw new Error',s)
        self.assertIn('requireSingleSelectedCandidate(tabId, requestedIds, "XDM")',s)
        self.assertIn('requireSingleSelectedCandidate(tabId, requestedIds, "1DM+")',s)
        self.assertIn('requestFingerprint === selected.requestFingerprint',s)
    def test_fast_ci_runs_node_fixture_without_gradle(self):
        s=WORKFLOW.read_text()
        fast=s.split('\n  hotfix-fast:\n',1)[1].split('\n  validate:\n',1)[0]
        self.assertIn('test_mp02_discovery.js',fast)
        self.assertIn('test_xgo_mp02a_source_contract.py',fast)
        self.assertNotIn('./gradlew',fast)
if __name__=='__main__':unittest.main(verbosity=2)
