#!/usr/bin/env python3
"""P07: exact-inventory physical ARM64 instrumentation (NOT media/release approval).

Invoked by run_physical_arm64_instrumentation.sh only AFTER its native-device,
ABI, provenance-pinned APK and explicit-install checks. Performs no device
installation, package mutation or signature operation itself. Designed for
strict AndroidJUnitRunner -e notClass architecture segregation.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FILE = ROOT / 'scripts/xgo_arm64_expected_methods.json'
EXPECTED_SHA256 = 'edc86a2eda1eb69b9a7e3e921d5ee1c1438852d360ce23ef5d02107599d8e342'
RUNNER = 'com.mikeyphw.xdm.android.debug.test/androidx.test.runner.AndroidJUnitRunner'
EXCLUDED = (
    'com.mikeyphw.xdm.android.XgoX86JniSmokeTest',
    'com.mikeyphw.xdm.android.XgoX86NativeMediaInstrumentedTest',
)
PATTERN = re.compile(r'[A-Za-z0-9._:-]{1,80}\Z')

class Refused(ValueError):
    pass


def need(ok: bool, reason: str) -> None:
    if not ok:
        raise Refused('XGO_P07_ARM64_REFUSED_' + reason)


def expected_methods() -> list[str]:
    need(EXPECTED_FILE.is_file() and not EXPECTED_FILE.is_symlink(), 'METHODS_SOURCE_UNSAFE')
    payload = EXPECTED_FILE.read_bytes()
    need(hashlib.sha256(payload).hexdigest() == EXPECTED_SHA256, 'METHODS_SHA256_MISMATCH')
    data = json.loads(payload, object_pairs_hook=unique)
    need(type(data) is list and len(data) == 36 and len(set(data)) == 36,
         'METHOD_INVENTORY_NOT_EXACT_36')
    need(all(type(s) is str and re.fullmatch(r'[\w.]+#[A-Za-z0-9_]+', s) for s in data),
         'METHOD_FORMAT')
    need(not any(method.startswith(cls + '#') for method in data for cls in EXCLUDED),
         'INCLUDED_X86_ONLY_TEST')
    return data


def unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def parse_statuses(data: str):
    test_class = test_method = ''
    started, finished, bad = Counter(), Counter(), []
    for line in data.splitlines():
        if line.startswith('INSTRUMENTATION_STATUS: class='):
            test_class = line.partition('class=')[2].strip()
        elif line.startswith('INSTRUMENTATION_STATUS: test='):
            test_method = line.partition('test=')[2].strip()
        elif line.startswith('INSTRUMENTATION_STATUS_CODE:'):
            value = line.partition(':')[2].strip()
            if not re.fullmatch(r'-?[0-9]+', value):
                bad.append('STATUS_INVALID')
                continue
            item = f'{test_class}#{test_method}'
            if not test_class or not test_method:
                bad.append('STATUS_NO_TEST')
            elif value == '1':
                started[item] += 1
            elif value == '0':
                finished[item] += 1
            elif value == '2':
                pass  # AndroidJUnitRunner progress / stream event
            else:
                bad.append('STATUS_FAILURE_' + value)
    return started, finished, bad


def verify(data: str, expected: list[str], *, executed: bool) -> dict:
    need(len(expected) == 36 and len(set(expected)) == 36, 'EXPECTED_INVENTORY_INVALID')
    started, finished, bad = parse_statuses(data)
    need(not bad, 'TEST_STATUS_FAILURE')
    need(set(started) | set(finished) == set(expected), 'METHOD_INVENTORY_MISMATCH')
    need(all(started[item] == 1 for item in expected), 'TEST_START_MISSING_OR_DUPLICATED')
    need(not any(item.startswith(cls + '#') for cls in EXCLUDED for item in started),
         'X86_TEST_OBSERVED')
    need('FAILURES!!!' not in data and 'INSTRUMENTATION_FAILED' not in data and
         'shortMsg=' not in data and 'Process crashed' not in data, 'FAILURE_MARKER')
    need(re.search(r'(?m)^INSTRUMENTATION_CODE: -1\s*$', data) is not None,
         'INSTRUMENTATION_CODE_MISSING')
    if executed:
        need(all(finished[item] == 1 for item in expected), 'TEST_SUCCESS_MISSING_OR_DUPLICATED')
        need(re.search(r'OK \(36 tests\)', data) is not None, 'JUNIT_36_SUCCESS_MISSING')
    else:
        need(not finished, 'DRY_RUN_EXECUTED_TEST_UNEXPECTEDLY')
        need('OK (36 tests)' not in data, 'DRY_RUN_NOT_A_RESULT')
    return {'test_count': len(expected), 'methods': sorted(expected), 'executed': executed}


def run_command(cmd: list[str], *, seconds: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                              errors='replace', timeout=seconds, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise Refused('XGO_P07_ARM64_REFUSED_COMMAND_TIMEOUT_OR_UNAVAILABLE') from None


def save_new(path: Path, data: bytes):
    need(not path.exists() and not path.is_symlink(), 'OUTPUT_ALREADY_EXISTS_' + path.name)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def device_guard(serial: str) -> dict:
    need(PATTERN.fullmatch(serial) is not None, 'SERIAL_INVALID')
    def adb(*args):
        r = run_command(['adb', '-s', serial, *args], seconds=30)
        need(r.returncode == 0, 'ADB_COMMAND_FAILED')
        return r.stdout.strip().replace('\r', '')
    need(adb('get-state') == 'device', 'ADB_NOT_DEVICE')
    abi = adb('shell', 'getprop', 'ro.product.cpu.abi')
    abilist = adb('shell', 'getprop', 'ro.product.cpu.abilist')
    qemu = adb('shell', 'getprop', 'ro.kernel.qemu')
    sdk = adb('shell', 'getprop', 'ro.build.version.sdk')
    need(abi == 'arm64-v8a' and 'arm64-v8a' in abilist.split(','), 'ARM64_REQUIRED')
    need(qemu in ('0', ''), 'EMULATOR_REFUSED')
    need(sdk == '36', 'API36_REQUIRED')
    return {'api': 36, 'abi': 'arm64-v8a', 'not_emulator': True}


def run(serial: str, outdir: Path, runner: str) -> dict:
    need(runner == RUNNER, 'RUNNER_ID_MISMATCH')
    expected = expected_methods()
    device = device_guard(serial)
    need(not outdir.is_symlink(), 'OUTPUT_DIRECTORY_SYMLINK')
    outdir.mkdir(mode=0o700, parents=True, exist_ok=True)
    need(outdir.is_dir(), 'OUTPUT_DIRECTORY_INVALID')
    outdir.chmod(0o700)
    for item in ('dry-run-discovery.log', 'physical-instrumentation.log', 'P07_EXACT_36_PHYSICAL_PASS.json'):
        need(not (outdir/item).exists(), 'RECEIPT_COLLISION_'+item)
    base = ['adb', '-s', serial, 'shell', 'am', 'instrument', '-w', '-r',
            '-e', 'notClass', ','.join(EXCLUDED)]
    print('XGO_P07_ARM64_DRY_RUN_DISCOVERY_BEGIN', flush=True)
    dry = run_command([*base, '-e', 'log', 'true', RUNNER], seconds=420)
    save_new(outdir/'dry-run-discovery.log', (dry.stdout+'\n'+dry.stderr).encode('utf-8'))
    need(dry.returncode == 0, 'DRY_RUN_ADB_FAILED')
    verify(dry.stdout, expected, executed=False)
    print('XGO_P07_ARM64_DRY_RUN_36_METHODS_PASS', flush=True)
    need(device_guard(serial) == device, 'DEVICE_DRIFT_BEFORE_EXECUTION')
    print('XGO_P07_ARM64_REAL_36_TESTS_BEGIN', flush=True)
    real = run_command([*base, RUNNER], seconds=1500)
    save_new(outdir/'physical-instrumentation.log', (real.stdout+'\n'+real.stderr).encode('utf-8'))
    need(real.returncode == 0, 'REAL_ADB_FAILED')
    summary = verify(real.stdout, expected, executed=True)
    source_sha = run_command(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], seconds=20)
    need(source_sha.returncode == 0 and re.fullmatch('[a-f0-9]{40}\\n?', source_sha.stdout) is not None,
         'SOURCE_SHA_UNAVAILABLE')
    result = {'schema':'xgo-p07-arm64-physical-36-v1',
              'source_commit':source_sha.stdout.strip(), 'device':device,
              'method_count':36,'method_inventory_sha256':EXPECTED_SHA256,
              'excluded_x86_only_classes':list(EXCLUDED),
              'physical_instrumentation_pass':True,
              'media_soak_qualified':False,'x86_64_native_qualified':False,
              'release_qualified':False,'signed_release_executed':False,
              'no_device_installs_by_gate':True,
              'dry_sha256':hashlib.sha256(dry.stdout.encode()).hexdigest(),
              'physical_sha256':hashlib.sha256(real.stdout.encode()).hexdigest(),
              'completed_utc':datetime.now(timezone.utc).isoformat(),
              'tested_methods':summary['methods']}
    save_new(outdir/'P07_EXACT_36_PHYSICAL_PASS.json',
             (json.dumps(result, sort_keys=True, indent=2)+'\n').encode())
    print('XGO_P07_ARM64_REAL_36_OF_36_TESTS_PASS_NOT_MEDIA_SOAK_NOT_RELEASE', flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--outdir', type=Path, required=True)
    parser.add_argument('--runner', default=RUNNER)
    args = parser.parse_args()
    run(args.serial,args.outdir,args.runner)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Refused, OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc) if isinstance(exc, Refused) else 'XGO_P07_ARM64_REFUSED_INPUT_OR_EVIDENCE',
              file=sys.stderr)
        sys.exit(2)
