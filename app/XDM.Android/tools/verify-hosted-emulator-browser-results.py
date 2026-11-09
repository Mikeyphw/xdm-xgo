#!/usr/bin/env python3
"""XP02B: strict API36 browser parser instrumentation receipt; no physical ARM64 proof."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

CLASS = 'XdmBrowserIntentFrameworkInstrumentedTest'
EXPECTED = frozenset({
    'debugSchemeAddIntentRoundTrip',
    'releaseSchemeCannotEnterDebugReceiver',
    'releaseSchemeResolvesOnlyReleaseParser',
    'v2EncryptedCaptureHasNoPlaintextUrl',
    'v3PlaintextCaptureIsRejectedEvenWithCandidateContext',
    'duplicateUrlParameterFailsClosed',
    'unsafeNestedUrlFailsClosed',
    'unknownHostFailsClosed',
    'oversizedEnvelopeRejected',
    'uriAuthorityCredentialsAndFragmentsAreRejected',
})


def inspect(path: Path) -> dict[str, object]:
    if not path.is_dir():
        raise ValueError('XGO_XP02B_RESULTS_MISSING')
    files = sorted(path.rglob('TEST-*.xml'))
    if not files:
        raise ValueError('XGO_XP02B_JUNIT_XML_MISSING')
    seen: set[str] = set()
    digests: dict[str, str] = {}
    for file in files:
        payload = file.read_bytes()
        digests[file.relative_to(path).as_posix()] = hashlib.sha256(payload).hexdigest()
        tree = ET.fromstring(payload)
        suites = [tree] if tree.tag == 'testsuite' else list(tree.iter('testsuite'))
        if not suites:
            raise ValueError('XGO_XP02B_TESTSUITE_MISSING')
        for suite in suites:
            cases = list(suite.iter('testcase'))
            for attr in ('failures', 'errors', 'skipped'):
                raw = suite.get(attr)
                if raw is not None:
                    if not raw.isdecimal():
                        raise ValueError('XGO_XP02B_INVALID_SUITE_COUNT')
                    if int(raw) != 0:
                        raise ValueError('XGO_XP02B_SUITE_' + attr.upper())
            reported = suite.get('tests')
            if reported is not None:
                if not reported.isdecimal() or int(reported) != len(cases):
                    raise ValueError('XGO_XP02B_SUITE_COUNT_MISMATCH')
        for case in tree.iter('testcase'):
            cls = (case.get('classname') or '').split('.')[-1].split('$')[0]
            name = case.get('name') or ''
            if cls != CLASS or name not in EXPECTED:
                raise ValueError(f'XGO_XP02B_UNEXPECTED_TEST:{cls}.{name}')
            if name in seen:
                raise ValueError('XGO_XP02B_DUPLICATE_TEST:' + name)
            if case.find('failure') is not None or case.find('error') is not None:
                raise ValueError('XGO_XP02B_TEST_FAILED:' + name)
            if case.find('skipped') is not None:
                raise ValueError('XGO_XP02B_TEST_SKIPPED:' + name)
            seen.add(name)
    if seen != EXPECTED:
        raise ValueError('XGO_XP02B_MISSING_TESTS:' + ','.join(sorted(EXPECTED - seen)))
    return {
        'status': 'EMULATOR_X86_64_BROWSER_INTAKE_PASS',
        'module': ':browser-integration',
        'android_api': 36,
        'abi': 'x86_64',
        'native_arm64_executed': False,
        'app_composition_executed': False,
        'test_count': len(seen),
        'test_class': CLASS,
        'test_methods': sorted(seen),
        'github_sha': os.environ.get('GITHUB_SHA', ''),
        'xml_sha256': digests,
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
    args.receipt.write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
    print(f"XGO_XP02B_JUNIT_PASS: {receipt['test_count']} browser intake cases; 0 failures/errors/skips")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
