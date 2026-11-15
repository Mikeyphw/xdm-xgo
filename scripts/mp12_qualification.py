#!/usr/bin/env python3
"""MP12 P01: evidence-bound, fail-closed readiness ledger (not a release gate).

All GitHub checks are scoped to the same exact PR head. A source-only contract
never certifies a device, a release, or a licensed black-box comparator.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

REPO = 'Mikeyphw/xdm-xgo'
BRANCH = 'feature/xgo-mp09-consolidated-recording-20261111'
PR = 28
SHA = re.compile(r'^[a-f0-9]{40}$')
P04_JOB = 'MP11 P04 API36 Compose UI Acceptance (explicit dispatch only)'
P04_MARK = 'MP11_P04_API36_FIVE_REAL_COMPOSE_TESTS_PASS_NOT_PHYSICAL_ARM64'
P04_STARTED = 'Starting 5 tests on'
P04_FINISHED = 'Finished 5 tests on'
SOURCE_JOB = 'XGO targeted checks passed (NOT full qualification)'
MP08_JOB = 'Source contracts and real Linux FFmpeg golden'
X86_JOB = 'Exact-head x86_64 FFmpeg FFprobe aria2 source build and API36 runtime'
GATES = (
    'targeted_source', 'mp08b3_linux_media', 'mp11_p04_compose_api36',
    'x86_full_native_api36', 'physical_arm64_media', 'signed_android_provenance',
    'go_canary_rollback', 'desktop_protocol_parity', 'licensed_1dm_differential',
    'perf_chaos_reproducibility', 'user_visible_limitations',
)
EXTERNAL = GATES[4:]

class Refused(Exception):
    pass

def require(value: bool, label: str) -> None:
    if not value: raise Refused('MP12_P01_REFUSED_' + label)

def _text(root: Path, name: str) -> str:
    p = root/name
    require(p.is_file() and not p.is_symlink(), 'SOURCE_MISSING_'+name.replace('/','_'))
    return p.read_text(encoding='utf-8')

def source_guard(root: Path) -> list[str]:
    """Structural guards, not proof of executed media or signed artifacts."""
    android = _text(root, 'app/XDM.Android/app/build.gradle.kts')
    opt = _text(root, '.github/workflows/xgo-mp08b3-acceptance.yml')
    x86 = _text(root, '.github/workflows/xgo-x86-native-media.yml')
    p04 = _text(root, '.github/workflows/media-parity.yml')
    physical = _text(root, 'scripts/run_physical_arm64_instrumentation.sh')
    ci = _text(root, '.github/workflows/xgo-targeted.yml')
    checks = {
        'production_arm64_only': 'abiFilters += setOf("arm64-v8a")' in android,
        'test_only_x86_optin_default_off': bool(re.search(
            r'(?m)^\s*x86_64_media_test:\s*\n(?:\s+[^\n]*\n){0,8}?\s*default:\s*false\s*$', opt)),
        'x86_only_labeled_event': ('types: [labeled]' in x86 and
            'github.event.label.name == \'xgo-x86-native-media\'' in x86 and
            'github.event.pull_request.head.repo.full_name == github.repository' in x86),
        'p04_optin_and_exact_sha': ('mp11-p04-api36-registered:' in p04 and
            'github.event_name == \'workflow_dispatch\'' in p04 and
            'test "$pr_head" = "$EXPECTED_SHA"' in p04 and
            'python3 -B scripts/test_mp11_p04_instrumentation.py --api36-execute' in p04),
        'physical_arm64_refuses_emulation': ('ro.kernel.qemu' in physical and
            'XGO_ADB_EMULATOR_REFUSED' in physical and 'XGO_ADB_NATIVE_ARM64_REQUIRED' in physical),
        'targeted_not_release': ('NOT full qualification' in ci and 'targeted-qualification:' in ci),
    }
    for key, passed in checks.items():
        require(passed, 'SOURCE_GUARD_'+key)
    return sorted(checks)

def _pick(runs: list[dict[str, Any]], sha: str, name: str, event: str) -> dict[str, Any] | None:
    matches = [r for r in runs if r.get('name') == name and r.get('head_sha') == sha
        and r.get('event') == event and isinstance(r.get('id'), int)]
    return max(matches, key=lambda r: r['id']) if matches else None

def _verified(run: dict[str, Any] | None, jobs: list[dict[str, Any]], job_name: str) -> bool:
    if not run or run.get('status') != 'completed' or run.get('conclusion') != 'success':
        return False
    matches = [j for j in jobs if j.get('name') == job_name]
    return len(matches) == 1 and matches[0].get('status') == 'completed' and matches[0].get('conclusion') == 'success'

def _entry(ok: bool, run: dict[str, Any] | None, reason: str) -> dict[str, Any]:
    return {'status': 'verified' if ok else 'not_qualified',
            'evidence_run': run['id'] if run and ok else None,
            'reason_code': 'EXACT_HEAD_HOSTED_PASS' if ok else reason}

def build_ledger(sha: str, runs: list[dict[str, Any]], jobs_by_run: dict[int, list[dict[str, Any]]],
                 p04_log: str = '') -> dict[str, Any]:
    require(bool(SHA.fullmatch(sha)), 'INVALID_SHA')
    require(isinstance(runs, list), 'INVALID_RUNS')
    entries: dict[str, dict[str, Any]] = {}
    specs = (
        ('targeted_source', 'XGO Targeted CI', 'pull_request', SOURCE_JOB),
        ('mp08b3_linux_media', 'XGO MP08B3 Real Media Acceptance', 'pull_request', MP08_JOB),
        ('mp11_p04_compose_api36', 'XDM MP00 Media Parity Baseline', 'workflow_dispatch', P04_JOB),
        ('x86_full_native_api36', 'XGO x86_64 Native Media Runtime (opt-in only)', 'pull_request', X86_JOB),
    )
    for key, name, event, job in specs:
        run = _pick(runs, sha, name, event)
        ok = _verified(run, jobs_by_run.get(run['id'], []) if run else [], job)
        if key == 'mp11_p04_compose_api36':
            ok = ok and all(x in p04_log for x in (P04_MARK, P04_STARTED, P04_FINISHED,
                                                   'MP11_P04_KVM_OPEN_PASS'))
        entries[key] = _entry(ok, run, 'EXACT_HEAD_REAL_EXECUTION_NOT_PROVEN')
    for key in EXTERNAL:
        entries[key] = {'status': 'not_qualified', 'evidence_run': None,
                        'reason_code': 'MANUAL_OR_DEDICATED_RELEASE_EVIDENCE_REQUIRED'}
    require(set(entries) == set(GATES), 'GATE_INVENTORY_INCOMPLETE')
    return {'schema': 'xgo-mp12-p01-qualification-v1', 'repository': REPO,
            'pr': PR, 'branch': BRANCH, 'exact_head_sha': sha,
            'source_checks_are_release_proof': False,
            'physical_arm64_inferred_from_x86': False,
            'release_qualified': False,
            'verified_gate_count': sum(v['status'] == 'verified' for v in entries.values()),
            'gate_count': len(GATES), 'gates': entries}

def _gh(*args: str, limit: int = 2_000_000) -> str:
    try:
        p = subprocess.run(['gh', *args], capture_output=True, text=True,
                           timeout=70, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise Refused('MP12_P01_REFUSED_GH_UNAVAILABLE') from None
    require(p.returncode == 0 and len(p.stdout) <= limit, 'GH_FAILED_OR_OVERSIZE')
    return p.stdout

def _api(path: str) -> dict[str, Any]:
    try: value = json.loads(_gh('api', 'repos/'+REPO+'/'+path))
    except (ValueError, TypeError): raise Refused('MP12_P01_REFUSED_BAD_API_JSON') from None
    require(isinstance(value, dict), 'GH_API_NONOBJECT')
    return value

def _job_list(run_id: int) -> list[dict[str, Any]]:
    j = _api(f'actions/runs/{run_id}/jobs?per_page=100')
    require(isinstance(j.get('jobs'), list) and len(j['jobs']) < 100, 'JOBS_MISSING_OR_PAGED')
    return j['jobs']

def live_evidence(root: Path, sha: str) -> dict[str, Any]:
    source_guard(root)
    pr = _api(f'pulls/{PR}')
    require(pr.get('state') == 'open' and not pr.get('merged'), 'PR_NOT_OPEN_UNMERGED')
    head = pr.get('head') or {}
    require(head.get('sha') == sha and head.get('ref') == BRANCH and
            (head.get('repo') or {}).get('full_name') == REPO, 'PR_HEAD_DRIFT')
    all_runs = _api(f'actions/runs?head_sha={sha}&per_page=100')
    runs = all_runs.get('workflow_runs')
    require(isinstance(runs, list) and len(runs) < 100, 'RUNS_MISSING_OR_PAGED')
    require(all(r.get('head_sha') == sha for r in runs), 'RUN_HEAD_MISMATCH')
    jobs: dict[int, list[dict[str, Any]]] = {}
    for name, event in (
        ('XGO Targeted CI', 'pull_request'),
        ('XGO MP08B3 Real Media Acceptance', 'pull_request'),
        ('XDM MP00 Media Parity Baseline', 'workflow_dispatch'),
        ('XGO x86_64 Native Media Runtime (opt-in only)', 'pull_request'),
    ):
        run = _pick(runs, sha, name, event)
        if run: jobs[run['id']] = _job_list(run['id'])
    p04 = _pick(runs, sha, 'XDM MP00 Media Parity Baseline', 'workflow_dispatch')
    log = ''
    if p04 and p04.get('conclusion') == 'success':
        match = [j for j in jobs[p04['id']] if j.get('name') == P04_JOB and
                 j.get('conclusion') == 'success']
        if len(match) == 1 and isinstance(match[0].get('id'), int):
            # Transient in-process inspection only. Never print raw logs or tokens.
            log = _gh('run', 'view', '--job', str(match[0]['id']), '-R', REPO,
                      '--log', limit=8_000_000)
    return build_ledger(sha, runs, jobs, p04_log=log)

def main() -> int:
    p = argparse.ArgumentParser(description='MP12 P01 release-readiness evidence ledger (read-only)')
    p.add_argument('--repo', default='.')
    p.add_argument('--source-only', action='store_true')
    p.add_argument('--live', action='store_true')
    p.add_argument('--release-gate', action='store_true')
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    root = Path(args.repo).expanduser().resolve()
    guards = source_guard(root)
    if args.source_only:
        print('MP12_P01_SIX_SOURCE_POLICY_GUARDS_PASS_NOT_RELEASE_QUALIFICATION')
        return 0
    require(args.live or args.release_gate, 'MODE_REQUIRED')
    try:
        pr_head = subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],
                                           text=True, timeout=15).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise Refused('MP12_P01_REFUSED_GIT_HEAD_UNAVAILABLE') from None
    require(bool(SHA.fullmatch(pr_head)), 'INVALID_LOCAL_HEAD')
    report = live_evidence(root, pr_head)
    # Bounded, closed-set JSON only; no raw logs, URLs, credentials or device IDs.
    content = json.dumps(report, sort_keys=True, indent=2) + '\n'
    if args.output:
        require(not args.output.is_symlink(), 'OUTPUT_SYMLINK')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding='utf-8')
    print('MP12_P01_EXACT_HEAD_READINESS ' + str(report['verified_gate_count']) + '/' + str(report['gate_count']))
    print('MP12_P01_RELEASE_NOT_QUALIFIED')
    return 2 if args.release_gate else 0

if __name__ == '__main__':
    try: sys.exit(main())
    except Refused as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
