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
     'arch: x86_64', 'script: python3 -B scripts/test_xgo_mp08b3_source_contract.py --api36-execute',
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
 if s.count("github.event.label.name == 'xgo-mp08b3-api36'") != 5 or s.count('github.event.pull_request.head.repo.full_name == github.repository') != 4:
  raise AssertionError('MP08B3_SOURCE_REFUSED: opt-in guard absent from a job')
 if s.count('github.event.pull_request.head.sha || inputs.exact_head_sha') != 5:
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
 bootstrap=job.split('      - name: Enable runner KVM for real API36 instrumentation',1)[1].split('      - uses: actions/setup-java@v6',1)[0]
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
 """Match emulator-runner's actual behavior: ONE shell command per line."""
 job = s.split('  api36-real-android:', 1)[1].split('  manual-qualification:', 1)[0]
 stage_name = '      - name: API36 instrumentation, real MediaStore and required attested FFmpeg/FFprobe'
 if job.count(stage_name) != 1:
  raise AssertionError('MP08B3_API36_REFUSED: missing uniquely named job')
 stage = job.split(stage_name,1)[1]
 require(stage, (
  'uses: ReactiveCircus/android-emulator-runner@a421e43855164a8197daf9d8d40fe71c6996bb0d',
  'MP08B3_EXPECTED_HEAD: ${{ github.event.pull_request.head.sha || inputs.exact_head_sha }}',
  "MP08B3_OPTED_IN: ${{ (github.event_name == 'workflow_dispatch' && inputs.x86_64_media_test == true) ||",
  "github.event.label.name == 'xgo-mp08b3-api36'",
  'github.event.pull_request.head.repo.full_name == github.repository',
  'api-level: 36', 'arch: x86_64'))
 commands = re.findall(r'(?m)^\s*script:\s*(.+?)\s*$',stage)
 expected = 'python3 -B scripts/test_xgo_mp08b3_source_contract.py --api36-execute'
 if commands != [expected] or re.search(r'(?m)^\s*script:\s*[>|]\s*$',stage):
  raise AssertionError('MP08B3_API36_REFUSED: one-line POSIX-safe action command required')
 if 'continue-on-error: true' in stage or '|| true' in stage:
  raise AssertionError('MP08B3_API36_REFUSED: action failure bypass forbidden')
 # This command must parse and run under /bin/sh; no Bash or heredocs.
 import subprocess
 parsed=subprocess.run(['/bin/sh','-n','-c',commands[0]],capture_output=True,text=True)
 if parsed.returncode:raise AssertionError('MP08B3_API36_REFUSED: invalid POSIX action command')
 return expected

API36_CLASS='com.mikeyphw.xdm.android.MP08B3MediaStoreAcceptanceInstrumentedTest'
API36_CASES=frozenset((
 'b3_01RealMediaStorePublicationReadbackAndIdempotency',
 'b3_02NoAuthorizationAndCorruptedCandidateFailClosed',
 'b3_03InterruptedPendingMediaStoreRowIsReconciled',
 'b3_04RealEmbeddedFfmpegProbeMuxAndMediaStoreRoundTrip',
))
API36_SERIAL='emulator-5554'


def api36_receipt_contract(directory):
 """Strict, fresh, local JUnit evidence from Gradle connectedDebugAndroidTest."""
 from pathlib import Path
 import xml.etree.ElementTree as ET
 root=Path(directory)
 if not root.is_dir() or root.is_symlink():
  raise AssertionError('MP08B3_API36_REFUSED: fresh JUnit results directory absent')
 docs=sorted(root.rglob('*.xml'))
 if not docs or len(docs)>30:
  raise AssertionError('MP08B3_API36_REFUSED: no bounded fresh JUnit XML')
 matches=[]
 for file in docs:
  if file.is_symlink() or not file.is_file() or file.stat().st_size>5_000_000:
   raise AssertionError('MP08B3_API36_REFUSED: unsafe JUnit file')
  data=file.read_bytes()
  if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
   raise AssertionError('MP08B3_API36_REFUSED: untrusted XML DTD')
  try: report=ET.fromstring(data)
  except ET.ParseError as exc:
   raise AssertionError('MP08B3_API36_REFUSED: malformed JUnit XML') from exc
  for case in report.iter('testcase'):
   if case.get('classname','') == API36_CLASS:
    matches.append(case)
 names=[c.get('name') for c in matches]
 if len(names)!=4 or frozenset(names)!=API36_CASES:
  raise AssertionError('MP08B3_API36_REFUSED: four unique real tests required: '+repr(names))
 for case in matches:
  if any(case.find(tag) is not None for tag in ('failure','error','skipped')):
   raise AssertionError('MP08B3_API36_REFUSED: failed/skipped Android test '+str(case.get('name')))
 return True


def api36_sanitize_crash_line(raw):
 """Minimize exposed diagnostics: never include bearer data, URL signatures or cookies."""
 text = str(raw).replace('\x00', '')[:450]
 text = re.sub(r'(?i)\b(?:https?|ftp)://[^\s\]\[()<>]+', '[REDACTED_URL]', text)
 text = re.sub(r'(?i)\bbearer\s+[^\s,;]+', 'Bearer [REDACTED]', text)
 text = re.sub(r'(?i)\b(authorization|proxy-authorization|cookie|set-cookie|x-api-key|api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|signature|sig)\s*[:=]\s*[^\s,;]+', r'\1=[REDACTED]', text)
 text = re.sub(r'\b(?:[0-9a-f]{40,}|[A-Za-z0-9_\-]{120,})\b', '[REDACTED_ID]', text)
 return text


def api36_crash_excerpt(raw, max_lines=52):
 """Extract process-local failure signals; never upload an unfiltered logcat."""
 lines=str(raw).splitlines()
 anchors=re.compile(r'FATAL EXCEPTION|Fatal signal|java\.lang\.(?:UnsatisfiedLinkError|NoClassDefFoundError|ExceptionInInitializerError)|Process:\s*com\.mikeyphw\.xdm\.android|Instrumentation run failed|INSTRUMENTATION_FAILED|Abort message|AndroidJUnitRunner',re.I)
 windows=[]
 for idx,line in enumerate(lines):
  if anchors.search(line):
   start=max(0,idx-2)
   stop=min(len(lines),idx+19)
   chunk=lines[start:stop]
   # A foreign app cannot turn its own logcat into a project diagnostic.
   if not any(('com.mikeyphw.xdm.android' in x or 'AndroidJUnitRunner' in x or 'INSTRUMENTATION_FAILED' in x) for x in chunk):
    continue
   windows.extend(range(start,stop))
 picked=sorted(set(windows))[:max_lines]
 return [api36_sanitize_crash_line(lines[i]) for i in picked]


def api36_collect_crash_diagnostics():
 """Best-effort diagnostics only; this function NEVER turns a failed test green."""
 import subprocess
 print('MP08B3_API36_CRASH_DIAGNOSTIC_BEGIN',flush=True)
 total=0
 for buffer in ('crash','main','events'):
  try:
   p=subprocess.run(['adb','-s',API36_SERIAL,'logcat','-d','-b',buffer,'-v','brief','-t','1500'],
                    text=True,capture_output=True,timeout=22,check=False)
   if p.returncode:
    print('MP08B3_API36_LOGCAT_'+buffer.upper()+'_UNAVAILABLE',flush=True)
    continue
   for line in api36_crash_excerpt(p.stdout,max_lines=52 if buffer=='crash' else 36):
    print('MP08B3_API36_DIAG_'+buffer.upper()+': '+line,flush=True)
    total+=1
  except (OSError,subprocess.TimeoutExpired):
   print('MP08B3_API36_LOGCAT_'+buffer.upper()+'_UNAVAILABLE',flush=True)
 if not total:print('MP08B3_API36_NO_REDACTED_CRASH_TRACE_AVAILABLE',flush=True)
 print('MP08B3_API36_CRASH_DIAGNOSTIC_END',flush=True)
 return total


def run_api36_acceptance():
 """Executed only in an opt-in GitHub Actions API36 emulator job."""
 import os, shutil, subprocess
 from pathlib import Path
 env=os.environ
 if (env.get('GITHUB_ACTIONS'),env.get('RUNNER_OS'),env.get('GITHUB_REPOSITORY'),env.get('MP08B3_OPTED_IN')) != ('true','Linux','Mikeyphw/xdm-xgo','true'):
  raise AssertionError('MP08B3_API36_REFUSED: opt-in hosted runner provenance missing')
 expected=env.get('MP08B3_EXPECTED_HEAD','')
 if not re.fullmatch('[0-9a-f]{40}',expected):
  raise AssertionError('MP08B3_API36_REFUSED: missing exact PR head SHA')
 def run(argv,cwd=None,timeout=240):
  return subprocess.run(argv,cwd=cwd,check=True,text=True,capture_output=True,timeout=timeout).stdout.strip()
 repo=Path(__file__).resolve().parents[1]
 if run(['git','rev-parse','HEAD'],repo)!=expected:
  raise AssertionError('MP08B3_API36_REFUSED: checked-out git head mismatch')
 lines=run(['adb','devices','-l']).splitlines()
 devices=[line.split() for line in lines[1:] if line.strip()]
 if len(devices)!=1 or len(devices[0])<2 or devices[0][0]!=API36_SERIAL or devices[0][1]!='device':
  raise AssertionError('MP08B3_API36_REFUSED: exact single authorized emulator required')
 def prop(key):return run(['adb','-s',API36_SERIAL,'shell','getprop',key],timeout=25).strip()
 for key,required in (
  ('ro.build.version.sdk','36'),
  ('ro.kernel.qemu','1'),
  ('ro.product.cpu.abi','x86_64'),
  ('sys.boot_completed','1'),
 ):
  if prop(key)!=required:
   raise AssertionError('MP08B3_API36_REFUSED: wrong Android property '+key)
 print('MP08B3_API36_EXACT_HEAD_AND_EMULATOR_PASS',flush=True)
 android=repo/'app/XDM.Android'
 output=android/'app/build/outputs/androidTest-results/connected'
 if output.is_symlink() or any(node.is_symlink() for node in (output.parent,output.parent.parent,output.parent.parent.parent)):
  raise AssertionError('MP08B3_API36_REFUSED: unsafe JUnit output path')
 if output.exists():shutil.rmtree(output)
 result=subprocess.run(['./gradlew','--no-daemon','--max-workers=2',':app:connectedDebugAndroidTest',
  '-Pandroid.testInstrumentationRunnerArguments.class='+API36_CLASS],cwd=android,check=False,timeout=3600)
 if result.returncode!=0:
  api36_collect_crash_diagnostics()
  raise AssertionError('MP08B3_API36_REFUSED: real instrumentation Gradle failure rc='+str(result.returncode))
 api36_receipt_contract(output)
 print('MP08B3_API36_FOUR_REAL_INSTRUMENTATION_TESTS_PASS',flush=True)
 return True


def execute_api36_mock(command, *, sdk='36', qemu='1', abi='x86_64', boot='1', suite='pass', gradle_rc=0,
                      head=True, opted=True, offline=False, extra_device=False, crash_log=None):
 """Model the REAL action by invoking ONE command via /bin/sh -c."""
 import tempfile, subprocess, os, html
 from pathlib import Path
 with tempfile.TemporaryDirectory(prefix='mp08b3-linewise-') as t:
  root=Path(t);bin=root/'bin';bin.mkdir();scripts=root/'scripts';scripts.mkdir()
  (scripts/'test_xgo_mp08b3_source_contract.py').write_text(Path(__file__).read_text(),encoding='utf-8')
  mockhead='a'*40
  (bin/'git').write_text('#!/bin/sh\n[ "$*" = "rev-parse HEAD" ] || exit 5\necho '+(mockhead if head else 'b'*40)+'\n')
  import shlex
  diagnostic=crash_log if crash_log is not None else 'E AndroidRuntime: FATAL EXCEPTION: Instrumentation\nE AndroidRuntime: Process: com.mikeyphw.xdm.android.debug, PID: 4321\nE AndroidRuntime: java.lang.UnsatisfiedLinkError: dlopen failed: libexample.so not found'
  (root/'mock-crash.txt').write_text(diagnostic,encoding='utf-8')
  (bin/'adb').write_text('#!/bin/sh\n'
   'case "$*" in *" logcat -d -b crash "*) cat '+shlex.quote(str(root/'mock-crash.txt'))+'; exit 0 ;; esac\n'
   'case "$*" in *" logcat -d -b main "*) cat '+shlex.quote(str(root/'mock-crash.txt'))+'; exit 0 ;; esac\n'
   'if [ "$*" = "devices -l" ]; then\n'
   'printf "List of devices attached\\n'+API36_SERIAL+'\\t'+('offline' if offline else 'device')+' product:sdk\\n"\n'
   +('printf "other-1234\\tdevice\\n"\n' if extra_device else '')+
   'exit 0\nfi\n'
   'case "$*" in\n'
   '"-s emulator-5554 shell getprop ro.build.version.sdk") echo "'+sdk+'" ;;\n'
   '"-s emulator-5554 shell getprop ro.kernel.qemu") echo "'+qemu+'" ;;\n'
   '"-s emulator-5554 shell getprop ro.product.cpu.abi") echo "'+abi+'" ;;\n'
   '"-s emulator-5554 shell getprop sys.boot_completed") echo "'+boot+'" ;;\n'
   '*) exit 55 ;;\nesac\n')
  android=root/'app/XDM.Android';android.mkdir(parents=True)
  tests=sorted(API36_CASES)
  names=tests
  if suite=='three':names=tests[:3]
  if suite=='wrong':names=tests[:3]+['unrelated_case']
  if suite=='duplicate':names=tests+[tests[0]]
  if suite=='wrongclass':names=tests
  xml='<testsuite>'+''.join('<testcase classname="'+('not.the.test.Class' if suite=='wrongclass' else API36_CLASS)+'" name="'+html.escape(name,quote=True)+'">'+(
    '<skipped/>' if suite=='skipped' and i==0 else '<error/>' if suite=='error' and i==0 else '<failure/>' if suite=='fail' and i==0 else '')+'</testcase>' for i,name in enumerate(names))+'</testsuite>'
  if suite=='malformed':xml='<testsuite invalid'
  if suite=='dtd':xml='<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]>'+xml
  if suite=='missing':xml=''
  gradle=android/'gradlew'
  import shlex
  gradle.write_text('#!/bin/sh\n'
   'case "$*" in *:app:connectedDebugAndroidTest*) ;; *) exit 90 ;; esac\n'
   'case "$*" in *testInstrumentationRunnerArguments.class='+API36_CLASS+'*) ;; *) exit 91 ;; esac\n'
   'mkdir -p app/build/outputs/androidTest-results/connected\n'
   + ('printf %s '+shlex.quote(xml)+' > app/build/outputs/androidTest-results/connected/TEST-fresh.xml\n' if xml else '')
   +'exit '+str(gradle_rc)+'\n')
  for item in (bin/'git',bin/'adb',gradle):item.chmod(0o755)
  env={**os.environ,'PATH':str(bin)+os.pathsep+os.environ.get('PATH',''),
       'GITHUB_ACTIONS':'true','RUNNER_OS':'Linux','GITHUB_REPOSITORY':'Mikeyphw/xdm-xgo',
       'MP08B3_EXPECTED_HEAD':mockhead,'MP08B3_OPTED_IN':'true' if opted else 'false'}
  return subprocess.run(['/bin/sh','-c',command],cwd=root,env=env,capture_output=True,text=True,timeout=25)

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
 def test_api36_crash_capture_source_contract(self):
  src=read('scripts/test_xgo_mp08b3_source_contract.py')
  require(src, ('api36_collect_crash_diagnostics()', 'MP08B3_API36_CRASH_DIAGNOSTIC_BEGIN', 'MP08B3_API36_DIAG_', 'api36_sanitize_crash_line', 'api36_crash_excerpt', 'if result.returncode!=0:', 'raise AssertionError(\'MP08B3_API36_REFUSED: real instrumentation Gradle failure rc=\''))
 def test_api36_action_one_command_and_realistic_mock(self):
  command=api36_execution_contract(read(WORKFLOW))
  p=execute_api36_mock(command)
  self.assertEqual(p.returncode,0,(p.stdout,p.stderr))
  self.assertIn('MP08B3_API36_FOUR_REAL_INSTRUMENTATION_TESTS_PASS',p.stdout)
  for scenario in ('missing','three','wrong','duplicate','wrongclass','skipped','error','fail','malformed','dtd'):
   with self.subTest(scenario=scenario):
    bad=execute_api36_mock(command,suite=scenario)
    self.assertNotEqual(bad.returncode,0,(bad.stdout,bad.stderr))
    self.assertNotIn('MP08B3_API36_FOUR_REAL_INSTRUMENTATION_TESTS_PASS',bad.stdout)
  for kwargs in ({'sdk':'35'},{'qemu':'0'},{'abi':'arm64-v8a'},
                 {'boot':'0'},{'gradle_rc':1},{'head':False},
                 {'opted':False},{'offline':True},{'extra_device':True}):
   with self.subTest(kwargs=kwargs):
    bad=execute_api36_mock(command,**kwargs)
    self.assertNotEqual(bad.returncode,0,(bad.stdout,bad.stderr))
    self.assertNotIn('MP08B3_API36_FOUR_REAL_INSTRUMENTATION_TESTS_PASS',bad.stdout)
 def test_api36_crash_diagnostics_fail_closed(self):
  command=api36_execution_contract(read(WORKFLOW))
  crash='E AndroidRuntime: FATAL EXCEPTION: Instrumentation\nE AndroidRuntime: Process: com.mikeyphw.xdm.android.debug, PID: 99\nE AndroidRuntime: java.lang.UnsatisfiedLinkError: libxdmcore.so https://test.invalid/media?token=SECRET_VALUE Authorization: Bearer PASSWORD_VALUE'
  bad=execute_api36_mock(command,gradle_rc=1,crash_log=crash)
  self.assertNotEqual(bad.returncode,0)
  self.assertIn('MP08B3_API36_CRASH_DIAGNOSTIC_BEGIN',bad.stdout)
  self.assertIn('UnsatisfiedLinkError',bad.stdout)
  self.assertIn('REDACTED_URL',bad.stdout)
  self.assertNotIn('SECRET_VALUE',bad.stdout+bad.stderr)
  self.assertNotIn('PASSWORD_VALUE',bad.stdout+bad.stderr)
  self.assertNotIn('MP08B3_API36_FOUR_REAL_INSTRUMENTATION_TESTS_PASS',bad.stdout)
  self.assertEqual(api36_crash_excerpt('E AndroidRuntime: FATAL EXCEPTION\nE AndroidRuntime: Process: com.other.app, PID: 99\nE AndroidRuntime: java.lang.IllegalStateException'),[])
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
   (api36_execution_contract,w.replace('script: python3 -B scripts/test_xgo_mp08b3_source_contract.py --api36-execute','script: echo bypass',1)),
   (api36_execution_contract,w.replace('script: python3 -B scripts/test_xgo_mp08b3_source_contract.py --api36-execute','script: |\n            set -euo pipefail',1)),
   (api36_execution_contract,w.replace("MP08B3_OPTED_IN: ${{ (github.event_name == 'workflow_dispatch' && inputs.x86_64_media_test == true) ||", "MP08B3_OPTED_IN: true",1)),
   (api36_execution_contract,w.replace('MP08B3_EXPECTED_HEAD: ${{ github.event.pull_request.head.sha || inputs.exact_head_sha }}','MP08B3_EXPECTED_HEAD: none',1)),
   (api36_execution_contract,w.replace('arch: x86_64','arch: arm64-v8a',1)),
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

if __name__=='__main__':
 import sys
 if sys.argv[1:]==['--api36-execute']:
  try:run_api36_acceptance()
  except Exception as exc:
   # Never print environment, authorization headers, or signed media URLs.
   print('MP08B3_API36_REFUSED: '+str(exc),file=sys.stderr,flush=True)
   raise SystemExit(1)
 elif len(sys.argv)!=1:
  raise SystemExit('MP08B3_API36_REFUSED: unknown or multiple execution flags')
 else:unittest.main(verbosity=2)

