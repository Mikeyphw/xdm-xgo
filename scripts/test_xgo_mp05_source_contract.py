#!/usr/bin/env python3
"""MP05 fail-closed source, security, and hosted test-routing contract."""
from __future__ import annotations
import os,re,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
APP='app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/'
def source(path):return (ROOT/path).read_text(encoding='utf-8')
class MP05Contracts(unittest.TestCase):
 def test_store_real_durable_order_and_failclosed_recovery(self):
  s=source('engine/media/fragment_store.go')
  for x in ('WriteAndCommitFragment(', 'f.Sync()', 'os.Rename(temp, path)', 'fragmentSyncDir(dir)',
            's.writeJournalLocked(next)', 's.verifyLocked(input)', 'func (s *FileFragmentStore) Reconcile()',
            'func (s *FileFragmentStore) VerifyCommitted(', 'ErrFragmentStale', 'ErrFragmentQuota',
            'info.Mode().IsRegular()', 'rec.DurableBytesWritten = false', 'func StorageCapacity('):
   self.assertIn(x,s,x)
  self.assertLess(s.index('fragmentAtomicWrite(target, payload, s.fail)'),s.index('s.writeJournalLocked(next)'))
  self.assertLess(s.index('s.writeJournalLocked(next)'),s.index('s.verifyLocked(input)'))
  self.assertNotIn('os.WriteFile(target',s)
  # Inspect real Go imports and network calls, not the prose comment that
  # explains why HTTP headers must never be stored in the fragment journal.
  imports=s.split('import (',1)[1].split('\n)',1)[0]
  self.assertNotIn('"net/http"',imports)
  self.assertNotRegex(s, r'\bhttp\s*\.\s*(?:Get|Post|NewRequest|DefaultClient|Client)\b')
 def test_hls_dash_cannot_invent_committed_fragment_receipts(self):
  for p in ('engine/media/hls_execution.go','engine/media/dash.go'):
   s=source(p)
   self.assertIn('BindDurableStore(store DurableFragmentSink)',s)
   self.assertIn('e.store.WriteAndCommitFragment(ctx,',s)
   self.assertIn('e.store.VerifyCommitted(',s)
   self.assertIn('e.ledger.Commit(receipt)',s)
   self.assertNotIn('LocalArtifactRef: artifact, DurableBytesWritten: true',s)
   self.assertNotIn('LocalArtifactRef: art, DurableBytesWritten: true',s)
   self.assertIn('"init"',s)
   self.assertIn('durable_store_required',s)
 def test_mp05_ci_hf03_real_go_kotlin_compiler_boundaries(self):
  hls=source('engine/media/hls_execution.go')
  imports=hls.split('import (',1)[1].split('\n)',1)[0]
  self.assertIn('"encoding/hex"',imports)
  self.assertIn('hex.DecodeString(raw)',hls)
  self.assertEqual(imports.count('"encoding/hex"'),1)
  kotlin=source(APP+'AndroidDurableFragmentStore.kt')
  self.assertNotIn('OsConstants.O_DIRECTORY',kotlin)
  self.assertIn('require(dir.isDirectory && canonicalChild(dir))',kotlin)
  self.assertIn('Os.open(dir.absolutePath, OsConstants.O_RDONLY, 0)',kotlin)
  self.assertIn('try { Os.fsync(fd) } finally { Os.close(fd) }',kotlin)
  self.assertIn('FileOutputStream(temp)',kotlin)
  self.assertIn('output.fd.sync()',kotlin)
  dispatcher=source(APP+'AndroidPlatformRequestDispatcher.kt')
  self.assertRegex(dispatcher,r'(?m)^internal class AndroidPlatformRequestDispatcher\(')
  self.assertIn('private val fragmentStore: AndroidDurableFragmentStore,',dispatcher)
  self.assertIn('fragmentStore.execute(payload)',dispatcher)
 def test_android_bridge_is_typed_bounded_and_non_blocking(self):
  go=source('engine/runtime/android_fragment_store.go')
  broker=source('engine/runtime/platform/broker.go')
  dispatcher=source(APP+'AndroidPlatformRequestDispatcher.kt')
  authority=source(APP+'AndroidEngineProcessAuthority.kt')
  for val in ('"android_fragment_store"','AndroidFragmentStore,'):
   self.assertIn(val,broker)
  for val in ('platform.AndroidFragmentStore','WriteAndCommitFragment(', 'VerifyCommitted(',
              'receiptMatches(', 'mp05MaxBridgeFragmentBytes', '"body_base64"'):
   self.assertIn(val,go)
  self.assertIn('request.optString("kind") == "android_fragment_store"',dispatcher)
  self.assertIn('mediaToolScope.launch',dispatcher)
  self.assertIn('fragmentStore.execute(payload)',dispatcher)
  self.assertIn('AndroidDurableFragmentStore(appContext)',authority)
  self.assertNotIn('Log.',go+dispatcher)
 def test_android_private_storage_privacy_no_ready_or_cutover(self):
  kotlin=source(APP+'AndroidDurableFragmentStore.kt')
  for val in ('context.applicationContext.filesDir', 'MediaRequestHandoffStore.forCapture(capture)',
              'handoff.expiresAtEpochMs', 'FileOutputStream(temp)', 'output.fd.sync()',
              'Os.rename(', 'Os.fsync(', 'readJournal()', 'checkReceipt(',
              'MaxFragmentBytes = 2 * 1024 * 1024', 'MaxQuotaBytes = 512L * 1024L * 1024L',
              '"write" -> write(payload)', '"verify" -> verify(payload)', '"reconcile" -> reconcile()'):
   self.assertIn(val,kotlin,val)
  for val in ('Log.', 'CookieManager', 'SharedPreferences', 'externalStorage',
              'getExternalFilesDir', 'payload.optString("url")', 'body_secret', 'DownloadReady: true'):
   self.assertNotIn(val,kotlin)
  fallback=source(APP+'AndroidMediaPlatformBroker.kt')
  self.assertIn('"finalize_adaptive"',fallback)
  self.assertIn('FfmpegOperation.FinalizeAdaptive(',fallback)
  self.assertNotIn('AndroidDurableFragmentStore',fallback)
 def test_real_crash_and_negative_fixtures_present(self):
  fixture=source('engine/media/fragment_store_test.go')
  for val in ('TestMP05STORE01VerifiedBytesAndRestart', 'TestMP05STORE02Through05CrashPhases',
              'before_write', 'after_write', 'after_fsync', 'after_rename', 'after_journal',
              'TestMP05STORE06GenerationAndDuplicateOwner','TestMP05STORE07CorruptedDigestAndReconcile',
              'TestMP05STORE08QuotaAndLargeIntegerBoundary','TestMP05STORE09InitRangeAndKeyRejection',
              'TestMP05STORE10ConcurrentCommitExactlyOnce','TestMP05StoreSymlinkRootRefused'):
   self.assertIn(val,fixture,val)
  # Go shifts permit whitespace either side of <<; require both 4 GiB+ probes
  # rather than testing a formatting convention.
  self.assertGreaterEqual(len(re.findall(r'\b1\s*<<\s*32\b',fixture)),2)
  self.assertIn('NewFileFragmentStore(t.TempDir()',source('engine/media/hls_execution_test.go'))
  self.assertIn('NewFileFragmentStore(t.TempDir()',source('engine/media/dash_test.go'))
 def test_mp05_aes128_transport_vs_plaintext_and_key_privacy(self):
  store=source('engine/media/fragment_store.go')
  timeline=source('engine/media/hls_timeline.go')
  tests=source('engine/media/fragment_store_test.go')
  lineage=source('engine/media/hls_timeline_test.go')
  self.assertIn('func fragmentStoredRangeAllowed(',store)
  self.assertIn('!fragmentStoredRangeAllowed(input, int64(len(payload)))',store)
  self.assertIn('strings.HasPrefix(input.Identity.EncryptionID, "aes-128:hls-key_")',store)
  self.assertIn('paddingBytes >= 1 && paddingBytes <= 16',store)
  self.assertIn('input.Identity.Protocol == FragmentProtocolHLS && input.Role == "media"',store)
  self.assertIn('strings.Contains(input.Identity.EncryptionID, "://")',store)
  self.assertIn('digestID("hls-key",',timeline)
  self.assertNotIn('string(seg.Key.Method), seg.Key.ResolvedURI, seg.Key.IV',timeline)
  for test in ('TestMP05STORE11AES128CipherRangePlaintextReadback',
               'TestMP05STORE12AES128RangeBypassFailsClosed'):
   self.assertIn(test,tests)
  self.assertIn('TestMP05HLSKeyIdentityDoesNotRetainSignedURL',lineage)
 def test_ci05_exact_go_android_mandatory(self):
  policy=source('scripts/ci/xgo_ci_policy.py')
  workflow=source('.github/workflows/xgo-targeted.yml')
  for item in ('MP05_PYTHON = [','test_xgo_mp05_source_contract.py','test_xgo_mp05_staleness_audit.py',
               'tests.update(MP05_PYTHON)', 'subprocess.run(["go", "test", "./..."]',
               '"app/XDM.Android/app/src/"'):
   self.assertIn(item,policy)
  for item in ('actions/setup-go@v6','go-version-file: engine/go.mod',
               'if: needs.scope.outputs.needs_go', ':app:compileDebugKotlin',
               'test "$SOURCE" = success', 'test "$ANDROID" = success'):
   self.assertIn(item,workflow)
  self.assertNotIn('curl | bash',policy)
if __name__=='__main__':unittest.main(verbosity=2)
