#!/usr/bin/env python3
"""Safe human-readable timing/cache evidence for opt-in x86 native media CI."""
from __future__ import annotations
import argparse
import datetime
import json
import os
from pathlib import Path
import sys
import time

ALLOWED={'toolchain','native','gradle_apk','emulator'}
PREFIX='XGO_X86_PERF'

def refuse(msg):raise ValueError(PREFIX+'_REFUSED:'+msg)

def root():
    if os.environ.get('GITHUB_ACTIONS')!='true':refuse('HOSTED_ONLY')
    base=os.environ.get('RUNNER_TEMP','')
    if not base or not Path(base).is_dir():refuse('NO_RUNNER_TEMP')
    return Path(base)/'xgo-x86-perf'

def stamp(phase,point):
    if phase not in ALLOWED or point not in ('start','end'):refuse('PHASE')
    folder=root();folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    target=folder/f'{phase}.{point}.json'
    if target.exists():refuse('STAMP_ALREADY_EXISTS:'+target.name)
    with target.open('x') as f:
        json.dump({'phase':phase,'point':point,'unix_ms':time.time_ns()//1_000_000},f)
    print(PREFIX+'_MARK='+phase+' '+point,flush=True)

def report(status):
    if status not in ('success','failure','cancelled','skipped'):refuse('JOB_STATUS')
    folder=root();out=[];json_out={'schema_version':1,'job_status':status,'phases':{}}
    for phase in ('toolchain','native','gradle_apk','emulator'):
        values={}
        for point in ('start','end'):
            path=folder/f'{phase}.{point}.json'
            if path.is_file() and not path.is_symlink() and path.stat().st_size<1024:
                values[point]=json.loads(path.read_text())['unix_ms']
        delta=(values['end']-values['start'])/1000 if 'start' in values and 'end' in values and values['end']>=values['start'] else None
        json_out['phases'][phase]={'elapsed_sec':delta,'complete':delta is not None}
        out.append(f'| `{phase}` | '+(f'{delta:.1f} s' if delta is not None else 'Incomplete')+' |')
    verdict=folder/'native-mode.txt'
    mode=verdict.read_text().strip() if verdict.is_file() and not verdict.is_symlink() else 'not recorded'
    if mode not in ('same-pr-native-cache','cross-pr-artifact','pinned-source-build','not recorded'):mode='unrecognized'
    json_out['native_output_mode']=mode
    native_cache=os.environ.get('XGO_NATIVE_SOURCE_CACHE_HIT','').lower()
    if native_cache not in ('true','false'):native_cache='unknown'
    json_out['native_object_cache_hit']=native_cache
    summary='\n'.join([
       '### XGO x86_64 media CI performance',
       f'Job status: **{status}** (never implies ARM64, production, or 1DM qualification)',
       f'Native output mode: **{mode}**',
       f'Native source/object cache hit: **{native_cache}**',
       'Gradle Basic cache: PR writes enabled; see setup-gradle job summary for actual restore/save status.',
       '', '| Phase | Measured duration |','|---|---:|',*out,
       '', 'Native artifact cache is ABI/source-fingerprint restricted; Gradle cache is PR-scoped.',
       'A fresh source build is mandatory when no qualified artifact matches.'])+'\n'
    folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    (folder/'performance.json').write_text(json.dumps(json_out,sort_keys=True,indent=2)+'\n')
    target=os.environ.get('GITHUB_STEP_SUMMARY')
    if target:
        with open(target,'a') as f:f.write(summary)
    print(summary,flush=True)

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('mark');a.add_argument('phase');a.add_argument('point')
    a=sub.add_parser('mode');a.add_argument('native_mode',choices=['same-pr-native-cache','cross-pr-artifact','pinned-source-build'])
    a=sub.add_parser('summary');a.add_argument('--status',required=True)
    arg=p.parse_args()
    if arg.action=='mark':stamp(arg.phase,arg.point)
    elif arg.action=='mode':
        folder=root();folder.mkdir(mode=0o700,parents=True,exist_ok=True)
        (folder/'native-mode.txt').write_text(arg.native_mode+'\n')
    else:report(arg.status)

if __name__=='__main__':
    try:main()
    except Exception as ex:print(str(ex),file=sys.stderr);raise SystemExit(2)
