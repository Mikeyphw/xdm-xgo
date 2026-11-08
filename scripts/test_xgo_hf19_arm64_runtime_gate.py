#!/usr/bin/env python3
"""HF19 offline native runtime CI contracts; no Gradle/ADB/SDK/network."""
import ast
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / 'app/XDM.Android/tools/build-aria2-runtime.py'
COMMON = ROOT / 'app/XDM.Android/tools/run-final-common-validation.sh'
WF = ROOT / '.github/workflows/android.yml'
SSL = ROOT / 'app/XDM.Android/tools/android_native_openssl.py'
BASE = 'ef0892eeca92e469f8170d543fbb295c68f1ecab'

class HF19(unittest.TestCase):
    def test_openssl_legacy_remains_disabled(self):
        src = SSL.read_text()
        self.assertIn('"no-legacy"', src)
        self.assertIn('"no-module"', src)
        self.assertIn('"no-shared"', src)

    def test_aria2_builder_patches_only_verified_source(self):
        src = BUILDER.read_text()
        tree = ast.parse(src)
        fun = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'patch_aria2_no_legacy_openssl'), None)
        self.assertIsNotNone(fun)
        self.assertIn('patch_aria2_no_legacy_openssl(source_roots["aria2"])', src)
        self.assertLess(src.index('authority.ensure_verified_source_tree('), src.index('patch_aria2_no_legacy_openssl(source_roots["aria2"])'))
        self.assertIn('"default"', ast.get_source_segment(src, fun))
        ns = {'Path': Path, 'SystemExit': SystemExit}
        defs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.Assign)) and (
            (isinstance(n, ast.FunctionDef) and n.name == fun.name) or
            (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ('UPSTREAM_PROVIDER','SECURE_ANDROID_PROVIDER') for t in n.targets))
        )]
        exec(compile(ast.Module(body=defs, type_ignores=[]), str(BUILDER), 'exec'), ns)
        with tempfile.TemporaryDirectory() as tmp:
            platform = Path(tmp) / 'src/Platform.cc';platform.parent.mkdir()
            original = '''#ifdef HAVE_OPENSSL
#  if OPENSSL_VERSION_NUMBER >= 0x30000000L
''' + ns['UPSTREAM_PROVIDER'] + '''
  default_provider_ = OSSL_PROVIDER_load(nullptr, "default");
  if (!default_provider_) {
    throw DL_ABORT_EX("OSSL_PROVIDER_load 'default' failed.");
  }
#endif
'''
            platform.write_text(original)
            ns['patch_aria2_no_legacy_openssl'](Path(tmp))
            patched = platform.read_text()
            self.assertIn('legacy_provider_ = nullptr;', patched)
            self.assertNotIn('OSSL_PROVIDER_load(nullptr, "legacy")', patched)
            self.assertIn('OSSL_PROVIDER_load(nullptr, "default")', patched)
            self.assertIn('throw DL_ABORT_EX("OSSL_PROVIDER_load \'default\' failed.");', patched)
            ns['patch_aria2_no_legacy_openssl'](Path(tmp))
            self.assertEqual(patched, platform.read_text())
            platform.write_text(original.replace('  // RC4 is in the legacy provider.', '  // unexpected upstream drift'))
            with self.assertRaises(SystemExit):
                ns['patch_aria2_no_legacy_openssl'](Path(tmp))

    def test_ci_requires_attested_ffmpeg_and_aria2(self):
        validation = COMMON.read_text()
        self.assertIn('-Pxdm.requireAria2Runtime=true -Pxdm.requireFfmpegRuntime=true', validation)
        self.assertIn(':app:assembleDebugAndroidTest', validation)
        self.assertIn('assembleDebug', validation)
        workflow = WF.read_text()
        self.assertIn('scripts/test_xgo_hf19_arm64_runtime_gate.py', workflow)
        validate = workflow.split('\n  validate:\n',1)[1].split('\n  instrumentation:\n',1)[0]
        self.assertIn('    timeout-minutes: 120',validate)
        required = 'python3 tools/verify-ffmpeg-runtime.py --require-payload --require-16kb-alignment --apk app/build/outputs/apk/debug/app-debug.apk'
        self.assertIn(required, validate)
        self.assertLess(validate.index('Post-DL03 final common validation'), validate.index(required))
        self.assertLess(validate.index(required),validate.index('scripts/xgo_hf16_apk_pair.py'))
        self.assertLess(validate.index(required),validate.index('xdm-android-physical-arm64-apk-pair'))
        self.assertIn('if-no-files-found: error',validate)

    def test_signed_release_byte_identical(self):
        current = WF.read_text().split('\n  signed-release:\n',1)[1].split('\n  emulator-compatibility:\n',1)[0]
        prior = subprocess.check_output(['git','-C',str(ROOT),'show',BASE+':.github/workflows/android.yml'],text=True)
        baseline = prior.split('\n  signed-release:\n',1)[1].split('\n  emulator-compatibility:\n',1)[0]
        self.assertEqual(current,baseline)
        self.assertIn('XDM_XAR16_FULL_RELEASE_GATE',current)
        self.assertIn('run-hosted-emulator-instrumentation.sh --signed-release',current)

    def test_no_automatic_translation_and_no_duplicate_ci(self):
        src = WF.read_text()
        self.assertIn("    branches: [main]\n    tags: ['android-v*']",src)
        self.assertIn('  pull_request:',src)
        i=src.split('\n  instrumentation:\n',1)[1].split('\n  signed-release:\n',1)[0]
        self.assertIn("if: github.event_name == 'workflow_dispatch' && inputs.arm64_translation_diagnostic",i)
        self.assertIn('run-hosted-emulator-instrumentation.sh --device',i)

if __name__ == '__main__':
    unittest.main(verbosity=2)
