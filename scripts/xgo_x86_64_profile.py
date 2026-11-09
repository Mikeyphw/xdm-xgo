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
AUTHORITY = ROOT / 'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidEngineProcessAuthority.kt'
AUTHORITY_BLOB = '8c5a0bc74f96b67dfaea4545f9bf99f4a4c451ca'
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


# Only a disposable, opt-in x86_64 CI checkout may change the provenance contract.
# Production ARM64 source and its strict arch gate remain exactly as checked in.
ARCH_PROVENANCE_SOURCE = 'require(provenance.optString("target_arch") == "arm64") { "xdmcore target arch provenance mismatch" }'
ARCH_PROVENANCE_TEST = 'require(provenance.optString("target_arch") == "amd64") { "xdmcore target arch provenance mismatch" }'


def transform_authority(source: str) -> str:
    if source.count(ARCH_PROVENANCE_SOURCE) != 1 or ARCH_PROVENANCE_TEST in source:
        raise ValueError('XGO_X86_AUTHORITY_ARCH_ANCHOR_MISMATCH')
    return source.replace(ARCH_PROVENANCE_SOURCE, ARCH_PROVENANCE_TEST, 1)


def git_blob(repo: pathlib.Path, target: pathlib.Path) -> str:
    return subprocess.check_output(
        ['git', '-C', str(repo), 'hash-object', str(target)],
        text=True,
    ).strip()


def verify_source_pins(repo: pathlib.Path, app: pathlib.Path, authority: pathlib.Path) -> None:
    for target, expected, label in (
        (app, BASE_BLOB, 'APP_GRADLE'),
        (authority, AUTHORITY_BLOB, 'ENGINE_AUTHORITY'),
    ):
        if not target.is_file() or target.is_symlink():
            raise ValueError(f'XGO_X86_{label}_MISSING_OR_SYMLINK')
        observed = git_blob(repo, target)
        if observed != expected:
            raise ValueError(f'XGO_X86_{label}_BLOB_MISMATCH:{observed}')


def prepare(repo: pathlib.Path = ROOT) -> None:
    target = repo / APP.relative_to(ROOT)
    authority = repo / AUTHORITY.relative_to(ROOT)
    native = repo / 'tools/xgo/build_android_xdmcore_x86_64.py'
    if not (os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_OS') == 'Linux'):
        raise ValueError('XGO_X86_PROFILE_CI_ONLY')
    if not native.is_file():
        raise ValueError('XGO_X86_NATIVE_BUILDER_MISSING')
    # Validate both source hashes and both transformations BEFORE either write.
    verify_source_pins(repo, target, authority)
    patched = transform(target.read_text(encoding='utf-8'))
    patched_authority = transform_authority(authority.read_text(encoding='utf-8'))
    target.write_text(patched, encoding='utf-8')
    authority.write_text(patched_authority, encoding='utf-8')
    print('XGO_X86_GRADLE_AND_PROVENANCE_PROFILE_PREPARED: test-only amd64; production ARM64 unchanged')


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
        transform_authority(AUTHORITY.read_text(encoding='utf-8'))
        print('XGO_X86_PROFILE_SOURCE_PASS: Gradle and native arch policy anchors verified')
    else:
        prepare()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
