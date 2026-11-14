#!/usr/bin/env python3
"""MP12 P07: source-bound ARM64 APK-pair retrieval, read-only preflight, opt-in test.

A successful build / read-only preflight is *not* physical instrumentation or
media/cutover/release qualification.  Device writes require a fresh interactive
confirmation and the explicit --ack-install opt-in.
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
import tempfile
import time
import zipfile

REPO='Mikeyphw/xdm-xgo'
PR=28
BRANCH='feature/xgo-mp09-consolidated-recording-20261111'
BASE='1a0806a069ae27eea322332c9f05f70cf6fd4d34'
ARTIFACT='xdm-android-physical-arm64-apk-pair'
WORKFLOW='XDM Android CI'
FILES=('app-debug.apk','app-debug-androidTest.apk','SHA256SUMS','APK_PAIR_RECEIPT.json')
SHA40=re.compile(r'^[0-9a-f]{40}$')
AUTH='I_AUTHORIZE_P07_TWO_APK_INSTALL'
RUN_LIMIT=100
MAX_ARTIFACT=220_000_000
PINS={
 'scripts/xgo_hf16_apk_pair.py':'6bb9376ef422af8a052950de322a7d80e0d98688',
 'scripts/mp12_p02_provenance.py':'0fb1f07e4144c9b0c9e737ab51d908e202cbf3eb',
 'scripts/mp12_p06_final_qualification.py':'424455cf14b229451c8c6bb87a868792becd9035',
 'scripts/run_physical_arm64_instrumentation.sh':'872db6b4909764e94e2ea31f313274a8dd04bcb6',
 '.github/workflows/android.yml':'9db9afa13e9a5c7944d727888968bac6766ca043',
 '.github/workflows/xgo-targeted.yml':'242365dee226ac16a4e8ad9b83c045214df1f2d6',
}

try:
 from rich.console import Console
 from rich.panel import Panel
 from rich.prompt import Prompt
 C=Console()
except ImportError:
 C=None

class Refused(ValueError):pass

def need(ok,reason):
 if not ok:raise Refused('XGO_MP12_P07_REFUSED_'+reason)

def emit(msg):
 if C:C.print('[bold cyan]XGO_MP12_P07_'+msg+'[/bold cyan]')
 else:print('XGO_MP12_P07_'+msg,flush=True)

def blob(content):return hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
def sha(content):return hashlib.sha256(content).hexdigest()
def run(cmd,*,timeout=75,cwd=None,check=True):
 try:r=subprocess.run([str(x) for x in cmd],cwd=cwd,text=True,stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE,timeout=timeout,check=False)
 except (OSError,subprocess.TimeoutExpired):raise Refused('XGO_MP12_P07_REFUSED_COMMAND_UNAVAILABLE_OR_TIMEOUT') from None
 if check:need(r.returncode==0,'COMMAND_FAILED_'+str(cmd[0])+'_'+str(r.returncode))
 return r.stdout

def github(path):
 out=run(['gh','api','repos/'+REPO+'/'+path],timeout=130)
 need(len(out)<3_000_000,'GH_RESPONSE_OVERSIZE')
 try:
  return json.loads(out,object_pairs_hook=lambda pairs: unique(pairs))
 except (ValueError,TypeError):raise Refused('XGO_MP12_P07_REFUSED_GH_JSON') from None

def unique(pairs):
 out={}
 for k,v in pairs:
  need(k not in out,'DUPLICATE_JSON_KEY')
  out[k]=v
 return out

def checked_root(root):
 raw_root=Path(root).expanduser()
 need(not raw_root.is_symlink(),'REPO_SYMLINK')
 root=raw_root.resolve()
 need(root.is_dir(),'REPO_MISSING')
 need(Path(run(['git','-C',root,'rev-parse','--show-toplevel']).strip()).resolve()==root,'REPO_TOPLEVEL')
 need(run(['git','-C',root,'branch','--show-current']).strip()==BRANCH,'BRANCH_DRIFT')
 need(not run(['git','-C',root,'status','--porcelain','--untracked-files=normal']).strip(),'DIRTY_WORKTREE')
 head=run(['git','-C',root,'rev-parse','HEAD']).strip()
 need(bool(SHA40.fullmatch(head)),'HEAD_INVALID')
 need(run(['git','-C',root,'remote','get-url','origin']).strip() in (
  'git@github.com:'+REPO+'.git','git@github.com:'+REPO,'https://github.com/'+REPO,
  'https://github.com/'+REPO+'.git','ssh://git@github.com/'+REPO+'.git'),'ORIGIN_DRIFT')
 return root,head

def source_guard(root):
 root=Path(root)
 checked=[]
 for path,pin in PINS.items():
  f=root/path
  need(f.is_file() and not f.is_symlink(),'SOURCE_MISSING_'+path.replace('/','_'))
  need(blob(f.read_bytes())==pin,'SOURCE_BLOB_DRIFT_'+path.replace('/','_'))
  checked.append(path)
 wf=(root/'.github/workflows/android.yml').read_text()
 need("  signed-release:\n    if: startsWith(github.ref, 'refs/tags/android-v')" in wf,'TAG_ONLY_SIGNING_POLICY')
 need('name: xdm-android-physical-arm64-apk-pair' in wf and
      'python3 -B scripts/xgo_hf16_apk_pair.py' in wf,'APK_PAIR_BUILD_PIPELINE')
 physical=(root/'scripts/run_physical_arm64_instrumentation.sh').read_text()
 need('XGO_ADB_EMULATOR_REFUSED' in physical and 'XGO_ADB_NATIVE_ARM64_REQUIRED' in physical and
      'XGO_REAL_ARM64_DEVICE_INSTRUMENTATION_PASS' in physical,'PHYSICAL_GUARDS')
 return {'source_pins_checked':len(checked),'signing_or_publication_performed':False}

def pr_head(root):
 root,head=checked_root(root)
 data=github('pulls/'+str(PR))
 a=data.get('head') or {};b=data.get('base') or {}
 need(data.get('state')=='open' and not data.get('merged') and a.get('sha')==head and
      a.get('ref')==BRANCH and (a.get('repo') or {}).get('full_name')==REPO and
      b.get('sha')==BASE,'PR_HEAD_BASE_DRIFT')
 need(a.get('ref')==BRANCH,'PR_BRANCH_DRIFT')
 source_guard(root)
 return root,head

def verify_run(run_record,head,jobs):
 need(run_record.get('head_sha')==head and run_record.get('event')=='workflow_dispatch' and
      run_record.get('name')==WORKFLOW and run_record.get('head_branch')==BRANCH and
      run_record.get('status')=='completed' and run_record.get('conclusion')=='success',
      'BUILD_RUN_NOT_EXACT_HEAD_SUCCESS')
 hit=[j for j in jobs if j.get('name')=='validate']
 need(len(hit)==1 and hit[0].get('status')=='completed' and hit[0].get('conclusion')=='success',
      'BUILD_VALIDATE_JOB_NOT_PASS')
 return run_record['id']

def find_build(head):
 data=github('actions/runs?head_sha='+head+'&per_page='+str(RUN_LIMIT))
 runs=data.get('workflow_runs')
 need(isinstance(runs,list) and len(runs)<RUN_LIMIT,'RUN_INVENTORY_PAGED_OR_MISSING')
 need(all(r.get('head_sha')==head for r in runs),'RUN_HEAD_SPOOF')
 relevant=[r for r in runs if r.get('name')==WORKFLOW and r.get('event')=='workflow_dispatch' and r.get('head_branch')==BRANCH]
 if not relevant:return None
 r=max(relevant,key=lambda x:x.get('id',0))
 need(isinstance(r.get('id'),int),'RUN_ID_INVALID')
 if r.get('status')!='completed':return {'status':'pending','id':r['id'],'head':head}
 need(r.get('conclusion')=='success','LATEST_BUILD_FAILED_NO_OLD_GREEN_FALLBACK')
 details=github('actions/runs/'+str(r['id']))
 jobs=github('actions/runs/'+str(r['id'])+'/jobs?per_page=100').get('jobs')
 need(isinstance(jobs,list) and len(jobs)<100,'BUILD_JOBS_PAGED')
 verify_run(details,head,jobs)
 return {'status':'ready','id':r['id'],'head':head}

def artifact_record(run_id):
 data=github('actions/runs/'+str(run_id)+'/artifacts?per_page=100')
 records=data.get('artifacts')
 need(isinstance(records,list) and len(records)<100,'ARTIFACT_INVENTORY_MISSING_OR_PAGED')
 found=[r for r in records if r.get('name')==ARTIFACT]
 need(len(found)==1,'ARM64_APK_PAIR_ARTIFACT_ABSENT_OR_AMBIGUOUS')
 a=found[0]
 need(isinstance(a.get('id'),int) and isinstance(a.get('size_in_bytes'),int) and
      1_024<a['size_in_bytes']<=MAX_ARTIFACT and a.get('expired') is False,
      'ARTIFACT_EXPIRED_OR_SIZE')
 if a.get('workflow_run') is not None:
  need(a['workflow_run'].get('id')==run_id,'ARTIFACT_RUN_MISMATCH')
 return a

def extract_bounded(archive,destination):
 dest=Path(destination)
 need(dest.parent.is_dir() and dest.is_dir() and not dest.is_symlink(),'DESTINATION_INVALID')
 need(not any(dest.iterdir()),'DESTINATION_NOT_EMPTY')
 with zipfile.ZipFile(archive,'r') as z:
  infos=z.infolist();names=[x.filename for x in infos]
  need(len(names)==len(FILES) and len(set(names))==len(FILES) and set(names)==set(FILES),'ZIP_INVENTORY')
  for i in infos:
   mode=(i.external_attr>>16)&0o170000
   need(mode!=0o120000 and not i.is_dir() and 0<i.file_size<=MAX_ARTIFACT and
        i.compress_size<=MAX_ARTIFACT and (i.file_size<=50*max(1,i.compress_size)),'ZIP_MEMBER_UNSAFE')
  need(sum(i.file_size for i in infos)<MAX_ARTIFACT,'ZIP_TOTAL_OVERSIZE')
  for i in infos:
   out=dest/i.filename
   fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
   with os.fdopen(fd,'wb') as f, z.open(i) as src:
    shutil.copyfileobj(src,f,length=1024*1024)
    f.flush();os.fsync(f.fileno())
 return dest

def verify_pair(root,pair,head,run_id):
 pair=Path(pair)
 need(pair.is_dir() and not pair.is_symlink(),'PAIR_DIR')
 # Reuse existing independently tested ARM64 ELF/receipt/ABI verifier.
 spec=importlib.util.spec_from_file_location('p07_inherited_p02',Path(root)/'scripts/mp12_p02_provenance.py')
 need(spec is not None and spec.loader is not None,'P02_VERIFIER_MISSING')
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 try:verified=m.audit_arm64_pair(pair,head)
 except Exception as exc:
  if isinstance(exc,KeyboardInterrupt):raise
  raise Refused('XGO_MP12_P07_REFUSED_INHERITED_P02_PAIR_VERIFICATION') from None
 # Independently bind actual artifact metadata and exact head to receipt.
 receipt=json.loads((pair/'APK_PAIR_RECEIPT.json').read_text(),object_pairs_hook=unique)
 need(receipt['github_run_id']==str(run_id),'APKS_WRONG_BUILD_RUN')
 need(receipt['commit_sha']==head,'APKS_WRONG_COMMIT')
 need(verified['artifact_built_only'] and not verified['physical_arm64_runtime_qualified'],'BUILT_ONLY_POLICY_DRIFT')
 return verified

def read_only_device(serial):
 need(bool(serial) and re.fullmatch(r'[A-Za-z0-9._:-]{1,100}',serial) is not None,'ADB_SERIAL_INVALID')
 need(run(['adb','-s',serial,'get-state'],timeout=18).strip()=='device','ADB_NOT_ONLINE')
 def prop(name):return run(['adb','-s',serial,'shell','getprop',name],timeout=20).strip().replace('\r','')
 sdk=prop('ro.build.version.sdk');abi=prop('ro.product.cpu.abi');abilist=prop('ro.product.cpu.abilist');qemu=prop('ro.kernel.qemu')
 need(sdk.isdecimal() and int(sdk)>=26,'DEVICE_SDK_INVALID')
 need(abi=='arm64-v8a' and 'arm64-v8a' in abilist.split(','),'DEVICE_ABI_NOT_ARM64')
 need(qemu in ('','0'),'DEVICE_EMULATOR_REFUSED')
 return {'abi':abi,'api':int(sdk),'preflight_only':True,'device_write':False,'physical_media_qualified':False}

def safe_private_dir(path):
 raw=Path(path).expanduser()
 need(not raw.is_symlink(),'OUTPUT_SYMLINK')
 p=raw.resolve()
 if not p.exists():p.mkdir(parents=True,mode=0o700)
 need(p.is_dir(),'OUTPUT_NOT_DIRECTORY')
 p.chmod(0o700)
 return p

def prepare(root,serial,*,dispatch,wait_minutes,outdir):
 root,head=pr_head(root)
 device=read_only_device(serial)
 emit('REAL_ARM64_READ_ONLY_PREFLIGHT_PASS_NO_DEVICE_INSTALL')
 candidate=find_build(head)
 if candidate is None:
  if not dispatch:
   emit('NO_EXACT_HEAD_ANDROID_BUILD_USE_--dispatch')
   return 3
  before=github('actions/runs?head_sha='+head+'&per_page=100').get('workflow_runs',[])
  prior={x['id'] for x in before}
  run(['gh','workflow','run','android.yml','-R',REPO,'--ref',BRANCH,
       '-f','signed_release=false','-f','arm64_translation_diagnostic=false','-f','x86_64_native_test=false'],timeout=120)
  emit('ANDROID_BUILD_DISPATCHED_NO_RELEASE_SIGNING')
  # Only new run IDs qualify, and only at exact head. No older green fallback.
  end=time.monotonic()+max(0,wait_minutes)*60
  while True:
   c=find_build(head)
   if c and c['id'] not in prior:
    candidate=c
    break
   if time.monotonic()>=end:
    emit('BUILD_QUEUED_REEXECUTE_PREPARE_LATER')
    return 3
   time.sleep(12)
 if candidate['status']=='pending':
  emit('EXACT_HEAD_BUILD_PENDING_RUN_'+str(candidate['id']))
  end=time.monotonic()+max(0,wait_minutes)*60
  while time.monotonic()<end:
   time.sleep(20)
   candidate=find_build(head)
   if candidate and candidate['status']=='ready':break
  if not candidate or candidate['status']!='ready':return 3
 rid=candidate['id']
 artifact=artifact_record(rid)
 folder=safe_private_dir(outdir)/('head-'+head[:12]+'-run-'+str(rid))
 need(not folder.exists() and not folder.is_symlink(),'OUTPUT_ARTIFACT_DIRECTORY_ALREADY_EXISTS')
 with tempfile.TemporaryDirectory(prefix='xgo-p07-',dir=os.environ.get('TMPDIR') or None) as temp:
  zfile=Path(temp)/'artifact.zip'
  # Use GH CLI to download ZIP bytes, not auto-extract untrusted archive paths.
  with open(zfile,'wb') as f:
   try:cp=subprocess.run(['gh','api','repos/'+REPO+'/actions/artifacts/'+str(artifact['id'])+'/zip'],
       stdout=f,stderr=subprocess.PIPE,timeout=240,check=False)
   except (OSError,subprocess.TimeoutExpired):raise Refused('XGO_MP12_P07_REFUSED_ARTIFACT_DOWNLOAD_ERROR') from None
  need(cp.returncode==0 and zfile.stat().st_size<=MAX_ARTIFACT,'ARTIFACT_DOWNLOAD_FAILED_OR_OVERSIZE')
  folder.mkdir(mode=0o700)
  try:
   payload_dir=folder/'apk-pair'
   payload_dir.mkdir(mode=0o700)
   extract_bounded(zfile,payload_dir)
   verified=verify_pair(root,payload_dir,head,rid)
  except BaseException:
   shutil.rmtree(folder)
   raise
 emit('EXACT_SHA_RUN_APK_PAIR_DOWNLOAD_AND_ELF_PROVENANCE_PASS_BUILT_ONLY')
 report={'schema':'xgo-mp12-p07-prepare-v1','repository':REPO,'head':head,'run_id':rid,
         'artifact_id':artifact['id'],'files':{f:sha((folder/'apk-pair'/f).read_bytes()) for f in FILES},
         'device_preflight':device,'arm64_pair':verified,
         'instrumentation_executed':False,'physical_arm64_media_qualified':False,
         'release_qualified':False,'production_cutover_authorized':False}
 report_path=folder/'P07_READ_ONLY_RECEIPT.json'
 fd=os.open(report_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:json.dump(report,f,indent=2,sort_keys=True);f.write('\n')
 emit('VERIFIED_PAIR_READY_'+str(folder))
 emit('DEVICE_INSTALL_NOT_AUTHORIZED_OR_EXECUTED')
 return 0

def install_and_test(root,serial,pair,ack):
 need(ack==AUTH,'INSTALL_EXPLICIT_ACK_REQUIRED')
 root,head=pr_head(root)
 device=read_only_device(serial)
 raw_pair=Path(pair).expanduser()
 need(not raw_pair.is_symlink(),'PAIR_SYMLINK')
 pair=raw_pair.resolve()
 need(pair.is_dir() and (pair/'P07_READ_ONLY_RECEIPT.json').is_file(),'P07_PREPARED_RECEIPT_REQUIRED')
 report=json.loads((pair/'P07_READ_ONLY_RECEIPT.json').read_text(),object_pairs_hook=unique)
 need(report.get('head')==head and report.get('device_preflight',{}).get('api')==device['api']
      and not report.get('instrumentation_executed') and not report.get('release_qualified'),'PREPARED_RECEIPT_DRIFT')
 rid=report.get('run_id');need(type(rid)==int and rid>0,'RUN_ID_INVALID')
 # Revalidate remote run before any write. Offline receipts alone are not trust.
 build=find_build(head)
 need(build is not None and build.get('status')=='ready' and build['id']==rid,'LATEST_HOSTED_BUILD_DRIFT')
 verify_pair(root,pair/'apk-pair',head,rid)
 if C:C.print(Panel(f'Will INSTALL two debug APKs on device {serial} (API {device["api"]}).\nNo uninstall, reset, root, or release. This can replace an installed debug app.',title='Device write authorization',style='yellow'))
 else:print('Will install two debug APKs; may replace existing debug app on '+serial)
 try:confirmation=Prompt.ask('Type INSTALL TWO TEST APKS to continue') if C else input('Type INSTALL TWO TEST APKS to continue: ')
 except (EOFError,KeyboardInterrupt):raise Refused('XGO_MP12_P07_REFUSED_INSTALL_NOT_CONFIRMED') from None
 need(confirmation=='INSTALL TWO TEST APKS','INSTALL_NOT_CONFIRMED')
 evidence=safe_private_dir(pair/'device-evidence')
 env=os.environ.copy();env['XGO_ADB_EVIDENCE_DIR']=str(evidence)
 # The repository's existing qualified script owns the actual install/test.
 args=['bash',str(root/'scripts/run_physical_arm64_instrumentation.sh'),serial,
       str(pair/'apk-pair/app-debug.apk'),str(pair/'apk-pair/app-debug-androidTest.apk')]
 try:r=subprocess.run(args,cwd=root,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
       timeout=1350,check=False)
 except (OSError,subprocess.TimeoutExpired):raise Refused('XGO_MP12_P07_REFUSED_DEVICE_TEST_TIMEOUT_OR_UNAVAILABLE') from None
 log=evidence/'P07_runner.log';fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:f.write(r.stdout)
 need(r.returncode==0 and 'XGO_REAL_ARM64_DEVICE_INSTRUMENTATION_PASS:' in r.stdout,
      'PHYSICAL_INSTRUMENTATION_NOT_PASS_CHECK_PRIVATE_LOG')
 emit('REAL_ARM64_INSTRUMENTATION_PASS_NOT_MEDIA_SOAK_OR_RELEASE')
 return 0

def main():
 p=argparse.ArgumentParser(description='MP12 P07 source-bound physical ARM64 acceptance (fail-closed)')
 p.add_argument('mode',choices=('source-only','preflight','prepare','verify-local','install-and-test'))
 p.add_argument('--repo',default='.')
 p.add_argument('--serial',default='localhost:5555')
 p.add_argument('--pair-dir',type=Path)
 p.add_argument('--dispatch',action='store_true',help='dispatch unsigned Android CI, never install')
 p.add_argument('--wait-minutes',type=int,default=0,help='optional hosted build polling (0=resume later)')
 p.add_argument('--outdir',default=str(Path.home()/'.local/share/xgo-p07-acceptance'))
 p.add_argument('--ack-install',default='',help='explicit write authorization plus fresh typed confirmation')
 a=p.parse_args()
 if a.mode=='source-only':
  result=source_guard(Path(a.repo))
  emit('SOURCE_POLICY_PINS_'+str(result['source_pins_checked'])+'_PASS_NOT_PHYSICAL_ACCEPTANCE')
 elif a.mode=='preflight':
  pr_head(a.repo);read_only_device(a.serial);emit('ARM64_READ_ONLY_PREFLIGHT_PASS')
 elif a.mode=='prepare':return prepare(a.repo,a.serial,dispatch=a.dispatch,wait_minutes=a.wait_minutes,outdir=a.outdir)
 elif a.mode=='verify-local':
  need(a.pair_dir is not None,'PAIR_DIRECTORY_REQUIRED')
  root,head=pr_head(a.repo);read_only_device(a.serial)
  location=a.pair_dir/'apk-pair' if (a.pair_dir/'apk-pair').is_dir() else a.pair_dir
  receipt=json.loads((location/'APK_PAIR_RECEIPT.json').read_text(),object_pairs_hook=unique)
  rid=receipt.get('github_run_id');need(isinstance(rid,str) and rid.isdecimal(),'RUN_ID_MISSING')
  found=find_build(head);need(found and found.get('status')=='ready' and str(found['id'])==rid,'HOSTED_RUN_DRIFT')
  verify_pair(root,location,head,int(rid));emit('EXACT_HEAD_PAIR_SOURCE_ELF_PASS_BUILT_ONLY')
 else:
  need(a.pair_dir is not None,'PAIR_DIRECTORY_REQUIRED')
  return install_and_test(a.repo,a.serial,a.pair_dir,a.ack_install)
 return 0

if __name__=='__main__':
 try:sys.exit(main())
 except (Refused,ValueError,zipfile.BadZipFile) as exc:
  print(str(exc) if isinstance(exc,Refused) else 'XGO_MP12_P07_REFUSED_INPUT_OR_ARCHIVE',file=sys.stderr)
  sys.exit(2)
