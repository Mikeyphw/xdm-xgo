#!/usr/bin/env python3
"""MP05 provenance: validate preserved fallback/XPI and no stale test shortcut."""
from __future__ import annotations
import os,subprocess,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=Path(os.environ.get('XGO_MP05_REAL_REPO',ROOT))
PARENT='67fad5ed25341b93a24ebd2148d0593655b604b9'
class MP05Stale(unittest.TestCase):
 def baseline(self,p):return subprocess.check_output(['git','show',f'{PARENT}:{p}'],cwd=ORIGINAL)
 def test_original_ffmpeg_broker_unchanged(self):
  p='app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidMediaPlatformBroker.kt'
  self.assertEqual((ROOT/p).read_bytes(),self.baseline(p))
 def test_kotlin_hls_fallback_preserved_except_mp06_gap_gate(self):
  # MP06 adds only two completion-verifier lines: the explicit GAP predicate
  # and its failure reason. Every other byte of the original Kotlin HLS
  # executor, including normal download/fallback behavior, remains immutable.
  p='app/XDM.Android/media/src/main/kotlin/com/mikeyphw/xdm/android/media/NativeHlsExecutionEngine.kt'
  original=self.baseline(p).decode('utf-8')
  staged=(ROOT/p).read_text(encoding='utf-8')
  old_valid='val valid = artifactBytes.size >= expectedMin && !containsManifest && !html && plan.nativeExecutable && hashMatches'
  new_valid=('// An explicit EXT-X-GAP is an intentional hole, not a downloaded part.\n'
             '        // MP08 owns the separate, explicitly partial salvage operation.\n'
             '        val hasExplicitGaps = plan.parts.any { it.gap }\n'
             '        val valid = artifactBytes.size >= expectedMin && !containsManifest && !html && plan.nativeExecutable && hashMatches && !hasExplicitGaps')
  old_reason='            !plan.nativeExecutable -> "Native HLS plan was not executable; completion rejected."'
  new_reason=old_reason+'\n            hasExplicitGaps -> "Explicit HLS gaps require partial recovery, not Completed."'
  self.assertEqual(original.count(old_valid),1)
  self.assertEqual(original.count(old_reason),1)
  self.assertEqual(staged.count(new_valid),1)
  self.assertEqual(staged.count(new_reason),1)
  reconstructed=staged.replace(new_valid,old_valid,1).replace(new_reason,old_reason,1)
  self.assertEqual(reconstructed,original,'Only the MP06 explicit gap gate may differ from the original fallback')
 def test_historical_xpi_sha_unchanged(self):
  p='docs/xgo/XGO_XPI_V161_REFERENCE_DIGESTS.json'
  self.assertEqual((ROOT/p).read_bytes(),self.baseline(p))
 def test_original_mp04_contracts_not_silently_rewritten(self):
  for p in ('scripts/test_xgo_mp04_source_contract.py',
            'engine/media/manifest_selection.go', '.github/workflows/xgo-targeted.yml'):
   self.assertEqual((ROOT/p).read_bytes(),self.baseline(p))
 def test_inherited_mp04_contract_retargeted_without_weakening(self):
  p='scripts/test_xgo_mp04_staleness_audit.py'
  original=self.baseline(p).decode()
  current=(ROOT/p).read_text()
  # This is the single previously immutable source that MP05 must change:
  # retain XPI/manifest/selection tests; require new real-durability guard.
  for anchor in ('validate_ci05_contract(', 'test_ci05_negative_removed_go_execution',
                 'test_transport_secret_boundary', 'manifest_selection.go',
                 'XGO_XPI_V161_REFERENCE_DIGESTS.json', 'test_no_stale_fixture_inheritance'):
   self.assertIn(anchor,original)
   self.assertIn(anchor,current)
  self.assertNotIn("'docs/xgo/XGO_XPI_V161_REFERENCE_DIGESTS.json','engine/media/hls_execution.go',",current)
  self.assertIn('test_mp05_hls_mutation_requires_actual_durable_sink',current)
  self.assertIn('e.store.WriteAndCommitFragment(ctx,',current)

 def test_no_synthetic_success_after_network_fetch(self):
  for p, start, finish in (
      ('engine/media/hls_execution.go', 'func (e *HLSExecutor) executeSegment(', '\nfunc DecryptHLSAES128('),
      ('engine/media/dash.go', 'func (e *DASHExecutor) executeDASHFragment(', '\nfunc convertDASHTemplate('),
  ):
   a=(ROOT/p).read_text()
   self.assertNotIn('artifact := artifactRefForFragment(',a)
   self.assertNotIn('art := artifactRefForFragment(',a)
   # Inspect the actual fragment writer, not unrelated constructors/comments;
   # gofmt and valid Go permit spaces around comparison operators.
   self.assertEqual(a.count(start),1,p)
   function=a.split(start,1)[1].split(finish,1)[0]
   self.assertRegex(function,r'\bif\s+e\.store\s*==\s*nil\s*\{',p)
   self.assertIn('e.store.WriteAndCommitFragment(ctx,',function)
   self.assertIn('e.store.VerifyCommitted(',function)
   self.assertIn('e.ledger.Commit(receipt)',function)
 def test_no_unsafe_force_or_local_android_build(self):
  text=(ROOT/'scripts/ci/xgo_ci_policy.py').read_text()
  self.assertIn('DEFAULT_INTERVAL = 5',text)
  self.assertIn('tests.update(MP05_PYTHON)',text)
  self.assertTrue((ROOT/'.github/workflows/xgo-full-gate-router.yml').is_file())
if __name__=='__main__':unittest.main(verbosity=2)
