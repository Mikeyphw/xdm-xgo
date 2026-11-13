#!/usr/bin/env python3
"""MP12 P02: executable fixture and adversarial provenance regressions."""
from __future__ import annotations
import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
import importlib.util
from unittest import mock

SOURCE=Path(__file__).with_name('mp12_p02_provenance.py')
spec=importlib.util.spec_from_file_location('mp12_p02_provenance',SOURCE)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
HEAD='a'*40

def elf(machine=183,align=16384,typ=3,vt=0):
 data=bytearray(8192)
 data[:6]=b'\x7fELF\x02\x01'
 struct.pack_into('<HH',data,16,typ,machine)
 struct.pack_into('<Q',data,32,64)
 struct.pack_into('<HH',data,54,56,1)
 struct.pack_into('<I',data,64,1)
 struct.pack_into('<QQ',data,72,0,vt)
 struct.pack_into('<Q',data,112,align)
 return bytes(data)

def make_zip(path,files):
 with zipfile.ZipFile(path,'w',zipfile.ZIP_STORED) as z:
  for name,value in files.items():z.writestr(name,value)

def raw_json(o):return (json.dumps(o,sort_keys=True)+'\n').encode()

class CrossArch(unittest.TestCase):
 def setUp(self):
  temp=tempfile.TemporaryDirectory(prefix='mp12-p02-')
  self.addCleanup(temp.cleanup)
  self.root=Path(temp.name)
  self.pair=self.root/'pair';self.pair.mkdir()
  self.x86=self.root/'x86-native.zip'
  self.inputs={name:(name+' sample').encode() for name in m.X86_SOURCE_FILES}
  self.key,self.source=m.fingerprint(self.inputs)
  self.armfiles={'classes.dex':b'dex\n'*300}
  for name in m.ARM_LIBS:self.armfiles['lib/arm64-v8a/'+name]=elf()
  self.armtest={'classes.dex':b'dex\n'*300}
  self.generate_pair()
  self.generate_x86()

 def generate_pair(self):
  make_zip(self.pair/'app-debug.apk',self.armfiles)
  make_zip(self.pair/'app-debug-androidTest.apk',self.armtest)
  apks=[]
  for file in ('app-debug.apk','app-debug-androidTest.apk'):
   data=(self.pair/file).read_bytes();apks.append({'file':file,'size':len(data),'sha256':m.sha(data)})
  receipt={'schema':1,'result':'BUILT_ONLY_NO_DEVICE_TESTS','commit_sha':HEAD,
    'github_repository':m.REPO,'github_run_id':'123456','artifact_name':'xdm-android-physical-arm64-apk-pair',
    'app_package':'com.mikeyphw.xdm.android.debug',
    'test_package':'com.mikeyphw.xdm.android.debug.test',
    'target_package':'com.mikeyphw.xdm.android.debug',
    'instrumentation_runner':'androidx.test.runner.AndroidJUnitRunner',
    'abi':'arm64-v8a','jni_elf':'EM_AARCH64','jni_min_pt_load_alignment':16384,
    'apks':apks}
  (self.pair/'APK_PAIR_RECEIPT.json').write_bytes(raw_json(receipt))
  (self.pair/'SHA256SUMS').write_text(''.join(x['sha256']+'  '+x['file']+'\n' for x in apks))

 def generate_x86(self):
  self.native={}
  for path in m.X86_FILES:
   if path.endswith('.so'):self.native[path]=elf(62)
   elif path.endswith('lock.json'):
    lock={'abi':'x86_64','ndkVersion':m.NDK}
    if path.endswith('aria2-runtime.lock.json'):
     lock.update(sourceKind='source-build',buildProfile='android-x86_64-source-v1')
    self.native[path]=raw_json(lock)
   else:self.native[path]=b'Upstream LGPL GPL Apache LICENSE notice retained\n'
  manifest={'schema_version':1,'purpose':'CI_TEST_ONLY_NEVER_RELEASE','abi':'x86_64',
       'ndk':m.NDK,'source_fingerprint':self.key,'inputs':self.source,
       'head_sha':HEAD,'repo':m.REPO,'workflow_path':'.github/workflows/xgo-x86-native-media.yml',
       'qualified_physical_arm64':False,'qualified_licensed_1dm':False,'run_id':'7654321',
       'files':{name:{'size':len(b),'sha256':m.sha(b)} for name,b in self.native.items()}}
  self.x86_receipt=manifest
  self.make_x86_zip()

 def make_x86_zip(self):
  data={'manifest.json':raw_json(self.x86_receipt)}
  data.update({'files/'+path:raw for path,raw in self.native.items()})
  make_zip(self.x86,data)

 def refuse_arm(self,code=None):
  with self.assertRaises(m.Refused) as exc:m.audit_arm64_pair(self.pair,HEAD)
  if code:self.assertIn(code,str(exc.exception))
 def refuse_x86(self,code=None):
  with self.assertRaises(m.Refused) as exc:
   m.audit_x86_native_bundle(self.x86,HEAD,self.key,self.source)
  if code:self.assertIn(code,str(exc.exception))

 def test_valid_pair_and_bundle_are_test_only(self):
  arm=m.audit_arm64_pair(self.pair,HEAD)
  x86=m.audit_x86_native_bundle(self.x86,HEAD,self.key,self.source)
  self.assertEqual(len(arm['jni_libraries_checked']),4)
  self.assertEqual(len(x86['binaries_checked']),3)
  self.assertFalse(arm['signed_release_qualified'])
  self.assertFalse(x86['release_eligible'])
  self.assertFalse(x86['x86_api36_runtime_qualified'])

 def test_source_fingerprint_separates_abi_and_rejects_missing(self):
  self.assertEqual(self.source['abi'],'x86_64')
  self.assertEqual(self.source['ndk'],m.NDK)
  self.assertNotEqual(self.key,m.sha(b'different'))
  with self.assertRaises(m.Refused):m.fingerprint({'missing':b'no'})
  with self.assertRaises(m.Refused):m.audit_x86_native_bundle(self.x86,HEAD,'f'*64,self.source)

 def test_arm64_sha_receipt_mismatch(self):
  r=json.loads((self.pair/'APK_PAIR_RECEIPT.json').read_text());r['apks'][0]['sha256']='e'*64
  (self.pair/'APK_PAIR_RECEIPT.json').write_bytes(raw_json(r));self.refuse_arm('ARM64_APK_DIGEST_MISMATCH')
 def test_arm64_stale_commit_refused(self):
  r=json.loads((self.pair/'APK_PAIR_RECEIPT.json').read_text());r['commit_sha']='b'*40
  (self.pair/'APK_PAIR_RECEIPT.json').write_bytes(raw_json(r));self.refuse_arm('ARM64_PAIR_RECEIPT_COMMIT_SHA')
 def test_arm64_forged_signed_flag_has_no_effect(self):
  r=json.loads((self.pair/'APK_PAIR_RECEIPT.json').read_text());r['signed_release_qualified']=True
  (self.pair/'APK_PAIR_RECEIPT.json').write_bytes(raw_json(r))
  self.assertFalse(m.audit_arm64_pair(self.pair,HEAD)['signed_release_qualified'])
 def test_arm64_wrong_machine(self):
  self.armfiles['lib/arm64-v8a/libxdmcore.so']=elf(62);self.generate_pair();self.refuse_arm('NATIVE_WRONG_MACHINE')
 def test_arm64_wrong_alignment(self):
  self.armfiles['lib/arm64-v8a/libxdmcore.so']=elf(183,4096);self.generate_pair();self.refuse_arm('NATIVE_PT_LOAD')
 def test_arm64_missing_native(self):
  self.armfiles.pop('lib/arm64-v8a/libaria2c.so');self.generate_pair();self.refuse_arm('ARM64_REQUIRED_NATIVE_MISSING')
 def test_arm64_mixed_architecture(self):
  self.armfiles['lib/x86_64/libfake.so']=elf(62);self.generate_pair();self.refuse_arm('ARM64_APK_CROSS_ABI_NATIVE')
 def test_arm64_corrupt_checksum_inventory(self):
  (self.pair/'SHA256SUMS').write_text('wrong\n');self.refuse_arm('ARM64_CHECKSUM_FILE_MISMATCH')
 def test_arm64_missing_test_dex(self):
  self.armtest={'resources.arsc':b'A'*500};self.generate_pair();self.refuse_arm('ARM64_TEST_DEX_MISSING')
 def test_android_apk_canonical_directory_entries_allowed(self):
  app=self.pair/'app-debug.apk'
  with zipfile.ZipFile(app,'w',zipfile.ZIP_STORED) as z:
   z.writestr('lib/',b'')
   z.writestr('lib/arm64-v8a/',b'')
   for name,value in self.armfiles.items():z.writestr(name,value)
  self.refresh_arm64_hashes()
  self.assertEqual(len(m.audit_arm64_pair(self.pair,HEAD)['jni_libraries_checked']),4)
 def test_android_apk_symlink_member_rejected(self):
  app=self.pair/'app-debug.apk'
  info=zipfile.ZipInfo('lib/arm64-v8a/untrusted.so')
  info.create_system=3
  info.external_attr=(0o120777<<16)
  with zipfile.ZipFile(app,'a') as z:z.writestr(info,b'../escape')
  self.refresh_arm64_hashes();self.refuse_arm('ARCHIVE_SPECIAL_FILE')

 def test_arm64_path_duplication_rejected(self):
  app=self.pair/'app-debug.apk'
  with zipfile.ZipFile(app,'a') as z:z.writestr('classes.dex',b'override')
  # Reset SHA receipts to isolate archive inventory verification.
  self.refresh_arm64_hashes();self.refuse_arm('ARCHIVE_DUPLICATE_MEMBER')
 def refresh_arm64_hashes(self):
  r=json.loads((self.pair/'APK_PAIR_RECEIPT.json').read_text());apks=[]
  for file in ('app-debug.apk','app-debug-androidTest.apk'):
   data=(self.pair/file).read_bytes();apks.append({'file':file,'sha256':m.sha(data),'size':len(data)})
  r['apks']=apks;(self.pair/'APK_PAIR_RECEIPT.json').write_bytes(raw_json(r))
  (self.pair/'SHA256SUMS').write_text(''.join(x['sha256']+'  '+x['file']+'\n' for x in apks))

 def test_x86_wrong_elf_machine(self):
  name='app/XDM.Android/media-ffmpeg/src/main/jniLibs/x86_64/libxdm_ffmpeg.so'
  self.native[name]=elf(183);self.update_x86_hash(name);self.refuse_x86('NATIVE_WRONG_MACHINE')
 def update_x86_hash(self,name):
  self.x86_receipt['files'][name]={'size':len(self.native[name]),'sha256':m.sha(self.native[name])}
  self.make_x86_zip()
 def test_x86_lock_wrong_abi(self):
  name='app/XDM.Android/transfer-aria2/runtime/aria2-runtime.lock.json'
  self.native[name]=raw_json({'abi':'arm64-v8a','ndkVersion':m.NDK,'sourceKind':'source-build','buildProfile':'android-x86_64-source-v1'})
  self.update_x86_hash(name);self.refuse_x86('X86_SOURCE_LOCK_ABI')
 def test_x86_lock_prebuilt_rejected(self):
  name='app/XDM.Android/transfer-aria2/runtime/aria2-runtime.lock.json'
  self.native[name]=raw_json({'abi':'x86_64','ndkVersion':m.NDK,'sourceKind':'compatibility-prebuilt','buildProfile':'android-x86_64-source-v1'})
  self.update_x86_hash(name);self.refuse_x86('X86_ARIA2_SOURCE_BUILD')
 def test_x86_missing_license(self):
  name='app/XDM.Android/media-ffmpeg/runtime/licenses/FFmpeg-LGPL-2.1.txt'
  del self.native[name];del self.x86_receipt['files'][name];self.make_x86_zip();self.refuse_x86('X86_BUNDLE_INVENTORY_DRIFT')
 def test_x86_digest_forgery(self):
  name='app/XDM.Android/transfer-aria2/src/main/jniLibs/x86_64/libaria2c.so'
  self.native[name]=elf(62,4096);self.make_x86_zip();self.refuse_x86('X86_NATIVE_DIGEST_MISMATCH')
 def test_x86_source_fingerprint_forgery(self):
  self.x86_receipt['source_fingerprint']='e'*64;self.make_x86_zip();self.refuse_x86('X86_PROVENANCE_MISMATCH')
 def test_x86_stale_commit_refused(self):
  self.x86_receipt['head_sha']='b'*40;self.make_x86_zip();self.refuse_x86('X86_PROVENANCE_MISMATCH_HEAD')
 def test_x86_release_purpose_refused(self):
  self.x86_receipt['purpose']='PRODUCTION_RELEASE';self.make_x86_zip();self.refuse_x86('X86_PROVENANCE_MISMATCH_PURPOSE')
 def test_x86_native_16k_required(self):
  name='app/XDM.Android/transfer-aria2/src/main/jniLibs/x86_64/libaria2c.so'
  self.native[name]=elf(62,4096);self.update_x86_hash(name);self.refuse_x86('NATIVE_PT_LOAD')
 def test_zip_traversal_refused(self):
  self.native['../escape.so']=b'bad';self.make_x86_zip();self.refuse_x86('ARCHIVE_PATH_UNSAFE')
 def test_duplicate_json_keys_refused(self):
  with self.assertRaises(m.Refused):m.read_json(b'{"x":1,"x":2}')
 def test_output_fail_closed_on_existing_path(self):
  o=self.root/'receipt.json';o.write_text('existing')
  with self.assertRaises(m.Refused):m.write_report(o,{'release_eligible':False})
 def test_output_sanitized_and_private(self):
  o=self.root/'receipt.json';m.write_report(o,{'release_eligible':False,'source_sha':HEAD})
  self.assertEqual(o.stat().st_mode & 0o777,0o600)
  self.assertNotIn('token',o.read_text())
 def test_report_writer_does_not_require_os_link_on_termux(self):
  o=self.root/'termux-receipt.json'
  with mock.patch.object(m.os,'link',None,create=True):
   m.write_report(o,{'release_eligible':False,'source_sha':HEAD})
  self.assertEqual(json.loads(o.read_text())['source_sha'],HEAD)
 def test_report_writer_refuses_preexisting_symlink(self):
  target=self.root/'target.json';target.write_text('must not change')
  o=self.root/'receipt.json';o.symlink_to(target)
  with self.assertRaisesRegex(m.Refused,'OUTPUT_EXISTS_OR_SYMLINK'):
   m.write_report(o,{'release_eligible':False})
  self.assertEqual(target.read_text(),'must not change')
 def test_report_writer_refuses_symlink_parent(self):
  target=self.root/'real';target.mkdir()
  link=self.root/'linked';link.symlink_to(target,target_is_directory=True)
  with self.assertRaisesRegex(m.Refused,'OUTPUT_PARENT_SYMLINK'):
   m.write_report(link/'receipt.json',{'release_eligible':False})
  self.assertFalse((target/'receipt.json').exists())
 def test_report_writer_refuses_exclusive_creation_race(self):
  o=self.root/'receipt.json'
  with mock.patch.object(m.os,'open',side_effect=FileExistsError):
   with self.assertRaisesRegex(m.Refused,'OUTPUT_RACE'):
    m.write_report(o,{'release_eligible':False})
  self.assertFalse(o.exists())
 def test_report_writer_removes_partial_file_after_io_failure(self):
  o=self.root/'receipt.json'
  with mock.patch.object(m.os,'fsync',side_effect=OSError('simulated fsync failure')):
   with self.assertRaises(OSError):
    m.write_report(o,{'release_eligible':False})
  self.assertFalse(o.exists())
 def test_report_writer_rejects_large_receipt_without_writing(self):
  o=self.root/'receipt.json'
  with self.assertRaisesRegex(m.Refused,'REPORT_TOO_LARGE'):
   m.write_report(o,{'long_payload':'x'*200001})
  self.assertFalse(o.exists())

if __name__=='__main__':unittest.main(verbosity=2)
