#!/usr/bin/env python3
"""Baseline test inventory: truthful status accounting, no invented pass."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path


def inventory(matrix_path, evidence_path=None):
    with Path(matrix_path).open(newline='', encoding='utf-8') as file:
        matrix = list(csv.DictReader(file))
    if len(set(row['test_id'] for row in matrix)) != len(matrix):
        raise ValueError('duplicate matrix test ID')
    evidence = {} if not evidence_path else json.loads(Path(evidence_path).read_text())
    unknown = set(evidence) - {row['test_id'] for row in matrix}
    if unknown:
        raise ValueError(f'unknown evidence IDs: {sorted(unknown)}')
    for k, v in evidence.items():
        if v.get('status') not in ('passed', 'failed', 'not_run', 'unsupported'):
            raise ValueError(f'unknown result state: {k}')
        if v['status'] in ('passed', 'failed') and not v.get('command_or_receipt'):
            raise ValueError(f'evidence without test command/receipt: {k}')
    status = {row['test_id']: evidence.get(row['test_id'], {'status': 'not_run'})['status']
              for row in matrix}
    return {'schema_version': 1, 'total': len(matrix),
            'counts': dict(Counter(status.values())), 'cases': status,
            'pass_is_not_inferred_from_suite_success': True}


def main():
    root = Path(__file__).resolve().parent
    p = argparse.ArgumentParser()
    p.add_argument('--matrix', default=str(root / 'test_matrix.csv'))
    p.add_argument('--evidence', help='Optional explicitly recorded per-case receipts')
    p.add_argument('--out', default='-')
    a = p.parse_args()
    report = json.dumps(inventory(a.matrix, a.evidence), indent=2, sort_keys=True) + '\n'
    if a.out == '-':
        print(report, end='')
    else:
        Path(a.out).write_text(report)
    print('MP00_INVENTORY_PASS', flush=True)


if __name__ == '__main__':
    main()
