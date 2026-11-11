#!/usr/bin/env python3
"""P01: run FOUR real MP08B3 API36 x86_64 tests after the THREE proven native-media tests.

No new native build recipe, no ARM64 translation, no APK identity downgrade,
no success from merely compiling androidTest, and no release qualification.
Runs exclusively in the labeled, exact-head PR's hosted x86_64 emulator.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_REPO = 'Mikeyphw/xdm-xgo'
PARENT = '36e8e318305023a8edbc5cff836bfeea2f5c56d6'
CONTRACT = ROOT/'scripts/test_xgo_mp08b3_source_contract.py'
CLASS = 'com.mikeyphw.xdm.android.MP08B3MediaStoreAcceptanceInstrumentedTest'
CASES = frozenset((
 'b3_01RealMediaStorePublicationReadbackAndIdempotency',
 'b3_02NoAuthorizationAndCorruptedCandidateFailClosed',
 'b3_03InterruptedPendingMediaStoreRowIsReconciled',
 'b3_04RealEmbeddedFfmpegProbeMuxAndMediaStoreRoundTrip',
))
NATIVE_CLASS='com.mikeyphw.xdm.android.XgoX86NativeMediaInstrumentedTest'
NATIVE_CASES=frozenset(('x86_01PinnedFfmpegExecutes','x86_02PinnedFfprobeExecutes',
                        'x86_03SourceBuiltAria2Executes'))
MP08_SOURCE_BLOB='aa1d5ea1090e4cdeb0d0e526b704a0d01e62d81d'
CONTRACT_SOURCE_BLOB='3e06a4a5a726cb68ce4ec2f4ffe250b5adde23fe'


def refuse(why: str) -> None:
    raise RuntimeError('MP08B3_X86_P01_REFUSED: '+why)


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(['git','-C',str(ROOT),*args],text=True,timeout=25).strip()


def require_source() -> None:
    for path,identity in (
      (ROOT/'app/XDM.Android/app/src/androidTest/kotlin/com/mikeyphw/xdm/android/MP08B3MediaStoreAcceptanceInstrumentedTest.kt',MP08_SOURCE_BLOB),
      (CONTRACT,CONTRACT_SOURCE_BLOB)):
        if not path.is_file() or path.is_symlink() or git('hash-object',str(path))!=identity:
            refuse('MP08B3_SOURCE_BLOB_DRIFT:'+str(path.relative_to(ROOT)))
    spec=importlib.util.spec_from_file_location('mp08b3_existing_acceptance',CONTRACT)
    if spec is None or spec.loader is None: refuse('MP08B3_CONTRACT_IMPORT_MISSING')
    return spec


def require_authorized_runner(expected: str) -> None:
    if not re.fullmatch(r'[0-9a-f]{40}',expected):refuse('INVALID_GIT_SHA')
    if git('rev-parse','HEAD')!=expected:refuse('CHECKOUT_SHA_DRIFT')
    subprocess.run(['git','-C',str(ROOT),'merge-base','--is-ancestor',PARENT,expected],check=True,timeout=25)
    vars_expected={'GITHUB_ACTIONS':'true','RUNNER_OS':'Linux',
      'GITHUB_REPOSITORY':EXPECTED_REPO,'GITHUB_EVENT_NAME':'pull_request',
      'GITHUB_EVENT_ACTION':'labeled','XGO_X86_MEDIA_OPT_IN':'yes',
      'XGO_X86_MEDIA_EXPECTED_HEAD':expected}
    for key,value in vars_expected.items():
        if os.environ.get(key)!=value:refuse('UNAUTHORIZED_RUNNER_ENV:'+key)
    if os.uname().machine != 'x86_64':refuse('WRONG_LINUX_HOST_ARCH')
    require_source()


def checked_xml(path: Path) -> tuple[str,list[dict[str,str]]]:
    if not path.is_file() or path.is_symlink() or not 1<=path.stat().st_size<=2_000_000:
        refuse('MISSING_OR_UNSAFE_JUNIT:'+path.name)
    raw=path.read_bytes()
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():refuse('JUNIT_XML_DTD_FORBIDDEN')
    try:root=ET.fromstring(raw)
    except ET.ParseError as ex:refuse('MALFORMED_JUNIT:'+str(ex))
    cases=[]
    for elem in root.iter('testcase'):
        item={'class':elem.get('classname',''),'name':elem.get('name','')}
        if any(elem.find(kind) is not None for kind in ('failure','error','skipped')):
            refuse('FAILED_OR_SKIPPED_JUNIT:'+item['name'])
        cases.append(item)
    return checksum(raw),cases


def verify_exact_junit(directory: Path, klass: str, cases: frozenset[str]) -> dict:
    if not directory.is_dir() or directory.is_symlink():refuse('FRESH_JUNIT_DIRECTORY_MISSING')
    xmls=sorted(directory.rglob('*.xml'))
    if not 1<=len(xmls)<=30:refuse('JUNIT_XML_COUNT_INVALID')
    found=[];digests={}
    for path in xmls:
        digest,items=checked_xml(path)
        digests[str(path.relative_to(directory))]=digest
        found.extend(items)
    if len(found)!=len(cases) or {(x['class'],x['name']) for x in found} != {(klass,c) for c in cases}:
        refuse('EXACT_JUNIT_CASES_REFUSED:'+repr(found)[:500])
    if len({(x['class'],x['name']) for x in found})!=len(cases):refuse('DUPLICATED_JUNIT_METHOD')
    return {'tests':len(cases),'names':sorted(cases),'sha256_by_xml':digests}


def require_safe_evidence(path: Path) -> Path:
    if not path.is_dir() or path.is_symlink() or path.stat().st_mode & 0o002:
        refuse('UNSAFE_EVIDENCE_DIRECTORY')
    return path


def verify_preceding_native_gate(evidence: Path,expected: str) -> dict:
    require_safe_evidence(evidence)
    apkr=evidence/'native-media-receipt.json'
    if not apkr.is_file() or apkr.is_symlink() or apkr.stat().st_size>150_000:
        refuse('NATIVE_APK_RECEIPT_MISSING')
    try:receipt=json.loads(apkr.read_text())
    except (OSError,ValueError):refuse('NATIVE_APK_RECEIPT_INVALID')
    if (receipt.get('head_sha')!=expected or receipt.get('abi')!='x86_64' or
        receipt.get('android_api')!=36 or receipt.get('release_eligible') is not False or
        not re.fullmatch(r'[0-9a-f]{64}',str(receipt.get('apk_sha256','')))):
        refuse('NATIVE_APK_RECEIPT_IDENTITY_FAILURE')
    native=receipt.get('native',{})
    expected_names={'lib/x86_64/libxdmcore.so','lib/x86_64/libxdm_ffmpeg.so',
                    'lib/x86_64/libxdm_ffprobe.so','lib/x86_64/libaria2c.so'}
    if set(native)!=expected_names:refuse('NATIVE_APK_RECEIPT_BINARY_INVENTORY_FAILURE')
    for key,value in native.items():
        if value.get('machine')!=62 or value.get('min_load_alignment',0)<16384 or not re.fullmatch(r'[0-9a-f]{64}',str(value.get('sha256',''))):
            refuse('NATIVE_APK_RECEIPT_ELF_POLICY:'+key)
    previous=evidence/'android-junit.xml'
    digest,rows=checked_xml(previous)
    if len(rows)!=3 or {(x['class'],x['name']) for x in rows}!={(NATIVE_CLASS,x) for x in NATIVE_CASES}:
        refuse('PRECEDING_THREE_NATIVE_EXECUTIONS_UNQUALIFIED')
    return {'apk_sha256':receipt['apk_sha256'],'native_three_junit_sha256':digest}


def check_identity() -> None:
    # Don't inherit a process-level indicator alone; check actual emulator again.
    exe=['adb','-s','emulator-5554','shell','getprop']
    def getprop(key: str) -> str:
        return subprocess.check_output([*exe,key],text=True,timeout=30).strip().replace('\r','')
    import importlib.util
    script=ROOT/'scripts/xgo_x86_native_media.py'
    spec=importlib.util.spec_from_file_location('xgo_x86_media_gate',script)
    if spec is None or spec.loader is None:refuse('NATIVE_GATE_MODULE_MISSING')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    devices=subprocess.check_output(['adb','devices','-l'],text=True,timeout=30)
    props={k:getprop(k) for k in ('ro.build.version.sdk','ro.kernel.qemu','ro.boot.qemu','ro.product.cpu.abi','sys.boot_completed')}
    module.validate_emulator_identity(devices,props)


def run(expected: str,evidence: Path) -> None:
    require_authorized_runner(expected)
    native=verify_preceding_native_gate(evidence,expected)
    check_identity()
    android=ROOT/'app/XDM.Android'
    out=android/'app/build/outputs/androidTest-results/connected'
    for candidate in (out,*out.parents):
        if candidate == ROOT.parent:break
        if candidate.is_symlink():refuse('JUNIT_RESULT_PATH_SYMLINK')
    if out.exists():
        if not out.is_dir():refuse('PREEXISTING_JUNIT_NOT_DIRECTORY')
        shutil.rmtree(out)
    # This is a *second actual Android instrumentation session* on the same emulator,
    # with no native rebuild, no Android emulator reboot, and exact class selection.
    cmd=['./gradlew','--no-daemon','--max-workers=2',
         '-Pxdm.requireFfmpegRuntime=true','-Pxdm.requireAria2Runtime=true',
         ':app:connectedDebugAndroidTest',
         '-Pandroid.testInstrumentationRunnerArguments.class='+CLASS]
    print('MP08B3_X86_P01_REAL_FOUR_TEST_ANDROID_SESSION_STARTED',flush=True)
    completed=subprocess.run(cmd,cwd=android,check=False,timeout=3600)
    if completed.returncode:
        try:
            spec=require_source();module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            module.api36_collect_crash_diagnostics()
        except Exception as exc:print('MP08B3_X86_P01_DIAGNOSTICS_UNAVAILABLE:'+str(exc)[:120],flush=True)
        refuse('ANDROID_INSTRUMENTATION_FAILED_RC='+str(completed.returncode))
    checked=verify_exact_junit(out,CLASS,CASES)
    spec=require_source();module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.api36_receipt_contract(out)  # independent inherited four-case contract
    if (evidence/'mp08b3-four-junit.json').exists():refuse('PREEXISTING_FOUR_TEST_RECEIPT')
    report={'schema_version':1,'source_head':expected,'test_suite':'MP08B3',
      'abi':'x86_64','android_api':36,'native_preceding_tests_passed':3,
      'mediastore_tests_passed':4,'evidence':checked,'native':native,
      'physical_arm64_qualified':False,'go_published_byte_equivalence_qualified':False,
      'release_eligible':False,'licensed_1dm_qualified':False}
    path=evidence/'mp08b3-four-junit.json'
    with path.open('x',encoding='utf-8') as fp:json.dump(report,fp,indent=2,sort_keys=True);fp.write('\n')
    print('MP08B3_X86_P01_SEVEN_REAL_API36_TESTS_PASS_NOT_ARM64_OR_RELEASE='+expected,flush=True)


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['run','check'])
    parser.add_argument('--head')
    parser.add_argument('--evidence',type=Path)
    args=parser.parse_args()
    if args.mode=='check':
        require_source()
        print('MP08B3_X86_P01_SOURCE_PIN_PASS',flush=True)
    else:
        if not args.head or not args.evidence:refuse('EXACT_HEAD_AND_EVIDENCE_REQUIRED')
        run(args.head,args.evidence)

if __name__=='__main__':
    try:main()
    except Exception as err:
        print('MP08B3_X86_P01_REFUSED: '+str(err),file=sys.stderr,flush=True)
        raise SystemExit(2)
