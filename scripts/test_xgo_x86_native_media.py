#!/usr/bin/env python3
"""Native-free XGO x86_64 FFmpeg, FFprobe, aria2 source/security negatives."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import re
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'scripts/xgo_x86_native_media.py'
WORKFLOW=ROOT/'.github/workflows/xgo-x86-native-media.yml'
ANDROID=ROOT/'app/XDM.Android/app/src/androidTest/kotlin/com/mikeyphw/xdm/android/XgoX86NativeMediaInstrumentedTest.kt'

def mod():
    spec=importlib.util.spec_from_file_location('x86_media_module',TARGET)
    assert spec and spec.loader
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

class X86MediaSourceContracts(unittest.TestCase):
    def test_deterministic_source_pins_and_parent(self):
        m=mod()
        self.assertEqual(m.PARENT,'fbda3835e5a252df577d1ce8676a39768cf8de22')
        self.assertEqual(len(m.PINS),11)
        self.assertTrue(all(re.fullmatch(r'[0-9a-f]{40}',v) for v in m.PINS.values()))
        self.assertEqual(m.PINS[m.X86_CORE],'519ddf0952da78cc2c7f052069127118ccdff45e')
        self.assertIn('git',TARGET.read_text())
        self.assertIn('hash-object',TARGET.read_text())

    def test_source_transforms_and_bad_anchors(self):
        m=mod()
        ff='aarch64-linux-android arm64-v8a aarch64 android-arm64 machine != 183'
        out=m.source_transform(ff,'ffmpeg')
        self.assertIn('x86_64-linux-android',out)
        self.assertIn('machine != 62',out)
        self.assertNotIn('machine != 183',out)
        for text,role in [('host clang only','ffmpeg'),('arm64-v8a','aria2'),('x86_64 host','openssl')]:
            with self.subTest(role=role),self.assertRaises(RuntimeError):m.source_transform(text,role)
        aria=m.source_transform('aarch64-linux-android android-arm64-source-v1','aria2')
        self.assertIn('android-x86_64-source-v1',aria)
        openssl=m.source_transform('android-arm64 arm64-v8a','openssl')
        self.assertIn('android-x86_64',openssl)

    def test_ffmpeg_manifest_requires_pinned_licenses_and_arch(self):
        m=mod()
        ff={'abi':'arm64-v8a','elfMachine':183,'ndkVersion':'29.0.14206865',
            'ffmpegLicense':'LGPL-2.1-or-later','gplEnabled':False,'nonfreeEnabled':False,
            'ffmpegPackagedPath':'media-ffmpeg/src/main/jniLibs/arm64-v8a/libxdm_ffmpeg.so',
            'ffprobePackagedPath':'media-ffmpeg/src/main/jniLibs/arm64-v8a/libxdm_ffprobe.so',
            'configureFlags':['--arch=aarch64','--cpu=armv8-a','--disable-gpl','--disable-nonfree']}
        result=json.loads(m.manifest_transform(json.dumps(ff),'ffmpeg'))
        self.assertEqual(result['abi'],'x86_64')
        self.assertEqual(result['elfMachine'],62)
        self.assertIn('--cpu=x86-64',result['configureFlags'])
        for bad in ({'gplEnabled':True},{'nonfreeEnabled':True},{'ndkVersion':'other'},
                    {'configureFlags':['--arch=aarch64']},{'abi':'x86_64'}):
            with self.subTest(bad=bad),self.assertRaises(RuntimeError):
                m.manifest_transform(json.dumps({**ff,**bad}),'ffmpeg')

    def test_aria2_source_build_not_prebuilt(self):
        m=mod()
        manifest={'abi':'arm64-v8a','elfMachine':183,'ndkVersion':'29.0.14206865',
                  'schemaVersion':3,'buildProfile':'android-arm64-source-v1','license':'GPL-2.0-or-later',
                  'packagedPath':'transfer-aria2/src/main/jniLibs/arm64-v8a/libaria2c.so',
                  'compatibilityPrebuilt':{'url':'https://untrusted.invalid/bin'}}
        result=json.loads(m.manifest_transform(json.dumps(manifest),'aria2'))
        self.assertNotIn('compatibilityPrebuilt',result)
        self.assertEqual(result['buildProfile'],'android-x86_64-source-v1')
        for bad in ({'license':'MIT'},{'schemaVersion':2},{'buildProfile':'test'}):
            with self.assertRaises(RuntimeError):m.manifest_transform(json.dumps({**manifest,**bad}),'aria2')

    def test_elf_refusal_different_arch_and_alignment(self):
        m=mod()
        elf=bytearray(4200)
        elf[:6]=b'\x7fELF\x02\x01'
        struct.pack_into('<HH',elf,16,3,62)
        struct.pack_into('<Q',elf,32,64)
        struct.pack_into('<HH',elf,54,56,1)
        struct.pack_into('<I',elf,64,1)
        struct.pack_into('<Q',elf,112,16384)
        self.assertEqual(m.verify_native(bytes(elf),'test')['machine'],62)
        for off,fmt,value in [(18,'H',183),(112,'Q',4096),(16,'H',2)]:
            bad=bytearray(elf);struct.pack_into('<'+fmt,bad,off,value)
            with self.subTest(off=off),self.assertRaises(RuntimeError):m.verify_native(bytes(bad),'negative')

    def test_workflow_explicit_label_no_default_expensive_runner(self):
        w=WORKFLOW.read_text()
        needed=("types: [labeled]", "github.event.label.name == 'xgo-x86-native-media'",
                'github.event.pull_request.head.repo.full_name == github.repository',
                'fetch-depth: 0','persist-credentials: false',
                'fbda3835e5a252df577d1ce8676a39768cf8de22',
                'go-version-file: engine/go.mod','ndk;29.0.14206865',
                'tools/install-ffmpeg-runtime.py --build-pinned',
                'tools/build-aria2-runtime.py --build-pinned',
                '--require-source-build','-Pxdm.requireAria2Runtime=true',
                '-Pxdm.requireFfmpegRuntime=true', 'arch: x86_64',
                'xgo_x86_native_media.py emulator', 'if: always()')
        for item in needed:self.assertIn(item,w)
        for bad in ('continue-on-error: true','if-no-files-found: ignore','workflow_dispatch:',
                    'push:', 'schedule:', 'git push --force','git reset --hard'):
            self.assertNotIn(bad,w)
        self.assertEqual(len(re.findall(r'(?m)^jobs:\s*$',w)),1)
        self.assertEqual(len(re.findall(r'(?m)^  x86-native-media:\s*$',w)),1)
        self.assertIn('GITHUB_EVENT_ACTION: ${{ github.event.action }}',w)
        self.assertIn('xgo-x86-native-media',w)

    def test_x86_native_build_caching_is_abi_separated_and_verified(self):
        src=WORKFLOW.read_text()
        job_env=src.split('    env:\n',1)[1].split('    steps:\n',1)[0]
        self.assertNotIn('runner.temp',job_env)
        self.assertIn('actions/cache/restore@v4',src)
        self.assertIn('actions/cache/save@v4',src)
        self.assertNotIn('restore-keys:',src)
        self.assertIn('scripts/xgo_x86_native_media.py',src)
        self.assertIn('tool',src.lower())
        self.assertLess(src.index('Build and independently verify native FFmpeg'),src.index('Save x86_64 verified native'))
        self.assertLess(src.index('Save x86_64 verified native'),src.index('Build genuine x86_64 app'))
        self.assertIn('test_xgo_native_cache_contract.py',src)

    def test_three_unskipped_instrumentation_cases_and_no_release_claim(self):
        a=ANDROID.read_text()
        self.assertEqual(len(re.findall(r'(?m)^\s*@Test\s*$',a)),3)
        for name in ('x86_01PinnedFfmpegExecutes','x86_02PinnedFfprobeExecutes',
                     'x86_03SourceBuiltAria2Executes','ProcessBuilder(',
                     'capabilities(force = true)','Build.SUPPORTED_ABIS.first()',
                     'libaria2c.so','libxdm_ffmpeg.so'):
            if name!='libxdm_ffmpeg.so':self.assertIn(name,a)
        self.assertNotRegex(a,r'@Ignore|Assume\.|assumeTrue|assumeFalse')
        self.assertIn('False',TARGET.read_text())
        self.assertIn("'release_eligible':False",TARGET.read_text())
        self.assertIn('len(names)!=3',TARGET.read_text())

if __name__=='__main__':unittest.main(verbosity=2)
