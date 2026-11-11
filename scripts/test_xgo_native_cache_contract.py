#!/usr/bin/env python3
"""Native-free x86/ARM64 caching contracts; never claim device qualification."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
PATCHER=ROOT/'scripts/xgo_native_cache_patch.py'
WORKFLOW=ROOT/'.github/workflows/xgo-x86-native-media.yml'
ANDROID_WORKFLOW=ROOT/'.github/workflows/android.yml'


def load():
    spec=importlib.util.spec_from_file_location('xgo_native_cache_patch',PATCHER)
    assert spec and spec.loader
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bash_block(text: str,name: str) -> str:
    match=re.search(r'(?m)^      - name: '+re.escape(name)+r'\n        shell: bash\n        run: \|\n((?:          .*\n)+)',text)
    if not match:
        raise AssertionError('missing or broken bash block '+name)
    return '\n'.join(line[10:] for line in match.group(1).splitlines())+'\n'


class NativeCachingTests(unittest.TestCase):
    def test_x86_job_level_env_never_uses_runner_context(self):
        src=WORKFLOW.read_text()
        job_env=src.split('    env:\n',1)[1].split('    steps:\n',1)[0]
        self.assertNotIn('runner.temp',job_env)
        self.assertNotIn('XDM_FFMPEG_BUILD_CACHE:',job_env)
        self.assertNotIn('XDM_ARIA2_SOURCE_CACHE_DIR:',job_env)
        self.assertNotIn('XDM_ANDROID_NATIVE_DEPS_CACHE:',job_env)
        self.assertIn('xgo-x86-native-media',src)
        self.assertNotIn('continue-on-error: true',src)
        self.assertIn('actions/cache/restore@v5',src)
        self.assertIn('actions/cache/save@v5',src)
        self.assertEqual(src.count('actions/cache/restore@v5'),1)
        self.assertEqual(src.count('actions/cache/save@v5'),1)

    def test_exact_abi_and_source_locked_keys(self):
        m=load()
        self.assertEqual(m.ARM64_ORIGINAL_BLOB,'e8b85baa02a0076877c221709b361c5851bf4810')
        for arch in ('arm64','x86_64'):
            key=m.cache_key(arch)
            self.assertIn('-ndk29.0.14206865-',key)
            self.assertIn('-'+arch+'-native-v2-',key)
            self.assertIn('hashFiles(',key)
            self.assertIn('android_native_openssl.py',key)
            self.assertIn('build-aria2-runtime.py',key)
            self.assertIn('install-ffmpeg-runtime.py',key)
            self.assertIn('ffmpeg-runtime.json',key)
            self.assertIn('aria2-runtime.json',key)
            self.assertNotIn('restore-keys:',m.cache_steps(arch)[1])
            self.assertNotIn('XDM_RELEASE_', '\n'.join(m.cache_steps(arch)))
        self.assertNotEqual(m.cache_key('arm64'),m.cache_key('x86_64'))
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED_ABI'):m.cache_key('x86')

    def test_runner_initializer_sets_isolated_caches_and_refuses_missing_env(self):
        m=load()
        for arch in ('arm64','x86_64'):
            setup=m.cache_steps(arch)[0]
            src=bash_block(setup,'Initialize '+arch+' native source and object cache directories')
            with tempfile.TemporaryDirectory() as td:
                root=Path(td)
                tmp=root/'runner';tmp.mkdir()
                envfile=root/'github_env';envfile.touch()
                env={**os.environ,'RUNNER_TEMP':str(tmp),'GITHUB_ENV':str(envfile)}
                result=subprocess.run(['bash','-e','-c',src],capture_output=True,text=True,env=env)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('BUILD_CACHE_PATHS_READY',result.stdout)
                lines=dict(x.split('=',1) for x in envfile.read_text().splitlines())
                self.assertEqual(set(lines),{'XDM_FFMPEG_BUILD_CACHE','XDM_ARIA2_SOURCE_CACHE_DIR','XDM_ANDROID_NATIVE_DEPS_CACHE'})
                for path in lines.values():
                    self.assertTrue(Path(path).is_dir())
                    self.assertEqual(Path(path).stat().st_mode&0o777,0o700)
                    self.assertIn(arch if arch=='arm64' else 'x86',Path(path).name)
                bad_env={**env,'RUNNER_TEMP':''}
                self.assertNotEqual(subprocess.run(['bash','-e','-c',src],env=bad_env,capture_output=True).returncode,0)

    def test_arm64_release_patch_only_two_exact_anchors_and_fails_closed(self):
        m=load()
        fixture='''name: XDM Android CI
jobs:
  validate:
    steps:
      - name: Static release contracts
        run: true
      - name: Post-DL03 final common validation
        run: bash tools/run-final-common-validation.sh
  signed-release:
    runs-on: ubuntu-24.04
    steps:
      - name: Setup tools
        run: true
      - name: Build pinned ARM64 aria2 runtime from source
        run: python3 tools/build-aria2-runtime.py --build-pinned
      - name: Build pinned FFmpeg runtime
        run: python3 tools/install-ffmpeg-runtime.py --build-pinned
      - name: Fetch provenance-pinned previous release fixture
        run: true
'''
        output=m.patch_arm64_workflow(fixture)
        self.assertEqual(output.count('signed-release:'),1)
        self.assertIn('Produce and verify ARM64 native source-built media before common validation',output)
        self.assertLess(output.index('Produce and verify ARM64'),output.index('Post-DL03 final common validation'))
        self.assertIn('Verify both ARM64 native source-built runtimes before cache save',output)
        self.assertIn('--require-source-build',output)
        self.assertIn('--require-16kb-alignment',output)
        release=output.split('  signed-release:\n',1)[1]
        self.assertLess(release.index('Restore arm64 verified'),release.index('Build pinned ARM64'))
        self.assertLess(release.index('Build pinned FFmpeg runtime'),release.index('Verify both ARM64'))
        self.assertLess(release.index('Verify both ARM64'),release.index('Save arm64 verified'))
        self.assertLess(release.index('Save arm64 verified'),release.index('Fetch provenance-pinned'))
        self.assertEqual(output.count('actions/cache/restore@v5'),2)
        self.assertEqual(output.count('actions/cache/save@v5'),2)
        for bad in (fixture.replace('signed-release:','release:'),fixture.replace('Build pinned ARM64','Build random ARM64'),fixture.replace('Post-DL03 final common validation','Altered validation'),fixture+fixture,output):
            with self.assertRaisesRegex(ValueError,'DRIFT|ALREADY_APPLIED'):m.patch_arm64_workflow(bad)

    def test_x86_restoration_and_save_only_after_verified_native_outputs(self):
        src=WORKFLOW.read_text()
        self.assertIn('      - name: Initialize x86_64 native source and object cache directories',src)
        self.assertLess(src.index('Restore x86_64 verified native source'),src.index('Build and independently verify native'))
        self.assertLess(src.index('Build and independently verify native'),src.index('Save x86_64 verified native'))
        self.assertLess(src.index('Save x86_64 verified native'),src.index('Build genuine x86_64 app'))
        self.assertIn("steps.xgo-native-cache.outputs.cache-hit != 'true'",src)
        self.assertIn('steps.xgo-native-cache.outputs.cache-primary-key',src)
        self.assertNotIn('XDM_RELEASE_STORE_FILE',src)
        self.assertIn('python3 -B tools/verify-ffmpeg-runtime.py --require-payload --require-16kb-alignment',src)
        self.assertIn('python3 -B tools/verify-aria2-runtime.py --require-payload --require-16kb-alignment --require-source-build',src)

    def test_node24_actions_and_go_cache_path(self):
        src=WORKFLOW.read_text()
        for action in ('actions/cache/restore@v5','actions/cache/save@v5',
                       'actions/setup-python@v7','actions/setup-java@v6',
                       'actions/upload-artifact@v6','gradle/actions/setup-gradle@v6'):
            self.assertIn(action,src)
        self.assertIn('cache-dependency-path: engine/go.sum',src)
        self.assertIn('cache-provider: basic',src)
        for stale in ('actions/cache/restore@v4','actions/cache/save@v4',
                      'actions/setup-python@v5','actions/setup-java@v4',
                      'actions/upload-artifact@v4','gradle/actions/setup-gradle@v4'):
            self.assertNotIn(stale,src)
        if ANDROID_WORKFLOW.is_file():
            arm=ANDROID_WORKFLOW.read_text()
            for stale in ('actions/cache/restore@v4','actions/cache/save@v4',
                          'actions/setup-java@v4','actions/upload-artifact@v4',
                          'gradle/actions/setup-gradle@v4'):
                self.assertNotIn(stale,arm)
            self.assertIn('actions/cache/restore@v5',arm)
            self.assertIn('cache-provider: basic',arm)

    def test_actual_arm64_workflow_when_present(self):
        if not ANDROID_WORKFLOW.is_file():return
        m=load();txt=ANDROID_WORKFLOW.read_text()
        self.assertIn('signed-release:',txt)
        if 'Restore arm64 verified native source and object cache' in txt:
            self.assertIn('Verify both ARM64 native source-built runtimes before cache save',txt)
        else:
            m.patch_arm64_workflow(txt)

if __name__=='__main__':unittest.main(verbosity=2)
