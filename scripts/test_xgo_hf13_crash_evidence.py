#!/usr/bin/env python3
"""HF13 source contracts and deterministic, network-free failure evidence tests."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
HELPER=ROOT/'app/XDM.Android/tools/capture-hosted-instrumentation-evidence.sh'
WF=ROOT/'.github/workflows/android.yml'
WR=ROOT/'app/XDM.Android/tools/run-hosted-emulator-instrumentation.sh'

class HF13Tests(unittest.TestCase):
    def test_shell_syntax(self):
        for path in (HELPER, WR):
            p=subprocess.run(['bash','-n',str(path)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)

    def test_hosted_gate_preserves_actual_device_and_release_tests(self):
        src=WR.read_text()
        for needle in ('XDM_ARM64_TRANSLATION_UNAVAILABLE', 'XDM_HOST_KVM_UNAVAILABLE',
            'ro.kernel.qemu', 'ro.build.version.sdk', 'run-bug-hunt-phase11-validation-matrix.sh --device-only',
            './gradlew :app:connectedDebugAndroidTest','run-xar16-signed-release-gate.sh --ci',
            'exit "$original_exit"'):
            self.assertIn(needle,src)

    def test_each_job_keeps_real_emulator_and_uploads_evidence(self):
        wf=WF.read_text()
        self.assertEqual(wf.count('ReactiveCircus/android-emulator-runner@a421e43855164a8197daf9d8d40fe71c6996bb0d'),2)
        for name in ('instrumentation','signed-release'):
            section=wf.split('\n  '+name+':\n',1)[1]
            if name=='instrumentation':section=section.split('\n  signed-release:\n',1)[0]
            self.assertIn('if: always()',section)
            self.assertIn('xdm-instrumentation-evidence/',section)
            self.assertIn('script: bash app/XDM.Android/tools/run-hosted-emulator-instrumentation.sh --',section)
        self.assertIn("startsWith(github.ref, 'refs/tags/android-v')",wf)
        self.assertIn('XDM_RELEASE_KEYSTORE_BASE64',wf)

    def test_refuses_nonhost(self):
        p=subprocess.run(['bash',str(HELPER),'--device','1','emulator-5554'],env={**os.environ,'GITHUB_ACTIONS':'false','RUNNER_OS':'Linux'},capture_output=True,text=True)
        self.assertEqual(p.returncode,2)
        self.assertIn('XDM_HF13_HOST_ONLY',p.stderr)

    def test_bounded_crash_diagnostics_does_not_alter_exit(self):
        with tempfile.TemporaryDirectory() as d:
            fake=Path(d)/'bin';fake.mkdir()
            adb=fake/'adb'
            adb.write_text('#!/bin/sh\ncase "$*" in\n  *"logcat"*"crash"*) echo "Fatal signal 11 (SIGSEGV)" ;;\n  *"logcat"*) echo "AndroidRuntime: FATAL EXCEPTION: Instrumentation" ;;\n  *"instrumentation"*) echo "instrumentation:com.example.test/AndroidJUnitRunner (target=com.example.debug)" ;;\n  *"screencap"*) printf "PNG-MOCK" ;;\nesac\n')
            adb.chmod(0o755)
            uname=fake/'uname';uname.write_text('#!/bin/sh\necho x86_64\n');uname.chmod(0o755)
            env={**os.environ,'GITHUB_ACTIONS':'true','RUNNER_OS':'Linux','RUNNER_TEMP':d,'PATH':str(fake)+os.pathsep+os.environ.get('PATH','')}
            p=subprocess.run(['bash',str(HELPER),'--device','1','emulator-5554'],env=env,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            out=Path(d)/'xdm-instrumentation-evidence'
            self.assertIn('INSTRUMENTATION_FAILED_FAIL_CLOSED',(out/'HF13_RESULT.txt').read_text())
            self.assertIn('SIGSEGV',(out/'android-crash-buffer.txt').read_text())
            self.assertIn('FATAL EXCEPTION',(out/'android-runtime-errors.txt').read_text())
            self.assertIn('XDM_HF13_INSTRUMENTATION_FAILED',p.stderr)

    def test_succeeded_command_reports_success_not_device_acceptance(self):
        with tempfile.TemporaryDirectory() as d:
            fake=Path(d)/'bin';fake.mkdir()
            uname=fake/'uname';uname.write_text('#!/bin/sh\necho x86_64\n');uname.chmod(0o755)
            env={**os.environ,'GITHUB_ACTIONS':'true','RUNNER_OS':'Linux','RUNNER_TEMP':d,'PATH':str(fake)+os.pathsep+os.environ.get('PATH','')}
            p=subprocess.run(['bash',str(HELPER),'--device','0','emulator-5554'],env=env,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            t=(Path(d)/'xdm-instrumentation-evidence/HF13_RESULT.txt').read_text()
            self.assertIn('HF13_TEST_EXIT=0',t)
            self.assertIn('HF13_RELEASE_ACCEPTANCE=false',t)

if __name__ == '__main__':
    unittest.main(verbosity=2)
