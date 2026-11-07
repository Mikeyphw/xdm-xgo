#!/usr/bin/env python3
"""HF12 host-library regression checks; no root, Android SDK, Gradle or network."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'app/XDM.Android/tools/provision-hosted-emulator-runtime.sh'
WORKFLOW = ROOT / '.github/workflows/android.yml'
RUNNER = ROOT / 'app/XDM.Android/tools/run-hosted-emulator-instrumentation.sh'
MOCK_SHELL = shutil.which('sh')
if not MOCK_SHELL or not Path(MOCK_SHELL).is_absolute():
    raise RuntimeError('HF12 test harness requires an absolute POSIX sh path')


def job_text(source: str, name: str) -> str:
    marker = f'\n  {name}:\n'
    assert source.count(marker) == 1, name
    tail = source.split(marker, 1)[1]
    return tail.split('\n  signed-release:\n', 1)[0] if name == 'instrumentation' else tail


def executable(path: Path, content: str) -> None:
    # Mock commands must run on Ubuntu *and* native Termux (which has no /bin/sh).
    if content.startswith('#!/bin/sh\n'):
        content = f'#!{MOCK_SHELL}\n' + content[len('#!/bin/sh\n'):]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    path.chmod(0o755)


def mock_host_env(folder: Path, **overrides: str) -> dict[str, str]:
    """Model a GitHub x86_64 host for subcommands, without changing host checks.

    Only subprocesses with this private PATH see the fake uname. The production
    helper continues rejecting ARM64/Termux outside the isolated mock environment.
    No privilege, network, or Android SDK is needed for these tests.
    """
    executable(folder / 'uname', '#!/bin/sh\necho x86_64\n')
    # `--prepare` checks availability of apt-get. Never touch host package tools.
    executable(folder / 'apt-get', '#!/bin/sh\nexit 87\n')
    env = dict(os.environ, GITHUB_ACTIONS='true', RUNNER_OS='Linux',
               PATH=f'{folder}:{os.environ.get("PATH", "")}')
    env.update(overrides)
    return env


class HF12Contracts(unittest.TestCase):
    def test_both_emulator_jobs_prepare_and_verify_in_correct_workdir(self) -> None:
        wf = WORKFLOW.read_text(encoding='utf-8')
        for name, prefix in (
            ('instrumentation', 'app/XDM.Android/tools/'),
            ('signed-release', 'tools/'),
        ):
            job = job_text(wf, name)
            prepare = f'bash {prefix}provision-hosted-emulator-runtime.sh --prepare'
            verify = f'bash {prefix}provision-hosted-emulator-runtime.sh --verify "$sdk_root"'
            self.assertEqual(job.count(prepare), 1, name)
            self.assertEqual(job.count(verify), 1, name)
            self.assertLess(job.index(prepare), job.index("sdkmanager --install 'emulator'"))
            self.assertLess(job.index("sdkmanager --install 'emulator'"), job.index(verify))
            self.assertIn('test -d "$sdk_root/system-images/android-36/google_apis/x86_64"', job)
            self.assertNotIn(' -version >/dev/null 2>&1', job)
            self.assertIn('Require KVM acceleration for Android instrumentation', job)
        self.assertIn('script: bash app/XDM.Android/tools/run-hosted-emulator-instrumentation.sh --device', wf)
        self.assertIn('script: bash app/XDM.Android/tools/run-hosted-emulator-instrumentation.sh --signed-release', wf)

    def test_critical_native_and_release_gates_are_not_bypassed(self) -> None:
        workflow = WORKFLOW.read_text(encoding='utf-8')
        runner = RUNNER.read_text(encoding='utf-8')
        self.assertIn("startsWith(github.ref, 'refs/tags/android-v')", workflow)
        self.assertIn('XDM_RELEASE_SIGNER_SHA256', workflow)
        self.assertIn('bash tools/run-xar16-signed-release-gate.sh --ci', runner)
        self.assertIn('./gradlew :app:connectedDebugAndroidTest', runner)
        self.assertIn('ro.kernel.qemu', runner)
        self.assertIn('arm64-v8a', runner)
        self.assertIn('XDM_ARM64_TRANSLATION_UNAVAILABLE', runner)
        self.assertIn('XDM_HOST_KVM_UNAVAILABLE', runner)
        self.assertIn('run-bug-hunt-phase11-validation-matrix.sh --device-only', runner)

    def test_shell_syntax(self) -> None:
        proc = subprocess.run(['bash', '-n', str(HELPER)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_prepare_denies_non_hosted_execution(self) -> None:
        env = dict(os.environ, GITHUB_ACTIONS='false', RUNNER_OS='Linux')
        proc = subprocess.run(['bash', str(HELPER), '--prepare'], env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn('XDM_HF12_HOSTED_LINUX_X64_REQUIRED', proc.stderr)

    def test_real_host_arch_gate_stays_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix='hf12-arm64-') as tmp:
            folder = Path(tmp)
            executable(folder / 'uname', '#!/bin/sh\necho aarch64\n')
            env = dict(os.environ, GITHUB_ACTIONS='true', RUNNER_OS='Linux',
                       PATH=f'{folder}:{os.environ.get("PATH", "")}')
            proc = subprocess.run(['bash', str(HELPER), '--prepare'], env=env, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2)
            self.assertIn('XDM_HF12_HOSTED_LINUX_X64_REQUIRED', proc.stderr)

    def test_prepare_requests_ubuntu_libraries_without_root_or_network(self) -> None:
        with tempfile.TemporaryDirectory(prefix='hf12-libs-') as tmp:
            folder = Path(tmp)
            log = folder / 'sudo.log'
            executable(folder / 'sudo', '#!/bin/sh\nprintf "%s\\n" "$*" >> "$XDM_HF12_TEST_SUDO_LOG"\nexit 0\n')
            env = mock_host_env(folder, XDM_HF12_TEST_SUDO_LOG=str(log))
            proc = subprocess.run(['bash', str(HELPER), '--prepare'], env=env, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            calls = log.read_text(encoding='utf-8')
            self.assertIn('apt-get update -qq', calls)
            self.assertIn('apt-get install -y -qq --no-install-recommends', calls)
            self.assertIn('libpulse0', calls)
            self.assertIn('libasound2t64', calls)
            self.assertIn('XDM_HF12_EMULATOR_LIBRARIES_INSTALLED', proc.stdout)

    def test_verify_reports_real_loader_error_without_suppressing(self) -> None:
        with tempfile.TemporaryDirectory(prefix='hf12-error-') as tmp:
            sdk = Path(tmp) / 'sdk'
            executable(sdk / 'emulator/emulator', '#!/bin/sh\necho "qemu: error while loading shared libraries: libpulse.so.0: cannot open shared object file" >&2\nexit 127\n')
            (sdk / 'system-images/android-36/google_apis/x86_64').mkdir(parents=True)
            env = mock_host_env(Path(tmp), RUNNER_TEMP=tmp)
            proc = subprocess.run(['bash', str(HELPER), '--verify', str(sdk)], env=env, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2)
            self.assertIn('libpulse.so.0', proc.stderr)
            self.assertIn('exit=127', proc.stderr)
            self.assertIn('XDM_HF12_EMULATOR_RUNTIME_FAILED', proc.stderr)

    def test_verify_reports_missing_binary_or_image(self) -> None:
        with tempfile.TemporaryDirectory(prefix='hf12-missing-') as tmp:
            sdk = Path(tmp) / 'sdk'
            sdk.mkdir()
            env = mock_host_env(Path(tmp), RUNNER_TEMP=tmp)
            args = ['bash', str(HELPER), '--verify', str(sdk)]
            missing = subprocess.run(args, env=env, capture_output=True, text=True)
            self.assertEqual(missing.returncode, 2)
            self.assertIn('XDM_HF12_EMULATOR_MISSING', missing.stderr)
            executable(sdk / 'emulator/emulator', '#!/bin/sh\necho emulator valid\n')
            no_image = subprocess.run(args, env=env, capture_output=True, text=True)
            self.assertEqual(no_image.returncode, 2)
            self.assertIn('XDM_HF12_API36_GOOGLE_APIS_IMAGE_MISSING', no_image.stderr)
            (sdk / 'system-images/android-36/google_apis/x86_64').mkdir(parents=True)
            success = subprocess.run(args, env=env, capture_output=True, text=True)
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertIn('XDM_HF12_EMULATOR_RUNTIME_PASS', success.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
