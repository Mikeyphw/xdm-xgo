#!/usr/bin/env python3
"""XGO MP12 P06: fail-closed, read-only qualification evidence ledger.

Intentionally incapable of signing, releasing, promoting canaries or inferring
physical ARM64 from emulator/hosted source evidence. ``--live`` reads GitHub
and writes only a bounded, credential-free report when explicitly requested.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

REPO = 'Mikeyphw/xdm-xgo'
PR = 28
BRANCH = 'feature/xgo-mp09-consolidated-recording-20261111'
BASE_BRANCH = 'feature/xgo-mp09-p02-durable-live-poll-20261111'
BASE = '1a0806a069ae27eea322332c9f05f70cf6fd4d34'
SHA = re.compile(r'^[a-f0-9]{40}$')
P04_MARKS = ('MP11_P04_KVM_OPEN_PASS', 'MP11_P04_API36_FIVE_REAL_COMPOSE_TESTS_PASS_NOT_PHYSICAL_ARM64')
P04_STARTED = re.compile(r'(?m)^.*Starting 5 tests on .*$')
P04_FINISHED = re.compile(r'(?m)^.*Finished 5 tests on .*$')
GATES = (
    'targeted_source', 'mp08b3_linux_media', 'mp11_p04_compose_api36',
    'x86_full_native_api36', 'physical_arm64_media', 'signed_android_provenance',
    'go_canary_rollback', 'desktop_protocol_parity', 'licensed_1dm_differential',
    'perf_chaos_reproducibility', 'user_visible_limitations',
)
SPECS = (
    ('targeted_source', 'XGO Targeted CI', 'pull_request', 'XGO targeted checks passed (NOT full qualification)'),
    ('mp08b3_linux_media', 'XGO MP08B3 Real Media Acceptance', 'pull_request', 'Source contracts and real Linux FFmpeg golden'),
    ('mp11_p04_compose_api36', 'XDM MP00 Media Parity Baseline', 'workflow_dispatch',
     'MP11 P04 API36 Compose UI Acceptance (explicit dispatch only)'),
    ('x86_full_native_api36', 'XGO x86_64 Native Media Runtime (opt-in only)', 'pull_request',
     'Exact-head x86_64 FFmpeg FFprobe aria2 source build and API36 runtime'),
)
# These paths have historical Git blobs; P06 modifies none of them.
SOURCE_PINS = {
    '.github/workflows/xgo-targeted.yml': '242365dee226ac16a4e8ad9b83c045214df1f2d6',
    '.github/workflows/xgo-mp08b3-acceptance.yml': '4180cc7c6234a6e75c4a6eb079885a7aedcf626d',
    '.github/workflows/xgo-x86-native-media.yml': '066867020077e2611f2b3cd35616e825d991fce6',
    '.github/workflows/media-parity.yml': '569325773881929ee0a247cbb7a6f1c0e82a87a1',
    '.github/workflows/android.yml': '9db9afa13e9a5c7944d727888968bac6766ca043',
    'scripts/run_physical_arm64_instrumentation.sh': '872db6b4909764e94e2ea31f313274a8dd04bcb6',
    'scripts/mp12_p02_provenance.py': '0fb1f07e4144c9b0c9e737ab51d908e202cbf3eb',
    'scripts/mp12_p04_signed_release.py': 'a4acd661e622c325e48961a922432a590adefda1',
    'scripts/mp12_p05_desktop_parity.py': 'd5a6a1be3d829d484aa38b0a69eeb7dba167c36d',
    'engine/runtime/canary/controller.go': '7df3c25a2273c71e3215f9a327609b6ce5946b37',
    'engine/runtime/mp12_canary_handlers.go': 'e4d9e207ef8054a5b8a8b9a2b57a9adca90bf5e7',
    'scripts/ci/xgo_ci_policy.py': 'fa4e54474a8f4133fb54dcc447ac683b14c9b5c5',
}
MAX_SOURCE = 300000
MAX_RUNS = 99
MAX_LOG = 8000000

class Refused(ValueError):
    pass

def require(ok: bool, code: str) -> None:
    if not ok:
        raise Refused('MP12_P06_REFUSED_' + code)

def blob(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()

def read_source(root: Path, name: str) -> str:
    path = root / name
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_SOURCE,
            'SOURCE_UNSAFE_' + name.replace('/', '_'))
    return path.read_text(encoding='utf-8')

def source_guard(root: Path, pins: dict[str, str] = SOURCE_PINS) -> dict[str, Any]:
    require(set(pins) == set(SOURCE_PINS), 'SOURCE_PIN_INVENTORY')
    read = {}
    for name, expected in pins.items():
        require(bool(SHA.fullmatch(expected)), 'SOURCE_INVALID_BLOB_PIN')
        src = read_source(root, name)
        require(blob(src.encode('utf-8')) == expected,
                'SOURCE_BLOB_DRIFT_' + name.replace('/', '_'))
        read[name] = src
    workflows = read['.github/workflows/android.yml']
    signed = workflows.split('\n  signed-release:\n')
    require(len(signed) == 2 and len(signed[1].split('\n  emulator-compatibility:\n')) == 2,
            'SIGNED_RELEASE_JOB_SECTION')
    release = signed[1].split('\n  emulator-compatibility:\n', 1)[0]
    for marker in ("startsWith(github.ref, 'refs/tags/android-v')",
                   'XDM_XAR16_FULL_RELEASE_GATE', 'XDM_RELEASE_SIGNER_SHA256',
                   'run-hosted-emulator-instrumentation.sh --signed-release',
                   'xdm-android-signed-release'):
        require(marker in release, 'SIGNED_RELEASE_POLICY_DRIFT')
    require('continue-on-error: true' not in release and '|| true' not in release,
            'SIGNED_RELEASE_WEAKENED')
    x86 = read['.github/workflows/xgo-x86-native-media.yml']
    require("types: [labeled]" in x86 and
            "github.event.label.name == 'xgo-x86-native-media'" in x86 and
            'github.event.pull_request.head.repo.full_name == github.repository' in x86,
            'X86_NOT_EXPLICIT_OPT_IN')
    physical = read['scripts/run_physical_arm64_instrumentation.sh']
    require(all(term in physical for term in
                ('ro.kernel.qemu', 'XGO_ADB_EMULATOR_REFUSED',
                 'XGO_ADB_NATIVE_ARM64_REQUIRED', 'INSTRUMENTATION_CODE: -1',
                 'XGO_REAL_ARM64_DEVICE_INSTRUMENTATION_PASS')),
            'PHYSICAL_NOT_REAL_DEVICE_FENCED')
    canary = read['engine/runtime/canary/controller.go']
    require(all(term in canary for term in
                ('ProductionCutoverAuthorized: false', 'Primary: "legacy"',
                 'UnsafePromotion()', 'os.O_EXCL', 'func Open(')),
            'CANARY_LEGACY_FIRST_BROKEN')
    require('ProtocolVersion = "2.0"' in read['scripts/mp12_p05_desktop_parity.py'] or
            '"2.0"' in read['scripts/mp12_p05_desktop_parity.py'],
            'DESKTOP_SOURCE_POLICY_DRIFT')
    require('SOURCE_PINS' in read['scripts/mp12_p04_signed_release.py'] and
            'publication_automatically_authorized' in read['scripts/mp12_p04_signed_release.py'],
            'SIGNED_PROVENANCE_SOURCE_POLICY_DRIFT')
    require('release_eligible' in read['scripts/mp12_p02_provenance.py'],
            'CROSS_ABI_RELEASE_POLICY_DRIFT')
    return {'checked_source_git_blobs': len(pins), 'tag_only_signing': True,
            'physical_fenced': True, 'x86_opt_in_only': True,
            'canary_legacy_first': True, 'source_guards_are_device_proof': False}

def _status(ok: bool, reason: str, run: dict[str, Any] | None = None) -> dict[str, Any]:
    return {'status': 'verified' if ok else 'not_qualified',
            'reason_code': 'EXACT_HEAD_HOSTED_PASS' if ok else reason,
            'github_run_id': run.get('id') if ok and run else None}

def _positive_id(item: Any) -> bool:
    return isinstance(item, int) and not isinstance(item, bool) and item > 0

def latest_run(runs: list[dict[str, Any]], head: str, name: str, event: str) -> dict[str, Any] | None:
    hits = [r for r in runs if r.get('name') == name and r.get('event') == event
            and r.get('head_sha') == head]
    if not hits:
        return None
    # Duplicate or malformed GitHub run IDs cannot select a convenient green run.
    require(all(_positive_id(r.get('id')) for r in hits), 'RUN_INVALID_ID')
    require(len({r['id'] for r in hits}) == len(hits), 'RUN_DUPLICATE_ID')
    return max(hits, key=lambda x: x['id'])

def job_pass(run: dict[str, Any] | None, jobs: list[dict[str, Any]], name: str) -> bool:
    if run is None or run.get('status') != 'completed' or run.get('conclusion') != 'success':
        return False
    require(isinstance(jobs, list) and len(jobs) <= MAX_RUNS, 'JOB_LIST_INVALID')
    candidates = [j for j in jobs if j.get('name') == name]
    return (len(candidates) == 1 and _positive_id(candidates[0].get('id'))
            and candidates[0].get('status') == 'completed'
            and candidates[0].get('conclusion') == 'success')

def compose_markers_pass(log: str) -> bool:
    return (isinstance(log, str) and len(log) <= MAX_LOG and
            all(s in log for s in P04_MARKS) and
            len(P04_STARTED.findall(log)) == 1 and len(P04_FINISHED.findall(log)) == 1 and
            'Starting 5 tests on' in log and 'Finished 5 tests on' in log)

def build_ledger(head: str, runs: list[dict[str, Any]], jobs: dict[int, list[dict[str, Any]]],
                 compose_log: str = '', *, provenance: str = 'github_verified') -> dict[str, Any]:
    """Pure, fail-closed evaluator. Synthetic test input NEVER authorizes release."""
    require(bool(SHA.fullmatch(head)), 'HEAD_INVALID')
    require(provenance in ('github_verified', 'synthetic_test_only'), 'PROVENANCE_MODE_INVALID')
    require(isinstance(runs, list) and len(runs) <= MAX_RUNS and
            all(isinstance(x, dict) for x in runs), 'RUNS_INVALID_OR_PAGED')
    require(all(r.get('head_sha') == head for r in runs), 'CROSS_HEAD_EVIDENCE')
    require(len([r['id'] for r in runs if _positive_id(r.get('id'))]) == len(set(
        r['id'] for r in runs if _positive_id(r.get('id')))), 'DUPLICATE_GLOBAL_RUN_ID')
    require(isinstance(jobs, dict), 'JOBS_INVALID')
    gates: dict[str, dict[str, Any]] = {}
    for gate, name, event, job in SPECS:
        run = latest_run(runs, head, name, event)
        candidates = jobs.get(run['id'], []) if run else []
        ok = job_pass(run, candidates, job)
        if gate == 'mp11_p04_compose_api36':
            ok = ok and compose_markers_pass(compose_log)
        if provenance != 'github_verified':
            ok = False
        gates[gate] = _status(ok, 'EXACT_HEAD_REAL_HOSTED_EVIDENCE_MISSING', run)
    for gate in GATES[4:]:
        gates[gate] = _status(False, 'INDEPENDENT_PHYSICAL_DESKTOP_SIGNING_COMPARATOR_OR_PERF_PROOF_REQUIRED')
    require(tuple(gates) == GATES, 'GATE_INVENTORY_DRIFT')
    return {
        'schema': 'xgo-mp12-p06-final-readiness-v1',
        'repository': REPO, 'pr': PR, 'branch': BRANCH, 'exact_head_sha': head,
        'evidence_origin': provenance,
        'verified_hosted_gate_count': sum(g['status'] == 'verified' for g in gates.values()),
        'total_gate_count': len(GATES), 'gates': gates,
        'go_canary_primary': 'legacy', 'go_shadow_executes_downloads': False,
        'physical_arm64_inferred_from_api36_x86': False,
        'source_contracts_are_release_proof': False,
        'signed_release_executed_by_this_tool': False,
        'production_cutover_authorized': False,
        'release_qualified': False,
    }

def _run(argv: list[str], timeout: int = 60) -> str:
    try:
        p = subprocess.run(argv, text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise Refused('MP12_P06_REFUSED_EXECUTION_UNAVAILABLE') from None
    require(p.returncode == 0 and len(p.stdout) <= MAX_LOG,
            'COMMAND_FAILED_OR_OVERSIZED')
    return p.stdout

def _gh(path: str) -> dict[str, Any]:
    try:
        obj = json.loads(_run(['gh', 'api', 'repos/' + REPO + '/' + path], 90))
    except ValueError:
        raise Refused('MP12_P06_REFUSED_GITHUB_JSON_INVALID') from None
    require(isinstance(obj, dict), 'GITHUB_RESPONSE_NOT_OBJECT')
    return obj

def check_checkout(root: Path) -> str:
    require(root.is_dir() and not root.is_symlink(), 'REPO_DIR_UNSAFE')
    top = _run(['git', '-C', str(root), 'rev-parse', '--show-toplevel'], 30).strip()
    require(Path(top).resolve() == root.resolve(), 'NOT_REPOSITORY_ROOT')
    head = _run(['git', '-C', str(root), 'rev-parse', '--verify', 'HEAD'], 30).strip()
    require(bool(SHA.fullmatch(head)), 'LOCAL_HEAD_INVALID')
    require(_run(['git', '-C', str(root), 'branch', '--show-current'], 30).strip() == BRANCH,
            'CHECKOUT_BRANCH_MISMATCH')
    require(not _run(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=normal'], 30).strip(),
            'WORKTREE_NOT_CLEAN')
    return head

def live_ledger(root: Path) -> dict[str, Any]:
    head = check_checkout(root)
    source_guard(root)
    pr = _gh('pulls/' + str(PR))
    ph, pb = pr.get('head') or {}, pr.get('base') or {}
    require(pr.get('state') == 'open' and not pr.get('merged') and
            ph.get('sha') == head and ph.get('ref') == BRANCH and
            (ph.get('repo') or {}).get('full_name') == REPO and
            pb.get('sha') == BASE and pb.get('ref') == BASE_BRANCH,
            'PR_IDENTITY_OR_HEAD_DRIFT')
    all_runs = _gh('actions/runs?head_sha=' + head + '&per_page=100')
    runs = all_runs.get('workflow_runs')
    require(isinstance(runs, list) and len(runs) < 100, 'GITHUB_RUNS_PAGED_OR_INVALID')
    jobs: dict[int, list[dict[str, Any]]] = {}
    p04_log = ''
    for gate, name, event, job in SPECS:
        hit = latest_run(runs, head, name, event)
        if not hit:
            continue
        data = _gh('actions/runs/' + str(hit['id']) + '/jobs?per_page=100')
        children = data.get('jobs')
        require(isinstance(children, list) and len(children) < 100, 'GITHUB_JOBS_PAGED_OR_INVALID')
        jobs[hit['id']] = children
        if gate == 'mp11_p04_compose_api36' and job_pass(hit, children, job):
            match = [j for j in children if j.get('name') == job]
            require(len(match) == 1 and _positive_id(match[0].get('id')), 'COMPOSE_JOB_ID_INVALID')
            # Never print raw logs; they are only inspected transiently.
            p04_log = _run(['gh', 'run', 'view', '--job', str(match[0]['id']),
                            '-R', REPO, '--log'], 180)
    return build_ledger(head, runs, jobs, p04_log)

def inspect_physical(serial: str, adb: str = 'adb') -> dict[str, Any]:
    """Read-only ADB probes only. Does not install, root or run instrumentation."""
    require(bool(re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', serial)), 'ADB_SERIAL_INVALID')
    require(_run([adb, '-s', serial, 'get-state'], 30).strip() == 'device', 'ADB_NOT_ONLINE')
    def prop(name: str) -> str:
        return _run([adb, '-s', serial, 'shell', 'getprop', name], 30).strip()
    api, abi, primary, qemu = (prop('ro.build.version.sdk'), prop('ro.product.cpu.abilist'),
                               prop('ro.product.cpu.abi'), prop('ro.kernel.qemu'))
    require(api.isdigit() and 26 <= int(api) <= 99, 'ADB_API_INVALID')
    require(primary == 'arm64-v8a' and 'arm64-v8a' in abi.split(','), 'ADB_NATIVE_ARM64_REQUIRED')
    require(qemu in ('', '0'), 'ADB_EMULATOR_OR_UNKNOWN_QEMU_REFUSED')
    # This is deliberately NOT physical media acceptance.
    return {'physical_device_read_only_preflight': 'passed', 'api': int(api),
            'abi': 'arm64-v8a', 'instrumentation_executed': False,
            'physical_arm64_media_qualified': False,
            'device_identifier_recorded': False}

def private_write(path: Path, report: dict[str, Any]) -> None:
    require(path.parent.is_dir() and not path.parent.is_symlink(), 'REPORT_PARENT_UNSAFE')
    require(not path.exists() and not path.is_symlink(), 'REPORT_EXISTS_OR_SYMLINK')
    raw = (json.dumps(report, sort_keys=True, indent=2) + '\n').encode()
    require(len(raw) <= 20000, 'REPORT_OVERSIZE')
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        raise Refused('MP12_P06_REFUSED_REPORT_CREATE_FAILED') from None
    with os.fdopen(fd, 'wb') as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())

def main() -> int:
    p = argparse.ArgumentParser(description='MP12 P06 read-only final readiness (never release)')
    p.add_argument('mode', choices=('source-only', 'live', 'physical-preflight'),
                   help='no write/action on devices; source-only or GitHub read-only')
    p.add_argument('--repo', default='.')
    p.add_argument('--serial', help='required for read-only physical-preflight')
    p.add_argument('--output', type=Path, help='create private JSON ledger; refuses overwrite')
    args = p.parse_args()
    root = Path(args.repo).expanduser().resolve()
    if args.mode == 'physical-preflight':
        require(bool(args.serial), 'ADB_SERIAL_REQUIRED')
        report = inspect_physical(args.serial)
        print('MP12_P06_REAL_ARM64_READ_ONLY_PREFLIGHT_PASS_NOT_INSTRUMENTATION_OR_RELEASE')
    elif args.mode == 'source-only':
        result = source_guard(root)
        report = {'source_policy': result, 'release_qualified': False,
                  'physical_arm64_media_qualified': False, 'go_cutover_authorized': False}
        print('MP12_P06_TWELVE_HISTORICAL_SOURCE_PINS_AND_QUALIFICATION_REFUSALS_PASS_NOT_RELEASE')
    else:
        report = live_ledger(root)
        print('MP12_P06_LIVE_EXACT_HEAD_HOSTED_GATE_COUNT_' +
              str(report['verified_hosted_gate_count']) + '_OF_' + str(report['total_gate_count']))
        print('MP12_P06_PRODUCTION_RELEASE_AND_GO_CUTOVER_NOT_QUALIFIED')
    if args.output:
        private_write(args.output.expanduser(), report)
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
