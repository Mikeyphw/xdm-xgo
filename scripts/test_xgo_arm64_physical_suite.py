#!/usr/bin/env python3
"""P07 physical suite: architecture isolation, strict JUnit and negative receipts."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile
from unittest import mock
import unittest

SOURCE = Path(__file__).with_name('xgo_arm64_physical_suite.py')
spec = importlib.util.spec_from_file_location('physical_gate_qualification', SOURCE)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def receipt(expected, *, executed: bool) -> str:
    s=[]
    for index, value in enumerate(expected, 1):
        cls, method=value.split('#',1)
        s.extend(['INSTRUMENTATION_STATUS: class='+cls,
                  'INSTRUMENTATION_STATUS: current='+str(index),
                  'INSTRUMENTATION_STATUS: numtests=36',
                  'INSTRUMENTATION_STATUS: test='+method,
                  'INSTRUMENTATION_STATUS_CODE: 1'])
        if executed:
            s.extend(['INSTRUMENTATION_STATUS: test='+method,
                      'INSTRUMENTATION_STATUS_CODE: 0'])
    s += ['INSTRUMENTATION_RESULT: stream=' + ('\n\nOK (36 tests)' if executed else 'log-only'),
          'INSTRUMENTATION_CODE: -1']
    return '\n'.join(s)+'\n'


class SourceAndRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.expected=m.expected_methods()

    def refused(self, fn, *a, **k):
        with self.assertRaises(m.Refused):fn(*a, **k)

    def test_01_exact_manifest_hash_and_classes(self):
        b=m.EXPECTED_FILE.read_bytes()
        self.assertEqual(hashlib.sha256(b).hexdigest(),m.EXPECTED_SHA256)
        self.assertEqual(len(self.expected),36)
        self.assertNotIn('XgoX86JniSmokeTest', ' '.join(self.expected))

    def test_02_dry_run(self):
        self.assertEqual(m.verify(receipt(self.expected,executed=False),self.expected,executed=False)['test_count'],36)

    def test_03_real_run(self):
        self.assertTrue(m.verify(receipt(self.expected,executed=True),self.expected,executed=True)['executed'])

    def test_04_missing(self):
        data=receipt(self.expected,executed=True).replace('INSTRUMENTATION_STATUS: test='+self.expected[0].split('#')[1],
                                                          'INSTRUMENTATION_STATUS: test=missing',2)
        self.refused(m.verify,data,self.expected,executed=True)

    def test_05_duplicated(self):
        data=receipt(self.expected,executed=True).replace('INSTRUMENTATION_CODE: -1',
            'INSTRUMENTATION_STATUS: class='+self.expected[0].split('#')[0]+'\nINSTRUMENTATION_STATUS: test='+
            self.expected[0].split('#')[1]+'\nINSTRUMENTATION_STATUS_CODE: 0\nINSTRUMENTATION_CODE: -1')
        self.refused(m.verify,data,self.expected,executed=True)

    def test_06_negative_status(self):
        data=receipt(self.expected,executed=True).replace('INSTRUMENTATION_STATUS_CODE: 0',
                                                            'INSTRUMENTATION_STATUS_CODE: -2',1)
        self.refused(m.verify,data,self.expected,executed=True)

    def test_07_wrong_final_code(self):
        data=receipt(self.expected,executed=True).replace('INSTRUMENTATION_CODE: -1','INSTRUMENTATION_CODE: 0')
        self.refused(m.verify,data,self.expected,executed=True)

    def test_08_no_success_summary(self):
        data=receipt(self.expected,executed=True).replace('OK (36 tests)','OK (35 tests)')
        self.refused(m.verify,data,self.expected,executed=True)

    def test_09_progress_only_not_pass(self):
        data=receipt(self.expected,executed=True).replace('INSTRUMENTATION_STATUS_CODE: 0',
                                                            'INSTRUMENTATION_STATUS_CODE: 2',1)
        self.refused(m.verify,data,self.expected,executed=True)

    def test_10_x86_only_reappearance_refused(self):
        data=receipt(self.expected,executed=True).replace(self.expected[0].split('#')[0],m.EXCLUDED[0],1)
        self.refused(m.verify,data,self.expected,executed=True)

    def test_11_dry_run_cannot_succeed_as_execution(self):
        self.refused(m.verify,receipt(self.expected,executed=False),self.expected,executed=True)
        self.refused(m.verify,receipt(self.expected,executed=True),self.expected,executed=False)

    def test_12_instrumentation_failure_marker(self):
        data=receipt(self.expected,executed=True)+'FAILURES!!!\n'
        self.refused(m.verify,data,self.expected,executed=True)

    def test_13_guard_serial_and_runner(self):
        with tempfile.TemporaryDirectory() as td:
            self.refused(m.run,'localhost:5555',Path(td),'/bad/Runner')
            self.refused(m.device_guard,'localhost:5555; rm -rf /')

    def test_14_persisted_receipt_is_immutable(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'immutable.json'
            m.save_new(p,b'first')
            self.refused(m.save_new,p,b'second')
            self.assertEqual(p.read_bytes(),b'first')
            self.assertEqual(p.stat().st_mode&0o777,0o600)

    def test_15_fake_adb_execution_exact_36_and_reject_duplicates(self):
        outputs=[receipt(self.expected,executed=False),receipt(self.expected,executed=True)]
        commands=[]
        def runner(cmd,*,seconds):
            commands.append(cmd)
            if cmd[0]=='git':
                return subprocess.CompletedProcess(cmd,0,'a'*40+'\n','')
            self.assertTrue(cmd[0:4]==['adb','-s','localhost:5555','shell'])
            self.assertIn('notClass',cmd)
            self.assertIn(','.join(m.EXCLUDED),cmd)
            self.assertNotIn('install',cmd)
            return subprocess.CompletedProcess(cmd,0,outputs.pop(0),'')
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(m,'run_command',side_effect=runner),mock.patch.object(m,'device_guard',return_value={'api':36,'abi':'arm64-v8a','not_emulator':True}):
                result=m.run('localhost:5555',Path(td),m.RUNNER)
                self.assertTrue(result['physical_instrumentation_pass'])
                self.assertFalse(result['release_qualified'])
                self.assertFalse(result['media_soak_qualified'])
                self.assertEqual(result['source_commit'],'a'*40)
                self.assertTrue((Path(td)/'P07_EXACT_36_PHYSICAL_PASS.json').exists())
                self.refused(m.run,'localhost:5555',Path(td),m.RUNNER)
            self.assertEqual(len(commands),3)

    def test_16_negative_real_run_retains_evidence_without_approval(self):
        outputs=[receipt(self.expected,executed=False),receipt(self.expected,executed=True).replace('OK (36 tests)','FAILURES!!!')]
        def fake(cmd,*,seconds):return subprocess.CompletedProcess(cmd,0,outputs.pop(0),'')
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(m,'run_command',side_effect=fake),mock.patch.object(m,'device_guard',return_value={'api':36}):
                self.refused(m.run,'localhost:5555',Path(td),m.RUNNER)
            self.assertTrue((Path(td)/'physical-instrumentation.log').exists())
            self.assertFalse((Path(td)/'P07_EXACT_36_PHYSICAL_PASS.json').exists())

    def test_17_manifest_tampering_refused(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'methods.json';p.write_text(json.dumps(self.expected[:-1]))
            with mock.patch.object(m,'EXPECTED_FILE',p):self.refused(m.expected_methods)

    def test_18_source_runner_and_pin_contract(self):
        source=(m.ROOT/'scripts/run_physical_arm64_instrumentation.sh').read_text()
        self.assertIn('xgo_arm64_physical_suite.py',source)
        self.assertNotIn('adb -s "$serial" shell am instrument -w -r "$runner"',source)
        self.assertIn('XGO_ADB_NATIVE_ARM64_REQUIRED',source)
        self.assertIn('XGO_ADB_EMULATOR_REFUSED',source)
        self.assertIn('XGO_REAL_ARM64_DEVICE_INSTRUMENTATION_PASS',source)
        self.assertIn('sha256sum -c SHA256SUMS',source)
        self.assertIn('python3 -B',source)


if __name__=='__main__':
    unittest.main(verbosity=2)
