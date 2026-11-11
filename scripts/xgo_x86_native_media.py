#!/usr/bin/env python3
"""Opt-in, source-pinned x86_64 Android FFmpeg/FFprobe/aria2 parity lane.

ONLY mutates a disposable Github Actions checkout for an explicitly labeled
same-repository PR. ARM64 production manifests and toolchains remain untouched
in Git. No downloaded executable is trusted without source SHA, build lock,
Android ELF policy, apk bytes and independent instrumentation evidence.
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
import struct
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'Mikeyphw/xdm-xgo'
PARENT = 'fbda3835e5a252df577d1ce8676a39768cf8de22'
LABEL = 'xgo-x86-native-media'
APP = 'app/XDM.Android/app/build.gradle.kts'
AUTH = 'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidEngineProcessAuthority.kt'
FF_MANIFEST = 'app/XDM.Android/media-ffmpeg/runtime/ffmpeg-runtime.json'
ARIA_MANIFEST = 'app/XDM.Android/transfer-aria2/runtime/aria2-runtime.json'
FF_BUILD = 'app/XDM.Android/tools/install-ffmpeg-runtime.py'
ARIA_BUILD = 'app/XDM.Android/tools/build-aria2-runtime.py'
OPENSSL = 'app/XDM.Android/tools/android_native_openssl.py'
X86_PROFILE = 'scripts/xgo_x86_64_profile.py'
X86_CORE = 'tools/xgo/build_android_xdmcore_x86_64.py'
FF_VERIFY = 'app/XDM.Android/tools/verify-ffmpeg-runtime.py'
ARIA_VERIFY = 'app/XDM.Android/tools/verify-aria2-runtime.py'
PINS = {
 APP:'7040b8359d3b2a8f31e1a1ec5c7d53aaec6bcae2',
 AUTH:'659663b890fc4450e9534743ffc725e92179fe34',
 FF_MANIFEST:'35ae54e2e24fd2acc023dc3dcfde4e9ebe08f570',
 ARIA_MANIFEST:'8347a5e71dc23de2215b38164e66e7435bce4182',
 FF_BUILD:'2c6f88f89b3a5cbe26a2a78ff3391496b26ea904',
 ARIA_BUILD:'27d536627a0153a2cedfbcfac62a3c2a610e0109',
 OPENSSL:'d8d7a5f5a09c86d76c56726c01ebe32b97dc12ba',
 X86_PROFILE:'7fbcafa86ec02e4449ad7aeef3851d0ec4867862',
 X86_CORE:'519ddf0952da78cc2c7f052069127118ccdff45e',
 FF_VERIFY:'c803464f03a1677856069308d000fc785ec9679d',
 ARIA_VERIFY:'e534de8a20a4c0912a290b9e4dec2c42177575c2',
}
NATIVE_FILES = {
 'lib/x86_64/libxdmcore.so': 'app/XDM.Android/app/src/main/jniLibs/x86_64/libxdmcore.so',
 'lib/x86_64/libxdm_ffmpeg.so': 'app/XDM.Android/media-ffmpeg/src/main/jniLibs/x86_64/libxdm_ffmpeg.so',
 'lib/x86_64/libxdm_ffprobe.so': 'app/XDM.Android/media-ffmpeg/src/main/jniLibs/x86_64/libxdm_ffprobe.so',
 'lib/x86_64/libaria2c.so': 'app/XDM.Android/transfer-aria2/src/main/jniLibs/x86_64/libaria2c.so',
}
SHA = re.compile(r'^[0-9a-f]{40}$')

def refuse(reason: str) -> None:
    raise RuntimeError('XGO_X86_MEDIA_REFUSED: '+reason)

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def git(*args: str, root: Path = ROOT) -> str:
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()

def checked_blob(path: Path, expected: str, root: Path = ROOT) -> str:
    if not path.is_file() or path.is_symlink(): refuse('missing/linked source: '+str(path))
    actual = git('hash-object', str(path), root=root)
    if actual != expected: refuse('stale source '+str(path)+' expected='+expected+' got='+actual)
    return path.read_text(encoding='utf-8')

def check_pins(root: Path = ROOT) -> dict[str,str]:
    return {name:checked_blob(root/name, blob, root) for name,blob in PINS.items()}

def require_host(expected: str) -> None:
    if not SHA.fullmatch(expected) or git('rev-parse','HEAD') != expected:
        refuse('exact PR head mismatch')
    subprocess.run(['git','-C',str(ROOT),'merge-base','--is-ancestor',PARENT,expected], check=True)
    if (os.environ.get('GITHUB_ACTIONS'),os.environ.get('RUNNER_OS'),
        os.environ.get('GITHUB_REPOSITORY'),os.environ.get('XGO_X86_MEDIA_OPT_IN'),
        os.environ.get('GITHUB_EVENT_NAME'),os.environ.get('GITHUB_EVENT_ACTION')) != (
        'true','Linux',REPOSITORY,'yes','pull_request','labeled'):
        refuse('manual, same-repo PR label opt-in required')
    if os.uname().machine != 'x86_64': refuse('host is not x86_64')
    if os.environ.get('XGO_X86_MEDIA_EXPECTED_HEAD') != expected: refuse('event SHA mismatch')
    if git('status','--porcelain','--untracked-files=no'): refuse('source must be clean before temporary adaptation')

def source_transform(text: str, role: str) -> str:
    """Adapt existing *pinned* native recipes, never a committed ARM64 file."""
    expected = {
        'ffmpeg': ('aarch64-linux-android', 'machine != 183'),
        'aria2': ('aarch64-linux-android','android-arm64-source-v1'),
        'openssl': ('android-arm64','arm64-v8a'),
    }[role]
    for anchor in expected:
        if anchor not in text: refuse('recipe anchor drift '+role+':'+anchor)
    substitutions = (
        ('aarch64-linux-android','x86_64-linux-android'),
        ('android-arm64','android-x86_64'),
        ('arm64-v8a','x86_64'),
        ('aarch64','x86_64'),
        ('arm64','x86_64'),
    )
    out=text
    for before,after in substitutions: out=out.replace(before,after)
    if role=='ffmpeg':
        if out.count('machine != 183') != 1: refuse('FFmpeg ELF hardcode drift')
        out=out.replace('machine != 183','machine != 62',1)
    if out == text: refuse('recipe mutation did not happen '+role)
    for forbidden in ('aarch64-linux-android','android-arm64','arm64-v8a'):
        if forbidden in out: refuse('ARM64 recipe residue '+role+':'+forbidden)
    return out

def manifest_transform(original: str, which: str) -> str:
    m=json.loads(original)
    if m.get('abi')!='arm64-v8a' or m.get('elfMachine')!=183 or m.get('ndkVersion')!='29.0.14206865':
        refuse('manifest source drift '+which)
    m['abi']='x86_64';m['elfMachine']=62
    if which=='ffmpeg':
        m['ffmpegPackagedPath']=m['ffmpegPackagedPath'].replace('arm64-v8a','x86_64')
        m['ffprobePackagedPath']=m['ffprobePackagedPath'].replace('arm64-v8a','x86_64')
        flags=m['configureFlags']
        if flags.count('--arch=aarch64')!=1 or flags.count('--cpu=armv8-a')!=1:
            refuse('FFmpeg CPU profile drift')
        m['configureFlags']=[{'--arch=aarch64':'--arch=x86_64','--cpu=armv8-a':'--cpu=x86-64'}.get(v,v) for v in flags]
        if m.get('gplEnabled') or m.get('nonfreeEnabled') or m.get('ffmpegLicense')!='LGPL-2.1-or-later':
            refuse('FFmpeg license policy changed')
    else:
        if m.get('schemaVersion')!=3 or m.get('buildProfile')!='android-arm64-source-v1' or m.get('license')!='GPL-2.0-or-later':
            refuse('aria2 source/license policy drift')
        m['packagedPath']=m['packagedPath'].replace('arm64-v8a','x86_64')
        m['buildProfile']='android-x86_64-source-v1'
        # Never reuse an ARM64-only third-party binary even in diagnostic CI.
        m.pop('compatibilityPrebuilt',None)
    return json.dumps(m,sort_keys=True,indent=2)+'\n'

def transform_all(originals: dict[str,str], root: Path=ROOT) -> dict[str,str]:
    spec=importlib.util.spec_from_file_location('xgo_x86_profile',root/X86_PROFILE)
    if spec is None or spec.loader is None: refuse('existing XP03 profile missing')
    p=importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
    if p.BASE_BLOB!=PINS[APP] or p.ARCH_PROVENANCE_SOURCE not in originals[AUTH]:
        refuse('XP03 profile/source contract changed')
    result={
        APP:p.transform(originals[APP]),
        AUTH:p.transform_authority(originals[AUTH]),
        FF_BUILD:source_transform(originals[FF_BUILD],'ffmpeg'),
        ARIA_BUILD:source_transform(originals[ARIA_BUILD],'aria2'),
        OPENSSL:source_transform(originals[OPENSSL],'openssl'),
        FF_MANIFEST:manifest_transform(originals[FF_MANIFEST],'ffmpeg'),
        ARIA_MANIFEST:manifest_transform(originals[ARIA_MANIFEST],'aria2'),
    }
    if 'abiFilters += setOf("x86_64")' not in result[APP]: refuse('x86_64 APK ABI filter missing')
    if 'target_arch") == "amd64"' not in result[AUTH]: refuse('temporary Go arch provenance missing')
    if 'machine != 62' not in result[FF_BUILD]: refuse('x86 FFmpeg ELF verifier missing')
    return result

def prepare(expected: str) -> None:
    require_host(expected)
    originals=check_pins()
    target=transform_all(originals)
    # All checks and transformations happen BEFORE any mutation.
    for name,data in target.items():
        (ROOT/name).write_text(data,encoding='utf-8')
    print('XGO_X86_MEDIA_EPHEMERAL_SOURCE_PROFILE_PASS='+expected,flush=True)

def verify_native(data: bytes, name: str) -> dict:
    if len(data)<4096 or data[:4]!=b'\x7fELF' or data[4:6]!=b'\x02\x01':
        refuse('native payload missing ELF64 LE: '+name)
    elf_type,machine=struct.unpack_from('<HH',data,16)
    if elf_type != 3 or machine != 62: refuse('not x86_64 PIE/ET_DYN: '+name)
    phoff=struct.unpack_from('<Q',data,32)[0]
    size,count=struct.unpack_from('<HH',data,54)
    if size<56 or count<1 or phoff+size*count>len(data):refuse('invalid ELF headers: '+name)
    alignments=[struct.unpack_from('<Q',data,phoff+i*size+48)[0] for i in range(count)
        if struct.unpack_from('<I',data,phoff+i*size)[0]==1]
    if not alignments or min(alignments)<16384:refuse('ELF load alignment insufficient: '+name)
    return {'sha256':digest(data),'size':len(data),'machine':machine,'min_load_alignment':min(alignments)}

def verify_apk(expected: str, apk: Path, receipt: Path) -> None:
    if not SHA.fullmatch(expected) or git('rev-parse','HEAD') != expected:
        refuse('source/receipt SHA mismatch')
    subprocess.run(['git','-C',str(ROOT),'merge-base','--is-ancestor',PARENT,expected],check=True)
    if not apk.is_file():refuse('app APK missing')
    results={}
    with zipfile.ZipFile(apk) as z:
        if z.testzip():refuse('APK CRC failure')
        libs=[n for n in z.namelist() if n.startswith('lib/') and n.endswith('.so')]
        if any(not n.startswith('lib/x86_64/') for n in libs):refuse('foreign architecture in x86 APK')
        for name,path in NATIVE_FILES.items():
            if name not in z.namelist():refuse('required native payload missing: '+name)
            blob=z.read(name)
            local=ROOT/path
            if not local.is_file() or local.read_bytes()!=blob:refuse('APK payload differs from source-built binary: '+name)
            results[name]=verify_native(blob,name)
    for which,manifest_path,lock_path in (
        ('ffmpeg',FF_MANIFEST,'app/XDM.Android/media-ffmpeg/runtime/ffmpeg-runtime.lock.json'),
        ('aria2',ARIA_MANIFEST,'app/XDM.Android/transfer-aria2/runtime/aria2-runtime.lock.json')):
        manifest=json.loads((ROOT/manifest_path).read_text())
        lock=json.loads((ROOT/lock_path).read_text())
        if manifest['abi']!='x86_64' or lock['abi']!='x86_64' or lock['ndkVersion']!='29.0.14206865':
            refuse('ABI/NDK provenance mismatch '+which)
        if which=='aria2':
            if lock.get('sourceKind')!='source-build' or lock.get('buildProfile')!='android-x86_64-source-v1':
                refuse('aria2 source-build attestation missing')
            if lock.get('binarySha256')!=results['lib/x86_64/libaria2c.so']['sha256']:
                refuse('aria2 lock digest mismatch')
        else:
            if lock.get('ffmpegBinarySha256')!=results['lib/x86_64/libxdm_ffmpeg.so']['sha256'] or lock.get('ffprobeBinarySha256')!=results['lib/x86_64/libxdm_ffprobe.so']['sha256']:
                refuse('FFmpeg/FFprobe lock digest mismatch')
            if lock.get('gplEnabled') or lock.get('nonfreeEnabled'):refuse('FFmpeg license attestation mismatch')
    payload={'schema_version':1,'head_sha':expected,'abi':'x86_64','android_api':36,
        'native':results,'apk_sha256':digest(apk.read_bytes()),
        'qualified_hosted_runtime':False,'qualified_physical_arm64':False,
        'qualified_licensed_1dm':False,'release_eligible':False}
    receipt.parent.mkdir(parents=True,exist_ok=True)
    if receipt.exists():refuse('refusing to overwrite a previous receipt')
    receipt.write_text(json.dumps(payload,sort_keys=True,indent=2)+'\n')
    print('XGO_X86_MEDIA_APK_SOURCE_AND_ELF_PASS_NOT_RUNTIME_QUALIFIED',flush=True)

def main() -> None:
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest='mode',required=True)
    a=sub.add_parser('prepare');a.add_argument('--head',required=True)
    a=sub.add_parser('check');a.add_argument('--head',required=False)
    a=sub.add_parser('verify-apk');a.add_argument('--head',required=True);a.add_argument('--apk',type=Path,required=True);a.add_argument('--receipt',type=Path,required=True)
    a=sub.add_parser('emulator');a.add_argument('--head',required=True);a.add_argument('--evidence',type=Path,required=True)
    args=p.parse_args()
    if args.mode=='prepare':prepare(args.head)
    elif args.mode=='check':
        check_pins(); transform_all(check_pins()); print('XGO_X86_MEDIA_PINNED_TRANSFORM_PASS',flush=True)
    elif args.mode=='verify-apk':verify_apk(args.head,args.apk,args.receipt)
    else: emulator_accept(args.head,args.evidence)

# The single-line emulator action invokes this entry point, rather than passing
# a multi-line heredoc through ReactiveCircus' per-line /usr/bin/sh -c behavior.
def parse_adb_inventory(output: str) -> list[tuple[str,str]]:
    """Parse adb devices -l with tabs OR spaces, rejecting non-device rows."""
    rows=[]
    for raw in output.splitlines():
        value=raw.strip()
        if not value or value == 'List of devices attached':
            continue
        tokens=value.split()
        if len(tokens) < 2 or not re.fullmatch(r'[A-Za-z0-9:._-]+',tokens[0]):
            refuse('malformed ADB device inventory')
        rows.append((tokens[0],tokens[1]))
    return rows


def validate_emulator_identity(devices: str, props: dict[str,str]) -> None:
    rows=parse_adb_inventory(devices)
    expected=[('emulator-5554','device')]
    relevant={key:props.get(key,'') for key in (
        'ro.build.version.sdk','ro.kernel.qemu','ro.boot.qemu',
        'ro.product.cpu.abi','sys.boot_completed')}
    # Small, bounded identity evidence. No raw logcat, shell output, credentials or URLs.
    print('XGO_X86_MEDIA_EMULATOR_IDENTITY='+json.dumps(
        {'device_rows':rows[:8],'device_count':len(rows),'properties':relevant},
        sort_keys=True),flush=True)
    if rows != expected:
        refuse('exact single emulator-5554 device inventory required')
    if (relevant['ro.build.version.sdk'] != '36' or
        relevant['ro.product.cpu.abi'] != 'x86_64' or
        relevant['sys.boot_completed'] != '1' or
        (relevant['ro.kernel.qemu'] != '1' and relevant['ro.boot.qemu'] != '1')):
        refuse('API36 x86_64 native emulator property mismatch')
    print('XGO_X86_MEDIA_API36_X86_NATIVE_IDENTITY_PASS',flush=True)

def emulator_accept(expected: str, evidence_dir: Path) -> None:
    import xml.etree.ElementTree as ET
    if not re.fullmatch(r'[0-9a-f]{40}',expected) or git('rev-parse','HEAD')!=expected:
        refuse('emulator SHA mismatch')
    if (os.environ.get('GITHUB_ACTIONS'),os.environ.get('GITHUB_REPOSITORY'),
        os.environ.get('XGO_X86_MEDIA_OPT_IN'),os.environ.get('XGO_X86_MEDIA_EXPECTED_HEAD')) != (
        'true',REPOSITORY,'yes',expected): refuse('unapproved emulator')
    def adb(*a: str) -> str:
        return subprocess.check_output(['adb','-s','emulator-5554',*a],text=True,timeout=30).strip().replace('\r','')
    devices=subprocess.check_output(['adb','devices','-l'],text=True,timeout=30)
    keys=('ro.build.version.sdk','ro.kernel.qemu','ro.boot.qemu',
          'ro.product.cpu.abi','sys.boot_completed')
    props={key:adb('shell','getprop',key) for key in keys}
    validate_emulator_identity(devices,props)
    klass='com.mikeyphw.xdm.android.XgoX86NativeMediaInstrumentedTest'
    android=ROOT/'app/XDM.Android'
    output=android/'app/build/outputs/androidTest-results/connected'
    if output.is_symlink(): refuse('JUnit output cannot be symlink')
    if output.is_dir(): shutil.rmtree(output)
    args=['./gradlew','--no-daemon','--max-workers=2',
          '-Pxdm.requireFfmpegRuntime=true','-Pxdm.requireAria2Runtime=true',
          ':app:connectedDebugAndroidTest',
          '-Pandroid.testInstrumentationRunnerArguments.class='+klass]
    p=subprocess.run(args,cwd=android,check=False,timeout=2400)
    if p.returncode:refuse('real Android media instrumentation failed rc='+str(p.returncode))
    expected_cases={'x86_01PinnedFfmpegExecutes','x86_02PinnedFfprobeExecutes',
                    'x86_03SourceBuiltAria2Executes'}
    xmls=sorted(output.rglob('*.xml')) if output.is_dir() else []
    if not xmls:refuse('no fresh real Android JUnit XML')
    cases=[]
    for f in xmls:
        if f.is_symlink() or f.stat().st_size>2_000_000:refuse('unsafe JUnit XML')
        data=f.read_bytes()
        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():refuse('XML entity unsupported')
        for case in ET.fromstring(data).iter('testcase'):
            if case.get('classname') == klass:cases.append(case)
    names=[c.get('name') for c in cases]
    if len(names)!=3 or set(names)!=expected_cases or any(
            any(c.find(x) is not None for x in ('failure','error','skipped')) for c in cases):
        refuse('exact three real instrumented runtime tests not passed: '+repr(names))
    evidence_dir.mkdir(parents=True,exist_ok=True)
    if (evidence_dir/'android-junit.xml').exists():refuse('cannot overwrite JUnit receipt')
    # Redacted, synthesized evidence; no raw Android logs or user data.
    import xml.sax.saxutils as sx
    receipt='<testsuite tests="3" failures="0" skipped="0" errors="0">\n'+''.join(
      '  <testcase classname="'+klass+'" name="'+sx.escape(name)+'"/>\n' for name in sorted(names))+'</testsuite>\n'
    (evidence_dir/'android-junit.xml').write_text(receipt,encoding='utf-8')
    print('XGO_X86_FFMPEG_FFPROBE_ARIA2_REAL_API36_PASS_NOT_ARM64_OR_RELEASE='+expected,flush=True)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('XGO_X86_MEDIA_REFUSED: '+str(exc),file=sys.stderr)
        raise SystemExit(2)
