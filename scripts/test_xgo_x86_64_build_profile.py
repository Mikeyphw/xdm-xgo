#!/usr/bin/env python3
"""Native-free XP03 x86_64 profile/ELF/CI source and refusal regression tests."""
from __future__ import annotations
import importlib.util
import pathlib
import hashlib
import os
import subprocess
from unittest import mock
import struct
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class X86SourceAndIntegrity(unittest.TestCase):
    def test_profile_patches_only_five_exact_abi_inputs(self):
        p = load('scripts/xgo_x86_64_profile.py', 'profile_x86')
        fixture = '\n'.join(before for before, _ in p.PAIRS)
        replaced = p.transform(fixture)
        for old, new in p.PAIRS:
            if old not in new:
                self.assertNotIn(old, replaced)
            self.assertIn(new, replaced)
        self.assertEqual(len(p.PAIRS), 5)
        self.assertRaisesRegex(ValueError, 'ANCHOR_MISMATCH', p.transform, fixture.replace('arm64-v8a', 'x86_64'))
        self.assertRaisesRegex(ValueError, 'ANCHOR_MISMATCH', p.transform, fixture + '\n' + p.PAIRS[0][0])

    def test_x86_provenance_mapping_is_strictly_test_only(self):
        p = load('scripts/xgo_x86_64_profile.py', 'profile_arch_policy')
        src = 'prefix\n' + p.ARCH_PROVENANCE_SOURCE + '\nsuffix'
        result = p.transform_authority(src)
        self.assertIn(p.ARCH_PROVENANCE_TEST, result)
        self.assertNotIn(p.ARCH_PROVENANCE_SOURCE, result)
        self.assertIn('amd64', result)
        self.assertNotIn('== "arm64"', result)
        with self.assertRaisesRegex(ValueError, 'AUTHORITY_ARCH_ANCHOR_MISMATCH'):
            p.transform_authority(result)
        with self.assertRaisesRegex(ValueError, 'AUTHORITY_ARCH_ANCHOR_MISMATCH'):
            p.transform_authority(src + '\n' + p.ARCH_PROVENANCE_SOURCE)
        with self.assertRaisesRegex(ValueError, 'AUTHORITY_ARCH_ANCHOR_MISMATCH'):
            p.transform_authority(src.replace('"arm64"', '"x86_64"'))
        self.assertEqual(len(p.AUTHORITY_BLOB), 40)
        self.assertIn("GITHUB_ACTIONS", pathlib.Path(p.__file__).read_text())
        self.assertIn("RUNNER_OS", pathlib.Path(p.__file__).read_text())

    def test_atomic_preparation_source_validation(self):
        p = load('scripts/xgo_x86_64_profile.py', 'profile_atomic')
        with tempfile.TemporaryDirectory() as td:
            repo = pathlib.Path(td)
            app = repo / p.APP.relative_to(p.ROOT)
            auth = repo / p.AUTHORITY.relative_to(p.ROOT)
            builder = repo / 'tools/xgo/build_android_xdmcore_x86_64.py'
            for target in (app, auth, builder):
                target.parent.mkdir(parents=True, exist_ok=True)
            a_src = '\n'.join(x for x, _ in p.PAIRS) + '\n'
            b_src = 'Kotlin\n' + p.ARCH_PROVENANCE_SOURCE + '\n'
            app.write_text(a_src)
            auth.write_text(b_src)
            builder.write_text('native compiler source exists\n')
            def blob(data):
                content = data.encode()
                return hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
            with mock.patch.object(p, 'BASE_BLOB', blob(a_src)), \
                 mock.patch.object(p, 'AUTHORITY_BLOB', blob(b_src)), \
                 mock.patch.dict(os.environ, {'GITHUB_ACTIONS':'true', 'RUNNER_OS':'Linux'}):
                # No partial rewrite when either source pin has drifted.
                auth.write_text(b_src + 'different\n')
                with self.assertRaisesRegex(ValueError, 'ENGINE_AUTHORITY_BLOB_MISMATCH'):
                    p.prepare(repo)
                self.assertEqual(app.read_text(), a_src)
                auth.write_text(b_src)
                p.prepare(repo)
                self.assertEqual(app.read_text(), p.transform(a_src))
                self.assertEqual(auth.read_text(), p.transform_authority(b_src))

        p = load('scripts/xgo_x86_64_profile.py', 'profile_real')
        gradle = ROOT / 'app/XDM.Android/app/build.gradle.kts'
        if gradle.is_file():
            self.assertEqual(gradle.read_text().count('abiFilters += setOf("arm64-v8a")'), 1)
            p.transform(gradle.read_text())
        self.assertEqual(len(p.BASE_BLOB), 40)
        self.assertIn('androidTestImplementation(libs.androidx.test.runner)', p.transform('\n'.join(before for before, _ in p.PAIRS)))
        self.assertIn('XGO_X86_PROFILE_CI_ONLY', (ROOT / 'scripts/xgo_x86_64_profile.py').read_text())
        authority = ROOT / 'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidEngineProcessAuthority.kt'
        if authority.is_file():
            self.assertEqual(authority.read_text().count(p.ARCH_PROVENANCE_SOURCE), 1)
            self.assertEqual(authority.read_text().count(p.ARCH_PROVENANCE_TEST), 0)
            self.assertEqual(p.git_blob(ROOT, authority), p.AUTHORITY_BLOB)
        self.assertNotIn('git reset --hard', (ROOT / 'scripts/xgo_x86_64_profile.py').read_text())

    def test_workflow_preserves_prior_gates_and_executes_runtime_only_on_manual_opt_in(self):
        s = (ROOT / '.github/workflows/android.yml').read_text()
        self.assertIn('x86_64-app-runtime:', s)
        app_job = s.split('\n  x86_64-app-runtime:\n', 1)[1]
        self.assertIn("if: github.event_name == 'workflow_dispatch' && inputs.x86_64_native_test == true", app_job)
        self.assertIn('x86_64_native_test:', s)
        self.assertIn("default: false", s.split('x86_64_native_test:', 1)[1].split('permissions:', 1)[0])
        self.assertNotIn('if: github.event_name != \'push\'', app_job)
        self.assertIn('go-version-file: engine/go.mod', s)
        self.assertIn('ndk;${XDM_ANDROID_NDK_VERSION}', s)
        self.assertIn('scripts/run_xgo_x86_64_emulator.sh', s)
        self.assertIn('xdm-android-x86_64-apk-and-jni-evidence', s)
        self.assertIn('name: XGO X86 x86_64 APK build-profile regressions', s)
        self.assertIn('emulator-compatibility:', s)
        self.assertIn('xdm-emulator-browser-intake-test-results', s)
        self.assertIn('xdm-emulator-persistence-test-results', s)
        self.assertIn('run_physical_arm64_instrumentation.sh', s)

    def test_x86_builder_declares_real_ndk_and_no_fallback_arch(self):
        b=load('tools/xgo/build_android_xdmcore_x86_64.py', 'x86builder')
        self.assertEqual(b.GOARCH, 'amd64')
        self.assertEqual(b.ABI, 'x86_64')
        self.assertEqual(b.NDK_VERSION, '29.0.14206865')
        self.assertEqual(b.API, 26)
        self.assertIn('jniLibs/x86_64/libxdmcore.so', str(b.OUTPUT))
        self.assertEqual(len(b.EXPECTED_JNI), 7)
        self.assertNotIn('libndk_translation', (ROOT / 'tools/xgo/build_android_xdmcore_x86_64.py').read_text())

    def test_x86_elf_refuses_wrong_machine_and_alignment(self):
        b=load('tools/xgo/build_android_xdmcore_x86_64.py', 'x86elf')
        elf=bytearray(256)
        elf[:6]=b'\x7fELF\x02\x01'
        struct.pack_into('<HH',elf,16,3,183)
        struct.pack_into('<Q',elf,32,64)
        struct.pack_into('<HH',elf,54,56,1)
        struct.pack_into('<I',elf,64,1)
        struct.pack_into('<Q',elf,64+48,16384)
        with tempfile.TemporaryDirectory() as td:
            p=pathlib.Path(td)/'core.so'
            p.write_bytes(elf)
            with self.assertRaisesRegex(RuntimeError,'WRONG_ELF'):
                b.verify_elf(p)
            struct.pack_into('<HH',elf,16,3,62)
            struct.pack_into('<Q',elf,64+48,4096)
            p.write_bytes(elf)
            with self.assertRaisesRegex(RuntimeError,'LOAD_ALIGNMENT'):
                b.verify_elf(p)

    def test_apk_refuses_arm64_and_missing_x86_core(self):
        v=load('scripts/verify_xgo_x86_apk.py', 'x86apk')
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/'bad.apk'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('lib/arm64-v8a/libxdmcore.so','invalid')
            with self.assertRaisesRegex(ValueError,'NON_X86'):
                v.inspect(path)
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('lib/x86_64/libother.so','invalid')
            with self.assertRaisesRegex(ValueError,'CORE_MISSING'):
                v.inspect(path)
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('lib/x86_64/libxdmcore.so',b'fake_core')
            core=pathlib.Path(td)/'core.so';core.write_bytes(b'different_core')
            with self.assertRaisesRegex(ValueError,'CORE_SOURCE_MISMATCH'):
                v.inspect(path,core)

    def test_xp03b_existing_app_journeys_manual_only(self):
        runner = (ROOT/'scripts/run_xgo_x86_64_emulator.sh').read_text()
        wf = (ROOT/'.github/workflows/android.yml').read_text()
        self.assertIn("inputs.x86_64_native_test == true",wf)
        self.assertIn('XGO_X86_TEST_EXPLICIT_OPT_IN',runner)
        self.assertIn('com.mikeyphw.xdm.android.AppSmokeTest',runner)
        self.assertIn('ExternalControlSecurityInstrumentedTest#exportedAutomationResolvesOnlyToReviewGate',runner)
        self.assertIn('verify_xgo_x86_ui_runs.py',runner)
        self.assertNotIn(':app:connectedDebugAndroidTest',runner)
        compose=(ROOT/'app/XDM.Android/app/src/androidTest/kotlin/com/mikeyphw/xdm/android/AppSmokeTest.kt').read_text()
        route=(ROOT/'app/XDM.Android/app/src/androidTest/kotlin/com/mikeyphw/xdm/android/ExternalControlSecurityInstrumentedTest.kt').read_text()
        verifier=load('scripts/verify_xgo_x86_ui_runs.py','xp03b_methods')
        self.assertEqual(len(verifier.SUITES['compose'][1]),4)
        for method in verifier.SUITES['compose'][1]:
            self.assertIn('fun '+method+'()',compose)
        self.assertIn('fun exportedAutomationResolvesOnlyToReviewGate()',route)

    def test_xp03b_receipt_fails_closed_on_missing_skipped_duplicate_and_wrong_method(self):
        verifier=load('scripts/verify_xgo_x86_ui_runs.py','xp03b_receipt')
        def transcript(cls,methods):
            lines=[]
            for method in methods:
                lines.extend([f'INSTRUMENTATION_STATUS: class={cls}',
                  f'INSTRUMENTATION_STATUS: test={method}',
                  'INSTRUMENTATION_STATUS_CODE: 0'])
            lines.extend(['OK ('+str(len(methods))+(' test)' if len(methods)==1 else ' tests)'),
              'INSTRUMENTATION_CODE: -1'])
            return '\n'.join(lines)
        valid={k:transcript(*v) for k,v in verifier.SUITES.items()}
        self.assertEqual(verifier.inspect(valid)['total_instrumentation_tests'],6)
        for name in valid:
            d=dict(valid);d[name]=valid[name].replace('INSTRUMENTATION_CODE: -1','INSTRUMENTATION_CODE: 0')
            with self.assertRaisesRegex(ValueError,'INSTRUMENTATION_FAILED'):verifier.inspect(d)
            d=dict(valid);d[name]=valid[name].replace('INSTRUMENTATION_STATUS_CODE: 0','INSTRUMENTATION_STATUS_CODE: -2',1)
            with self.assertRaisesRegex(ValueError,'INSTRUMENTATION_FAILED'):verifier.inspect(d)
            d=dict(valid);d[name]=valid[name].replace('INSTRUMENTATION_STATUS_CODE: 0','INSTRUMENTATION_STATUS_CODE: 0\nINSTRUMENTATION_STATUS_CODE: 0',1)
            with self.assertRaisesRegex(ValueError,'METHOD_COUNT_MISMATCH'):verifier.inspect(d)
        d=dict(valid);d['compose']=valid['compose'].replace('downloadsShellIsVisible','unknownMethod')
        with self.assertRaisesRegex(ValueError,'METHODS_MISMATCH'):verifier.inspect(d)

    def test_smoke_exercises_actual_jni_and_launch(self):
        smoke=(ROOT/'app/XDM.Android/app/src/androidTest/kotlin/com/mikeyphw/xdm/android/XgoX86JniSmokeTest.kt').read_text()
        runner=(ROOT/'scripts/run_xgo_x86_64_emulator.sh').read_text()
        self.assertIn('JniNativeXdmCore.create',smoke)
        self.assertIn('assertEquals("x86_64", Build.SUPPORTED_ABIS.first())',smoke)
        self.assertIn('am instrument -w -r',runner)
        self.assertIn('am start -W',runner)
        self.assertIn('verify_xgo_x86_apk.py',runner)
        self.assertIn('--core app/src/main/jniLibs/x86_64/libxdmcore.so',runner)
        self.assertIn('XGO_XP03B_EMULATOR_JNI_AND_UI_PASS',runner)


if __name__ == '__main__':
    unittest.main(verbosity=2)
