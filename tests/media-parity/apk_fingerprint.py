#!/usr/bin/env python3
"""Offline, read-only 1DM reference metadata; never uploads the APK."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from zipfile import ZipFile


def fingerprint(apk):
    apk = Path(apk).resolve(strict=True)
    with apk.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    with ZipFile(apk) as zipfile:
        corrupt = zipfile.testzip()
        if corrupt:
            raise ValueError('reference APK ZIP CRC check failed')
        names = zipfile.namelist()
        abi = sorted({match.group(1) for n in names
                      if (match := re.fullmatch(r'lib/([^/]+)/[^/]+\.so', n))})
        dex = len([n for n in names if re.fullmatch(r'classes\d*\.dex', n)])
        libraries = len([n for n in names if re.fullmatch(r'lib/[^/]+/[^/]+\.so', n)])
    receipt = {'sha256': digest, 'size_bytes': apk.stat().st_size, 'abi': abi,
               'dex_files': dex, 'native_libraries': libraries,
               'zip_crc_verified': True, 'signer_identity_verified': False,
               'installed_or_behaviorally_tested': False}
    apksigner = shutil.which('apksigner')
    if apksigner:
        p = subprocess.run([apksigner, 'verify', '--print-certs', str(apk)],
                           capture_output=True, text=True, timeout=30)
        receipt['android_signature_structurally_valid'] = p.returncode == 0
        if p.returncode == 0:
            cert = re.search(r'Signer #1 certificate SHA-256 digest:\s*([a-f\d:]+)', p.stdout, re.I)
            if cert:
                receipt['signing_certificate_sha256'] = cert.group(1).replace(':', '').lower()
        # APK cryptographic validation is not vendor identity or license verification.
    else:
        receipt['android_signature_structurally_valid'] = None
    return receipt


def main():
    p = argparse.ArgumentParser()
    p.add_argument('apk', help='Path on an owner-controlled workstation only')
    p.add_argument('--output', default='-')
    args = p.parse_args()
    data = json.dumps(fingerprint(args.apk), indent=2, sort_keys=True) + '\n'
    if args.output == '-':
        print(data, end='')
    else:
        Path(args.output).write_text(data)


if __name__ == '__main__':
    main()
