#!/usr/bin/env python3
"""Adversarial no-Gradle MP08B3 x86 integration source/security regressions."""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'scripts/xgo_mp08b3_x86_integration.py'
WORKFLOW=ROOT/'.github/workflows/xgo-x86-native-media.yml'


def load():
    spec=importlib.util.spec_from_file_location('mp08_x86_integrated',TARGET)
    assert spec and spec.loader
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def xml(klass,names,problem=None):
    inner=''.join(f'<testcase classname="{klass}" name="{n}">'+(
        '<failure/>' if problem=='failure' and i==0 else
        '<skipped/>' if problem=='skipped' and i==0 else '')+'</testcase>'
        for i,n in enumerate(names))
    return '<testsuite>'+inner+'</testsuite>'

class P01SourceTests(unittest.TestCase):
    def test_expected_source_and_pr_pins(self):
        m=load()
        self.assertEqual(m.PARENT,'36e8e318305023a8edbc5cff836bfeea2f5c56d6')
        self.assertEqual(len(m.CASES),4)
        self.assertEqual(len(m.NATIVE_CASES),3)
        self.assertEqual(m.MP08_SOURCE_BLOB,'aa1d5ea1090e4cdeb0d0e526b704a0d01e62d81d')
        self.assertEqual(m.CONTRACT_SOURCE_BLOB,'3e06a4a5a726cb68ce4ec2f4ffe250b5adde23fe')
        self.assertIn('require_source()',TARGET.read_text())

    def test_real_workflow_single_emulator_and_exact_seven_tests(self):
        text=WORKFLOW.read_text()
        self.assertIn('xgo-x86-native-media',text)
        self.assertIn('types: [labeled]',text)
        self.assertIn('test "$BASE_SHA" = 36e8e318305023a8edbc5cff836bfeea2f5c56d6',text)
        self.assertIn('feature/xgo-x86-media-runtimes-20261110',text)
        self.assertIn('xgo_x86_native_media.py emulator',text)
        self.assertIn('xgo_mp08b3_x86_integration.py run',text)
        self.assertEqual(text.count('uses: ReactiveCircus/android-emulator-runner@'),1)
        self.assertEqual(text.count('arch: x86_64'),1)
        self.assertIn('P01: one POSIX-safe line',text)
        self.assertNotIn('continue-on-error: true',text)
        self.assertNotIn('|| true',text)
        self.assertNotIn('if-no-files-found: ignore',text)
        self.assertLess(text.index('Build and independently verify native FFmpeg'),
                        text.index('Real API36 x86_64 FFmpeg FFprobe and aria2 instrumented execution'))
        self.assertIn('actions/cache/restore@v5',text)
        self.assertIn('actions/cache/save@v5',text)
        self.assertIn('actions/setup-python@v7',text)
        self.assertIn('actions/setup-java@v6',text)
        self.assertIn('gradle/actions/setup-gradle@v6',text)
        inherited=(ROOT/'scripts/test_xgo_x86_native_media.py').read_text()
        self.assertIn('test "$BASE_SHA" = 36e8e318305023a8edbc5cff836bfeea2f5c56d6',inherited)
        self.assertIn('test "$BASE_BRANCH" = feature/xgo-x86-media-runtimes-20261110',inherited)

    def test_four_case_receipt_requires_all_and_exact_class(self):
        m=load()
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);p=d/'test.xml';p.write_text(xml(m.CLASS,sorted(m.CASES)))
            result=m.verify_exact_junit(d,m.CLASS,m.CASES)
            self.assertEqual(result['tests'],4)
            self.assertEqual(result['names'],sorted(m.CASES))
            for content in (xml(m.CLASS,sorted(m.CASES)[:3]),
                            xml(m.CLASS,sorted(m.CASES)+[sorted(m.CASES)[0]]),
                            xml('other.Test',sorted(m.CASES)),
                            xml(m.CLASS,sorted(m.CASES),problem='skipped'),
                            xml(m.CLASS,sorted(m.CASES),problem='failure'),
                            '<!DOCTYPE testsuite><testsuite/>',
                            '<testsuite invalid'):
                p.write_text(content)
                with self.assertRaises(RuntimeError):m.verify_exact_junit(d,m.CLASS,m.CASES)

    def test_prior_three_tests_mandatory_and_apk_not_release(self):
        m=load();head='a'*40
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)
            payload={'head_sha':head,'abi':'x86_64','android_api':36,'release_eligible':False,
                     'apk_sha256':'1'*64,
                     'native':{name:{'machine':62,'min_load_alignment':16384,'sha256':'2'*64}
                               for name in ['lib/x86_64/libxdmcore.so','lib/x86_64/libxdm_ffmpeg.so',
                                            'lib/x86_64/libxdm_ffprobe.so','lib/x86_64/libaria2c.so']}}
            a=d/'native-media-receipt.json'; a.write_text(json.dumps(payload))
            j=d/'android-junit.xml';j.write_text(xml(m.NATIVE_CLASS,sorted(m.NATIVE_CASES)))
            self.assertEqual(m.verify_preceding_native_gate(d,head)['apk_sha256'],'1'*64)
            for patch in ({'abi':'arm64-v8a'},{'release_eligible':True},{'head_sha':'b'*40},
                          {'native':{}}):
                a.write_text(json.dumps({**payload,**patch}))
                with self.assertRaises(RuntimeError):m.verify_preceding_native_gate(d,head)
            a.write_text(json.dumps(payload))
            j.write_text(xml(m.NATIVE_CLASS,sorted(m.NATIVE_CASES)[:2]))
            with self.assertRaises(RuntimeError):m.verify_preceding_native_gate(d,head)

    def test_wrong_head_or_unapproved_runner_fails_closed(self):
        m=load()
        with mock.patch.object(m,'git',return_value='a'*40),mock.patch.object(m.subprocess,'run'):
            with self.assertRaises(RuntimeError):m.require_authorized_runner('bad')
            with self.assertRaises(RuntimeError):m.require_authorized_runner('b'*40)
            with mock.patch.dict(m.os.environ,{},clear=True):
                with self.assertRaises(RuntimeError):m.require_authorized_runner('a'*40)

    def test_no_hidden_skip_or_unqualified_claims(self):
        s=TARGET.read_text()
        for item in (':app:connectedDebugAndroidTest',
                     'api36_receipt_contract(out)',
                     'verify_preceding_native_gate(evidence,expected)',
                     'check_identity()',
                     'verify_exact_junit(out,CLASS,CASES)',
                     "'physical_arm64_qualified':False",
                     "'release_eligible':False",
                     "'go_published_byte_equivalence_qualified':False",
                     'mp08b3-four-junit.json',
                     'MP08B3_X86_P01_SEVEN_REAL_API36_TESTS_PASS'):
            self.assertIn(item,s)
        for forbidden in ('-Pandroid.testInstrumentationRunnerArguments.notAnnotation=',
                          'continue-on-error', 'assumeTrue', '@Ignore', 'git reset --hard',
                          'chmod 0777'):
            self.assertNotIn(forbidden,s)
        self.assertIn('shutil.rmtree(out)',s)

if __name__=='__main__':unittest.main(verbosity=2)
