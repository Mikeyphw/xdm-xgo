#!/usr/bin/env python3
"""MP08B3 exact-source and adversarial contract; no false device acceptance."""
from __future__ import annotations
import pathlib,re,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
ANDROID='app/XDM.Android/app/src/androidTest/kotlin/com/mikeyphw/xdm/android/MP08B3MediaStoreAcceptanceInstrumentedTest.kt'
WORKFLOW='.github/workflows/xgo-mp08b3-acceptance.yml'
HOST='tests/media-parity/mp08b3_real_media.py'

def read(path):return (ROOT/path).read_text(encoding='utf-8')
def require(haystack, values):
 for value in values:
  if value not in haystack:raise AssertionError('MP08B3_SOURCE_REFUSED: '+value)

def android_test_contract(s):
 require(s, ('class MP08B3MediaStoreAcceptanceInstrumentedTest',
   'MediaRequestHandoffStore.rememberCapture(',
   'MediaRequestHandoffStore.forgetCapture(capture)',
   'AndroidMP08PublicationBroker(context, runtime)',
   'MediaStore.MediaColumns.IS_PENDING',
   'b3_01RealMediaStorePublicationReadbackAndIdempotency',
   'b3_02NoAuthorizationAndCorruptedCandidateFailClosed',
   'b3_03InterruptedPendingMediaStoreRowIsReconciled',
   'b3_04RealEmbeddedFfmpegProbeMuxAndMediaStoreRoundTrip',
   'runtime.capabilities(force = true)', 'FfmpegPostProcessor(runtime,',
   'assertEquals(1, probe.videoStreams.size)', 'assertEquals(1, probe.audioStreams.size)',
   'publisher.execute(seedVerifiedCandidate(bytes))',
   'assertArrayEquals(bytes, context.contentResolver.openInputStream(uri)!!',
   'assertFalse("Android may never assert DownloadReady"',
   'assertFalse("orphan transaction must be removed"',
   'output.appendBytes(', 'assertFalse(tampered.toString()',
   'assertFalse(unauth.toString()'))
 if re.search(r'(?m)@Ignore\b|\bAssume\.|\bassumeTrue\s*\(|\bassumeFalse\s*\(',s):
  raise AssertionError('MP08B3_SOURCE_REFUSED: skipped device test')
 if len(re.findall(r'(?m)^\s*@Test\s*$',s))!=4:
  raise AssertionError('MP08B3_SOURCE_REFUSED: exact four non-skipped tests required')

def workflow_contract(s):
 require(s, ('pull_request:', 'workflow_dispatch:', 'exact_head_sha:',
     'x86_64_media_test:', 'default: false',
     'github.event_name == \'workflow_dispatch\' && inputs.x86_64_media_test == true',
     'test "$(git rev-parse HEAD)" = "$EXPECTED"',
     'test "$BRANCH_SHA" = "$EXPECTED"',
     'test -r /dev/kvm && test -w /dev/kvm',
     'android-emulator-runner@', 'api-level: 36', 'target: google_apis',
     'arch: x86_64', 'testInstrumentationRunnerArguments.class=com.mikeyphw.xdm.android.MP08B3MediaStoreAcceptanceInstrumentedTest',
     ':app:compileDebugAndroidTestKotlin', 'mp08b3_real_media.py',
     'scripts/test_xgo_mp08b3_source_contract.py',
     'test "$EMULATOR" = success',
     'test "$OPTED_IN" = true', 'test "$SOURCE" = success',
     'if: always() && github.event_name == \'workflow_dispatch\''))
 if re.search(r'(?m)^\s*x86_64_media_test:\s*true\s*$',s) or 'default: true' in s:
  raise AssertionError('MP08B3_SOURCE_REFUSED: test-only ABI must default disabled')
 if 'continue-on-error: true' in s or '|| true' in s or 'if-no-files-found: ignore' in s:
  raise AssertionError('MP08B3_SOURCE_REFUSED: silent hosted qualification bypass')

def host_contract(s):
 require(s, ('testsrc2=size=160x90:rate=10', 'sine=frequency=440:sample_rate=44100',
   "'-map', '0:v:0', '-map', '1:a:0'", "'-c', 'copy'", 
   "'-xerror'", 'sha256(corrupt)', 'verify(ffmpeg, ffprobe, corrupt, audio=True)',
   'verify(ffmpeg, ffprobe, video, audio=True)',
   "'android_qualified': False", "'physical_arm64_qualified': False",
   "'publication_qualified': False", 'MP08B3_LINUX_REAL_MEDIA_ACCEPTANCE_PASS'))
 if 'assume' in s.lower() and 'not assume' not in s.lower():
  raise AssertionError('MP08B3_SOURCE_REFUSED: unknown acceptance assumption')

class MP08B3Contracts(unittest.TestCase):
 def test_android_real_mediastore_instrumentation(self):android_test_contract(read(ANDROID))
 def test_manual_emulator_gated_and_fail_closed(self):workflow_contract(read(WORKFLOW))
 def test_host_real_media_and_negative_cases(self):host_contract(read(HOST))
 def test_prior_production_guards_not_replaced(self):
  for p in ('engine/media/verified_publication.go','engine/runtime/android_mp08_host.go',
            'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidMP08PublicationBroker.kt',
            '.github/workflows/xgo-targeted.yml', 'scripts/test_xgo_mp08_source_contract.py'):
   self.assertTrue((ROOT/p).is_file(),p)
  prod=read('app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidMP08PublicationBroker.kt')
  require(prod, ('MediaStore.MediaColumns.IS_PENDING, 1','MediaStore.MediaColumns.IS_PENDING, 0',
                 'recoverPending()', 'resolver.delete(uri, null, null)',
                 'verifyMediaStore(uriText, candidate.bytes, candidate.digest)',
                 '.put("download_ready", false)'))
 def test_negative_mutations(self):
  a=read(ANDROID);w=read(WORKFLOW);h=read(HOST)
  candidates=[
   (android_test_contract,a.replace('runtime.capabilities(force = true)','runtime.manifest()',1)),
   (android_test_contract,a.replace('@Test\n    fun b3_03','@Ignore\n    @Test\n    fun b3_03',1)),
   (android_test_contract,a.replace('assertFalse("Android may never assert DownloadReady"','assertTrue("Android may never assert DownloadReady"',1)),
   (workflow_contract,w.replace('default: false','default: true',1)),
   (workflow_contract,w.replace('test "$EMULATOR" = success','echo emulator-result',1)),
   (workflow_contract,w.replace(':app:compileDebugAndroidTestKotlin',':app:compileDebugKotlin',1)),
   (host_contract,h.replace('verify(ffmpeg, ffprobe, corrupt, audio=True)','pass # removed decode negative',1)),
   (host_contract,h.replace("'publication_qualified': False", "'publication_qualified': True",1)),
  ]
  for idx,(fn,bad) in enumerate(candidates):
   with self.subTest(index=idx),self.assertRaises(AssertionError):fn(bad)

if __name__=='__main__':unittest.main(verbosity=2)
