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
     'Enable runner KVM for real API36 instrumentation',
     'MP08B3_KVM_OPEN_PASS', 'MP08B3_KVM_ACCESS_READY',
     'android-emulator-runner@', 'api-level: 36', 'target: google_apis',
     'arch: x86_64', 'testInstrumentationRunnerArguments.class=com.mikeyphw.xdm.android.MP08B3MediaStoreAcceptanceInstrumentedTest',
     ':app:compileDebugAndroidTestKotlin', 'mp08b3_real_media.py',
     'Install pinned Ubuntu 24.04 FFmpeg and FFprobe',
     'sudo apt-get update -qq',
     'apt-get install -y --no-install-recommends ffmpeg',
     'MP08B3_HOST_FFMPEG_6_1_1_READY',
     "for tool in ('ffmpeg', 'ffprobe'):",
     "subprocess.check_output([tool, '-version'], text=True)",
     "if not re.match(rf'^{tool} version 6\\.1\\.1(?:[-+.]|$)', line):",
     "raise SystemExit('MP08B3_FFMPEG_6_1_1_REQUIRED: '",
     'scripts/test_xgo_mp08b3_source_contract.py',
     'test "$EMULATOR" = success',
     'test "$OPTED_IN" = true', 'test "$SOURCE" = success',
     "github.event.action == 'labeled'",
     "github.event.label.name == 'xgo-mp08b3-api36'",
     'github.event.pull_request.head.repo.full_name == github.repository',
     'github.event.pull_request.head.sha || inputs.exact_head_sha',
     'test "$PR_HEAD_REPO" = "$REPOSITORY"',
     'test "$IS_LABEL_EVENT" = true',
     'types: [opened, reopened, synchronize, ready_for_review, labeled]',
     'if: >-'))
 # Both the emulator and final receipt must be gated by an explicit
 # same-repository label, rather than silently activating on ordinary PR sync.
 if s.count("github.event.label.name == 'xgo-mp08b3-api36'") < 4 or s.count('github.event.pull_request.head.repo.full_name == github.repository') < 3:
  raise AssertionError('MP08B3_SOURCE_REFUSED: opt-in guard absent from a job')
 if s.count('github.event.pull_request.head.sha || inputs.exact_head_sha') != 4:
  raise AssertionError('MP08B3_SOURCE_REFUSED: explicit PR head SHA binding weakened')
 if s.count('github.event_name == \'workflow_dispatch\'') < 3:
  raise AssertionError('MP08B3_SOURCE_REFUSED: original manual trigger removed')
 if s.index('Install pinned Ubuntu 24.04 FFmpeg and FFprobe') > s.index('Run real FFmpeg with local video and audio sources'):
  raise AssertionError('MP08B3_SOURCE_REFUSED: FFmpeg setup must precede playback')
 if re.search(r'(?m)^\s*x86_64_media_test:\s*true\s*$',s) or 'default: true' in s:
  raise AssertionError('MP08B3_SOURCE_REFUSED: test-only ABI must default disabled')
 if 'continue-on-error: true' in s or '|| true' in s or 'if-no-files-found: ignore' in s:
  raise AssertionError('MP08B3_SOURCE_REFUSED: silent hosted qualification bypass')

def kvm_bootstrap_contract(s):
 # Contract based on the actual incident: exact SHA and label evidence must
 # precede KVM permission setup, which must precede any emulator invocation.
 require(s, ('Refuse missing exact SHA or wrong PR provenance',
   'Enable runner KVM for real API36 instrumentation',
   'MP08B3_KVM_ACCESS_READY', 'MP08B3_KVM_OPEN_PASS'))
 job=s.split('  api36-real-android:',1)[1].split('  manual-qualification:',1)[0]
 order=('Refuse missing exact SHA or wrong PR provenance',
        'Enable runner KVM for real API36 instrumentation',
        'Provision API36 image and emulator host dependencies',
        'API36 instrumentation, real MediaStore and required attested FFmpeg/FFprobe')
 if [job.index(x) for x in order]!=sorted(job.index(x) for x in order):
  raise AssertionError('MP08B3_SOURCE_REFUSED: KVM bootstrap after emulator')
 bootstrap=job.split('      - name: Enable runner KVM for real API36 instrumentation',1)[1].split('      - uses: actions/setup-java@v4',1)[0]
 require(bootstrap, ('set -euo pipefail',
   'if [[ ! -c /dev/kvm ]]; then',
   'MP08B3 KVM missing',
   'if [[ ! -r /dev/kvm || ! -w /dev/kvm ]]; then',
   'sudo chown "$(id -u):$(id -g)" /dev/kvm',
   'sudo chmod 0600 /dev/kvm',
   'test -r /dev/kvm && test -w /dev/kvm || {',
   'MP08B3 KVM permission denied',
   "fd = os.open('/dev/kvm', os.O_RDWR | os.O_CLOEXEC)",
   'os.close(fd)',
   "print('MP08B3_KVM_OPEN_PASS')",
   "echo 'MP08B3_KVM_ACCESS_READY'"))
 if bootstrap.count('exit 1') < 2:
  raise AssertionError('MP08B3_SOURCE_REFUSED: must fail closed for missing KVM')
 if bootstrap.index('test -r /dev/kvm && test -w /dev/kvm') > bootstrap.index('os.open('):
  raise AssertionError('MP08B3_SOURCE_REFUSED: KVM validation out of order')
 if 'continue-on-error:' in bootstrap or '|| true' in bootstrap:
  raise AssertionError('MP08B3_SOURCE_REFUSED: no bypass of KVM readiness')

def api36_execution_contract(s):
 # Triggered by real HF03 incident 42893899222: emulator boots, runner
 # invokes `sh -c`, and bare `set -euo pipefail` fails before Gradle.
 job = s.split('  api36-real-android:', 1)[1].split('  manual-qualification:', 1)[0]
 name = '      - name: API36 instrumentation, real MediaStore and required attested FFmpeg/FFprobe'
 if job.count(name) != 1: raise AssertionError('MP08B3_API36_REFUSED: missing action')
 stage = job.split(name, 1)[1]
 if stage.count('          script: |\n') != 1:
  raise AssertionError('MP08B3_API36_REFUSED: inline script anchor changed')
 raw = stage.split('          script: |\n', 1)[1]
 if any(line.strip() and not line.startswith('            ') for line in raw.splitlines()):
  raise AssertionError('MP08B3_API36_REFUSED: malformed YAML script indentation')
 script = '\n'.join(line[12:] for line in raw.splitlines()) + '\n'
 require(script, ("bash -euo pipefail <<'MP08B3_API36_BASH'",
   'MP08B3_API36_BASH\n', 'set -euo pipefail',
   "test \"$(adb shell getprop ro.build.version.sdk | tr -d '\\r')\" = 36",
   "test \"$(adb shell getprop ro.kernel.qemu | tr -d '\\r')\" = 1",
   'rm -rf app/build/outputs/androidTest-results/connected',
   ':app:connectedDebugAndroidTest',
   '-Pandroid.testInstrumentationRunnerArguments.class=com.mikeyphw.xdm.android.MP08B3MediaStoreAcceptanceInstrumentedTest',
   "python3 - <<'MP08B3_API36_JUNIT'",
   'MP08B3_API36_JUNIT\n',
   'xml.etree.ElementTree as ET',
   "root.rglob('*.xml')", "klass == suffix", 'len(names) != 4',
   'set(names) != expected', "('failure','error','skipped')",
   'MP08B3_API36_FOUR_REAL_INSTRUMENTATION_TESTS_PASS'))
 if script.splitlines()[3] != "bash -euo pipefail <<'MP08B3_API36_BASH'":
  raise AssertionError('MP08B3_API36_REFUSED: sh must launch Bash before pipefail')
 if script.count('MP08B3_API36_BASH') != 2 or script.count('MP08B3_API36_JUNIT') != 2:
  raise AssertionError('MP08B3_API36_REFUSED: unbalanced heredoc markers')
 if script.index('rm -rf app/build/outputs/androidTest-results/connected') > script.index('./gradlew'):
  raise AssertionError('MP08B3_API36_REFUSED: stale instrumentation receipt could be reused')
 if script.index('./gradlew') > script.index('python3 - <<'):
  raise AssertionError('MP08B3_API36_REFUSED: evidence read before Gradle tests')
 if any(marker in script for marker in ('|| true', 'continue-on-error:', 'Assume.', '@Ignore', 'pytest.skip')):
  raise AssertionError('MP08B3_API36_REFUSED: acceptance bypass')
 # Runs without Android, but under the EXACT POSIX shell used by emulator-runner.
 # No dependency on YAML parser or native emulator for this stage contract.
 import subprocess
 parsed = subprocess.run(['/bin/sh','-n','-c',script], capture_output=True, text=True)
 if parsed.returncode:
  raise AssertionError('MP08B3_API36_REFUSED: sh script parse failed: '+parsed.stderr)
 return script

def execute_api36_mock(script, *, api='36', qemu='1', suite='pass', gradle_rc=0):
 import tempfile, subprocess, os, stat, html
 from pathlib import Path
 with tempfile.TemporaryDirectory(prefix='mp08b3-api36-shell-') as t:
  root=Path(t); bin=root/'bin'; bin.mkdir()
  adb=bin/'adb'
  adb.write_text('#!/bin/sh\ncase "$*" in\n'
   '"shell getprop ro.build.version.sdk") echo "'+api+'" ;;\n'
   '"shell getprop ro.kernel.qemu") echo "'+qemu+'" ;;\n'
   '*) exit 22 ;;\nesac\n', encoding='utf-8')
  adb.chmod(0o755)
  android=root/'app/XDM.Android'; android.mkdir(parents=True)
  gradle=android/'gradlew'
  tests=['b3_01RealMediaStorePublicationReadbackAndIdempotency',
   'b3_02NoAuthorizationAndCorruptedCandidateFailClosed',
   'b3_03InterruptedPendingMediaStoreRowIsReconciled',
   'b3_04RealEmbeddedFfmpegProbeMuxAndMediaStoreRoundTrip']
  kind=tests if suite not in ('missing','three','wrong') else tests[:3]
  if suite=='wrong':kind=tests[:3]+['unrelated_nonreal_test']
  if suite=='duplicate':kind=tests+[tests[0]]
  xml='<testsuite>'+''.join('<testcase classname="com.mikeyphw.xdm.android.MP08B3MediaStoreAcceptanceInstrumentedTest" name="'+html.escape(n,quote=True)+'">'+(
   '<skipped/>' if suite=='skipped' and i==0 else '<failure/>' if suite=='fail' and i==0 else '')+'</testcase>' for i,n in enumerate(kind))+'</testsuite>'
  gradle.write_text('#!/bin/sh\n[ "$#" -ge 3 ] || exit 99\n'
   'case "$*" in *:app:connectedDebugAndroidTest*) ;; *) exit 98 ;; esac\n'
   'case "$*" in *testInstrumentationRunnerArguments.class=com.mikeyphw.xdm.android.MP08B3MediaStoreAcceptanceInstrumentedTest*) ;; *) exit 97 ;; esac\n'
   'mkdir -p app/build/outputs/androidTest-results/connected\n'
   + ('printf %s '+repr(xml)+ ' > app/build/outputs/androidTest-results/connected/TEST-mock.xml\n' if suite!='missing' else '')
   +'exit '+str(gradle_rc)+'\n',encoding='utf-8')
  gradle.chmod(0o755)
  env={**os.environ,'PATH':str(bin)+os.pathsep+os.environ.get('PATH',''),'TMPDIR':str(root)}
  return subprocess.run(['/bin/sh','-c',script],cwd=root,env=env,capture_output=True,text=True,timeout=15)

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
 def test_kvm_bootstrap_fails_closed(self):kvm_bootstrap_contract(read(WORKFLOW))
 def test_api36_real_posix_sh_launch_and_mocked_junit_receipts(self):
  script=api36_execution_contract(read(WORKFLOW))
  p=execute_api36_mock(script)
  self.assertEqual(p.returncode,0, (p.stdout,p.stderr))
  self.assertIn('MP08B3_API36_FOUR_REAL_INSTRUMENTATION_TESTS_PASS',p.stdout)
  for scenario in ('missing','three','wrong','duplicate','skipped','fail'):
   with self.subTest(scenario=scenario):
    bad=execute_api36_mock(script,suite=scenario)
    self.assertNotEqual(bad.returncode,0, (bad.stdout,bad.stderr))
    self.assertNotIn('MP08B3_API36_FOUR_REAL_INSTRUMENTATION_TESTS_PASS',bad.stdout)
  for settings in ({'api':'35'},{'qemu':'0'},{'gradle_rc':1}):
   with self.subTest(settings=settings):
    bad=execute_api36_mock(script,**settings)
    self.assertNotEqual(bad.returncode,0,(bad.stdout,bad.stderr))
    self.assertNotIn('MP08B3_API36_FOUR_REAL_INSTRUMENTATION_TESTS_PASS',bad.stdout)
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
   (workflow_contract,w.replace('ready_for_review, labeled','ready_for_review',1)),
   (workflow_contract,w.replace('test "$PR_HEAD_REPO" = "$REPOSITORY"','echo skip-repo',1)),
   (workflow_contract,w.replace('test "$IS_LABEL_EVENT" = true','echo skip-event',1)),
   (workflow_contract,w.replace('github.event.pull_request.head.sha || inputs.exact_head_sha','inputs.exact_head_sha',1)),
   (workflow_contract,w.replace("github.event.label.name == 'xgo-mp08b3-api36'",'true',1)),
   (workflow_contract,w.replace('github.event.pull_request.head.repo.full_name == github.repository','true',1)),
   (kvm_bootstrap_contract,w.replace('if [[ ! -c /dev/kvm ]]; then','if false; then',1)),
   (kvm_bootstrap_contract,w.replace('sudo chown "$(id -u):$(id -g)" /dev/kvm','echo bypass-chown',1)),
   (kvm_bootstrap_contract,w.replace('sudo chmod 0600 /dev/kvm','echo bypass-chmod',1)),
   (kvm_bootstrap_contract,w.replace("os.open('/dev/kvm', os.O_RDWR | os.O_CLOEXEC)","os.stat('/dev/kvm')",1)),
   (kvm_bootstrap_contract,w.replace('MP08B3 KVM permission denied','KVM-check-removed',1)),
   (kvm_bootstrap_contract,w.replace('test -r /dev/kvm && test -w /dev/kvm || {','echo no-permission-gate',1)),
   (kvm_bootstrap_contract,w.replace('exit 1','echo continued',1)),
   (kvm_bootstrap_contract,w.replace('Enable runner KVM for real API36 instrumentation','KVM stage removed',1)),
   (api36_execution_contract,w.replace("bash -euo pipefail <<'MP08B3_API36_BASH'",'set -euo pipefail',1)),
   (api36_execution_contract,w.replace('MP08B3_API36_FOUR_REAL_INSTRUMENTATION_TESTS_PASS','forged green',1)),
   (api36_execution_contract,w.replace('len(names) != 4','len(names) < 1',1)),
   (api36_execution_contract,w.replace('set(names) != expected','False',1)),
   (api36_execution_contract,w.replace("('failure','error','skipped')","('failure',)",1)),
   (api36_execution_contract,w.replace('rm -rf app/build/outputs/androidTest-results/connected','echo stale-allowed',1)),
   (api36_execution_contract,w.replace(':app:connectedDebugAndroidTest',':app:compileDebugAndroidTestKotlin',1)),
   (workflow_contract,w.replace('test "$EMULATOR" = success','echo emulator-result',1)),
   (workflow_contract,w.replace(':app:compileDebugAndroidTestKotlin',':app:compileDebugKotlin',1)),
   (workflow_contract,w.replace('sudo apt-get update -qq','echo unpinned-media',1)),
   (workflow_contract,w.replace('apt-get install -y --no-install-recommends ffmpeg','echo missing-ffmpeg',1)),
   (workflow_contract,w.replace('MP08B3_HOST_FFMPEG_6_1_1_READY','echo unqualified-version',1)),
   (workflow_contract,w.replace("if not re.match(rf'^{tool} version 6\\.1\\.1(?:[-+.]|$)', line):",'if False:',1)),
   (workflow_contract,w.replace('Install pinned Ubuntu 24.04 FFmpeg and FFprobe','Moved setup after media',1)),
   (host_contract,h.replace('verify(ffmpeg, ffprobe, corrupt, audio=True)','pass # removed decode negative',1)),
   (host_contract,h.replace("'publication_qualified': False", "'publication_qualified': True",1)),
  ]
  for idx,(fn,bad) in enumerate(candidates):
   with self.subTest(index=idx),self.assertRaises(AssertionError):fn(bad)

if __name__=='__main__':unittest.main(verbosity=2)
