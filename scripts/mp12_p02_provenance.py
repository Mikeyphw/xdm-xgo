#!/usr/bin/env python3
"""MP12 P02: independent cross-ABI native provenance and APK receipt audit.

Read-only. A successful result proves bounded artifact consistency, not a
signed release, physical ARM64 execution, real x86 runtime or Go cutover.
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

REPO='Mikeyphw/xdm-xgo'
NDK='29.0.14206865'
BRANCH='feature/xgo-mp09-consolidated-recording-20261111'
SHA40=re.compile(r'[0-9a-f]{40}\Z')
SHA64=re.compile(r'[0-9a-f]{64}\Z')
RUNID=re.compile(r'[0-9]{1,20}\Z')
ARM_LIBS=('libxdmcore.so','libxdm_ffmpeg.so','libxdm_ffprobe.so','libaria2c.so')
X86_FILES=(
 'app/XDM.Android/media-ffmpeg/src/main/jniLibs/x86_64/libxdm_ffmpeg.so',
 'app/XDM.Android/media-ffmpeg/src/main/jniLibs/x86_64/libxdm_ffprobe.so',
 'app/XDM.Android/media-ffmpeg/runtime/ffmpeg-runtime.lock.json',
 'app/XDM.Android/media-ffmpeg/runtime/licenses/FFmpeg-LGPL-2.1.txt',
 'app/XDM.Android/media-ffmpeg/runtime/licenses/OpenSSL-Apache-2.0.txt',
 'app/XDM.Android/transfer-aria2/src/main/jniLibs/x86_64/libaria2c.so',
 'app/XDM.Android/transfer-aria2/runtime/aria2-runtime.lock.json',
 'app/XDM.Android/transfer-aria2/runtime/licenses/GPL-2.0.txt',
 'app/XDM.Android/transfer-aria2/runtime/licenses/SOURCE-NOTICE.txt',
)
X86_SOURCE_FILES=(
 'app/XDM.Android/media-ffmpeg/runtime/ffmpeg-runtime.json',
 'app/XDM.Android/transfer-aria2/runtime/aria2-runtime.json',
 'app/XDM.Android/tools/install-ffmpeg-runtime.py',
 'app/XDM.Android/tools/build-aria2-runtime.py',
 'app/XDM.Android/tools/android_native_openssl.py',
 'app/XDM.Android/tools/android_elf_runtime.py',
 'app/XDM.Android/tools/verify-ffmpeg-runtime.py',
 'app/XDM.Android/tools/verify-aria2-runtime.py',
 'scripts/xgo_x86_native_media.py',
 'scripts/xgo_x86_64_profile.py',
)
# Source contracts are deliberate, immutable input pins for MP12 P02. Changing
# any requires reviewing and revalidating the provenance boundary.
SOURCE_PINS={
 'scripts/xgo_verified_native_artifact.py':'935d62b9ed781ccab2a8cf818456ee0fc12d5735',
 'scripts/xgo_hf16_apk_pair.py':'6bb9376ef422af8a052950de322a7d80e0d98688',
 'scripts/xgo_x86_native_media.py':'efb1791ffd94dfa9b176ab7288f3a06a1bf79011',
 '.github/workflows/xgo-x86-native-media.yml':'066867020077e2611f2b3cd35616e825d991fce6',
 '.github/workflows/android.yml':'9db9afa13e9a5c7944d727888968bac6766ca043',
 'app/XDM.Android/app/build.gradle.kts':'517b34ec27ef0c57237a99b6671dcf9829eae334',
 'app/XDM.Android/media-ffmpeg/runtime/ffmpeg-runtime.json':'35ae54e2e24fd2acc023dc3dcfde4e9ebe08f570',
 'app/XDM.Android/transfer-aria2/runtime/aria2-runtime.json':'8347a5e71dc23de2215b38164e66e7435bce4182',
 'scripts/xgo_hf16_apk_pair.py':'6bb9376ef422af8a052950de322a7d80e0d98688',
 'scripts/mp12_qualification.py':'124081ac4eebc78854f854b09361b01361a6c109',
}
MAX_ARCHIVE=450*1024*1024
MAX_MEMBER=160*1024*1024
MAX_UNCOMPRESSED=850*1024*1024
MAX_FILES=1800

class Refused(ValueError):pass

def require(ok,code):
 if not ok:raise Refused('MP12_P02_REFUSED_'+code)
def sha(data):return hashlib.sha256(data).hexdigest()
def blob(data):return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
def read_json(raw):
 def pairs(p):
  result={}
  for k,v in p:
   require(k not in result,'JSON_DUPLICATE_KEY')
   result[k]=v
  return result
 try:return json.loads(raw,object_pairs_hook=pairs)
 except (UnicodeDecodeError,ValueError,TypeError) as e:
  if isinstance(e,Refused):raise
  raise Refused('MP12_P02_REFUSED_JSON_INVALID') from None

def read_checked(path,limit=MAX_ARCHIVE):
 require(path.is_file() and not path.is_symlink(),'INPUT_NOT_REGULAR_FILE')
 require(0<path.stat().st_size<=limit,'INPUT_SIZE_INVALID')
 return path.read_bytes()

def validate_archive(z,*,allow_directories=False):
 members=z.infolist()
 require(0<len(members)<=MAX_FILES,'ARCHIVE_INVENTORY_SIZE')
 seen=set();total=0
 for info in members:
  name=info.filename
  directory=info.is_dir()
  if directory:
   require(allow_directories and name.endswith('/') and info.file_size==0,
           'ARCHIVE_DIRECTORY_ENTRY')
  canonical=name[:-1] if directory else name
  require(bool(canonical) and '\\' not in canonical and '\x00' not in canonical
          and not canonical.startswith('/') and not re.match('[a-zA-Z]:',canonical)
          and all(p not in ('','.','..') for p in canonical.split('/')),
          'ARCHIVE_PATH_UNSAFE')
  require(canonical not in seen,'ARCHIVE_DUPLICATE_MEMBER');seen.add(canonical)
  mode=(info.external_attr>>16)&0o170000
  require(mode!=0o120000 and mode in (0,0o100000,0o040000),
          'ARCHIVE_SPECIAL_FILE')
  if directory:
   require(mode in (0,0o040000),'ARCHIVE_DIRECTORY_MODE_INVALID')
   continue
  require(mode!=0o040000,'ARCHIVE_DIRECTORY_MODE_INVALID')
  require(0<info.file_size<=MAX_MEMBER,'ARCHIVE_MEMBER_SIZE')
  total+=info.file_size
  require(total<=MAX_UNCOMPRESSED,'ARCHIVE_EXPANDED_SIZE')
  if info.compress_size:
   require(info.file_size <= max(1,info.compress_size)*1000,'ARCHIVE_COMPRESSION_RATIO')
  else:require(info.file_size==0,'ARCHIVE_INVALID_COMPRESSED_SIZE')
 require(z.testzip() is None,'ARCHIVE_CRC_FAILURE')
 return seen

def native_elf(data,machine):
 require(len(data)>=4096 and data[:6]==b'\x7fELF\x02\x01','NATIVE_NOT_ELF64_LE')
 e_type,e_machine=struct.unpack_from('<HH',data,16)
 require(e_type==3 and e_machine==machine,'NATIVE_WRONG_MACHINE_OR_TYPE')
 phoff=struct.unpack_from('<Q',data,32)[0]
 entsize,number=struct.unpack_from('<HH',data,54)
 require(56<=entsize<=256 and 1<=number<=512 and phoff>=64 and phoff+entsize*number<=len(data),
         'NATIVE_PROGRAM_HEADERS_INVALID')
 load=[]
 for i in range(number):
  pos=phoff+entsize*i
  if struct.unpack_from('<I',data,pos)[0]!=1:continue
  offset,vaddr=struct.unpack_from('<QQ',data,pos+8)
  align=struct.unpack_from('<Q',data,pos+48)[0]
  require(align>=16384 and align&(align-1)==0 and offset%align==vaddr%align,
          'NATIVE_PT_LOAD_NOT_16K_COMPATIBLE')
  load.append(align)
 require(bool(load),'NATIVE_PT_LOAD_ABSENT')
 return {'sha256':sha(data),'size':len(data),'elf_machine':machine,'min_load_alignment':min(load)}

def audit_source(root):
 matched=[]
 for path,pin in SOURCE_PINS.items():
  file=root/path
  require(file.is_file() and not file.is_symlink(),'SOURCE_MISSING_OR_LINKED')
  require(blob(file.read_bytes())==pin,'SOURCE_GIT_BLOB_DRIFT_'+path.replace('/','_'))
  matched.append(path)
 app=(root/'app/XDM.Android/app/build.gradle.kts').read_text()
 x86=(root/'.github/workflows/xgo-x86-native-media.yml').read_text()
 android=(root/'.github/workflows/android.yml').read_text()
 cache=(root/'scripts/xgo_verified_native_artifact.py').read_text()
 pair=(root/'scripts/xgo_hf16_apk_pair.py').read_text()
 x86_script=(root/'scripts/xgo_x86_native_media.py').read_text()
 ff=read_json((root/'app/XDM.Android/media-ffmpeg/runtime/ffmpeg-runtime.json').read_bytes())
 ar=read_json((root/'app/XDM.Android/transfer-aria2/runtime/aria2-runtime.json').read_bytes())
 require('abiFilters += setOf("arm64-v8a")' in app,'PRODUCTION_ABI_DRIFT')
 require('types: [labeled]' in x86 and 'xgo-x86-native-media' in x86 and
         "github.event.pull_request.head.repo.full_name == github.repository" in x86 and
         'XGO_X86_MEDIA_OPT_IN' in x86,'X86_NO_OPT_IN_BOUNDARY')
 require('  signed-release:' in android and 'android-v*' in android and
         '--require-source-build' in android and '--require-16kb-alignment' in android,
         'ARM64_SOURCE_RELEASE_POLICY_DRIFT')
 require('CI_TEST_ONLY_NEVER_RELEASE' in cache and 'NATIVE' in cache and
         "ABI='x86_64'" in cache and 'check_bundle(' in cache,
         'X86_CACHE_PROVENANCE_GUARD_DRIFT')
 require('ensure_elf_16k_arm64' in pair and 'SHA256SUMS' in pair and
         'BUILT_ONLY_NO_DEVICE_TESTS' in pair,'ARM64_APK_PAIR_SOURCE_GUARD_DRIFT')
 require('release_eligible' in x86_script and 'False' in x86_script,
         'X86_DEBUG_RELEASE_BOUNDARY_DRIFT')
 require(ff.get('abi')=='arm64-v8a' and ff.get('elfMachine')==183 and
         ff.get('ndkVersion')==NDK and ff.get('requiredLoadAlignment')==16384 and
         ff.get('gplEnabled') is False and ff.get('nonfreeEnabled') is False,
         'ARM64_FFMPEG_MANIFEST_POLICY_DRIFT')
 require(ar.get('abi')=='arm64-v8a' and ar.get('elfMachine')==183 and
         ar.get('ndkVersion')==NDK and ar.get('buildProfile')=='android-arm64-source-v1',
         'ARM64_ARIA2_MANIFEST_POLICY_DRIFT')
 return {'source_file_pins_checked':len(matched),'production_abi':'arm64-v8a',
         'x86_mode':'CI_TEST_ONLY_NEVER_RELEASE','android_ndk':NDK}

def _read_zip(path):
 require(path.is_file() and not path.is_symlink(),'INPUT_NOT_REGULAR_FILE')
 require(0<path.stat().st_size<=MAX_ARCHIVE,'INPUT_SIZE_INVALID')
 try:return zipfile.ZipFile(path)
 except (OSError,zipfile.BadZipFile):raise Refused('MP12_P02_REFUSED_ZIP_INVALID') from None

def audit_arm64_pair(folder,head):
 require(folder.is_dir() and not folder.is_symlink(),'ARM64_PAIR_DIRECTORY_MISSING')
 required={'app-debug.apk','app-debug-androidTest.apk','SHA256SUMS','APK_PAIR_RECEIPT.json'}
 require({p.name for p in folder.iterdir()}==required,'ARM64_PAIR_INVENTORY_DRIFT')
 receipt=read_json(read_checked(folder/'APK_PAIR_RECEIPT.json',100000))
 for k,v in {'schema':1,'result':'BUILT_ONLY_NO_DEVICE_TESTS','commit_sha':head,
             'github_repository':REPO,'artifact_name':'xdm-android-physical-arm64-apk-pair',
             'app_package':'com.mikeyphw.xdm.android.debug',
             'test_package':'com.mikeyphw.xdm.android.debug.test',
             'target_package':'com.mikeyphw.xdm.android.debug',
             'instrumentation_runner':'androidx.test.runner.AndroidJUnitRunner',
             'abi':'arm64-v8a','jni_elf':'EM_AARCH64','jni_min_pt_load_alignment':16384}.items():
  require(receipt.get(k)==v,'ARM64_PAIR_RECEIPT_'+k.upper())
 require(bool(RUNID.fullmatch(str(receipt.get('github_run_id','')))),'ARM64_RUN_ID_INVALID')
 apks=receipt.get('apks')
 require(isinstance(apks,list) and len(apks)==2 and all(isinstance(x,dict) for x in apks),
         'ARM64_APK_RECEIPT_MISSING')
 names=['app-debug.apk','app-debug-androidTest.apk']
 receipts={}
 for i,name in enumerate(names):
  entry=apks[i]
  require(entry.get('file')==name and isinstance(entry.get('size'),int) and
          bool(SHA64.fullmatch(str(entry.get('sha256','')))), 'ARM64_APK_DESCRIPTOR')
  data=read_checked(folder/name)
  require(entry['size']==len(data) and entry['sha256']==sha(data),'ARM64_APK_DIGEST_MISMATCH')
  receipts[name]={'sha256':sha(data),'size':len(data)}
 sums=read_checked(folder/'SHA256SUMS',1024).decode('ascii')
 require(sums==''.join(receipts[x]['sha256']+'  '+x+'\n' for x in names),
         'ARM64_CHECKSUM_FILE_MISMATCH')
 with _read_zip(folder/'app-debug.apk') as z:
  listing=validate_archive(z,allow_directories=True)
  require('classes.dex' in listing,'ARM64_APP_DEX_MISSING')
  native={n for n in listing if n.startswith('lib/') and n.endswith('.so')}
  require(bool(native) and all(n.startswith('lib/arm64-v8a/') for n in native),
          'ARM64_APK_CROSS_ABI_NATIVE')
  checks={}
  for name in ARM_LIBS:
   part='lib/arm64-v8a/'+name
   require(part in listing,'ARM64_REQUIRED_NATIVE_MISSING_'+name)
   checks[name]=native_elf(z.read(part),183)
 with _read_zip(folder/'app-debug-androidTest.apk') as z:
  listing=validate_archive(z,allow_directories=True)
  require('classes.dex' in listing,'ARM64_TEST_DEX_MISSING')
 return {'artifact_source_sha':head,'apk_sha256':receipts['app-debug.apk']['sha256'],
         'test_apk_sha256':receipts['app-debug-androidTest.apk']['sha256'],
         'jni_libraries_checked':checks,'artifact_built_only':True,
         'physical_arm64_runtime_qualified':False,'signed_release_qualified':False}

def fingerprint(source_bytes):
 require(set(source_bytes)==set(X86_SOURCE_FILES),'X86_SOURCE_INPUT_INVENTORY')
 sources={name:sha(source_bytes[name]) for name in X86_SOURCE_FILES}
 inputs={'abi':'x86_64','ndk':NDK,'recipe_revision':2,'sources':sources}
 key=sha(json.dumps(inputs,sort_keys=True,separators=(',',':')).encode())
 return key,inputs

def audit_x86_native_bundle(bundle,head,key,inputs):
 with _read_zip(bundle) as z:
  listing=validate_archive(z)
  expected={'manifest.json'}|{'files/'+x for x in X86_FILES}
  require(listing==expected,'X86_BUNDLE_INVENTORY_DRIFT')
  receipt=read_json(z.read('manifest.json'))
  wanted={'schema_version':1,'purpose':'CI_TEST_ONLY_NEVER_RELEASE','abi':'x86_64',
          'ndk':NDK,'source_fingerprint':key,'inputs':inputs,'head_sha':head,
          'repo':REPO,'workflow_path':'.github/workflows/xgo-x86-native-media.yml',
          'qualified_physical_arm64':False,'qualified_licensed_1dm':False}
  for label,value in wanted.items():require(receipt.get(label)==value,'X86_PROVENANCE_MISMATCH_'+label.upper())
  require(bool(RUNID.fullmatch(str(receipt.get('run_id','')))),'X86_RUN_ID_INVALID')
  files=receipt.get('files')
  require(isinstance(files,dict) and set(files)==set(X86_FILES),'X86_FILE_RECEIPT_INVENTORY')
  binaries={}
  for path in X86_FILES:
   raw=z.read('files/'+path)
   item=files[path]
   require(isinstance(item,dict) and item.get('size')==len(raw) and
           bool(SHA64.fullmatch(str(item.get('sha256','')))) and item['sha256']==sha(raw),
           'X86_NATIVE_DIGEST_MISMATCH')
   if path.endswith('.so'):
    binaries[path.rsplit('/',1)[-1]]=native_elf(raw,62)
   elif path.endswith('lock.json'):
    lock=read_json(raw)
    require(lock.get('abi')=='x86_64' and lock.get('ndkVersion')==NDK,
            'X86_SOURCE_LOCK_ABI_NDK_MISMATCH')
    if path.endswith('aria2-runtime.lock.json'):
     require(lock.get('sourceKind')=='source-build' and
             lock.get('buildProfile')=='android-x86_64-source-v1',
             'X86_ARIA2_SOURCE_BUILD_NOT_VERIFIED')
   else:require(len(raw)>20,'X86_LICENSE_OR_SOURCE_NOTICE_EMPTY')
  require(set(binaries)=={'libxdm_ffmpeg.so','libxdm_ffprobe.so','libaria2c.so'},
          'X86_NATIVE_SET_INCOMPLETE')
 return {'artifact_source_sha':head,'source_fingerprint':key,
         'binaries_checked':binaries,'test_only':True,'release_eligible':False,
         'x86_api36_runtime_qualified':False,'physical_arm64_runtime_qualified':False}

def checkout_head_guard(root,head):
 # Report receipts are attacker-editable files. The claimed source SHA must
 # also be the actual Git checkout, not merely a value echoed by two inputs.
 require(bool(SHA40.fullmatch(head)),'EXPECTED_SHA_INVALID')
 require(root.is_dir() and not root.is_symlink(),'CHECKOUT_ROOT_INVALID')
 def git(*args):
  try:
   result=subprocess.run(['git','-C',str(root),*args],capture_output=True,
                         text=True,timeout=15,check=False)
  except (OSError,subprocess.TimeoutExpired):
   raise Refused('MP12_P02_REFUSED_CHECKOUT_GIT_UNAVAILABLE') from None
  require(result.returncode==0 and 0<len(result.stdout)<4096,
          'CHECKOUT_GIT_FAILED')
  return result.stdout.strip()
 top=git('rev-parse','--show-toplevel')
 require(Path(top).resolve()==root.resolve(),'CHECKOUT_TOPLEVEL_MISMATCH')
 actual=git('rev-parse','--verify','HEAD')
 require(bool(SHA40.fullmatch(actual)) and actual==head,'CHECKOUT_HEAD_MISMATCH')
 return actual

def evidence(root,head,armdir,x86bundle):
 checkout_head_guard(root,head)
 guard=audit_source(root)
 src={name:read_checked(root/name,3_000_000) for name in X86_SOURCE_FILES}
 key,inputs=fingerprint(src)
 arm=audit_arm64_pair(armdir,head)
 x86=audit_x86_native_bundle(x86bundle,head,key,inputs)
 require(set(arm['jni_libraries_checked']).issuperset(set(ARM_LIBS)),
         'ARM64_NATIVE_INVENTORY_INCOMPLETE')
 return {'schema':'xgo-mp12-p02-cross-abi-provenance-v1','repository':REPO,
         'branch':BRANCH,'exact_head_sha':head,'source_policy':guard,
         'arm64_build_provenance':arm,'x86_test_native_provenance':x86,
         'cross_arch_sources_compared':True,'cross_arch_runtime_parity_proven':False,
         'physical_arm64_qualified':False,'signed_android_qualified':False,
         'production_release_eligible':False,'go_cutover_authorized':False}

def write_report(path,report):
 # Android Termux builds of Python need not expose os.link(). Use an atomic
 # no-clobber CREATE (O_EXCL), not rename/replace, so existing receipts or
 # symlinks can never be overwritten. Synchronous write failures clean up.
 # This is a small private receipt, not an atomic rename publication protocol.
 require(not path.is_symlink() and not path.exists(),'OUTPUT_EXISTS_OR_SYMLINK')
 require(not path.parent.is_symlink(),'OUTPUT_PARENT_SYMLINK')
 path.parent.mkdir(parents=True,exist_ok=True)
 require(path.parent.is_dir() and not path.parent.is_symlink(),'OUTPUT_PARENT_SYMLINK')
 data=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
 require(len(data)<200000,'REPORT_TOO_LARGE')
 flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0)
 try:
  fd=os.open(path,flags,0o600)
 except FileExistsError:raise Refused('MP12_P02_REFUSED_OUTPUT_RACE') from None
 # Keep the identity of the created file, so an exception never unlinks a
 # different file if a concurrent process swaps the directory entry.
 created=os.fstat(fd)
 try:
  with os.fdopen(fd,'wb') as stream:
   stream.write(data)
   stream.flush()
   os.fsync(stream.fileno())
 except BaseException:
  try:os.close(fd)
  except OSError:pass
  try:
   current=os.lstat(path)
   if (current.st_dev,current.st_ino)==(created.st_dev,created.st_ino):
    path.unlink()
  except FileNotFoundError:pass
  raise

def main():
 p=argparse.ArgumentParser(description='MP12 P02 read-only cross-ABI source/native evidence audit')
 p.add_argument('mode',choices=('source-only','verify-pair'))
 p.add_argument('--repo',default='.')
 p.add_argument('--expected-head')
 p.add_argument('--arm64-pair-dir',type=Path)
 p.add_argument('--x86-bundle',type=Path)
 p.add_argument('--output',type=Path)
 args=p.parse_args();root=Path(args.repo).expanduser().resolve()
 if args.mode=='source-only':
  result=audit_source(root)
  print('MP12_P02_NATIVE_SOURCE_POLICY_GUARDS_PASS_'+str(result['source_file_pins_checked'])+'_PINS_NOT_RELEASE')
  return
 require(bool(args.expected_head and args.arm64_pair_dir and args.x86_bundle),
         'ARTIFACT_ARGUMENTS_REQUIRED')
 output=evidence(root,args.expected_head,args.arm64_pair_dir,args.x86_bundle)
 if args.output:write_report(args.output.expanduser(),output)
 print('MP12_P02_CROSS_ARCH_ARTIFACT_HASH_ELF_SOURCE_LOCKS_PASS_NOT_RELEASE')

if __name__=='__main__':
 try:main()
 except (Refused,OSError,zipfile.BadZipFile,struct.error,UnicodeError) as e:
  print(str(e) if isinstance(e,Refused) else 'MP12_P02_REFUSED_INPUT_OR_ARCHIVE_ERROR',file=sys.stderr)
  raise SystemExit(2)
