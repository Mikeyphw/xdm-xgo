#!/usr/bin/env python3
"""MP06 Go/Kotlin security and CI05 source contract; no stale string-format assumptions."""
from pathlib import Path
import re, unittest
ROOT=Path(__file__).resolve().parents[1]
def read(path):return (ROOT/path).read_text(encoding='utf-8')
class MP06SourceContract(unittest.TestCase):
 def test_master_selection_is_scoped_and_split_audio_is_explicit(self):
  src=read('engine/media/hls_vod_session.go')
  compact=re.sub(r'\s+','',src)
  for a in ('func PlanHLSVOD(req HLSVODRequest)', 'master.Kind!=HLSPlaylistMaster',
            'master.Variants[i].ResolvedURI!=req.VideoURI', 'rendition.GroupID==selected.AudioGroup',
            'mp06MediaPlan("audio",req.AudioURI,req.AudioBody)', 'HLSProtectionAES128',
            'strings.TrimSpace(initKey.IV)', 'result.ExpectedParts++', 'result.ExplicitGaps++'):
   self.assertIn(re.sub(r'\s+','',a),compact,a)
  self.assertNotRegex(src,r'\bhttp\s*\.\s*(Get|Post|Client|NewRequest)\s*\(')
  self.assertNotIn('log.',src)
 def test_required_output_never_equates_staging_with_completed_download(self):
  src=read('engine/media/hls_vod_session.go')
  compact=re.sub(r'\s+','',src)
  self.assertIn('DownloadReady:false',compact)
  self.assertIn('NeedsEmbeddedAudioProof',src)
  self.assertIn('sink.VerifyCommitted(record)',compact)
  self.assertIn('receipt.ReadyForMux=true',compact)
  self.assertNotIn('receipt.DownloadReady=true',compact)
  self.assertIn('ifctx==nil||fetcher==nil||videoStore==nil||(len(plan.Tracks)==2&&audioStore==nil)',compact)
 def test_encrypted_init_map_is_plaintext_verified_not_key_persisted(self):
  src=read('engine/media/hls_execution.go')
  snippet=src.split('func (e *HLSExecutor) executeSegment(',1)[1].split('\nfunc DecryptHLSAES128(',1)[0]
  for a in ('encrypted_init_requires_explicit_iv','HLSFetchInitMap','HLSFetchKey',
            'DecryptHLSAES128(initBytes, key.Bytes', 'identity.Range = nil',
            'digestID("hls-init-key",',
            'e.store.WriteAndCommitFragment(ctx, initRecord, initBytes)', 'e.store.VerifyCommitted(receipt)'):
   self.assertIn(a,snippet,a)
  self.assertNotIn('Role: "key"',snippet)
  self.assertIn('HLSExecutionPartial',src)
  self.assertRegex(src,r'if\s+result\.Gaps\s*>\s*0')
 def test_kotlin_partial_gap_gate_does_not_break_fallback(self):
  src=read('app/XDM.Android/media/src/main/kotlin/com/mikeyphw/xdm/android/media/NativeHlsExecutionEngine.kt')
  self.assertIn('val hasExplicitGaps = plan.parts.any { it.gap }',src)
  self.assertIn('&& !hasExplicitGaps',src)
  self.assertIn('Explicit HLS gaps require partial recovery, not Completed.',src)
  self.assertIn('NativeHlsSupportStatus.Supported',src)
  self.assertIn('NativeHlsExecutionStage.Completed',src)
 def test_hls01_to_hls14_and_init_map_privacy_cases_mandatory(self):
  src=read('engine/media/hls_vod_session_test.go')
  for i in range(1,15):self.assertRegex(src,rf'func TestMP06HLS{i:02d}[A-Za-z_0-9]*\(')
  for a in ('ReadVerified(rec.Identity)','ErrHLSVODIncomplete','ExplicitGapReportsPartial','AES128EncryptedInitMapDecryptedAndStored','MissingDurableAudioStoreFailClosedPreflight'):
   self.assertIn(a,src,a)
 def test_inherited_mp05_audit_requires_exact_kotlin_fallback_diff(self):
  inherited=read('scripts/test_xgo_mp05_staleness_audit.py')
  self.assertIn('def test_kotlin_hls_fallback_preserved_except_mp06_gap_gate',inherited)
  self.assertIn('staged.count(new_valid)',inherited)
  self.assertIn('staged.count(new_reason)',inherited)
  self.assertIn('self.assertEqual(reconstructed,original',inherited)
  self.assertNotIn('def test_kotlin_hls_fallback_untouched(self)',inherited)
  extended=read('scripts/test_xgo_mp06_staleness_audit.py')
  self.assertIn('test_original_kotlin_hls_executor_remains_except_exact_mp06_gap_gate',extended)
  self.assertIn('now.replace(new_valid,old_valid,1).replace(new_reason,old_reason,1)',extended)
 def test_init_map_declaration_key_is_separate_from_segment_key(self):
  parser=read('engine/media/hls.go')
  execution=read('engine/media/hls_execution.go')
  planner=read('engine/media/hls_vod_session.go')
  fixtures=read('engine/media/hls_map_key_binding_test.go')
  self.assertIn('Key              *HLSKey',parser)
  self.assertIn('m.Key = cloneHLSKey(currentKey)',parser)
  self.assertIn('c.Key = cloneHLSKey(m.Key)',parser)
  self.assertRegex(execution,r'initKey\s*:=\s*seg\.Map\.Key')
  self.assertIn('DecryptHLSAES128(initBytes, key.Bytes, initKey.IV',execution)
  self.assertIn('digestID("hls-init-key",',execution)
  self.assertIn('initKey := seg.Map.Key',execution)
  self.assertNotIn('identity.EncryptionID = entry.Identity.EncryptionID',execution)
  self.assertRegex(planner,r'initKey\s*:=\s*seg\.Map\.Key')
  self.assertNotIn('seg.Map != nil && seg.Key != nil && seg.Key.Method == HLSProtectionAES128',planner)
  for id in ('MapBeforeKeyKeepsInitClear','EncryptedInitRequiresExplicitIV',
             'EncryptedInitDecryptsWithDeclarationKey','KeyRotationDoesNotRebindInit',
             'SignedInitKeyNotJournaled'):
   self.assertIn('TestMP06HF02'+id,fixtures)
 def test_ci05_runs_mp06_and_compiles_media_module(self):
  policy=read('scripts/ci/xgo_ci_policy.py')
  for a in ('MP06_PYTHON = [','tests.update(MP06_PYTHON)',
            'scripts/test_xgo_mp06_source_contract.py','scripts/test_xgo_mp06_staleness_audit.py',
            '"app/XDM.Android/media/src/"', 'subprocess.run(["go", "test", "./..."]'):
   self.assertIn(a,policy,a)
  test=read('scripts/ci/test_xgo_ci_policy.py')
  self.assertIn('def test_mp06_hls_source_and_android_compile_route_to_real_contracts',test)
  workflow=read('.github/workflows/xgo-targeted.yml')
  self.assertIn('python3 -B scripts/ci/xgo_ci_policy.py run-targeted',workflow)
  self.assertIn(':app:compileDebugKotlin',workflow)
if __name__=='__main__':unittest.main(verbosity=2)
