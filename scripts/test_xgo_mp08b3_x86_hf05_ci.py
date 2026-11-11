#!/usr/bin/env python3
"""MP08B3 x86 HF05: Node24 cache + config-cache-safe native task gates.
Pure source contracts and negative mutations: no Android emulator or Gradle.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

def read(path):return (ROOT/path).read_text(encoding='utf-8')

class Hf05CIContracts(unittest.TestCase):
    def test_targeted_actions_are_node24_and_go_is_isolated(self):
        s=read('.github/workflows/xgo-targeted.yml')
        for needle in ('actions/setup-node@v5','actions/setup-go@v6',
              'actions/setup-java@v6','gradle/actions/setup-gradle@v6',
              'actions/cache@v5','cache-provider: basic','cache: false',
              'xgo-targeted-go-mod','xgo-targeted-go-build',
              'GOMODCACHE=', 'GOCACHE=',
              "hashFiles('engine/go.mod', 'engine/go.sum')"):
            self.assertIn(needle,s,needle)
        for deprecated in ('setup-node@v4','setup-go@v5','setup-java@v4',
               'gradle/actions/setup-gradle@v4','cache: true','restore-keys:'):
            self.assertNotIn(deprecated,s,deprecated)
        self.assertIn("if: needs.scope.outputs.needs_go == 'true'",s)
        self.assertIn('python3 -B scripts/ci/xgo_ci_policy.py run-targeted',s)
        self.assertIn('test "$ANDROID" = success',s)
        self.assertIn('test "$SOURCE" = success',s)

    def test_mp08b3_acceptance_workflow_node24_no_kvm_guard_change(self):
        s=read('.github/workflows/xgo-mp08b3-acceptance.yml')
        for required in ('actions/setup-python@v7','actions/setup-java@v6',
                         'gradle/actions/setup-gradle@v6','actions/upload-artifact@v6',
                         'MP08B3_KVM_OPEN_PASS','xgo-mp08b3-api36'):
            self.assertIn(required,s)
        for deprecated in ('actions/setup-python@v5','actions/setup-java@v4',
                           'gradle/actions/setup-gradle@v4','actions/upload-artifact@v4'):
            self.assertNotIn(deprecated,s)
        self.assertNotIn('continue-on-error: true',s)

    def test_native_lane_preserves_strict_gates_and_avoids_shared_setup_go_cache(self):
        s=read('.github/workflows/xgo-x86-native-media.yml')
        for needle in ('actions/setup-go@v6','cache: false','actions/cache@v5',
           'actions/cache/restore@v5','actions/cache/save@v5',
           'xgo-x86-go-mod','xgo-x86-go-build',
           'XGO_X86_NATIVE_ATTESTED=yes','--require-source-build',
           'xgo_mp08b3_x86_integration.py run','xgo_verified_native_artifact.py restore',
           'cache-read-only: false','actions/setup-python@v7',
           'test_xgo_mp08b3_x86_hf05_ci.py'):
            self.assertIn(needle,s,needle)
        self.assertNotIn('continue-on-error: true',s)
        self.assertNotIn('restore-keys:',s)
        self.assertNotIn('--no-configuration-cache',s)
        self.assertNotIn('configuration-cache-problems=warn',s)
        self.assertEqual(s.count('uses: ReactiveCircus/android-emulator-runner@'),1)
        self.assertEqual(s.count('actions/cache/restore@v5'),1)
        self.assertEqual(s.count('actions/cache/save@v5'),1)

    def test_gradle_native_skip_decided_only_at_configuration_time(self):
        source=read('scripts/xgo_mp08b3_x86_optimize.py')
        spec=importlib.util.spec_from_file_location('xgo_hf05_optim',ROOT/'scripts/xgo_mp08b3_x86_optimize.py')
        assert spec and spec.loader
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        for role,task,amount in (('ffmpeg','installPinnedFfmpegRuntime',8),('aria2','buildPinnedAria2Runtime',5)):
            fixture='val '+task+' = tasks.register<Exec>("'+task+'") {\n'
            fixture+=''.join('    outputs.file("src/main/jniLibs/arm64-v8a/lib'+str(i)+'.so")\n' for i in range(amount))
            fixture+='    commandLine("python3", "tools/build-aria2-runtime.py", "--build-pinned")\n}\n\nandroid {\n}\n'
            transformed=m.gradle_transform(fixture,role)
            self.assertIn(task+'.configure { enabled = false }',transformed)
            self.assertIn('if (xgoNativePreverified.get())',transformed)
            self.assertIn('XGO_X86_NATIVE_ATTESTED',transformed)
            self.assertIn('GITHUB_REPOSITORY',transformed)
            self.assertNotIn('onlyIf {',transformed)
            self.assertNotIn('src/main/jniLibs/arm64-v8a/',transformed)
            self.assertIn('tools/build-aria2-runtime.py',transformed)
            with self.assertRaises(ValueError):m.gradle_transform(transformed,role)
        self.assertNotIn('onlyIf {',source)
        self.assertNotIn('!xgoNativePreverified.get()',source)

    def test_no_go_module_cache_under_shared_home(self):
        for workflow in ('.github/workflows/xgo-targeted.yml',
                         '.github/workflows/xgo-x86-native-media.yml'):
            s=read(workflow)
            self.assertIn('GOMODCACHE=',s)
            self.assertIn('GOCACHE=',s)
            self.assertIn('cache: false',s)
            self.assertIn('actions/cache@v5',s)
            for unsafe in ('~/go/pkg/mod','~/.cache/go-build','GOMODCACHE=$HOME',
                            'cache-dependency-path: engine/go.sum'):
                self.assertNotIn(unsafe,s)

if __name__=='__main__':unittest.main(verbosity=2)
