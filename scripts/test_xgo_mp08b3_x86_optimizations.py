#!/usr/bin/env python3
"""Fail-closed, dependency-free optimization/negative regression tests."""
from __future__ import annotations
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
from unittest import mock
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/file)
    assert spec and spec.loader
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod

class OptTests(unittest.TestCase):
    def test_exact_seven_cases_and_junit4_unit_return(self):
        kotlin=(ROOT/'app/XDM.Android/app/src/androidTest/kotlin/com/mikeyphw/xdm/android/MP08B3MediaStoreAcceptanceInstrumentedTest.kt').read_text()
        anchor='fun b3_03InterruptedPendingMediaStoreRowIsReconciled() = runBlocking {'
        self.assertEqual(kotlin.count(anchor),1)
        body=kotlin.split(anchor,1)[1].split('\n    @Test',1)[0]
        self.assertRegex(body,r'(?m)^\s+Unit\s*$')
        self.assertEqual(kotlin.count('@Test'),4)
        self.assertIn('b3_04RealEmbeddedFfmpegProbeMuxAndMediaStoreRoundTrip',kotlin)
        self.assertNotIn('assumeTrue(',kotlin)

    def test_temporary_gradle_profiles_keep_real_validators(self):
        m=load('optprofile','xgo_mp08b3_x86_optimize.py')
        for role,task,count in [('ffmpeg','installPinnedFfmpegRuntime',8),('aria2','buildPinnedAria2Runtime',5)]:
            text='val '+task+' = tasks.register<Exec>("'+task+'") {\n'
            text+=''.join('    outputs.file("src/main/jniLibs/arm64-v8a/lib'+str(i)+'.so")\n' for i in range(count))
            text+='    commandLine("python3", "tools/build-aria2-runtime.py", "--build-pinned")\n}\n'
            out=m.gradle_transform(text,role)
            self.assertIn('XGO_X86_NATIVE_ATTESTED',out)
            self.assertIn('!xgoNativePreverified.get()',out)
            self.assertNotIn('src/main/jniLibs/arm64-v8a/',out)
            self.assertEqual(out.count('src/main/jniLibs/x86_64/'),count)
            self.assertIn('"--build-pinned"',out)  # source-build path remains available outside CI skip
            with self.assertRaisesRegex(ValueError,'ANCHOR'):
                m.gradle_transform(out,role)

    def test_preverified_flag_not_used_by_arm64_source_workflows(self):
        workflow=(ROOT/'.github/workflows/xgo-x86-native-media.yml').read_text()
        self.assertIn('-Pxdm.preverifiedNativeRuntime=true',workflow)
        self.assertIn('scripts/xgo_mp08b3_x86_optimize.py prepare',workflow)
        self.assertIn('scripts/xgo_x86_native_media.py prepare',workflow)
        self.assertLess(workflow.index('scripts/xgo_x86_native_media.py prepare'),
                        workflow.index('scripts/xgo_mp08b3_x86_optimize.py prepare'))
        self.assertLess(workflow.index('tools/verify-ffmpeg-runtime.py --require-payload'),
                        workflow.index('Build genuine x86_64 app'))
        self.assertLess(workflow.index('tools/verify-aria2-runtime.py --require-payload'),
                        workflow.index('Build genuine x86_64 app'))
        self.assertIn('XGO_X86_NATIVE_ATTESTED=yes',workflow)
        self.assertIn('mode same-pr-native-cache',workflow)
        self.assertIn('mode cross-pr-artifact',workflow)
        self.assertIn('mode pinned-source-build',workflow)
        self.assertIn("steps.native-source.outputs.mode == 'pinned-source-build'",workflow)
        restored=workflow.split('Restore x86_64 verified native source and object cache',1)[1].split('Build and independently verify native',1)[0]
        for binary in ('libxdm_ffmpeg.so','libxdm_ffprobe.so','libaria2c.so',
                       'ffmpeg-runtime.lock.json','aria2-runtime.lock.json'):
            self.assertIn(binary,restored)

        self.assertEqual(workflow.count('uses: ReactiveCircus/android-emulator-runner@'),1)
        self.assertIn('xgo_mp08b3_x86_integration.py run',workflow)

    def test_gradle_basic_writable_only_after_explicit_same_repo_pr_guard(self):
        s=(ROOT/'.github/workflows/xgo-x86-native-media.yml').read_text()
        self.assertIn("github.event.label.name == 'xgo-x86-native-media'",s)
        self.assertIn('github.event.pull_request.head.repo.full_name == github.repository',s)
        self.assertIn('cache-provider: basic',s)
        self.assertIn('cache-read-only: false',s)
        self.assertNotIn('cache-provider: enhanced',s)
        self.assertNotIn('continue-on-error: true',s)
        self.assertNotIn('restore-keys:',s)
        self.assertIn('actions: read',s)
        self.assertIn('retention-days: 30',s)
        self.assertNotIn('~/.gradle',s)

    def test_native_artifact_abi_and_source_fingerprint(self):
        m=load('xgo_artifact','xgo_verified_native_artifact.py')
        self.assertEqual(m.ABI,'x86_64');self.assertEqual(m.NDK,'29.0.14206865')
        self.assertGreater(len(m.SOURCE_FILES),7)
        self.assertEqual(len(m.ELF_FILES),3)
        self.assertTrue(all('/x86_64/' in f for f in m.ELF_FILES))
        self.assertNotIn('arm64', '\n'.join(m.OUTPUTS))
        self.assertEqual(m.artifact_name('a'*64),'xgo-native-x86-verified-'+'a'*32)

    def test_reject_artifact_missing_invalid_or_mismatched_receipt(self):
        m=load('xgo_artifact_bad','xgo_verified_native_artifact.py')
        key='0'*64;inputs={'sources':{},'abi':'x86_64'}
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as z:z.writestr('manifest.json','{}')
        with self.assertRaisesRegex(ValueError,'ARCHIVE_ENTRY_INVENTORY'):
            m.check_bundle(data.getvalue(),4,'f'*40,key,inputs)
        with self.assertRaises((OSError,zipfile.BadZipFile,ValueError)):
            m.check_bundle(b'invalid',4,'f'*40,key,inputs)
        # No prior trusted qualified artifact means a native SOURCE build is necessary.
        with mock.patch.object(m,'require_host',return_value='a'*40),\
             mock.patch.object(m,'fingerprint',return_value=(key,inputs)),\
             mock.patch.object(m,'request_json',return_value={'artifacts':[]}),\
             mock.patch.dict(os.environ,{'GH_TOKEN':'stub'},clear=False):
            self.assertEqual(m.restore(),10)

    def test_artifact_redirect_never_leaks_github_token(self):
        import urllib.request
        m=load('xgo_redirect_guard','xgo_verified_native_artifact.py')
        handler=m.SafeArtifactRedirect()
        req=urllib.request.Request('https://api.github.com/repo/actions/artifacts/1/zip',
            headers={'Authorization':'Bearer private-token'})
        with self.assertRaisesRegex(ValueError,'UNTRUSTED_ARTIFACT_REDIRECT'):
            handler.redirect_request(req,None,302,'Found',{},'https://evil.invalid/steal')
        dest=handler.redirect_request(req,None,302,'Found',{},
            'https://pipelinesghubeus.blob.core.windows.net/artifact.zip?sig=abc')
        self.assertNotIn('authorization',[name.lower() for name in dest.headers])

    def test_per_stage_timing_receipt_reports_absence_not_success(self):
        m=load('xgo_perf','xgo_ci_perf_receipt.py')
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ,{
              'GITHUB_ACTIONS':'true','RUNNER_TEMP':temp},clear=False):
            m.stamp('native','start');m.stamp('native','end')
            with self.assertRaisesRegex(ValueError,'STAMP_ALREADY_EXISTS'):m.stamp('native','end')
            m.report('failure')
            result=json.loads((Path(temp)/'xgo-x86-perf/performance.json').read_text())
            self.assertEqual(result['job_status'],'failure')
            self.assertTrue(result['phases']['native']['complete'])
            self.assertFalse(result['phases']['emulator']['complete'])

    def test_labeled_run_does_not_claim_arm64_or_release(self):
        wf=(ROOT/'.github/workflows/xgo-x86-native-media.yml').read_text()
        integration=(ROOT/'scripts/xgo_mp08b3_x86_integration.py').read_text()
        self.assertIn('MP08B3_X86_P01_SEVEN_REAL_API36_TESTS_PASS_NOT_ARM64_OR_RELEASE',integration)
        self.assertIn('verify_exact_junit(out,CLASS,CASES)',integration)
        self.assertIn('verify_preceding_native_gate',integration)
        self.assertIn('Native output mode:',(ROOT/'scripts/xgo_ci_perf_receipt.py').read_text())
        self.assertIn('if: always()',wf)
        self.assertIn('Write phase timings',wf)
        self.assertIn('native-output.zip',wf)

if __name__=='__main__':unittest.main(verbosity=2)
