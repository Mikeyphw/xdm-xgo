#!/usr/bin/env python3
"""MP03 integration staleness and unchanged lineage: pinned actual parent bytes."""
from pathlib import Path
import json, os, re, subprocess, unittest
ROOT=Path(__file__).resolve().parents[1]
PARENT='8471707c742ef991747ece24b7e03f9c8ccd921d'
ACTUAL=Path(os.environ.get('XGO_MP03_REAL_REPO',ROOT))
class Staleness(unittest.TestCase):
    def parent(self, rel): return subprocess.check_output(['git','show',f'{PARENT}:{rel}'],cwd=ACTUAL)
    def test_immutable_xpi_provenance(self):
        rel='docs/xgo/XGO_XPI_V161_REFERENCE_DIGESTS.json'
        self.assertEqual(json.loads((ROOT/rel).read_bytes()),json.loads(self.parent(rel)))
    def test_original_kotlin_hls_fallback(self):
        rel='app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidMediaPlatformBroker.kt'
        self.assertEqual((ROOT/rel).read_bytes(),self.parent(rel))
    def test_original_browser_handoff(self):
        for name in ('handoff.js','network-observer.js','detector-core.js'):
            rel='app/XDM.Android/browser-extension/src/main/extension/xdm-firefox/'+name
            self.assertEqual((ROOT/rel).read_bytes(),self.parent(rel))
    def test_new_footprint_is_real_and_no_untracked_compiler_skips(self):
        a=(ROOT/'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidEngineProcessAuthority.kt').read_text()
        p=(ROOT/'scripts/ci/xgo_ci_policy.py').read_text()
        self.assertIn('AndroidAuthorizedManifestFetcher(appContext)',a)
        self.assertIn('"android.media.resolve_manifest"',a)
        self.assertIn('test_xgo_mp03_android_e2e_contract.py',p)
        self.assertIn('test_xgo_mp03_android_staleness.py',p)
        self.assertIn('if planned["needs_go"]:',p)
        self.assertIn('DEFAULT_INTERVAL = 5',p)
        self.assertTrue((ROOT/'.github/workflows/xgo-targeted.yml').is_file())
        self.assertTrue((ROOT/'.github/workflows/xgo-full-gate-router.yml').is_file())
    def test_android_ci_trigger_contract_not_stale(self):
        # Path filtering is not used for release-tag or manual Actions events.
        # Keep a regression for the exact trigger semantics, rather than a
        # stale demand for two arbitrary YAML path-filter literals.
        gradle=(ROOT/'app/XDM.Android/build.gradle.kts').read_text()
        workflow=(ROOT/'.github/workflows/android.yml').read_text()
        trigger=workflow.split('\non:\n',1)[1].split('\npermissions:',1)[0]
        self.assertIn('workflow_dispatch:',trigger)
        self.assertIn("tags: ['android-v*']",trigger)
        self.assertNotIn('Android CI path filters must include Devtool and the canonical release helper.',gradle)
        self.assertIn('val ciTriggers = ',gradle)
        self.assertIn('if (filtered) {',gradle)
        self.assertIn("Filtered Android CI triggers must include Devtool and the canonical release helper.",gradle)
        self.assertIn('releaseHelperFile.readText().contains("run-bug-hunt-phase10-release-gate.sh")',gradle)
        self.assertIn('devtoolConfigFile.readText().contains(',gradle)
        self.assertIn('external_verification',gradle)
        policy=(ROOT/'scripts/ci/xgo_ci_policy.py').read_text()
        self.assertIn('"app/XDM.Android/build.gradle.kts"',policy)
        self.assertIn('"app/XDM.Android/build.gradle"',policy)
        self.assertTrue((ROOT/'.devtool.toml').is_file())
        self.assertTrue((ROOT/'build-release-apk.sh').is_file())
        # When adding a filtered push/PR trigger later, both tools must be
        # listed so changes to either artifact rerun mandatory validation.
        if re.search(r'(?m)^\s{4}paths(-ignore)?:\s*$',trigger):
            self.assertIn("- '.devtool.toml'",trigger)
            self.assertIn("- 'build-release-apk.sh'",trigger)

    def test_manifest_graph_not_download_authority(self):
        go=(ROOT/'engine/media/manifest_resolver.go').read_text()
        self.assertIn('DownloadReady: false',go)
        a=(ROOT/'engine/runtime/android_manifest_resolve.go').read_text()
        self.assertIn('graph.DownloadReady',a)
        self.assertNotIn('e.androidMedia.execute',a)

if __name__=='__main__': unittest.main(verbosity=2)
