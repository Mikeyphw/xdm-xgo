#!/usr/bin/env python3
"""MP12 P04 read-only Android signed publication verifier; never signs or publishes.

Source-only verifies the historical release job remained untouched. `verify`
independently validates an XAR16 publication directory AND the actual APK,
AAB and APKS bytes with Android/Java signing tools. A source-only or synthetic
unit-test pass is not a release, signer, emulator or physical-device pass.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
REPO='Mikeyphw/xdm-xgo'
SOURCE_PINS={
 '.github/workflows/android.yml':'9db9afa13e9a5c7944d727888968bac6766ca043',
 'app/XDM.Android/tools/build-xar16-release-artifacts.sh':'a1344d95ce6c8a899fe088d539fa98478db62e3e',
 'app/XDM.Android/tools/generate-xar16-publication-bundle.sh':'b7757b83509ff0c740d80e49e750cee544098458',
 'app/XDM.Android/tools/run-xar16-signed-release-gate.sh':'5ff12b30e3dffa0062ab5116db9ab366a3e6ff71',
 'app/XDM.Android/tools/verify-xar16-release-evidence.py':'19f075abdc449f8c570a746f974e7fce34dcc274',
 'app/XDM.Android/tools/validate-xar16-release-evidence-seal.py':'d6f63b5d361adf05b9be20887b2ad493cb9e66e5',
}
FILES=('release-metadata.json','phase10-release-attestation.json',
       'xar16-same-run-artifacts.json','xar16-device-matrix.json',
       'xar16-signed-release-journeys.json','rm04-validation-seal.json')
APK_LIBS=('libxdmcore.so','libxdm_ffmpeg.so','libxdm_ffprobe.so','libaria2c.so')
KIND_EXT={'apk':'.apk','aab':'.aab','apks':'.apks'}
R40=re.compile(r'[0-9a-f]{40}\Z');R64=re.compile(r'[0-9a-f]{64}\Z')
R_NAME=re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z')
MAX_FILE=420*1024*1024
MAX_MEMBERS=1800
MAX_UNPACK=850*1024*1024

class Refused(ValueError):pass

def need(ok,reason):
 if not ok:raise Refused('XGO_MP12_P04_REFUSED_'+reason)
def sha(data):return hashlib.sha256(data).hexdigest()
def gitblob(data):return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
def read_bytes(path,cap=2*1024*1024):
 need(path.is_file() and not path.is_symlink(),'NOT_REGULAR_FILE')
 sz=path.stat().st_size
 need(0<sz<=cap,'FILE_SIZE_BOUND')
 return path.read_bytes()
def unique_json(blob):
 def pairs(data):
  out={}
  for k,v in data:
   need(k not in out,'DUPLICATE_JSON_KEY')
   out[k]=v
  return out
 try:v=json.loads(blob,object_pairs_hook=pairs)
 except (ValueError,UnicodeError,TypeError):raise Refused('XGO_MP12_P04_REFUSED_INVALID_JSON') from None
 need(isinstance(v,dict),'JSON_OBJECT_REQUIRED')
 return v

def source_guard(root):
 for name,pin in SOURCE_PINS.items():
  p=root/name
  need(p.is_file() and not p.is_symlink(),'SOURCE_MISSING_'+name.replace('/','_'))
  need(gitblob(p.read_bytes())==pin,'SOURCE_BLOB_CHANGED_'+name.replace('/','_'))
 flow=(root/'.github/workflows/android.yml').read_text()
 step=flow.split('\n  signed-release:\n')
 need(len(step)==2 and '\n  emulator-compatibility:\n' in step[1], 'RELEASE_JOB_BOUNDARY')
 job=step[1].split('\n  emulator-compatibility:\n',1)[0]
 require=["startsWith(github.ref, 'refs/tags/android-v')",
          "github.event_name == 'push'",'inputs.signed_release',
          'XDM_RELEASE_SIGNER_SHA256','XDM_RELEASE_KEYSTORE_BASE64',
          'XDM_XAR16_FULL_RELEASE_GATE',
          'run-hosted-emulator-instrumentation.sh --signed-release',
          'actions/attest@v4','xdm-android-signed-release',
          'if-no-files-found: error']
 need(all(s in job for s in require),'RELEASE_JOB_SAFETY_CONTRACT')
 need('continue-on-error' not in job and '|| true' not in job,'RELEASE_JOB_FAIL_OPEN')
 generator=(root/'app/XDM.Android/tools/generate-xar16-publication-bundle.sh').read_text()
 need(generator.count('mp12_p04_signed_release.py checksum-write')==1 and
      'xargs -0 sha256sum' not in generator and 'xargs -0 sha512sum' not in generator,
      'CHECKSUM_GENERATOR_NOT_BOUNDED')
 return {'source_pins':len(SOURCE_PINS),'release_path':'TAG_ONLY_LOCKED',
         'signed_release_executed':False,'signed_release_qualified':False}

def githead(root):
 try: p=subprocess.run(('git','-C',str(root),'rev-parse','HEAD'),capture_output=True,
                        text=True,timeout=20,check=False)
 except (OSError,subprocess.TimeoutExpired):raise Refused('XGO_MP12_P04_REFUSED_GIT_UNAVAILABLE') from None
 need(p.returncode==0 and bool(R40.fullmatch(p.stdout.strip())),'CHECKOUT_GIT_HEAD_INVALID')
 return p.stdout.strip()

def run_id(value):
 need(isinstance(value,str) and bool(R_NAME.fullmatch(value)) and '..' not in value,
      'RUN_ID_INVALID')
 return value

def checksum_rows(content,length,run):
 try: rows=content.decode('ascii').splitlines()
 except UnicodeError:raise Refused('XGO_MP12_P04_REFUSED_CHECKSUM_CHARSET') from None
 need(len(rows)==len(FILES),'CHECKSUM_LINES_COUNT')
 prefix='build/release/publication/xar16-'+run+'/'
 found={}
 for row in rows:
  m=re.fullmatch('([0-9a-f]{'+str(length)+'})  (.+)',row)
  need(m is not None,'CHECKSUM_ROW_INVALID')
  digest,name=m.groups()
  need(name.startswith(prefix),'CHECKSUM_PATH_NOT_CANONICAL')
  basename=name[len(prefix):]
  need(basename in FILES and basename not in found, 'CHECKSUM_INVENTORY')
  found[basename]=digest
 need(set(found)==set(FILES),'CHECKSUM_INVENTORY')
 return found

def write_checksums(folder):
 # POSIX/Termux portable exclusive-create. Never hash SHA256SUMS or SHA512SUMS
 # themselves, and never overwrite an existing or symlinked receipt.
 need(folder.is_dir() and not folder.is_symlink(),'CHECKSUM_OUTPUT_DIR')
 need(folder.name.startswith('xar16-'),'CHECKSUM_OUTPUT_NAME')
 run=run_id(folder.name[len('xar16-'):])
 need({p.name for p in folder.iterdir()}==set(FILES),'CHECKSUM_SOURCE_INVENTORY')
 contents={name:read_bytes(folder/name) for name in FILES}
 prefix='build/release/publication/xar16-'+run+'/'
 for digest_name,hasher in (('SHA256SUMS',hashlib.sha256),('SHA512SUMS',hashlib.sha512)):
  target=folder/digest_name
  need(not target.exists() and not target.is_symlink(),'CHECKSUM_ALREADY_EXISTS')
  lines=''.join(hasher(contents[name]).hexdigest()+'  '+prefix+name+'\n' for name in sorted(FILES))
  flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0)
  try:fd=os.open(target,flags,0o600)
  except FileExistsError:raise Refused('XGO_MP12_P04_REFUSED_CHECKSUM_CREATE_RACE') from None
  with os.fdopen(fd,'wb') as stream:
   stream.write(lines.encode('ascii'))
   stream.flush()
   os.fsync(stream.fileno())
  rows=checksum_rows(read_bytes(target,10000),64 if digest_name=='SHA256SUMS' else 128,run)
  need(all(rows[n]==hasher(contents[n]).hexdigest() for n in FILES),'CHECKSUM_WRITTEN_BYTES_MISMATCH')
 print('XGO_MP12_P04_EXACT_SIX_EVIDENCE_CHECKSUMS_CREATED_NO_SELF_HASH')

def publication(folder,expected_sha,expected_run):
 run_id(expected_run)
 need(folder.is_dir() and not folder.is_symlink(),'PUBLICATION_DIR_MISSING')
 need(folder.name=='xar16-'+expected_run,'PUBLICATION_RUN_DIRECTORY')
 names={p.name for p in folder.iterdir()}
 need(names==set(FILES)|{'SHA256SUMS','SHA512SUMS'},'PUBLICATION_INVENTORY')
 data={name:read_bytes(folder/name) for name in FILES}
 sums256=checksum_rows(read_bytes(folder/'SHA256SUMS',10000),64,expected_run)
 sums512=checksum_rows(read_bytes(folder/'SHA512SUMS',12000),128,expected_run)
 for name in FILES:
  need(sha(data[name])==sums256[name] and
       hashlib.sha512(data[name]).hexdigest()==sums512[name],
       'PUBLICATION_DIGEST_MISMATCH_'+name)
 raw={name:unique_json(v) for name,v in data.items()}
 same=raw['xar16-same-run-artifacts.json'];meta=raw['release-metadata.json']
 phase=raw['phase10-release-attestation.json']
 device=raw['xar16-device-matrix.json'];journeys=raw['xar16-signed-release-journeys.json'];rm04=raw['rm04-validation-seal.json']
 for k,v in {'schemaVersion':1,'roadmapOverlay':'XAR16','runId':expected_run,
             'buildId':expected_sha,'sameRunArtifactProvenance':True,
             'publicationAllowed':False}.items():
  need(same.get(k)==v,'SAME_RUN_'+k.upper())
 for k,v in {'schemaVersion':1,'roadmapOverlay':'XAR16','publicationReady':True}.items():
  need(meta.get(k)==v,'METADATA_'+k.upper())
 need(meta.get('artifacts')==same.get('artifacts'),'METADATA_ARTIFACT_DRIFT')
 need(phase.get('apkSet',{}).get('splitSemantics')=='set-level-required-inventory',
      'SPLIT_SET_ATTESTATION_MISSING')
 need(device.get('apkSetInstalled') is True and device.get('upgradeRebootLaunchVerified') is True,
      'DEVICE_MATRIX_INCOMPLETE')
 need(journeys.get('signedReleaseJourneysPassed') is True,'SIGNED_JOURNEYS_INCOMPLETE')
 need(rm04.get('roadmapOverlay')=='RM04' and rm04.get('runId')==expected_run and
      rm04.get('canonicalNonDeviceValidationPassed') is True,'RM04_EVIDENCE_INCOMPLETE')
 for field in ('runtimeDiagnosticsPrivacyContract','finalDiagnosticsZipPrivacyIntegrity',
               'staticValidatorChain','releaseDocsValidator','routeTopologyValidator',
               'fullSelectedTaskValidation'):
  need(rm04.get(field) is True,'RM04_MISSING_'+field.upper())
 artifacts=same.get('artifacts')
 need(isinstance(artifacts,list) and len(artifacts)==3 and
      all(isinstance(x,dict) for x in artifacts),'RELEASE_ARTIFACT_LIST')
 by_kind={}
 for item in artifacts:
  kind=item.get('kind');path=item.get('path');digest=item.get('sha256')
  need(kind in KIND_EXT and kind not in by_kind,'RELEASE_ARTIFACT_KIND')
  need(isinstance(path,str) and path.endswith(KIND_EXT[kind]) and
       len(path)<300 and not path.startswith('/') and '\\' not in path and
       all(p not in ('','.','..') for p in path.split('/')),
       'RELEASE_ARTIFACT_PATH')
  need(bool(R64.fullmatch(str(digest))),'RELEASE_ARTIFACT_SHA256')
  by_kind[kind]=digest
 need(set(by_kind)==set(KIND_EXT),'RELEASE_ARTIFACT_INVENTORY')
 return by_kind

def zip_inventory(z):
 items=z.infolist()
 need(0<len(items)<=MAX_MEMBERS,'ZIP_MEMBER_COUNT')
 seen=set();total=0
 for info in items:
  name=info.filename
  directory=info.is_dir()
  p=name[:-1] if directory else name
  need(bool(p) and not p.startswith('/') and '\\' not in p and
       all(x not in ('','.','..') for x in p.split('/')),
       'ZIP_TRAVERSAL_OR_PATH')
  need(name not in seen,'ZIP_DUPLICATE_ENTRY');seen.add(name)
  mode=(info.external_attr>>16)&0o170000
  need(mode not in (0o120000,0o060000,0o020000) and mode in (0,0o100000,0o040000),
       'ZIP_UNSAFE_MEMBER')
  if directory:
   need(info.file_size==0 and mode in (0,0o040000),'ZIP_DIRECTORY_INVALID')
   continue
  need(mode!=0o040000 and info.file_size<=MAX_FILE,'ZIP_MEMBER_TOO_LARGE')
  total+=info.file_size
  need(total<=MAX_UNPACK,'ZIP_EXPANDED_SIZE')
  need((info.file_size==0 and info.compress_size==0) or
       (info.compress_size>0 and info.file_size<=info.compress_size*1000),
       'ZIP_COMPRESSION_RATIO')
 need(z.testzip() is None,'ZIP_CRC_FAILURE')
 return seen

def elf16(data):
 need(len(data)>=4096 and data[:6]==b'\x7fELF\x02\x01','ELF64_LE_REQUIRED')
 typ,machine=struct.unpack_from('<HH',data,16)
 need(typ==3 and machine==183,'ARM64_ELF_MACHINE')
 off=struct.unpack_from('<Q',data,32)[0];size,num=struct.unpack_from('<HH',data,54)
 need(56<=size<=256 and 1<=num<=512 and off>=64 and off+size*num<=len(data),
      'ELF_PROGRAM_HEADERS')
 loads=0
 for i in range(num):
  p=off+size*i
  if struct.unpack_from('<I',data,p)[0]!=1:continue
  loads+=1
  offset,vaddr=struct.unpack_from('<QQ',data,p+8)
  align=struct.unpack_from('<Q',data,p+48)[0]
  need(align>=16384 and align&(align-1)==0 and offset%align==vaddr%align,
       'ELF_PT_LOAD_NOT_16K_COMPATIBLE')
 need(loads>0,'ELF_NO_LOAD')

def inspect_apk(data,full=False):
 from io import BytesIO
 try:
  with zipfile.ZipFile(BytesIO(data)) as z:
   members=zip_inventory(z)
   native=[p for p in members if p.startswith('lib/') and p.endswith('.so')]
   need(all(p.startswith('lib/arm64-v8a/') for p in native),'FOREIGN_ANDROID_ABI')
   if full:
    need('classes.dex' in members,'RELEASE_APK_DEX_ABSENT')
    need(set('lib/arm64-v8a/'+x for x in APK_LIBS)<=set(native),'RELEASE_NATIVE_LIBRARY_INCOMPLETE')
   for p in native:elf16(z.read(p))
   return len(native)
 except (zipfile.BadZipFile,RuntimeError):raise Refused('XGO_MP12_P04_REFUSED_APK_ARCHIVE_INVALID') from None

def _run(argv,timeout=90):
 try:p=subprocess.run(argv,capture_output=True,text=True,timeout=timeout,check=False)
 except (OSError,subprocess.TimeoutExpired):raise Refused('XGO_MP12_P04_REFUSED_SIGNING_TOOL_UNAVAILABLE') from None
 need(p.returncode==0 and len(p.stdout)<2_000_000,'SIGNING_TOOL_FAILURE')
 return p.stdout

def cert_pin(pin):
 clean=str(pin).lower().replace(':','')
 need(bool(R64.fullmatch(clean)),'EXPECTED_CERT_SHA256_INVALID')
 return clean

def signed_apk(path,pin):
 # --print-certs prints the DER signer certificate digest, not an APK hash.
 out=_run(['apksigner','verify','--verbose','--print-certs',str(path)])
 found=re.findall(r'(?im)^Signer\s+#\d+\s+certificate\s+SHA-256\s+digest:\s*([0-9a-f]{64})\s*$',out)
 need(len(found)==1 and found[0].lower()==pin,'APK_SIGNER_CERTIFICATE_MISMATCH')

def signed_bundle(path,pin):
 jarsigner_output=_run(['jarsigner','-verify','-strict',str(path)],timeout=150)
 need('jar verified.' in jarsigner_output.lower(),'AAB_JAR_SIGNATURE_NOT_VERIFIED')
 out=_run(['keytool','-printcert','-jarfile',str(path)],timeout=90)
 matches=re.findall(r'(?im)^\s*SHA256:\s*([0-9a-f:]{64,95})\s*$',out)
 need(len(matches)==1 and cert_pin(matches[0])==pin,'AAB_CERTIFICATE_MISMATCH')

def check_binary(path,expected):
 # A bounded read is kept for ZIP inspection and SHA256 comparison.
 b=read_bytes(path,MAX_FILE)
 need(sha(b)==expected,'BINARY_DIGEST_MISMATCH')
 return b

def verify(root,folder,head,run,apk,aab,apks,pin):
 need(bool(R40.fullmatch(head)),'EXPECTED_HEAD_INVALID')
 need(githead(root)==head,'ACTUAL_CHECKOUT_HEAD_MISMATCH')
 source_guard(root)
 checks=publication(folder,head,run)
 pin=cert_pin(pin)
 actual={'apk':apk,'aab':aab,'apks':apks}
 need(len({x.resolve() for x in actual.values()})==3,'BINARY_PATH_COLLISION')
 for kind,path in actual.items():
  need(path.suffix==KIND_EXT[kind],'BINARY_EXTENSION_MISMATCH')
  check_binary(path,checks[kind])
 inspect_apk(read_bytes(apk,MAX_FILE),full=True)
 signed_apk(apk,pin)
 # jarsigner + keytool validate the actual signed AAB; do not infer from APK.
 with zipfile.ZipFile(aab) as z:zip_inventory(z)
 signed_bundle(aab,pin)
 apk_count=0;so_count=0
 with zipfile.ZipFile(apks) as z:
  members=zip_inventory(z)
  need('toc.pb' in members,'APKS_TOC_MISSING')
  names=sorted(x for x in members if x.endswith('.apk'))
  need(0<len(names)<=256,'APKS_SPLIT_SET_INVALID')
  with tempfile.TemporaryDirectory(prefix='xgo-p04-apks-',dir=os.environ.get('TMPDIR') or None) as tmp:
   for i,name in enumerate(names):
    b=z.read(name)
    need(len(b)>=1024,'APKS_SPLIT_SIZE')
    so_count+=inspect_apk(b)
    dest=Path(tmp)/('split-'+str(i)+'.apk')
    dest.write_bytes(b)
    signed_apk(dest,pin)
    apk_count+=1
 need(so_count>0,'APKS_ARM64_NATIVE_ABSENT')
 return {'schema':'xgo-mp12-p04-independent-release-audit-v1',
         'head_sha':head,'run_id':run,'file_sha256_verified':True,
         'signed_apk_certificate_verified':True,'signed_aab_certificate_verified':True,
         'signed_apks_splits_verified':apk_count,'expected_signer_sha256':pin,
         'arm64_native_16kb_checked':True,
         'source_release_job_unchanged':True,'release_qualified':False,
         'physical_arm64_qualified':False,'publication_automatically_authorized':False}

def main():
 p=argparse.ArgumentParser(description='MP12 P04 read-only XAR16 signing/provenance gate (no release action)')
 p.add_argument('mode',choices=['source-only','verify','checksum-write'])
 p.add_argument('--repo',default='.')
 p.add_argument('--publication-dir',type=Path)
 p.add_argument('--expected-head')
 p.add_argument('--run-id')
 p.add_argument('--apk',type=Path)
 p.add_argument('--aab',type=Path)
 p.add_argument('--apks',type=Path)
 p.add_argument('--signer-sha256')
 args=p.parse_args();root=Path(args.repo).expanduser().resolve()
 if args.mode=='checksum-write':
  need(args.publication_dir is not None,'CHECKSUM_DESTINATION_REQUIRED')
  write_checksums(args.publication_dir)
  return
 if args.mode=='source-only':
  result=source_guard(root)
  print('XGO_MP12_P04_SOURCE_SIGNING_TAG_POLICY_PINS_PASS_'+str(result['source_pins'])+'_NOT_RELEASE')
  return
 need(all(x is not None for x in (args.publication_dir,args.expected_head,args.run_id,args.apk,args.aab,args.apks,args.signer_sha256)),'INPUTS_REQUIRED')
 result=verify(root,args.publication_dir,args.expected_head,args.run_id,args.apk,args.aab,args.apks,args.signer_sha256)
 # No raw tool logs, credentials, private paths or signing aliases printed.
 print('XGO_MP12_P04_SIGNED_ARTIFACT_BYTES_CERT_AND_ARM64_POLICY_VERIFIED_NOT_RELEASE')
 print(json.dumps(result,sort_keys=True))

if __name__=='__main__':
 try:main()
 except (Refused,OSError,UnicodeError,struct.error,zipfile.BadZipFile) as e:
  print(str(e) if isinstance(e,Refused) else 'XGO_MP12_P04_REFUSED_INPUT_OR_ARCHIVE',file=sys.stderr)
  sys.exit(2)
