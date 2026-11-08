#!/usr/bin/env python3
"""Fail-closed verification of API36 x86_64 persistence instrumentation XML."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

EXPECTED = frozenset({
    'AppDatabaseMigrationTest',
    'BackendOwnershipStoreTest',
    'DownloadAdmissionDl01InstrumentedTest',
    'GenerationIntegrityMigrationTest',
    'MediaOutputAdmissionMc02InstrumentedTest',
    'PostProcessingMigrationTest',
    'Xar02GenerationOwnershipInstrumentedTest',
})


def inspect(path: Path) -> dict[str, object]:
    if not path.is_dir():
        raise ValueError(f'XGO_XP02_RESULTS_MISSING:{path}')
    xml_files = sorted(path.rglob('TEST-*.xml'))
    if not xml_files:
        raise ValueError('XGO_XP02_JUNIT_XML_MISSING')
    seen: set[str] = set()
    testcase_count = 0
    names: set[tuple[str, str]] = set()
    xml_digests: dict[str, str] = {}
    for xml_file in xml_files:
        payload = xml_file.read_bytes()
        xml_digests[str(xml_file.relative_to(path))] = hashlib.sha256(payload).hexdigest()
        suite = ET.fromstring(payload)
        suite_nodes = list(suite.iter('testsuite'))
        if not suite_nodes:
            raise ValueError(f'XGO_XP02_TESTSUITE_MISSING:{xml_file.name}')
        for node in suite_nodes:
            cases = list(node.iter('testcase'))
            for attr in ('failures', 'errors', 'skipped'):
                raw = node.get(attr)
                if raw is not None:
                    if not raw.isdecimal():
                        raise ValueError(f'XGO_XP02_INVALID_SUITE_COUNT:{attr}:{xml_file.name}')
                    if int(raw) != 0:
                        raise ValueError(f'XGO_XP02_SUITE_{attr.upper()}:{xml_file.name}')
            reported = node.get('tests')
            if reported is not None:
                if not reported.isdecimal() or int(reported) != len(cases):
                    raise ValueError(f'XGO_XP02_SUITE_COUNT_MISMATCH:{xml_file.name}')
        for case in suite.iter('testcase'):
            cls = (case.get('classname') or '').split('.')[-1].split('$')[0]
            method = case.get('name') or ''
            if not cls or not method:
                raise ValueError(f'XGO_XP02_TEST_ID_MISSING:{xml_file.name}')
            key = (cls, method)
            if key in names:
                raise ValueError(f'XGO_XP02_DUPLICATE_TEST:{cls}.{method}')
            names.add(key)
            if case.find('failure') is not None or case.find('error') is not None:
                raise ValueError(f'XGO_XP02_TEST_FAILED:{cls}.{method}')
            if case.find('skipped') is not None:
                raise ValueError(f'XGO_XP02_TEST_SKIPPED:{cls}.{method}')
            if cls not in EXPECTED:
                raise ValueError(f'XGO_XP02_UNEXPECTED_CLASS:{cls}')
            seen.add(cls)
            testcase_count += 1
    missing = EXPECTED - seen
    if missing:
        raise ValueError('XGO_XP02_MISSING_CLASSES:' + ','.join(sorted(missing)))
    if testcase_count < len(EXPECTED):
        raise ValueError('XGO_XP02_NO_TESTS_EXECUTED')
    return {
        'status': 'EMULATOR_X86_64_PERSISTENCE_PASS',
        'android_api': 36,
        'abi': 'x86_64',
        'native_arm64_executed': False,
        'module': ':persistence',
        'test_count': testcase_count,
        'test_classes': sorted(seen),
        'github_sha': os.environ.get('GITHUB_SHA', ''),
        'xml_files': len(xml_files),
        'xml_sha256': xml_digests,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--results-dir', type=Path, required=True)
    p.add_argument('--receipt', type=Path, required=True)
    args = p.parse_args()
    try:
        receipt = inspect(args.results_dir)
    except (ValueError, ET.ParseError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(f"XGO_XP02_JUNIT_PASS: {receipt['test_count']} executed tests across {len(EXPECTED)} classes; no failures, errors or skips")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
