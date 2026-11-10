#!/usr/bin/env python3
"""MP07 inherited contract audit; read-only, exact-pinned and fail-closed."""
from __future__ import annotations
import os,subprocess,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REAL=Path(os.environ.get('XGO_MP07_REAL_REPO',ROOT))
PARENT='81197fe4bcd8e1f80c06fee0621cbc9b33d4d615'

class MP07Staleness(unittest.TestCase):
    def baseline(self,path):
        return subprocess.check_output(['git','show',f'{PARENT}:{path}'],cwd=REAL)
    def test_original_dash_parser_and_executor_remain_untouched(self):
        for path in ('engine/media/dash.go','engine/media/dash_test.go'):
            self.assertEqual((ROOT/path).read_bytes(),self.baseline(path),path)
    def test_mp05_persistence_authentication_and_kotlin_fallback_untouched(self):
        for path in (
            'engine/media/fragment_store.go','engine/media/fragment_store_test.go',
            'engine/runtime/android_fragment_store.go',
            'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidDurableFragmentStore.kt',
            'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidMediaPlatformBroker.kt',
            'app/XDM.Android/media/src/main/kotlin/com/mikeyphw/xdm/android/media/NativeHlsExecutionEngine.kt',
            'docs/xgo/XGO_XPI_V161_REFERENCE_DIGESTS.json'):
            self.assertEqual((ROOT/path).read_bytes(),self.baseline(path),path)
    def test_mp06_hls_fixes_and_existing_ci_contract_preserved(self):
        for path in ('engine/media/hls.go','engine/media/hls_execution.go',
                     'engine/media/hls_vod_session.go',
                     'engine/media/hls_vod_session_test.go',
                     'engine/media/hls_map_key_binding_test.go',
                     'scripts/test_xgo_mp06_source_contract.py',
                     'scripts/test_xgo_mp06_staleness_audit.py',
                     '.github/workflows/xgo-targeted.yml'):
            self.assertEqual((ROOT/path).read_bytes(),self.baseline(path),path)
    def test_no_existing_phase_tests_removed_or_bypassed(self):
        before=self.baseline('scripts/ci/xgo_ci_policy.py').decode()
        after=(ROOT/'scripts/ci/xgo_ci_policy.py').read_text()
        for anchor in ('tests.update(MP03_PYTHON)','tests.update(MP04_PYTHON)',
                       'tests.update(MP05_PYTHON)','tests.update(MP06_PYTHON)',
                       'subprocess.run(["go", "test", "./..."]',
                       '"app/XDM.Android/media/src/"',
                       'DEFAULT_INTERVAL = 5'):
            self.assertIn(anchor,before)
            self.assertIn(anchor,after)
        self.assertIn('tests.update(MP07_PYTHON)',after)
        self.assertEqual(after.replace('MP07_PYTHON = [\n    "scripts/test_xgo_mp07_source_contract.py",\n    "scripts/test_xgo_mp07_staleness_audit.py",\n]\n', '').replace('        tests.update(MP07_PYTHON)\n',''),before)
    def test_legacy_phase_contracts_still_in_repository(self):
        for file in ('scripts/test_xgo_mp03_source_contract.py',
                     'scripts/test_xgo_mp04_source_contract.py',
                     'scripts/test_xgo_mp05_source_contract.py',
                     'scripts/test_xgo_mp06_source_contract.py',
                     'scripts/test_xgo_mp07_source_contract.py'):
            self.assertTrue((ROOT/file).is_file(),file)

if __name__=='__main__':unittest.main(verbosity=2)
