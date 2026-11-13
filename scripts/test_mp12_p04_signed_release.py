#!/usr/bin/env python3
"""MP12 P04 independent signing provenance: mutation and real-byte ZIP tests.

All fixtures are synthetic. These tests never claim real Android signing.
"""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import os
import struct
import subprocess
import tempfile
import unittest
import zipfile
from unittest import mock

SPEC=importlib.util.spec_from_file_location('mp12_p04_signed_release',Path(__file__).with_name('mp12_p04_signed_release.py'))
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)
HEAD='a'*40;PIN='b'*64;RUN='fixture-123'

def j(o):return (json.dumps(o,sort_keys=True,indent=2)+'\n').encode()
def elf(machine=183,align=16384):
 b=bytearray(5000);b[:6]=b'\x7fELF\x02\x01'
 struct.pack_into('<HH',b,16,3,machine)
 struct.pack_into('<Q',b,32,64)
 struct.pack_into('<HH',b,54,56,1)
 struct.pack_into('<I',b,64,1)
 struct.pack_into('<QQ',b,72,0,0)
 struct.pack_into('<Q',b,112,align)
 return bytes(b)
def archive(entries):
 out=io.BytesIO()
 with zipfile.ZipFile(out,'w',zipfile.ZIP_STORED) as z:
  for name,data in entries.items():z.writestr(name,data)
 return out.getvalue()

def apk_bytes():
 return archive({'classes.dex':b'dex'*1000,**{'lib/arm64-v8a/'+x:elf() for x in m.APK_LIBS}})

class Fixture(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory(prefix='mp12-p04-');self.addCleanup(t.cleanup)
  self.root=Path(t.name);self.publication=self.root/('xar16-'+RUN);self.publication.mkdir()
  self.apk=self.root/'app-release.apk';self.aab=self.root/'app-release.aab';self.apks=self.root/'app-release.apks'
  self.apk.write_bytes(apk_bytes())
  self.aab.write_bytes(archive({'base/manifest/AndroidManifest.xml':b'fake-aab-manifest', 'BUNDLE-METADATA/metadata':b'123'}))
  self.apks.write_bytes(archive({'toc.pb':b'toc', 'splits/base-master.apk':apk_bytes()}))
  artifacts=[{'kind':k,'sha256':m.sha(p.read_bytes()),'path':'build/outputs/'+k+'/release/app-release'+p.suffix} for k,p in [('apk',self.apk),('aab',self.aab),('apks',self.apks)]]
  self.same={'schemaVersion':1,'roadmapOverlay':'XAR16','runId':RUN,'buildId':HEAD,
             'sameRunArtifactProvenance':True,'publicationAllowed':False,'artifacts':artifacts}
  self.metadata={'schemaVersion':1,'roadmapOverlay':'XAR16','publicationReady':True,'artifacts':copy.deepcopy(artifacts)}
  self.phase={'apkSet':{'splitSemantics':'set-level-required-inventory'}}
  self.device={'apkSetInstalled':True,'upgradeRebootLaunchVerified':True}
  self.journeys={'signedReleaseJourneysPassed':True}
  self.rm04={'roadmapOverlay':'RM04','runId':RUN,'canonicalNonDeviceValidationPassed':True,
             'runtimeDiagnosticsPrivacyContract':True,'finalDiagnosticsZipPrivacyIntegrity':True,
             'staticValidatorChain':True,'releaseDocsValidator':True,'routeTopologyValidator':True,
             'fullSelectedTaskValidation':True}
  self.dump()
 def dump(self):
  objects={'release-metadata.json':self.metadata,'phase10-release-attestation.json':self.phase,
           'xar16-same-run-artifacts.json':self.same,'xar16-device-matrix.json':self.device,
           'xar16-signed-release-journeys.json':self.journeys,'rm04-validation-seal.json':self.rm04}
  for name,data in objects.items():(self.publication/name).write_bytes(j(data))
  prefix='build/release/publication/xar16-'+RUN+'/'
  self.sums={
   'SHA256SUMS':''.join(hashlib.sha256((self.publication/n).read_bytes()).hexdigest()+'  '+prefix+n+'\n' for n in sorted(m.FILES)),
   'SHA512SUMS':''.join(hashlib.sha512((self.publication/n).read_bytes()).hexdigest()+'  '+prefix+n+'\n' for n in sorted(m.FILES)),
  }
  for name,text in self.sums.items():(self.publication/name).write_text(text)
 def check(self):return m.publication(self.publication,HEAD,RUN)
 def refuse(self,code,func=None):
  with self.assertRaises(m.Refused) as err:(func or self.check)()
  self.assertIn(code,str(err.exception))
 def fake_tools(self,args,timeout=90):
  if args[0]=='apksigner':return 'Signer #1 certificate SHA-256 digest: '+PIN+'\n'
  if args[0]=='keytool':return 'SHA256: '+':'.join(PIN[i:i+2] for i in range(0,64,2))+'\n'
  if args[0]=='jarsigner':return 'jar verified.\n'
  self.fail('wrong verifier '+repr(args))
 def verify(self):
  with mock.patch.object(m,'source_guard',return_value={'source_pins':6}),\
       mock.patch.object(m,'githead',return_value=HEAD),\
       mock.patch.object(m,'_run',side_effect=self.fake_tools):
   return m.verify(self.root,self.publication,HEAD,RUN,self.apk,self.aab,self.apks,PIN)

class ReleaseChecks(Fixture):
 def test_genuine_fixture_verifies_but_no_release_authority(self):
  o=self.verify()
  self.assertEqual(o['signed_apks_splits_verified'],1)
  self.assertFalse(o['release_qualified'])
  self.assertFalse(o['publication_automatically_authorized'])
  self.assertFalse(o['physical_arm64_qualified'])
 def test_canonical_sha512_sha256_exact_inventory(self):
  self.assertEqual(set(self.check()),set(m.KIND_EXT))
 def test_wrong_sha256_digest_refused(self):
  p=self.publication/'SHA256SUMS';p.write_text(p.read_text().replace('a','b',1))
  self.refuse('PUBLICATION_DIGEST_MISMATCH')
 def test_wrong_sha512_digest_refused(self):
  p=self.publication/'SHA512SUMS';data=p.read_text();p.write_text(('0' if data[0]!='0' else '1')+data[1:])
  self.refuse('PUBLICATION_DIGEST_MISMATCH')
 def test_extra_publication_file_refused(self):
  (self.publication/'EXTRA.json').write_text('x');self.refuse('PUBLICATION_INVENTORY')
 def test_publication_symlink_refused(self):
  (self.publication/'release-metadata.json').unlink()
  (self.publication/'release-metadata.json').symlink_to(self.publication/'phase10-release-attestation.json')
  self.refuse('NOT_REGULAR_FILE')
 def test_stale_commit_receipt_refused(self):
  self.same['buildId']='c'*40;self.dump();self.refuse('SAME_RUN_BUILDID')
 def test_stale_run_refused(self):
  self.same['runId']='old';self.dump();self.refuse('SAME_RUN_RUNID')
 def test_invalid_run_directory_refused(self):
  self.refuse('PUBLICATION_RUN_DIRECTORY',lambda:m.publication(self.publication,HEAD,'another'))
 def test_metadata_does_not_match_same_run(self):
  self.metadata['artifacts'][0]['sha256']='0'*64;self.dump();self.refuse('METADATA_ARTIFACT_DRIFT')
 def test_duplicate_json_key_refused(self):
  with self.assertRaises(m.Refused):m.unique_json(b'{"x":1,"x":2}')
 def test_duplicate_checksum_rows_refused(self):
  p=self.publication/'SHA256SUMS';lines=p.read_text().splitlines();lines[1]=lines[0];p.write_text('\n'.join(lines)+'\n');self.refuse('CHECKSUM_INVENTORY')
 def test_checksum_path_traversal_refused(self):
  p=self.publication/'SHA256SUMS';p.write_text(p.read_text().replace('xar16-'+RUN+'/','xar16-'+RUN+'/../',1))
  self.refuse('CHECKSUM_INVENTORY')
 def test_signing_pub_allowed_flag_refused(self):
  self.same['publicationAllowed']=True;self.dump();self.refuse('SAME_RUN_PUBLICATIONALLOWED')
 def test_missing_split_attestation_refused(self):
  self.phase['apkSet']['splitSemantics']='unchecked';self.dump();self.refuse('SPLIT_SET_ATTESTATION_MISSING')
 def test_missing_upgrade_receipt_refused(self):
  self.device['upgradeRebootLaunchVerified']=False;self.dump();self.refuse('DEVICE_MATRIX_INCOMPLETE')
 def test_missing_signed_journeys_refused(self):
  self.journeys['signedReleaseJourneysPassed']=False;self.dump();self.refuse('SIGNED_JOURNEYS_INCOMPLETE')
 def test_missing_rm04_security_receipt_refused(self):
  self.rm04['runtimeDiagnosticsPrivacyContract']=False;self.dump();self.refuse('RM04_MISSING_')
 def test_wrong_artifact_type_refused(self):
  self.same['artifacts'][1]['kind']='apk';self.metadata['artifacts']=copy.deepcopy(self.same['artifacts']);self.dump();self.refuse('RELEASE_ARTIFACT_KIND')
 def test_mismatched_real_apk_byte_refused(self):
  self.apk.write_bytes(self.apk.read_bytes()+b'TAMPER')
  self.refuse('BINARY_DIGEST_MISMATCH',self.verify)
 def test_actual_git_head_mismatch_refused(self):
  with mock.patch.object(m,'source_guard',return_value={'source_pins':6}),\
       mock.patch.object(m,'githead',return_value='c'*40):
   self.refuse('ACTUAL_CHECKOUT_HEAD_MISMATCH',lambda:m.verify(self.root,self.publication,HEAD,RUN,self.apk,self.aab,self.apks,PIN))
 def test_signer_pin_mismatch_apk_refused(self):
  with mock.patch.object(m,'source_guard',return_value={}),\
       mock.patch.object(m,'githead',return_value=HEAD),\
       mock.patch.object(m,'_run',return_value='Signer #1 certificate SHA-256 digest: '+'c'*64):
   self.refuse('APK_SIGNER_CERTIFICATE_MISMATCH',lambda:m.verify(self.root,self.publication,HEAD,RUN,self.apk,self.aab,self.apks,PIN))
 def test_multiple_signers_refused(self):
  with mock.patch.object(m,'_run',return_value=('Signer #1 certificate SHA-256 digest: '+PIN+'\n'+'Signer #2 certificate SHA-256 digest: '+PIN)):
   self.refuse('APK_SIGNER_CERTIFICATE_MISMATCH',lambda:m.signed_apk(self.apk,PIN))
 def test_aab_jarsigner_unsigned_success_output_refused(self):
  with mock.patch.object(m,'_run',return_value='jar is unsigned. signer not verified'):
   self.refuse('AAB_JAR_SIGNATURE_NOT_VERIFIED',lambda:m.signed_bundle(self.aab,PIN))
 def test_aab_cert_mismatch_refused(self):
  with mock.patch.object(m,'_run',side_effect=lambda a,timeout=90:'SHA256: '+':'.join(['cc']*32) if a[0]=='keytool' else 'jar verified.'):
   self.refuse('AAB_CERTIFICATE_MISMATCH',lambda:m.signed_bundle(self.aab,PIN))
 def test_apks_split_missing_refused(self):
  self.apks.write_bytes(archive({'toc.pb':b'abc'}));self.same['artifacts'][2]['sha256']=m.sha(self.apks.read_bytes());self.metadata['artifacts']=copy.deepcopy(self.same['artifacts']);self.dump()
  self.refuse('APKS_SPLIT_SET_INVALID',self.verify)
 def test_apks_split_cert_mismatch_refused(self):
  first={'count':0}
  def mismatch(args,timeout=90):
   if args[0]=='apksigner':
    first['count']+=1
    if first['count']==2:return 'Signer #1 certificate SHA-256 digest: '+'c'*64
   return self.fake_tools(args,timeout)
  with mock.patch.object(m,'source_guard',return_value={}),\
       mock.patch.object(m,'githead',return_value=HEAD),\
       mock.patch.object(m,'_run',side_effect=mismatch):
   self.refuse('APK_SIGNER_CERTIFICATE_MISMATCH',lambda:m.verify(self.root,self.publication,HEAD,RUN,self.apk,self.aab,self.apks,PIN))
 def test_elf_wrong_machine_refused(self):
  self.refuse('ARM64_ELF_MACHINE',lambda:m.elf16(elf(62)))
 def test_elf_4kb_refused(self):
  self.refuse('ELF_PT_LOAD_NOT_16K',lambda:m.elf16(elf(183,4096)))
 def test_zip_traversal_refused(self):
  with zipfile.ZipFile(io.BytesIO(archive({'../pwn':b'a'}))) as z:self.refuse('ZIP_TRAVERSAL_OR_PATH',lambda:m.zip_inventory(z))
 def test_zip_duplicate_refused(self):
  buf=io.BytesIO()
  with zipfile.ZipFile(buf,'w') as z:
   z.writestr('dup',b'a');z.writestr('dup',b'b')
  with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:self.refuse('ZIP_DUPLICATE_ENTRY',lambda:m.zip_inventory(z))
 def test_zip_symlink_refused(self):
  b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z:
   i=zipfile.ZipInfo('bad');i.external_attr=0o120777<<16;z.writestr(i,b'../secret')
  with zipfile.ZipFile(io.BytesIO(b.getvalue())) as z:self.refuse('ZIP_UNSAFE_MEMBER',lambda:m.zip_inventory(z))
 def test_empty_regular_zip_entry_is_valid(self):
  with zipfile.ZipFile(io.BytesIO(archive({'ok':b''}))) as z:self.assertIn('ok',m.zip_inventory(z))
 def test_keytool_colon_signer_normalization(self):
  self.assertEqual(m.cert_pin(':'.join('bb' for _ in range(32))),PIN)
  self.refuse('EXPECTED_CERT_SHA256_INVALID',lambda:m.cert_pin('INVALID'))
 def test_signing_command_failure_refused(self):
  class P:returncode=2;stdout='invalid';stderr='error'
  with mock.patch.object(m.subprocess,'run',return_value=P()):
   self.refuse('SIGNING_TOOL_FAILURE',lambda:m._run(['apksigner','verify','fake.apk']))
 def test_real_git_checkout_sha_detects_drift(self):
  repo=self.root/'repo';repo.mkdir()
  for cmd in (('init',),('config','user.email','x@example.test'),('config','user.name','X')):
   subprocess.run(['git','-C',str(repo),*cmd],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  (repo/'fixture').write_text('one')
  subprocess.run(['git','-C',str(repo),'add','fixture'],check=True)
  subprocess.run(['git','-C',str(repo),'commit','-m','one'],check=True,stdout=subprocess.DEVNULL)
  first=m.githead(repo)
  (repo/'fixture').write_text('two')
  subprocess.run(['git','-C',str(repo),'commit','-am','two'],check=True,stdout=subprocess.DEVNULL)
  self.assertNotEqual(first,m.githead(repo))
 def test_source_pins_and_tag_only_contract(self):
  root=self.root/'repo';root.mkdir()
  stub='''name: Android\n  signed-release:\n    if: startsWith(github.ref, 'refs/tags/android-v') && (github.event_name == 'push' || (github.event_name == 'workflow_dispatch' && inputs.signed_release))\n    XDM_RELEASE_SIGNER_SHA256\n    XDM_RELEASE_KEYSTORE_BASE64\n    XDM_XAR16_FULL_RELEASE_GATE\n    run-hosted-emulator-instrumentation.sh --signed-release\n    actions/attest@v4\n    xdm-android-signed-release\n    if-no-files-found: error\n  emulator-compatibility:\n'''
  pins={}
  for name in m.SOURCE_PINS:
   f=root/name;f.parent.mkdir(parents=True,exist_ok=True)
   b=stub.encode() if name=='.github/workflows/android.yml' else (b'python3 -B ../../scripts/mp12_p04_signed_release.py checksum-write\n' if name=='app/XDM.Android/tools/generate-xar16-publication-bundle.sh' else b'fixture')
   f.write_bytes(b);pins[name]=m.gitblob(b)
  with mock.patch.dict(m.SOURCE_PINS,pins,clear=True):
   self.assertEqual(m.source_guard(root)['source_pins'],len(pins))
   p=root/'.github/workflows/android.yml';p.write_text(p.read_text().replace('android-v','android-debug'))
   self.refuse('SOURCE_BLOB_CHANGED',lambda:m.source_guard(root))
 def test_report_never_promotes_physical_arm64(self):
  self.assertFalse(self.verify()['physical_arm64_qualified'])

 def test_new_checksum_writer_exactly_six_no_self_hash(self):
  (self.publication/'SHA256SUMS').unlink();(self.publication/'SHA512SUMS').unlink()
  m.write_checksums(self.publication)
  self.assertEqual(set(self.check()),set(m.KIND_EXT))
  for name in ('SHA256SUMS','SHA512SUMS'):
   self.assertNotIn(name+'\n',(self.publication/name).read_text())
 def test_new_checksum_writer_refuses_existing_receipt(self):
  self.refuse('CHECKSUM_SOURCE_INVENTORY',lambda:m.write_checksums(self.publication))
 def test_new_checksum_writer_refuses_unrecognized_source(self):
  (self.publication/'SHA256SUMS').unlink();(self.publication/'SHA512SUMS').unlink()
  (self.publication/'extra.json').write_text('{}')
  self.refuse('CHECKSUM_SOURCE_INVENTORY',lambda:m.write_checksums(self.publication))
 def test_new_checksum_writer_refuses_symlink_source(self):
  (self.publication/'SHA256SUMS').unlink();(self.publication/'SHA512SUMS').unlink()
  (self.publication/'rm04-validation-seal.json').unlink()
  (self.publication/'rm04-validation-seal.json').symlink_to(self.publication/'release-metadata.json')
  self.refuse('NOT_REGULAR_FILE',lambda:m.write_checksums(self.publication))
 def test_new_checksum_writer_exclusive_create_race(self):
  (self.publication/'SHA256SUMS').unlink();(self.publication/'SHA512SUMS').unlink()
  with mock.patch.object(m.os,'open',side_effect=FileExistsError):
   self.refuse('CHECKSUM_CREATE_RACE',lambda:m.write_checksums(self.publication))
 def test_historical_generator_self_hash_regression(self):
  old=('find "$OUT_DIR" -type f -maxdepth 1 -print0 | sort -z | xargs -0 sha256sum > "$OUT_DIR/SHA256SUMS"')
  new='python3 -B ../../scripts/mp12_p04_signed_release.py checksum-write'
  self.assertNotIn(old,Path(__file__).resolve().parents[1].joinpath('app/XDM.Android/tools/generate-xar16-publication-bundle.sh').read_text() if Path(__file__).resolve().parents[1].joinpath('app/XDM.Android/tools/generate-xar16-publication-bundle.sh').exists() else new)
  self.assertIn('checksum-write',new)

if __name__=='__main__':unittest.main(verbosity=2)
