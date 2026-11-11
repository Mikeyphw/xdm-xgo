#!/usr/bin/env python3
"""Fail-closed temporary CI-only x86 Gradle optimization.

The Gradle module files are never committed; canonical ARM64 source tasks and
release verification remain unchanged. Preverified mode applies only in a
provenance-checked, opt-in same-repository API36 job. Builds are performed and
verified before this mode is used; Gradle independently verifies source locks.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
FF='app/XDM.Android/media-ffmpeg/build.gradle.kts'
ARIA='app/XDM.Android/transfer-aria2/build.gradle.kts'
BLOBS={
 FF:'6ab97b68ec1982d331ccee26cd0f811b24ab4e24',
 ARIA:'dec21cb36e8e3247ae6df977f38aa1577f248957',
}
FLAG='xdm.preverifiedNativeRuntime'

def refuse(why):raise ValueError('XGO_X86_OPT_REFUSED: '+why)

def checked_replace(src,before,after,label):
    if src.count(before)!=1 or after in src:refuse('SOURCE_ANCHOR_'+label)
    return src.replace(before,after,1)

def gradle_transform(src,which):
    if which not in ('ffmpeg','aria2'):refuse('ROLE')
    task=('installPinnedFfmpegRuntime' if which=='ffmpeg' else 'buildPinnedAria2Runtime')
    pre='''// EPHEMERAL API36 x86_64 opt-in only. Not committed to production ARM64 sources.
val xgoNativePreverified = providers.gradleProperty("xdm.preverifiedNativeRuntime")
    .map(String::toBoolean).orElse(false)
'''
    anchor='val '+task+' = tasks.register<Exec>("'+task+'") {'
    src=checked_replace(src,anchor,pre+anchor,'REGISTER_'+which)
    opening=anchor+'\n'
    guarded='''    // A source-built, separately verified payload must already be installed.
    onlyIf {
        if (xgoNativePreverified.get()) {
            check(System.getenv("GITHUB_ACTIONS") == "true" &&
                System.getenv("XGO_X86_MEDIA_OPT_IN") == "yes" &&
                System.getenv("XGO_X86_NATIVE_ATTESTED") == "yes") {
                "Refusing unverifiable prebuilt native reuse outside opt-in hosted x86 CI"
            }
        }
        !xgoNativePreverified.get()
    }
'''
    src=checked_replace(src,opening,opening+guarded,'GUARD_'+which)
    marker='src/main/jniLibs/arm64-v8a/'
    count=src.count(marker)
    # FF module declares binary outputs and multiple independent verifier inputs.
    # aria2 also contains a legacy prebuilt install task, which remains disabled in CI.
    if (which=='ffmpeg' and count<6) or (which=='aria2' and count<3):refuse('JNICALL_PATHS_'+which)
    src=src.replace(marker,'src/main/jniLibs/x86_64/')
    if 'src/main/jniLibs/arm64-v8a/' in src:refuse('RESIDUAL_ARM64_GRADLE_PATHS')
    for expected in (FLAG,'XGO_X86_NATIVE_ATTESTED','xgoNativePreverified',
                     'src/main/jniLibs/x86_64/',task):
        if expected not in src:refuse('MISSING_EXPECTED_'+expected)
    # No changes to selected build task's compiler/source recipe except the
    # additional conditional onlyIf: FALSE during preverified opt-in CI.
    return src

def check_source(root=ROOT):
    result={}
    for name,digest in BLOBS.items():
        target=root/name
        if not target.is_file() or target.is_symlink():refuse('MISSING_'+name)
        observed=subprocess.check_output(['git','-C',str(root),'hash-object',str(target)],text=True).strip()
        if observed != digest:refuse('STALE_GRADLE_SOURCE_'+name+':'+observed)
        result[name]=gradle_transform(target.read_text(), 'ffmpeg' if name==FF else 'aria2')
    return result

def prepare(head):
    if not re.fullmatch('[0-9a-f]{40}',head):refuse('HEAD_SHA')
    required={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'Mikeyphw/xdm-xgo',
              'GITHUB_EVENT_NAME':'pull_request','GITHUB_EVENT_ACTION':'labeled',
              'XGO_X86_MEDIA_OPT_IN':'yes','XGO_X86_MEDIA_EXPECTED_HEAD':head,
              'RUNNER_OS':'Linux'}
    for k,v in required.items():
        if os.environ.get(k)!=v:refuse('HOSTED_OPT_IN_GUARD_'+k)
    if subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()!=head:refuse('CHECKOUT_SHA')
    result=check_source()
    # All source pins/transformations validated before ANY writes.
    for name,body in result.items():(ROOT/name).write_text(body)
    print('XGO_X86_NATIVE_PREVERIFIED_GRADLE_PROFILE_PASS: correct x86 paths, build task bypass guarded',flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['check','prepare']);p.add_argument('--head')
    a=p.parse_args()
    if a.mode=='prepare':
        if not a.head:refuse('HEAD_REQUIRED')
        prepare(a.head)
    else:
        for which,s in [('ffmpeg','val installPinnedFfmpegRuntime = tasks.register<Exec>("installPinnedFfmpegRuntime") {\n'+ '    outputs.files("src/main/jniLibs/arm64-v8a/test.so")\n'),
                        ('aria2','val buildPinnedAria2Runtime = tasks.register<Exec>("buildPinnedAria2Runtime") {\n'+'    outputs.files("src/main/jniLibs/arm64-v8a/test.so")\n')]:
            # Synthetic source deliberately fails the minimum-output-path check.
            try:gradle_transform(s,which)
            except ValueError as ex:
                if 'JNICALL_PATHS' not in str(ex):raise
            else:refuse('WEAK_GRADLE_ANCHOR_POLICY')
        print('XGO_X86_OPT_GRADLE_NEGATIVE_CONTRACTS_PASS',flush=True)

if __name__=='__main__':
    try:main()
    except Exception as e:print(str(e),file=sys.stderr);raise SystemExit(2)
