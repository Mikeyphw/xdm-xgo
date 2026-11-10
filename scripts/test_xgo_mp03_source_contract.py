#!/usr/bin/env python3
"""MP03 source-security checks against the real staged/current project tree."""
from __future__ import annotations
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
RESOLVER=ROOT/'engine/media/manifest_resolver.go'
TESTS=ROOT/'engine/media/manifest_resolver_test.go'
ANDROID=ROOT/'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/ManifestGraphV1Contract.kt'
POLICY=ROOT/'scripts/ci/xgo_ci_policy.py'

class MP03SourceContract(unittest.TestCase):
    def test_authoritative_go_resolver_uses_existing_parsers(self):
        source=RESOLVER.read_text()
        for marker in ('func ResolveManifestGraph(', 'ParseHLSPlaylist(', 'ParseDASHManifest(',
                       'ManifestGraphSchemaV1 = 1', 'ErrManifestCycle', 'ErrManifestExpired',
                       'ErrManifestRedirect', 'MaxResponseBytes:', 'mp03AllowedMIME('):
            with self.subTest(marker=marker):self.assertIn(marker,source)
        self.assertNotIn('http.Get(',source)
        self.assertNotIn('http.DefaultClient',source)
        self.assertNotIn('log.Print',source)
    def test_security_scope_is_fail_closed(self):
        s=RESOLVER.read_text()
        for marker in ('!allowed[origin]', 'if replay && hopOrigin != rootOrigin',
                       'if current != finalURL', 'if !response.ExpiresAt.IsZero()',
                       'if total > maxBytes', 'if len(graph.Sources) >= maxNodes',
                       'if depth > maxDepth', 'func (g ManifestGraphV1) SafeSummary()'):
            with self.subTest(marker=marker):self.assertIn(marker,s)
        self.assertIn('DownloadReady: false',s)
        self.assertNotIn('Authorization:',s)
        self.assertNotIn('Cookie:',s)
    def test_contract_and_kotlin_hls_fallback_preserved(self):
        s=ANDROID.read_text()
        for marker in ('schema_version', 'root_url', 'audio_tracks','subtitle_tracks',
                       'duplicate option ID', 'download_ready', 'redactedSummary()',
                       'MP03 graph cannot authorize download completion'):
            with self.subTest(marker=marker):self.assertIn(marker,s)
        self.assertTrue((ROOT/'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidMediaPlatformBroker.kt').exists())
        self.assertTrue((ROOT/'engine/media/hls_execution.go').exists())
    def test_real_go_regression_matrix_not_only_source_strings(self):
        s=TESTS.read_text()
        for group in ('HLS01','HLS02','HLS03','HLS04','HLS05','HLS06','HLS07',
                      'DASH01','DASH02','DASH03','DASH04','DASH05','DASH06',
                      'RES01','RES02','RES03','RES04','RES05','RES06','RES07','RES08','RES09','RES10'):
            self.assertIn(group,s)
        self.assertIn('ResolveManifestGraph(',s)
        p=POLICY.read_text()
        self.assertIn('scripts/test_xgo_mp03_source_contract.py',p)
        self.assertIn('scripts/test_xgo_mp03_staleness_contract.py',p)
        self.assertIn('tests.update(MP03_PYTHON)',p)
        self.assertIn('subprocess.run(["go", "test", "./..."]',p)

if __name__=='__main__':unittest.main(verbosity=2)
