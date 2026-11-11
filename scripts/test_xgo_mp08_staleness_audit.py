#!/usr/bin/env python3
"""MP08A exact MP07 inherited source immutability and CI05 registry guard."""
from pathlib import Path
import os,subprocess,unittest,hashlib
ROOT=Path(__file__).resolve().parents[1]
REAL=Path(os.environ.get('XGO_MP08_REAL_REPO',ROOT))
PARENT='794ce9f66cb0bc3cb2f854b6f75cbf0f234c319b'
class MP08StaleContracts(unittest.TestCase):
 def source(self,p):return (ROOT/p).read_bytes()
 def baseline(self,p):return subprocess.check_output(['git','show',f'{PARENT}:{p}'],cwd=REAL)
 def test_mp05_durable_storage_untouched(self):
  for p in ('engine/media/fragment_store.go','engine/media/fragment_store_test.go','engine/media/fragment_ledger.go',
            'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidDurableFragmentStore.kt'):
   self.assertEqual(self.source(p),self.baseline(p),p)
 def test_mp06_hls_and_android_ffmpeg_broker_untouched(self):
  for p in ('engine/media/hls_execution.go','engine/media/hls_vod_session.go',
            'engine/media/hls_map_key_binding_test.go',
            'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidMediaPlatformBroker.kt',
            'app/XDM.Android/media/src/main/kotlin/com/mikeyphw/xdm/android/media/NativeHlsExecutionEngine.kt'):
   self.assertEqual(self.source(p),self.baseline(p),p)
 def test_mp07_dash_period_staging_untouched(self):
  for p in ('engine/media/dash.go','engine/media/dash_period_session.go','engine/media/dash_period_session_test.go',
            'scripts/test_xgo_mp07_source_contract.py'):
   self.assertEqual(self.source(p),self.baseline(p),p)
 def test_legacy_ffmpeg_probe_and_publication_contract_untouched(self):
  for p in ('engine/media/ffmpeg.go','engine/media/ffmpeg_test.go',
            'app/XDM.Android/media-ffmpeg/src/main/kotlin/com/mikeyphw/xdm/android/media/ffmpeg/FfmpegPostProcessor.kt',
            'app/XDM.Android/media-ffmpeg/src/main/kotlin/com/mikeyphw/xdm/android/media/ffmpeg/FfmpegMediaVerifier.kt'):
   self.assertEqual(self.source(p),self.baseline(p),p)
  # All historical media contracts remain unchanged. CI05 must equal the
  # single approved Node24 modernization of the exact MP08 Git baseline.
  from test_xgo_mp05_staleness_audit import approved_ci05_node24_upgrade
  p='.github/workflows/xgo-targeted.yml'
  self.assertEqual(self.source(p).decode('utf-8'),
                   approved_ci05_node24_upgrade(self.baseline(p).decode('utf-8')),p)
 def test_inherited_mp07_audit_has_only_exact_approved_mp08_exception(self):
  path='scripts/test_xgo_mp07_staleness_audit.py'
  self.assertNotEqual(self.source(path),self.baseline(path))
  # Derived from an exact, source-blob-pinned single insertion. Future edits
  # cannot disable MP07's original immutable CI-registry comparison.
  self.assertEqual(hashlib.sha256(self.source(path)).hexdigest(),
      '3f64f14f2924b1e40da50ff8dd9e94439c8a3b2a0d59cdd422ecb8214d440725')
  text=self.source(path).decode()
  for required in ('approved_ci05_node24_upgrade', 'mp08_block', 'after.count(mp08_block)',
                   "after=after.replace(mp08_block,'',1)",
                   "self.assertEqual(after.replace('MP07_PYTHON"):
   self.assertIn(required,text)
 def test_mp07_ci_registry_only_exact_mp08_addition(self):
  old=self.baseline('scripts/ci/xgo_ci_policy.py').decode()
  new=self.source('scripts/ci/xgo_ci_policy.py').decode()
  block='''MP08_PYTHON = [
    "scripts/test_xgo_mp08_source_contract.py",
    "scripts/test_xgo_mp08_staleness_audit.py",
]
'''
  self.assertEqual(new.count(block),1)
  reconstructed=new.replace(block,'',1).replace('        tests.update(MP08_PYTHON)\n','',1)
  self.assertEqual(reconstructed,old)
 def test_targeted_policy_still_requires_all_inherited_tests(self):
  s=self.source('scripts/ci/xgo_ci_policy.py').decode()
  for a in ('tests.update(MP03_PYTHON)','tests.update(MP04_PYTHON)','tests.update(MP05_PYTHON)',
            'tests.update(MP06_PYTHON)','tests.update(MP07_PYTHON)','tests.update(MP08_PYTHON)',
            'subprocess.run(["go", "test", "./..."]'):
   self.assertIn(a,s)
if __name__=='__main__':unittest.main(verbosity=2)
