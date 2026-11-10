#!/usr/bin/env python3
"""MP06 must retain MP05 journal, browser authority and inherited security tests."""
from pathlib import Path
import os, subprocess, unittest
ROOT=Path(__file__).resolve().parents[1]
REAL=Path(os.environ.get('XGO_MP06_REAL_REPO',ROOT))
PARENT='2979f4ca63f22bd97fcac5a1eda2556298759a17'
class MP06Staleness(unittest.TestCase):
 def baseline(self,path):return subprocess.check_output(['git','show',f'{PARENT}:{path}'],cwd=REAL)
 def test_mp05_journal_and_broker_unchanged(self):
  for p in ('engine/media/fragment_store.go','engine/media/fragment_store_test.go',
            'engine/runtime/android_fragment_store.go',
            'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidDurableFragmentStore.kt',
            'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidMediaPlatformBroker.kt'):
   self.assertEqual((ROOT/p).read_bytes(),self.baseline(p),p)
 def test_mp04_selection_and_xpi_unchanged(self):
  for p in ('engine/media/manifest_selection.go','engine/media/manifest_selection_test.go',
            'docs/xgo/XGO_XPI_V161_REFERENCE_DIGESTS.json',
            'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/ManifestSelectionV1Contract.kt'):
   self.assertEqual((ROOT/p).read_bytes(),self.baseline(p),p)
 def test_original_kotlin_hls_executor_remains_except_exact_mp06_gap_gate(self):
  # In addition to the inherited MP05 audit, independently check the full
  # Kotlin baseline diff instead of trusting a few unchanged marker words.
  p='app/XDM.Android/media/src/main/kotlin/com/mikeyphw/xdm/android/media/NativeHlsExecutionEngine.kt'
  now=(ROOT/p).read_text(encoding='utf-8')
  old=self.baseline(p).decode('utf-8')
  old_valid='val valid = artifactBytes.size >= expectedMin && !containsManifest && !html && plan.nativeExecutable && hashMatches'
  new_valid=('// An explicit EXT-X-GAP is an intentional hole, not a downloaded part.\n'
             '        // MP08 owns the separate, explicitly partial salvage operation.\n'
             '        val hasExplicitGaps = plan.parts.any { it.gap }\n'
             '        val valid = artifactBytes.size >= expectedMin && !containsManifest && !html && plan.nativeExecutable && hashMatches && !hasExplicitGaps')
  old_reason='            !plan.nativeExecutable -> "Native HLS plan was not executable; completion rejected."'
  new_reason=old_reason+'\n            hasExplicitGaps -> "Explicit HLS gaps require partial recovery, not Completed."'
  self.assertEqual(now.count(new_valid),1)
  self.assertEqual(now.count(new_reason),1)
  self.assertEqual(now.replace(new_valid,old_valid,1).replace(new_reason,old_reason,1),old)
  inherited=(ROOT/'scripts/test_xgo_mp05_staleness_audit.py').read_text()
  self.assertIn('test_kotlin_hls_fallback_preserved_except_mp06_gap_gate',inherited)
  self.assertIn('self.assertEqual(reconstructed,original',inherited)
 def test_go_durability_remains_verified_before_commit(self):
  now=(ROOT/'engine/media/hls_execution.go').read_text()
  for anchor in ('BindDurableStore(store DurableFragmentSink)',
                 'e.store.WriteAndCommitFragment(ctx,rec,payload)',
                 'e.store.VerifyCommitted(receipt)',
                 'e.ledger.Commit(receipt)', 'durable_store_required'):
   self.assertIn(anchor,now,anchor)
 def test_inherited_tests_and_gates_remain_registered(self):
  p=(ROOT/'scripts/ci/xgo_ci_policy.py').read_text()
  for anchor in ('tests.update(MP03_PYTHON)','tests.update(MP04_PYTHON)',
                 'tests.update(MP05_PYTHON)','tests.update(MP06_PYTHON)',
                 'DEFAULT_INTERVAL = 5'):
   self.assertIn(anchor,p)
  self.assertTrue((ROOT/'scripts/test_xgo_mp05_staleness_audit.py').is_file())
  self.assertTrue((ROOT/'.github/workflows/xgo-targeted.yml').is_file())
if __name__=='__main__':unittest.main(verbosity=2)
