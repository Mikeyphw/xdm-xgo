#!/usr/bin/env python3
"""Strict validator for owner-measured, licensed 1DM+ black-box receipts."""
import argparse
import csv
import json
import re
from pathlib import Path

STATUSES = {'measured', 'not_run', 'unsupported', 'failed'}
SECRET_FIELDS = {'cookie', 'authorization', 'token', 'password', 'secret', 'raw_url',
                 'url', 'headers', 'query', 'private_path'}
# Evidence is intentionally structured. Arbitrary private URLs/log lines are not allowed.
EVIDENCE_FIELDS = {'quality_labels', 'track_types', 'output_stream_types',
                   'duration_s', 'output_sha256', 'decoded_fingerprints',
                   'redacted_screenshot_sha256', 'request_counts', 'notes',
                   'app_version_observed', 'signer_identity_observed'}
SENSITIVE_TEXT = re.compile(r'(?i)(https?://|file://|xdmdownload:|idmdownload:|\bbearer\s+|\bcookie\s*:|\bauthorization\s*:|[?&]token=|[?&]key=|password=)')


def validate(reference, matrix):
    with Path(matrix).open(newline='', encoding='utf-8') as file:
        allowed = {r['test_id'] for r in csv.DictReader(file)
                   if r['test_id'].startswith('REF')}
    if set(reference.get('observations', {})) != allowed:
        raise ValueError('reference cases do not match test matrix')
    if reference.get('reference', {}).get('signer_identity_verified') is True:
        if not reference['reference'].get('signing_certificate_sha256'):
            raise ValueError('signer verification requires observed certificate evidence')
    for case, obs in reference['observations'].items():
        if obs.get('status') not in STATUSES:
            raise ValueError(f'invalid reference status for {case}')
        if obs['status'] in ('measured', 'failed'):
            if not obs.get('observed_at') or not obs.get('evidence'):
                raise ValueError(f'unsubstantiated measurement: {case}')
        else:
            if obs.get('evidence'):
                raise ValueError(f'{case} has evidence despite not being measured')
        if isinstance(obs.get('evidence'), dict):
            unexpected = set(obs['evidence']) - EVIDENCE_FIELDS
            if unexpected:
                raise ValueError(f'non-allowlisted evidence fields for {case}: {sorted(unexpected)}')
        def inspect(value):
            if isinstance(value, dict):
                for k, v in value.items():
                    if k.lower() in SECRET_FIELDS:
                        raise ValueError(f'disallowed sensitive field in {case}: {k}')
                    inspect(v)
            elif isinstance(value, list):
                for v in value:
                    inspect(v)
            elif isinstance(value, str) and SENSITIVE_TEXT.search(value):
                raise ValueError(f'sensitive or unredacted text in {case}')
        inspect(obs)
    return {status: sum(o['status'] == status for o in reference['observations'].values())
            for status in sorted(STATUSES)}


def main():
    base = Path(__file__).resolve().parent
    p = argparse.ArgumentParser()
    p.add_argument('--reference', default=str(base / 'reference_1dm.json'))
    p.add_argument('--matrix', default=str(base / 'test_matrix.csv'))
    a = p.parse_args()
    print(json.dumps(validate(json.loads(Path(a.reference).read_text()), a.matrix), sort_keys=True))


if __name__ == '__main__':
    main()
