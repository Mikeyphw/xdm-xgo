#!/usr/bin/env python3
"""Fail-closed x86_64 APK and native JNI ELF verifier, no ARM64 acceptance claims."""
from __future__ import annotations
import argparse
import hashlib
import json
import struct
import zipfile
from pathlib import Path


def inspect(apk: Path, expected_core: Path | None = None) -> dict:
    data=apk.read_bytes()
    with zipfile.ZipFile(apk) as archive:
        names=archive.namelist()
        libs=[x for x in names if x.startswith('lib/') and x.endswith('.so')]
        if not libs or any(not x.startswith('lib/x86_64/') for x in libs):
            raise ValueError('XGO_X86_APK_NON_X86_NATIVE_PAYLOAD:'+repr(libs))
        if 'lib/x86_64/libxdmcore.so' not in libs:
            raise ValueError('XGO_X86_APK_JNI_CORE_MISSING')
        core=archive.read('lib/x86_64/libxdmcore.so')
        if expected_core is not None and (not expected_core.is_file() or core != expected_core.read_bytes()):
            raise ValueError('XGO_X86_APK_CORE_SOURCE_MISMATCH')
        if len(core)<64 or core[:4]!=b'\x7fELF' or core[4:6]!=b'\x02\x01':
            raise ValueError('XGO_X86_APK_CORE_NOT_ELF64_LE')
        kind,machine=struct.unpack_from('<HH',core,16)
        if (kind,machine)!=(3,62):
            raise ValueError('XGO_X86_APK_CORE_NOT_X86_64')
        loads=[]
        pos=struct.unpack_from('<Q',core,32)[0]
        stride,count=struct.unpack_from('<HH',core,54)
        if stride < 56 or count == 0 or pos + stride * count > len(core):
            raise ValueError('XGO_X86_APK_CORE_BAD_ELF_HEADER')
        for i in range(count):
            offset=pos+i*stride
            if struct.unpack_from('<I',core,offset)[0]==1:
                loads.append(struct.unpack_from('<Q',core,offset+48)[0])
        if not loads or min(loads)<16384:
            raise ValueError('XGO_X86_APK_CORE_LOAD_ALIGNMENT')
        return {'abi':'x86_64','android_api':36,'core_sha256':hashlib.sha256(core).hexdigest(),
                'apk_sha256':hashlib.sha256(data).hexdigest(),'apk_bytes':len(data),
                'native_libs':libs,'native_arm64_executed':False}


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument('--apk',type=Path,required=True)
    p.add_argument('--receipt',type=Path)
    p.add_argument('--core',type=Path,required=True)
    a=p.parse_args()
    report=inspect(a.apk,a.core)
    if a.receipt:
        a.receipt.parent.mkdir(parents=True,exist_ok=True)
        a.receipt.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print('XGO_X86_APK_PAYLOAD_PASS:'+report['core_sha256'])
    return 0


if __name__=='__main__':
    raise SystemExit(main())
