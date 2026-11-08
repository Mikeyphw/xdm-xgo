#!/usr/bin/env python3
"""Fail-closed provenance and APK-pair publisher, hosted on GitHub Actions.

No network, Gradle, signing or device access. Outputs one download-ready directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import zipfile

APP_ID = 'com.mikeyphw.xdm.android.debug'
TEST_ID = APP_ID + '.test'
RUNNER = 'androidx.test.runner.AndroidJUnitRunner'
LIB = 'lib/arm64-v8a/libxdmcore.so'


def aapt_path() -> str:
    for root in (os.environ.get('ANDROID_SDK_ROOT'), os.environ.get('ANDROID_HOME')):
        if root and (Path(root) / 'build-tools/36.0.0/aapt').is_file():
            return str(Path(root) / 'build-tools/36.0.0/aapt')
    binary = shutil.which('aapt')
    if not binary:
        raise ValueError('XGO_PAIR_AAPT_NOT_FOUND: build-tools;36.0.0 required')
    return binary


def badging(aapt: str, apk: Path) -> str:
    p = subprocess.run((aapt, 'dump', 'badging', str(apk)), capture_output=True, text=True)
    if p.returncode:
        raise ValueError('XGO_PAIR_AAPT_FAILED:' + apk.name + ':' + p.stderr[:160])
    return p.stdout


def identity(src: str) -> str:
    match = re.search(r"(?m)^package:\s+name='([^']+)'", src)
    if not match:
        raise ValueError('XGO_PAIR_PACKAGE_MISSING')
    return match.group(1)


def instrumentation_identity(aapt: str, apk: Path) -> tuple[str, str]:
    """Read instrumentation from the compiled manifest, not badging.

    `aapt dump badging` does not reliably expose instrumentation attributes.
    Require one complete <instrumentation> element in the test APK's xmltree.
    """
    p = subprocess.run((aapt, 'dump', 'xmltree', str(apk), 'AndroidManifest.xml'),
                       capture_output=True, text=True)
    if p.returncode:
        raise ValueError('XGO_PAIR_XMLTREE_FAILED:' + apk.name + ':' + p.stderr[:160])
    records: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in p.stdout.splitlines():
        # E: is an XML element; only attributes directly beneath instrumentation
        # count, never a matching value in an unrelated element or a nested tag.
        element = re.match(r'^\s*E:\s+([^\s(]+)', line)
        if element:
            if current is not None:
                records.append(current)
                current = None
            if element.group(1) == 'instrumentation':
                current = {}
            continue
        if current is None:
            continue
        attr = re.match(r'^\s*A:\s+android:(name|targetPackage)\(0x[0-9a-fA-F]+\)="([^"]*)"', line)
        if attr:
            key, value = attr.groups()
            if key in current:
                raise ValueError('XGO_PAIR_DUPLICATE_INSTRUMENTATION_ATTRIBUTE')
            current[key] = value
    if current is not None:
        records.append(current)
    if len(records) != 1:
        raise ValueError('XGO_PAIR_INSTRUMENTATION_COUNT_INVALID:' + str(len(records)))
    result = records[0]
    if result.get('name') != RUNNER or result.get('targetPackage') != APP_ID:
        raise ValueError('XGO_PAIR_INSTRUMENTATION_TARGET_OR_RUNNER_MISMATCH')
    return result['name'], result['targetPackage']


def ensure_elf_16k_arm64(blob: bytes) -> None:
    if len(blob) < 64 or blob[:4] != b'\x7fELF' or blob[4] != 2 or blob[5] != 1:
        raise ValueError('XGO_PAIR_JNI_ELF64_LE_INVALID')
    if struct.unpack_from('<H', blob, 18)[0] != 183:  # EM_AARCH64
        raise ValueError('XGO_PAIR_JNI_NOT_AARCH64')
    phoff = struct.unpack_from('<Q', blob, 32)[0]
    phentsize = struct.unpack_from('<H', blob, 54)[0]
    phnum = struct.unpack_from('<H', blob, 56)[0]
    if phnum < 1 or phnum > 512 or phentsize < 56 or phoff + phnum * phentsize > len(blob):
        raise ValueError('XGO_PAIR_JNI_PROGRAM_HEADERS_INVALID')
    load_count = 0
    for i in range(phnum):
        pos = phoff + i * phentsize
        if struct.unpack_from('<I', blob, pos)[0] != 1:  # PT_LOAD
            continue
        load_count += 1
        offset, vaddr = struct.unpack_from('<QQ', blob, pos + 8)
        align = struct.unpack_from('<Q', blob, pos + 48)[0]
        if align < 16384 or align & (align - 1) or offset % align != vaddr % align:
            raise ValueError('XGO_PAIR_JNI_LOAD_ALIGNMENT_BELOW_16K')
    if not load_count:
        raise ValueError('XGO_PAIR_JNI_NO_LOAD_SEGMENTS')


def verify(app: Path, test: Path, aapt: str) -> dict:
    for p in (app, test):
        if not p.is_file() or p.stat().st_size < 1024:
            raise ValueError('XGO_PAIR_APK_MISSING_OR_TINY:' + str(p))
    if app.resolve() == test.resolve():
        raise ValueError('XGO_PAIR_SAME_FILE')
    with zipfile.ZipFile(app) as archive:
        names = set(archive.namelist())
        if LIB not in names:
            raise ValueError('XGO_PAIR_ARM64_JNI_MISSING')
        if 'classes.dex' not in names:
            raise ValueError('XGO_PAIR_APP_DEX_MISSING')
        # A fat host emulator APK does not qualify ARM64 JNI provenance either.
        other_native = [n for n in names if n.startswith('lib/') and n.endswith('.so') and not n.startswith('lib/arm64-v8a/')]
        if other_native:
            raise ValueError('XGO_PAIR_UNEXPECTED_ABI')
        ensure_elf_16k_arm64(archive.read(LIB))
    with zipfile.ZipFile(test) as archive:
        if 'classes.dex' not in archive.namelist():
            raise ValueError('XGO_PAIR_TEST_DEX_MISSING')
    main_badging = badging(aapt, app)
    test_badging = badging(aapt, test)
    app_id, test_id = identity(main_badging), identity(test_badging)
    if app_id != APP_ID or test_id != TEST_ID:
        raise ValueError(f'XGO_PAIR_PACKAGE_ID_MISMATCH:{app_id}:{test_id}')
    instrumentation_identity(aapt, test)
    return {'app_package': app_id, 'test_package': test_id, 'instrumentation_runner': RUNNER,
            'target_package': APP_ID, 'abi': 'arm64-v8a', 'jni_elf': 'EM_AARCH64',
            'jni_min_pt_load_alignment': 16384}


def publish(app: Path, test: Path, out: Path, aapt: str, sha: str, run_id: str) -> None:
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('XGO_PAIR_COMMIT_SHA_INVALID')
    if not re.fullmatch('[0-9]{1,20}', run_id):
        raise ValueError('XGO_PAIR_RUN_ID_INVALID')
    info = verify(app, test, aapt)
    if out.exists() and any(out.iterdir()):
        raise ValueError('XGO_PAIR_DESTINATION_NOT_EMPTY')
    out.mkdir(parents=True, exist_ok=True)
    names = (('app-debug.apk', app), ('app-debug-androidTest.apk', test))
    entries = []
    for filename, src in names:
        shutil.copyfile(src, out / filename)
        content = (out / filename).read_bytes()
        entries.append({'file': filename, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
    (out / 'SHA256SUMS').write_text(''.join(f'{row["sha256"]}  {row["file"]}\n' for row in entries))
    receipt = {'schema': 1, 'result': 'BUILT_ONLY_NO_DEVICE_TESTS', 'commit_sha': sha,
               'github_run_id': run_id, 'github_repository': 'Mikeyphw/xdm-xgo',
               'artifact_name': 'xdm-android-physical-arm64-apk-pair',
               'apks': entries, **info}
    (out / 'APK_PAIR_RECEIPT.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print('XGO_HF16_APK_PAIR_PUBLISHED_BUILT_ONLY:' + sha + ':run=' + run_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    for opt in ('app', 'test', 'out'):
        parser.add_argument('--' + opt, required=True, type=Path)
    parser.add_argument('--sha', default=os.environ.get('GITHUB_SHA', ''))
    parser.add_argument('--run-id', default=os.environ.get('GITHUB_RUN_ID', ''))
    args = parser.parse_args()
    publish(args.app, args.test, args.out, aapt_path(), args.sha, args.run_id)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        print('XGO_HF16_PAIR_REFUSED:' + str(exc), file=sys.stderr)
        raise SystemExit(2)
