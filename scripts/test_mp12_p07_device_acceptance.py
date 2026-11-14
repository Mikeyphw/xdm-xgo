#!/usr/bin/env python3
"""P07: run real fake APK archives, inherited P02 verifier, remote/job/ADB mutations.
No network, no actual ADB writes, no Git, no Gradle, no signing.
"""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest import mock
import zipfile

SCRIPT=Path(__file__).with_name('mp12_p07_device_acceptance.py')
spec=importlib.util.spec_from_file_location('mp12_p07_device_acceptance',SCRIPT)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
HEAD='fca4a4cdbef723032f52520dab2895c4a81bcf6c'
RID=43521234567

def elf():
 data=bytearray(4096);data[:6]=b'\x7fELF\x02\x01'
 struct.pack_into('<HH',data,16,3,183)
 struct.pack_into('<Q',data,32,64)
 struct.pack_into('<HH',data,54,56,1)
 struct.pack_into('<I',data,64,1)
 struct.pack_into('<QQ',data,64+8,0,0)
 struct.pack_into('<Q',data,64+48,16384)
 return bytes(data)

def pair_bytes():
 lib=elf()
 with io.BytesIO() as out:
  with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
   z.writestr('classes.dex',b'dex\nfixture')
   for name in ('libxdmcore.so','libxdm_ffmpeg.so','libxdm_ffprobe.so','libaria2c.so'):
    z.writestr('lib/arm64-v8a/'+name,lib)
  app=out.getvalue()
 with io.BytesIO() as out:
  with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('classes.dex',b'dex\ntest')
  test=out.getvalue()
 apks=[{'file':name,'size':len(raw),'sha256':m.sha(raw)} for name,raw in
       [('app-debug.apk',app),('app-debug-androidTest.apk',test)]]
 receipt=dict(schema=1,result='BUILT_ONLY_NO_DEVICE_TESTS',commit_sha=HEAD,
              github_run_id=str(RID),github_repository=m.REPO,artifact_name=m.ARTIFACT,
              apks=apks,app_package='com.mikeyphw.xdm.android.debug',
              test_package='com.mikeyphw.xdm.android.debug.test',
              target_package='com.mikeyphw.xdm.android.debug',
              instrumentation_runner='androidx.test.runner.AndroidJUnitRunner',
              abi='arm64-v8a',jni_elf='EM_AARCH64',jni_min_pt_load_alignment=16384)
 sums=''.join(f'{x["sha256"]}  {x["file"]}\n' for x in apks).encode()
 return {'app-debug.apk':app,'app-debug-androidTest.apk':test,'SHA256SUMS':sums,
         'APK_PAIR_RECEIPT.json':(json.dumps(receipt)+'\n').encode()}

def archive(mapping):
 b=io.BytesIO()
 with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
  for k,v in mapping.items():z.writestr(k,v)
 return b.getvalue()

def run_record(status='completed',conclusion='success',head=HEAD,id=RID):
 return {'head_sha':head,'event':'workflow_dispatch','name':m.WORKFLOW,
         'head_branch':m.BRANCH,'status':status,'conclusion':conclusion,'id':id}

class P07Tests(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory(prefix='p07-test-');self.addCleanup(tmp.cleanup)
  self.root=Path(tmp.name)
  (self.root/'scripts').mkdir()
  shutil.copyfile(SCRIPT.with_name('mp12_p02_provenance.py'),self.root/'scripts/mp12_p02_provenance.py')
  self.zip=self.root/'archive.zip'
  self.zip.write_bytes(archive(pair_bytes()))
 def create_pair(self):
  pair=self.root/'pair';pair.mkdir()
  m.extract_bounded(self.zip,pair)
  return pair
 def refused(self,fun,*args,**kw):
  with self.assertRaises(m.Refused):fun(*args,**kw)
 def test_real_zip_positive(self):
  self.assertEqual(set(x.name for x in self.create_pair().iterdir()),set(m.FILES))
 def test_zip_path_traversal(self):
  self.zip.write_bytes(archive({'../bad':b'unsafe',**pair_bytes()}));destination=self.root/'out';destination.mkdir();self.refused(m.extract_bounded,self.zip,destination)
 def test_zip_extra_member(self):
  self.zip.write_bytes(archive({**pair_bytes(),'extra':b'a'}));dest=self.root/'out';dest.mkdir();self.refused(m.extract_bounded,self.zip,dest)
 def test_zip_missing_member(self):
  d=pair_bytes();d.pop('SHA256SUMS');self.zip.write_bytes(archive(d));dest=self.root/'out';dest.mkdir();self.refused(m.extract_bounded,self.zip,dest)
 def test_zip_symlink(self):
  b=io.BytesIO();d=pair_bytes()
  with zipfile.ZipFile(b,'w') as z:
   for k,v in d.items():
    info=zipfile.ZipInfo(k)
    if k=='SHA256SUMS':info.create_system=3;info.external_attr=(0o120777)<<16
    z.writestr(info,v)
  self.zip.write_bytes(b.getvalue());out=self.root/'out';out.mkdir();self.refused(m.extract_bounded,self.zip,out)
 def test_zip_empty_member(self):
  d=pair_bytes();d['SHA256SUMS']=b'';self.zip.write_bytes(archive(d));out=self.root/'out';out.mkdir();self.refused(m.extract_bounded,self.zip,out)
 def test_zip_duplicate_member(self):
  b=io.BytesIO();d=pair_bytes()
  with zipfile.ZipFile(b,'w') as z:
   for k,v in d.items():z.writestr(k,v)
   z.writestr('SHA256SUMS',b'evil')
  self.zip.write_bytes(b.getvalue());out=self.root/'out';out.mkdir();self.refused(m.extract_bounded,self.zip,out)
 def test_zip_not_archived(self):
  self.zip.write_bytes(b'not-a-zip');out=self.root/'out';out.mkdir()
  with self.assertRaises(zipfile.BadZipFile):m.extract_bounded(self.zip,out)
 def test_zip_refuses_existing_data(self):
  out=self.root/'out';out.mkdir();(out/'x').write_text('data');self.refused(m.extract_bounded,self.zip,out)
 def test_zip_extracts_no_extra(self):
  p=self.create_pair();self.assertEqual((p/'app-debug.apk').read_bytes(),pair_bytes()['app-debug.apk'])
 def test_inherited_p02_elf_real_fixture(self):
  pair=self.create_pair();r=m.verify_pair(self.root,pair,HEAD,RID)
  self.assertTrue(r['artifact_built_only']);self.assertEqual(len(r['jni_libraries_checked']),4)
 def test_inherited_p02_sha_mutation_refused(self):
  pair=self.create_pair();(pair/'app-debug.apk').write_bytes(b'changed');self.refused(m.verify_pair,self.root,pair,HEAD,RID)
 def test_inherited_p02_extra_file_refused(self):
  pair=self.create_pair();(pair/'other').write_text('evil');self.refused(m.verify_pair,self.root,pair,HEAD,RID)
 def test_inherited_p02_wrong_run_refused(self):
  pair=self.create_pair();self.refused(m.verify_pair,self.root,pair,HEAD,RID+1)
 def test_inherited_p02_crossabi_refused(self):
  pair=self.create_pair()
  with zipfile.ZipFile(pair/'app-debug.apk','a') as z:z.writestr('lib/x86_64/libxdmcore.so',elf())
  self.refused(m.verify_pair,self.root,pair,HEAD,RID)
 def test_inherited_p02_native_16k_refused(self):
  pair=self.create_pair()
  bad=bytearray(elf());struct.pack_into('<Q',bad,64+48,4096)
  app=pair/'app-debug.apk'
  with zipfile.ZipFile(app,'w') as z:
   z.writestr('classes.dex',b'dex')
   for name in ('libxdmcore.so','libxdm_ffmpeg.so','libxdm_ffprobe.so','libaria2c.so'):
    z.writestr('lib/arm64-v8a/'+name,bytes(bad))
  self.refused(m.verify_pair,self.root,pair,HEAD,RID)
 def test_run_requires_head(self):
  self.refused(m.verify_run,run_record(head='0'*40),HEAD,[{'name':'validate','status':'completed','conclusion':'success'}])
 def test_run_requires_success(self):
  self.refused(m.verify_run,run_record(conclusion='failure'),HEAD,[{'name':'validate','status':'completed','conclusion':'success'}])
 def test_run_requires_dispatch(self):
  r=run_record();r['event']='pull_request';self.refused(m.verify_run,r,HEAD,[{'name':'validate','status':'completed','conclusion':'success'}])
 def test_run_requires_validate(self):
  self.refused(m.verify_run,run_record(),HEAD,[])
 def test_run_refuses_duplicate_validate(self):
  j=[{'name':'validate','status':'completed','conclusion':'success'}]*2
  self.refused(m.verify_run,run_record(),HEAD,j)
 def test_run_positive(self):
  self.assertEqual(m.verify_run(run_record(),HEAD,[{'name':'validate','status':'completed','conclusion':'success'}]),RID)
 def test_latest_failed_run_not_masked(self):
  runs=[run_record(id=RID-1),run_record(conclusion='failure')]
  with mock.patch.object(m,'github',return_value={'workflow_runs':runs}):self.refused(m.find_build,HEAD)
 def test_pending_latest_not_masked(self):
  runs=[run_record(id=RID-1),run_record(status='in_progress',conclusion=None)]
  with mock.patch.object(m,'github',return_value={'workflow_runs':runs}):self.assertEqual(m.find_build(HEAD)['status'],'pending')
 def test_head_mismatch_in_run_list(self):
  with mock.patch.object(m,'github',return_value={'workflow_runs':[run_record(head='0'*40)]}):self.refused(m.find_build,HEAD)
 def test_build_absent(self):
  with mock.patch.object(m,'github',return_value={'workflow_runs':[]}):self.assertIsNone(m.find_build(HEAD))
 def test_build_completed(self):
  def fake(path):
   if path.startswith('actions/runs?'):return {'workflow_runs':[run_record()]}
   if path.endswith('/jobs?per_page=100'):return {'jobs':[{'name':'validate','status':'completed','conclusion':'success'}]}
   return run_record()
  with mock.patch.object(m,'github',side_effect=fake):self.assertEqual(m.find_build(HEAD)['status'],'ready')
 def test_artifact_missing(self):
  with mock.patch.object(m,'github',return_value={'artifacts':[]}):self.refused(m.artifact_record,RID)
 def test_artifact_duplicate(self):
  a={'id':17,'name':m.ARTIFACT,'size_in_bytes':2000,'expired':False}
  with mock.patch.object(m,'github',return_value={'artifacts':[a,a]}):self.refused(m.artifact_record,RID)
 def test_artifact_expired(self):
  a={'id':17,'name':m.ARTIFACT,'size_in_bytes':2000,'expired':True}
  with mock.patch.object(m,'github',return_value={'artifacts':[a]}):self.refused(m.artifact_record,RID)
 def test_artifact_wrong_run(self):
  a={'id':17,'name':m.ARTIFACT,'size_in_bytes':2000,'expired':False,'workflow_run':{'id':RID-1}}
  with mock.patch.object(m,'github',return_value={'artifacts':[a]}):self.refused(m.artifact_record,RID)
 def test_artifact_good(self):
  a={'id':17,'name':m.ARTIFACT,'size_in_bytes':2000,'expired':False,'workflow_run':{'id':RID}}
  with mock.patch.object(m,'github',return_value={'artifacts':[a]}):self.assertEqual(m.artifact_record(RID)['id'],17)
 def test_source_guard_good(self):
  root=self.root/'source';root.mkdir()
  d={k:'dummy' for k in m.PINS}
  d['.github/workflows/android.yml']="  signed-release:\n    if: startsWith(github.ref, 'refs/tags/android-v')\nname: xdm-android-physical-arm64-apk-pair\npython3 -B scripts/xgo_hf16_apk_pair.py"
  d['scripts/run_physical_arm64_instrumentation.sh']='XGO_ADB_EMULATOR_REFUSED XGO_ADB_NATIVE_ARM64_REQUIRED XGO_REAL_ARM64_DEVICE_INSTRUMENTATION_PASS'
  with mock.patch.dict(m.PINS,{k:m.blob(v.encode()) for k,v in d.items()},clear=True):
   for name,value in d.items():
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
   self.assertEqual(m.source_guard(root)['source_pins_checked'],len(d))
   (root/'scripts/xgo_hf16_apk_pair.py').write_text('drift')
   self.refused(m.source_guard,root)
 def test_credential_reject_duplicate_json(self):
  self.refused(m.unique,[('hello',1),('hello',2)])
 def test_preflight_good(self):
  def fake(cmd,**kw):
   if cmd[-1]=='get-state':return 'device'
   return {'ro.build.version.sdk':'36','ro.product.cpu.abi':'arm64-v8a','ro.product.cpu.abilist':'arm64-v8a,armeabi-v7a','ro.kernel.qemu':'0'}[cmd[-1]]
  with mock.patch.object(m,'run',side_effect=fake):self.assertEqual(m.read_only_device('localhost:5555')['api'],36)
 def test_preflight_emulator_refused(self):
  def fake(cmd,**kw):return 'device' if cmd[-1]=='get-state' else {'ro.build.version.sdk':'36','ro.product.cpu.abi':'arm64-v8a','ro.product.cpu.abilist':'arm64-v8a','ro.kernel.qemu':'1'}[cmd[-1]]
  with mock.patch.object(m,'run',side_effect=fake):self.refused(m.read_only_device,'localhost:5555')
 def test_preflight_x86_refused(self):
  def fake(cmd,**kw):return 'device' if cmd[-1]=='get-state' else {'ro.build.version.sdk':'36','ro.product.cpu.abi':'x86_64','ro.product.cpu.abilist':'x86_64','ro.kernel.qemu':'0'}[cmd[-1]]
  with mock.patch.object(m,'run',side_effect=fake):self.refused(m.read_only_device,'localhost:5555')
 def test_preflight_offline_refused(self):
  with mock.patch.object(m,'run',return_value='offline'):self.refused(m.read_only_device,'localhost:5555')
 def test_preflight_bad_serial_refused(self):self.refused(m.read_only_device,'localhost:5555; rm')
 def test_preflight_sdk_old_refused(self):
  def fake(cmd,**kw):return 'device' if cmd[-1]=='get-state' else {'ro.build.version.sdk':'25','ro.product.cpu.abi':'arm64-v8a','ro.product.cpu.abilist':'arm64-v8a','ro.kernel.qemu':'0'}[cmd[-1]]
  with mock.patch.object(m,'run',side_effect=fake):self.refused(m.read_only_device,'localhost:5555')
 def test_prepare_without_dispatch_no_gh_write(self):
  with mock.patch.object(m,'pr_head',return_value=(self.root,HEAD)), mock.patch.object(m,'read_only_device',return_value={}), mock.patch.object(m,'find_build',return_value=None),mock.patch.object(m,'run') as host:
   self.assertEqual(m.prepare(self.root,'localhost:5555',dispatch=False,wait_minutes=0,outdir=self.root/'out'),3)
   host.assert_not_called()
 def test_install_without_ack_no_device_write(self):
  with mock.patch.object(m,'pr_head') as pr, mock.patch.object(m,'run') as host:
   self.refused(m.install_and_test,self.root,'localhost:5555',self.root/'pair','')
   pr.assert_not_called();host.assert_not_called()
 def test_install_wrong_ack_no_device_write(self):
  with mock.patch.object(m,'pr_head') as pr:self.refused(m.install_and_test,self.root,'localhost:5555',self.root/'pair','WRONG');pr.assert_not_called()
 def test_private_dir_mode(self):
  p=m.safe_private_dir(self.root/'private');self.assertEqual(p.stat().st_mode&0o777,0o700)
 def test_private_symlink_refused(self):
  target=self.root/'dir';target.mkdir();ln=self.root/'linked';ln.symlink_to(target)
  self.refused(m.safe_private_dir,ln)
 def test_privacy_report_no_false_cutover(self):
  self.assertNotIn("'release_qualified':True",SCRIPT.read_text().replace(' ',''))
  self.assertIn("'physical_arm64_media_qualified':False",SCRIPT.read_text().replace(' ',''))
  self.assertIn("'production_cutover_authorized':False",SCRIPT.read_text().replace(' ',''))
 def test_prepare_download_full_real_p02_and_private_receipt(self):
  from types import SimpleNamespace
  device={'api':36,'abi':'arm64-v8a','preflight_only':True,'device_write':False,'physical_media_qualified':False}
  record={'status':'ready','id':RID,'head':HEAD}
  artifact={'id':789,'size_in_bytes':self.zip.stat().st_size,'name':m.ARTIFACT,'expired':False}
  def fake_process(argv,*,stdout,stderr,timeout,check):
   self.assertEqual(argv[:2],['gh','api'])
   stdout.write(self.zip.read_bytes())
   return SimpleNamespace(returncode=0,stderr=b'')
  outdir=self.root/'output'
  with mock.patch.object(m,'pr_head',return_value=(self.root,HEAD)),mock.patch.object(m,'read_only_device',return_value=device),mock.patch.object(m,'find_build',return_value=record),mock.patch.object(m,'artifact_record',return_value=artifact),mock.patch.object(m.subprocess,'run',side_effect=fake_process):
   self.assertEqual(m.prepare(self.root,'localhost:5555',dispatch=False,wait_minutes=0,outdir=outdir),0)
  folder=outdir/('head-'+HEAD[:12]+'-run-'+str(RID))
  self.assertTrue((folder/'P07_READ_ONLY_RECEIPT.json').is_file())
  self.assertEqual(set(x.name for x in (folder/'apk-pair').iterdir()),set(m.FILES))
  report=json.loads((folder/'P07_READ_ONLY_RECEIPT.json').read_text())
  self.assertEqual(report['run_id'],RID)
  self.assertFalse(report['physical_arm64_media_qualified'])
  self.assertFalse(report['instrumentation_executed'])
  self.assertNotIn('localhost:5555',(folder/'P07_READ_ONLY_RECEIPT.json').read_text())
  self.assertEqual((folder/'P07_READ_ONLY_RECEIPT.json').stat().st_mode&0o777,0o600)
 def test_positive_prepare_refuses_existing_pair_no_overwrite(self):
  from types import SimpleNamespace
  device={'api':36,'abi':'arm64-v8a','preflight_only':True,'device_write':False,'physical_media_qualified':False}
  record={'status':'ready','id':RID,'head':HEAD}
  artifact={'id':789,'size_in_bytes':self.zip.stat().st_size,'name':m.ARTIFACT,'expired':False}
  outdir=self.root/'output';folder=outdir/('head-'+HEAD[:12]+'-run-'+str(RID))
  folder.mkdir(parents=True)
  marker=folder/'do-not-overwrite';marker.write_text('persisted')
  with mock.patch.object(m,'pr_head',return_value=(self.root,HEAD)),mock.patch.object(m,'read_only_device',return_value=device),mock.patch.object(m,'find_build',return_value=record),mock.patch.object(m,'artifact_record',return_value=artifact):
   self.refused(m.prepare,self.root,'localhost:5555',dispatch=False,wait_minutes=0,outdir=outdir)
  self.assertEqual(marker.read_text(),'persisted')
 def test_install_authorized_but_confirmation_refused_before_write(self):
  pair=self.root/'prepared';(pair/'apk-pair').mkdir(parents=True)
  report={'head':HEAD,'run_id':RID,'device_preflight':{'api':36},'instrumentation_executed':False,'release_qualified':False}
  (pair/'P07_READ_ONLY_RECEIPT.json').write_text(json.dumps(report))
  with mock.patch.object(m,'pr_head',return_value=(self.root,HEAD)),mock.patch.object(m,'read_only_device',return_value={'api':36}),mock.patch.object(m,'find_build',return_value={'id':RID,'status':'ready'}),mock.patch.object(m,'verify_pair',return_value={'artifact_built_only':True}),mock.patch.object(m,'C',None),mock.patch('builtins.input',return_value='DECLINE'),mock.patch.object(m.subprocess,'run') as host:
   self.refused(m.install_and_test,self.root,'localhost:5555',pair,m.AUTH)
   host.assert_not_called()
 def test_no_local_gradle_or_root(self):
  s=SCRIPT.read_text();self.assertNotIn('gradlew ',s);self.assertNotIn('su -c',s)
  self.assertNotIn('git reset --hard',s);self.assertNotIn('git push --force',s)

if __name__=='__main__':unittest.main(verbosity=2)
