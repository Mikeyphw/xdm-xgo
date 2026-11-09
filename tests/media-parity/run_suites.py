#!/usr/bin/env python3
"""Opt-in host-side existing XDM suites with a receipt separate from test-case parity."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SUITES = {
    'go_media': ([['go', 'test', './media/...']], ROOT / 'engine'),
    'extension_node': ([['node', str(p.relative_to(ROOT))] for p in sorted(
        (ROOT / 'app/XDM.Android/browser-extension/tests').glob('test_*.js'))], ROOT),
    'kotlin_media_native': ([['./gradlew', '--no-configuration-cache', ':media:test',
                              ':transfer-native:testDebugUnitTest']], ROOT / 'app/XDM.Android')
}


def execute(name):
    commands, cwd = SUITES[name]
    if not commands or not cwd.is_dir():
        raise FileNotFoundError(f'XDM suite source unavailable: {name}')
    result = {'name': name, 'status': 'passed', 'executed': 0,
              'observed_at': datetime.now(timezone.utc).isoformat(),
              'source': 'real command process exit code; no production parity inference'}
    for command in commands:
        p = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=900)
        result['executed'] += 1
        if p.returncode:
            result['status'] = 'failed'
            result['failed_command'] = command
            result['exit_code'] = p.returncode
            break
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('names', nargs='+', choices=sorted(SUITES))
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = []
    for name in args.names:
        try:
            row = execute(name)
        except Exception as exc:
            row = {'name': name, 'status': 'failed', 'error_type': type(exc).__name__}
        result.append(row)
        print(f"MP00_SUITE_{row['status'].upper()}: {name}", flush=True)
    Path(args.output).write_text(json.dumps({'schema_version': 1, 'suites': result},
                                            indent=2, sort_keys=True) + '\n')
    if any(row['status'] != 'passed' for row in result):
        sys.exit(1)


if __name__ == '__main__':
    main()
