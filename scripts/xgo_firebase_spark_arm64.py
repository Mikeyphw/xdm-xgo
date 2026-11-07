#!/usr/bin/env python3
"""Offline validation for the manual, single-device Firebase Spark ARM64 lane.

No Google calls here. Device discovery and the paid-quota guard are handled by
GitHub Actions before the gcloud test command is invoked.
"""
from __future__ import annotations
import argparse
import json
import re
import struct
import sys
import zipfile
from pathlib import Path


def check_model(data: dict, model: str, version: str) -> None:
    if not re.fullmatch(r'[A-Za-z0-9._-]{2,80}', model):
        raise ValueError('XGO_SPARK_MODEL_ID_REFUSED')
    if not re.fullmatch(r'[0-9]{2,3}', version):
        raise ValueError('XGO_SPARK_VERSION_ID_REFUSED')
    if not isinstance(data, dict) or data.get('id') != model:
        raise ValueError('XGO_SPARK_MODEL_CATALOG_MISMATCH')
    if data.get('form') != 'PHYSICAL':
        raise ValueError('XGO_SPARK_PHYSICAL_DEVICE_REQUIRED')
    if version not in data.get('supportedVersionIds', []):
        raise ValueError('XGO_SPARK_ANDROID_VERSION_UNAVAILABLE')
    abis = data.get('supportedAbis', [])
    if not any(abi == 'arm64-v8a' or abi == version + ':arm64-v8a' for abi in abis):
        raise ValueError('XGO_SPARK_NATIVE_ARM64_REQUIRED')
    if data.get('accessDeniedReasons'):
        raise ValueError('XGO_SPARK_MODEL_ACCESS_DENIED')
    if any(str(tag).lower() in {'deprecated', 'preview'} for tag in data.get('tags', [])):
        raise ValueError('XGO_SPARK_MODEL_NOT_STABLE')


def check_apks(app: Path, tests: Path) -> dict:
    if app.resolve() == tests.resolve():
        raise ValueError('XGO_SPARK_APK_PAIR_IDENTICAL')
    if not app.is_file() or not tests.is_file():
        raise ValueError('XGO_SPARK_APK_MISSING')
    with zipfile.ZipFile(app) as z:
        names = set(z.namelist())
        required = {'AndroidManifest.xml', 'classes.dex', 'lib/arm64-v8a/libxdmcore.so'}
        if not required.issubset(names):
            raise ValueError('XGO_SPARK_ARM64_APP_PAYLOAD_MISSING:' + ','.join(sorted(required - names)))
        with z.open('lib/arm64-v8a/libxdmcore.so') as f:
            elf = f.read(64)
        if len(elf) < 64 or elf[:4] != b'\x7fELF' or elf[4] != 2 or elf[5] != 1 or struct.unpack_from('<H', elf, 18)[0] != 183:
            raise ValueError('XGO_SPARK_NATIVE_ELF_AARCH64_REQUIRED')
        if any(name.startswith('lib/x86') and name.endswith('/libxdmcore.so') for name in names):
            raise ValueError('XGO_SPARK_WRONG_NATIVE_ABI_PACKAGED')
    with zipfile.ZipFile(tests) as z:
        names = set(z.namelist())
        if not {'AndroidManifest.xml', 'classes.dex'}.issubset(names):
            raise ValueError('XGO_SPARK_INSTRUMENTATION_APK_INVALID')
    return {'app_apk_bytes': app.stat().st_size, 'test_apk_bytes': tests.stat().st_size, 'arm64_native': True}


def main() -> int:
    p = argparse.ArgumentParser()
    subs = p.add_subparsers(dest='command', required=True)
    model = subs.add_parser('check-model')
    model.add_argument('--catalog-json', type=Path, required=True)
    model.add_argument('--model-id', required=True)
    model.add_argument('--version-id', required=True)
    apks = subs.add_parser('check-apks')
    apks.add_argument('--app', type=Path, required=True)
    apks.add_argument('--test', type=Path, required=True)
    a = p.parse_args()
    try:
        if a.command == 'check-model':
            check_model(json.loads(a.catalog_json.read_text(encoding='utf-8')), a.model_id, a.version_id)
            print('XGO_SPARK_NATIVE_PHYSICAL_CATALOG_PASS')
        else:
            print('XGO_SPARK_APK_PAIR_PASS:' + json.dumps(check_apks(a.app, a.test), sort_keys=True))
    except (ValueError, OSError, zipfile.BadZipFile, KeyError) as e:
        print('XGO_SPARK_PRECHECK_REFUSED: ' + str(e), file=sys.stderr)
        return 2
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
