#!/usr/bin/env python3
"""Offline tests of SHA receipt, manifest target identity and ELF16K guards."""
from __future__ import annotations
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from xgo_hf16_apk_pair import ensure_elf_16k_arm64, verify, publish  # noqa: E402


def elf(align: int = 16384) -> bytes:
    result = bytearray(256)
    result[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', result, 18, 183)
    struct.pack_into('<Q', result, 32, 64)
    struct.pack_into('<H', result, 54, 56)
    struct.pack_into('<H', result, 56, 1)
    struct.pack_into('<I', result, 64, 1)
    struct.pack_into('<QQ', result, 72, 0, 0)
    struct.pack_into('<Q', result, 112, align)
    return bytes(result)


class PairContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.app = self.folder / 'app-debug.apk'
        self.test = self.folder / 'app-debug-androidTest.apk'
        with zipfile.ZipFile(self.app, 'w') as z:
            z.writestr('lib/arm64-v8a/libxdmcore.so', elf())
            z.writestr('classes.dex', b'dex' * 512)
        with zipfile.ZipFile(self.test, 'w') as z:
            z.writestr('classes.dex', b'dex' * 512)
        aapt = self.folder / 'aapt'
        aapt.write_text('''#!/usr/bin/env python3
import sys
if 'androidTest' in sys.argv[-1]:
    print("package: name='com.mikeyphw.xdm.android.debug.test' versionCode='22'")
    print("instrumentation: name='androidx.test.runner.AndroidJUnitRunner' targetPackage='com.mikeyphw.xdm.android.debug'")
else:
    print("package: name='com.mikeyphw.xdm.android.debug' versionCode='22'")
''')
        aapt.chmod(0o755)
        self.aapt = str(aapt)

    def test_valid_native_elf(self):
        ensure_elf_16k_arm64(elf())

    def test_elf_4k_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'ALIGNMENT_BELOW_16K'):
            ensure_elf_16k_arm64(elf(4096))

    def test_missing_arm64_native_is_refused(self):
        with zipfile.ZipFile(self.app, 'w') as z:
            z.writestr('classes.dex', b'dex' * 512)
        with self.assertRaisesRegex(ValueError, 'ARM64_JNI_MISSING'):
            verify(self.app, self.test, self.aapt)

    def test_wrong_test_target_is_refused(self):
        Path(self.aapt).write_text('''#!/usr/bin/env python3
import sys
if 'androidTest' in sys.argv[-1]:
 print("package: name='com.mikeyphw.xdm.android.debug.test'")
 print("instrumentation: name='androidx.test.runner.AndroidJUnitRunner' targetPackage='com.example.other'")
else:
 print("package: name='com.mikeyphw.xdm.android.debug'")
''')
        with self.assertRaisesRegex(ValueError, 'TARGET_OR_RUNNER_MISMATCH'):
            verify(self.app, self.test, self.aapt)

    def test_publish_receipt_and_checksum_are_source_bound(self):
        out = self.folder / 'published'
        publish(self.app, self.test, out, self.aapt, 'a'*40, '123456')
        receipt = json.loads((out/'APK_PAIR_RECEIPT.json').read_text())
        self.assertEqual(receipt['commit_sha'], 'a'*40)
        self.assertEqual(receipt['result'], 'BUILT_ONLY_NO_DEVICE_TESTS')
        self.assertEqual(receipt['abi'], 'arm64-v8a')
        self.assertEqual(len(receipt['apks']), 2)
        result = subprocess.run(['sha256sum', '-c', 'SHA256SUMS'], cwd=out, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_publish_refuses_invalid_git_sha(self):
        with self.assertRaisesRegex(ValueError, 'COMMIT_SHA_INVALID'):
            publish(self.app, self.test, self.folder/'output', self.aapt, 'unbound', '42')

    def test_cannot_overwrite_stale_artifact(self):
        out = self.folder / 'published'
        out.mkdir()
        (out/'old.txt').write_text('stale')
        with self.assertRaisesRegex(ValueError, 'DESTINATION_NOT_EMPTY'):
            publish(self.app, self.test, out, self.aapt, 'a'*40, '42')

if __name__ == '__main__':
    unittest.main(verbosity=2)
