#!/usr/bin/env python3
"""Source-pinned, temporary Android x86_64 Gradle profile for hosted builds.

Run only inside CI; source tree changes are intentionally ephemeral. Keep the
canonical Gradle/ARM64 release definitions unchanged in Git. The produced APK is
x86_64-only, uses an actual Android/amd64 Go JNI engine and may omit optional
aria2/FFmpeg binary backends until independent x86_64 provenance is available.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / 'app/XDM.Android/app/build.gradle.kts'
BASE_BLOB = '7040b8359d3b2a8f31e1a1ec5c7d53aaec6bcae2'
PAIRS = [
    ('xgoRepositoryRoot.resolve("tools/xgo/build_android_xdmcore.py")',
     'xgoRepositoryRoot.resolve("tools/xgo/build_android_xdmcore_x86_64.py")'),
    ('file("src/main/jniLibs/arm64-v8a/libxdmcore.so")',
     'file("src/main/jniLibs/x86_64/libxdmcore.so")'),
    ('file("src/main/jniLibs/arm64-v8a/libxdmcore.h")',
     'file("src/main/jniLibs/x86_64/libxdmcore.h")'),
    ('abiFilters += setOf("arm64-v8a")',
     'abiFilters += setOf("x86_64")'),
    ('androidTestImplementation(libs.androidx.test.ext.junit)',
     'androidTestImplementation(libs.androidx.test.ext.junit)\n    androidTestImplementation(libs.androidx.test.runner)'),
]


def transform(source: str) -> str:
    output = source
    for before, after in PAIRS:
        if output.count(before) != 1 or after in output:
            raise ValueError('XGO_X86_BUILD_PROFILE_ANCHOR_MISMATCH:' + before)
        output = output.replace(before, after, 1)
    if source == output:
        raise ValueError('XGO_X86_PROFILE_NOT_CHANGED')
    return output


def prepare(repo: pathlib.Path = ROOT) -> None:
    target = repo / APP.relative_to(ROOT)
    native = repo / 'tools/xgo/build_android_xdmcore_x86_64.py'
    if not (os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_OS') == 'Linux'):
        raise ValueError('XGO_X86_PROFILE_CI_ONLY')
    if not native.is_file():
        raise ValueError('XGO_X86_NATIVE_BUILDER_MISSING')
    source = target.read_text(encoding='utf-8')
    sha = subprocess.check_output(['git','-C',str(repo),'hash-object',str(target)], text=True).strip()
    if sha != BASE_BLOB:
        raise ValueError('XGO_X86_WRONG_APP_GRADLE_BLOB:'+sha)
    patched = transform(source)
    target.write_text(patched, encoding='utf-8')
    print('XGO_X86_GRADLE_PROFILE_PREPARED: original ARM64 definitions remain in Git')


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if args.prepare == args.check:
        parser.error('choose exactly one of --prepare or --check')
    if args.check:
        original=APP.read_text(encoding='utf-8')
        transform(original)
        print('XGO_X86_PROFILE_SOURCE_PASS')
    else:
        prepare()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
