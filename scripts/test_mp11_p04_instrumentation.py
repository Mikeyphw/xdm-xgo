#!/usr/bin/env python3
"""MP11 P04 real API36 Compose instrumentation receipt gate.

Never use compileDebugAndroidTestKotlin or synthetic fixtures as an execution
receipt. A local self-test exercises only this receipt parser's fail-closed rules.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

CLASS = 'com.mikeyphw.xdm.android.MP11P04LiveRecordingUiInstrumentedTest'
CASES = frozenset({
    'recordingActionsRespectDvrAndUnknownState',
    'refreshNeedsAllThreeSameOriginUrlsAndExplicitApprove',
    'destructiveDiscardNeedsSeparateConfirmationAndSupportsKeep',
    'publishingRecoveryNeverOffersResumeOrDestructiveDiscard',
    'onlyVerifiedLiveTileExposesOpenAndDetails',
})
TOKEN = re.compile(r'^[0-9a-f]{40}$')

class Refused(Exception): pass

def verify_receipts(directory: Path, not_older_than: float, *, real_execution: bool = False) -> None:
    if not directory.is_dir(): raise Refused('MP11_P04_NO_JUNIT_DIRECTORY')
    files = list(directory.rglob('*.xml'))
    if not files or len(files) > 96: raise Refused('MP11_P04_INVALID_JUNIT_INVENTORY')
    found = {}
    for path in files:
        if path.is_symlink() or path.stat().st_size > 8 * 1024 * 1024:
            raise Refused('MP11_P04_UNSAFE_JUNIT_FILE')
        if path.stat().st_mtime < not_older_than:
            raise Refused('MP11_P04_STALE_JUNIT_FILE')
        raw = path.read_bytes()
        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            raise Refused('MP11_P04_XML_ENTITY_REFUSED')
        try: root = ET.fromstring(raw)
        except ET.ParseError: raise Refused('MP11_P04_MALFORMED_JUNIT')
        tests = root.findall('.//testcase')
        if root.tag == 'testcase': tests = [root]
        if not tests: raise Refused('MP11_P04_EMPTY_JUNIT')
        for test in tests:
            if test.attrib.get('classname') != CLASS: continue
            name = test.attrib.get('name')
            if name not in CASES or name in found:
                raise Refused('MP11_P04_WRONG_OR_DUPLICATE_CASE')
            if any(test.find(x) is not None for x in ('failure', 'error', 'skipped')):
                raise Refused('MP11_P04_CASE_NOT_PASSED')
            found[name] = True
    if frozenset(found) != CASES:
        raise Refused('MP11_P04_JUNIT_CASE_SET_INCOMPLETE')
    if real_execution:
        print('MP11_P04_API36_FIVE_REAL_COMPOSE_TESTS_PASS_NOT_PHYSICAL_ARM64')

def cmd(*args: str, timeout: int = 80) -> str:
    p = subprocess.run(args, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=timeout, check=False)
    if p.returncode: raise Refused('MP11_P04_HOST_COMMAND_FAILED_' + str(args[0]).upper())
    return p.stdout.strip()


# Only closed-set diagnostic codes leave the ephemeral API36 emulator.
# Never print, upload or persist raw logcat, URIs, signed requests or tokens.
def capture_crash_diagnostic(serial: str, output: Path) -> str:
    code = 'UNCLASSIFIED_ANDROID_TEST_FAILURE'
    try:
        p = subprocess.run(
            ['adb', '-s', serial, 'logcat', '-d', '-b', 'crash', '-v', 'brief'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            timeout=15, check=False,
        )
        if p.returncode == 0:
            raw = p.stdout[-600000:]
            signatures = (
                ('java.lang.UnsatisfiedLinkError', 'NATIVE_LIBRARY_LINK_ERROR'),
                ('java.lang.NoClassDefFoundError', 'MISSING_RUNTIME_CLASS'),
                ('java.lang.ClassNotFoundException', 'CLASS_NOT_FOUND'),
                ('java.lang.ExceptionInInitializerError', 'STATIC_INITIALIZER_FAILURE'),
                ('java.lang.SecurityException', 'ANDROID_SECURITY_EXCEPTION'),
                ('java.lang.IllegalStateException', 'ILLEGAL_STATE_EXCEPTION'),
                ('java.lang.RuntimeException', 'RUNTIME_EXCEPTION'),
                ('Fatal signal 11', 'NATIVE_SIGSEGV'),
                ('Fatal signal 6', 'NATIVE_SIGABRT'),
                ('FATAL EXCEPTION', 'JAVA_FATAL_EXCEPTION'),
            )
            for signature, reason in signatures:
                if signature in raw:
                    code = reason
                    break
            if not raw.strip():
                code = 'EMPTY_CRASH_BUFFER'
        else:
            code = 'CRASH_BUFFER_READ_FAILED'
    except (subprocess.TimeoutExpired, OSError):
        code = 'CRASH_BUFFER_UNAVAILABLE'
    # If the crash buffer has no actionable signature, use only bounded JUnit
    # markers (never a test's raw message or a credential-bearing stack trace).
    if code in ('UNCLASSIFIED_ANDROID_TEST_FAILURE', 'EMPTY_CRASH_BUFFER') and output.is_dir():
        for report in list(output.rglob('*.xml'))[:96]:
            if report.is_symlink() or report.stat().st_size > 8 * 1024 * 1024:
                continue
            content = report.read_bytes()
            if b'Process crashed' in content and b'tests="0"' in content:
                code = 'INSTRUMENTATION_PROCESS_CRASHED_ZERO_CASES'
                break
            if b'<failure' in content or b'<error' in content:
                code = 'INSTRUMENTED_CASE_FAILURE'
                break
    output.mkdir(parents=True, exist_ok=True)
    receipt = {
        'schema': 'mp11-p04-crash-code-v1',
        'reason_code': code,
        'raw_logcat_uploaded': False,
        'accepted_test_cases': 0,
        'api36_qualified': False,
        'arm64_qualified': False,
    }
    (output / 'mp11-p04-crash-diagnostic.json').write_text(
        json.dumps(receipt, sort_keys=True) + '\n', encoding='utf-8',
    )
    print('MP11_P04_CRASH_DIAGNOSTIC_CODE=' + code, flush=True)
    return code

def run_api36() -> None:
    expected = os.environ.get('MP11_P04_EXPECTED_SHA', '')
    if not TOKEN.fullmatch(expected) or os.environ.get('MP11_P04_OPTED_IN') != 'true':
        raise Refused('MP11_P04_EXACT_SHA_AND_EXPLICIT_OPTIN_REQUIRED')
    if cmd('git', 'rev-parse', 'HEAD') != expected:
        raise Refused('MP11_P04_CHECKOUT_SHA_MISMATCH')
    devices = cmd('adb', 'devices').splitlines()
    ready = [line.split('\t')[0] for line in devices[1:] if line.endswith('\tdevice')]
    if len(ready) != 1: raise Refused('MP11_P04_REQUIRES_ONE_REAL_EMULATOR')
    if cmd('adb', '-s', ready[0], 'shell', 'getprop', 'ro.build.version.sdk') != '36':
        raise Refused('MP11_P04_API36_REQUIRED')
    if cmd('adb', '-s', ready[0], 'shell', 'getprop', 'ro.kernel.qemu') != '1':
        raise Refused('MP11_P04_EMULATOR_REQUIRED')
    if cmd('adb', '-s', ready[0], 'shell', 'getprop', 'ro.product.cpu.abi') != 'x86_64':
        raise Refused('MP11_P04_X86_64_REQUIRED')
    # Clear only the disposable emulator crash buffer so a receipt cannot
    # accidentally classify a previous invocation as the current failure.
    cmd('adb', '-s', ready[0], 'logcat', '-c', '-b', 'crash')
    android = Path('app/XDM.Android')
    output = android / 'app/build/outputs/androidTest-results/connected'
    # Do not trust old reports from another commit or earlier instrumentation.
    if output.exists():
        import shutil
        shutil.rmtree(output)
    started = time.time() - 3
    print('MP11_P04_API36_REAL_COMPOSE_INTERACTIONS_BEGIN', flush=True)
    args = ['./gradlew', '--no-daemon', '--max-workers=2', ':app:connectedDebugAndroidTest',
        '-Pxdm.mp11P04UiIsolatedHost=true',
        '-Pandroid.testInstrumentationRunnerArguments.class=' + CLASS]
    try:
        p = subprocess.run(args, cwd=android, timeout=2700, check=False)
    except subprocess.TimeoutExpired:
        raise Refused('MP11_P04_API36_GRADLE_TIMEOUT')
    if p.returncode:
        reason = capture_crash_diagnostic(ready[0], output)
        raise Refused('MP11_P04_API36_GRADLE_FAILED_' + reason)
    verify_receipts(output, started, real_execution=True)

def self_test() -> None:
    import xml.sax.saxutils as escape
    with tempfile.TemporaryDirectory(prefix='mp11-p04-junit-') as t:
        folder = Path(t)
        test = folder / 'TEST-real.xml'
        cases = sorted(CASES)
        def write(names, classname=CLASS, flag='', header=''):
            test.write_text(header + '<testsuite>' + ''.join(
                f'<testcase classname="{classname}" name="{escape.escape(x)}">{flag}</testcase>'
                for x in names) + '</testsuite>')
        def fails():
            try: verify_receipts(folder, time.time()-60)
            except Refused: return
            raise AssertionError('MP11_P04_INJECTED_JUNIT_FAILURE_ACCEPTED')
        write(cases)
        verify_receipts(folder, time.time()-60)
        write(cases[:-1]); fails()
        write(cases + [cases[0]]); fails()
        write(cases, classname='not.the.real.test.Class'); fails()
        write(cases, flag='<skipped/>'); fails()
        write(cases, flag='<failure/>'); fails()
        write(cases, flag='<error/>'); fails()
        write(cases, header='<!DOCTYPE testsuite [<!ENTITY attack SYSTEM "file:///etc/passwd">]>'); fails()
        write(cases)
        os.utime(test,(10.0,10.0)); fails()
    print('MP11_P04_JUNIT_EIGHT_NEGATIVE_CONTRACTS_PASS')

if __name__=='__main__':
    try:
        if sys.argv[1:] == ['--self-test']: self_test()
        elif sys.argv[1:] == ['--api36-execute']: run_api36()
        else: raise Refused('MP11_P04_MODE_REQUIRED')
    except (Refused, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
