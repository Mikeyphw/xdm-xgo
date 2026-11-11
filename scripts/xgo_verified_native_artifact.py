#!/usr/bin/env python3
"""XGO CI-only, cross-PR, content-addressed native output reuse.

This is explicitly NOT a release path. Existing pinned-source builders must run
on cache miss; every cache hit is independently checked by the same native
ELF/manifest/lock verifiers and APK-byte comparison as a source-built miss.
GitHub Action artifacts are untrusted until source fingerprint, exact entry
inventory, per-file SHA256, ABI/ELF, run/repository provenance and native locks
have all been validated. No other PR's Gradle cache is imported.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
REPO='Mikeyphw/xdm-xgo'
WORKFLOW='.github/workflows/xgo-x86-native-media.yml'
ABI='x86_64'
NDK='29.0.14206865'
SOURCE_FILES=(
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
OUTPUTS=(
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
ELF_FILES=frozenset(p for p in OUTPUTS if p.endswith('.so'))
MAX_ARCHIVE=240_000_000
MAX_NATIVE=140_000_000
PREFIX='XGO_X86_ARTIFACT'

def fail(text):raise ValueError(PREFIX+'_REFUSED:'+text)
def sha(b):return hashlib.sha256(b).hexdigest()

def require_host():
    checks={'GITHUB_ACTIONS':'true','RUNNER_OS':'Linux',
      'GITHUB_REPOSITORY':REPO,'GITHUB_EVENT_NAME':'pull_request',
      'GITHUB_EVENT_ACTION':'labeled','XGO_X86_MEDIA_OPT_IN':'yes'}
    for name,value in checks.items():
        if os.environ.get(name)!=value:fail('HOSTED_OPT_IN_'+name)
    if os.uname().machine!='x86_64':fail('HOST_ARCH')
    expected=os.environ.get('XGO_X86_MEDIA_EXPECTED_HEAD','')
    if not re.fullmatch('[a-f0-9]{40}',expected):fail('EXPECTED_HEAD')
    checkout=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
    if checkout!=expected:fail('CHECKOUT_HEAD')
    return expected

def fingerprint():
    inputs={}
    for name in SOURCE_FILES:
        p=ROOT/name
        if not p.is_file() or p.is_symlink() or p.stat().st_size>3_000_000:fail('SOURCE_FILE_INVALID:'+name)
        inputs[name]=sha(p.read_bytes())
    values={'abi':ABI,'ndk':NDK,'recipe_revision':2,'sources':inputs}
    key=sha(json.dumps(values,sort_keys=True,separators=(',',':')).encode())
    return key,values

def artifact_name(key):return 'xgo-native-x86-verified-'+key[:32]

def elf_check(data,path):
    import importlib.util
    script=ROOT/'scripts/xgo_x86_native_media.py'
    spec=importlib.util.spec_from_file_location('xgo_media_artifact_elf',script)
    if spec is None or spec.loader is None:fail('ELF_VERIFIER_NOT_AVAILABLE')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result=module.verify_native(data,path)
    if result['machine']!=62 or result['min_load_alignment']<16384:fail('UNSAFE_ELF:'+path)
    return result

def collect_outputs():
    result={};total=0
    for name in OUTPUTS:
        file=ROOT/name
        if not file.is_file() or file.is_symlink():fail('MISSING_SOURCE_BUILT_OUTPUT:'+name)
        data=file.read_bytes()
        total+=len(data)
        if total>MAX_NATIVE or len(data)<1:fail('NATIVE_PAYLOAD_TOO_LARGE_OR_EMPTY')
        if name in ELF_FILES:elf_check(data,name)
        result[name]=data
    return result

def receipt_data(key,inputs,head,files):
    return {'schema_version':1,'purpose':'CI_TEST_ONLY_NEVER_RELEASE',
      'abi':ABI,'ndk':NDK,'source_fingerprint':key,'inputs':inputs,
      'head_sha':head,'run_id':str(os.environ.get('GITHUB_RUN_ID','')),
      'repo':REPO,'workflow_path':WORKFLOW,
      'files':{name:{'sha256':sha(blob),'size':len(blob)} for name,blob in sorted(files.items())},
      'qualified_physical_arm64':False,'qualified_licensed_1dm':False}

def package(destination):
    head=require_host();key,inputs=fingerprint();files=collect_outputs()
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():fail('BUNDLE_ALREADY_EXISTS')
    record=receipt_data(key,inputs,head,files)
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=False) as z:
        z.writestr('manifest.json',json.dumps(record,indent=2,sort_keys=True)+'\n')
        for name,data in sorted(files.items()):z.writestr('files/'+name,data)
    if destination.stat().st_size>MAX_ARCHIVE:fail('BUNDLE_OVERSIZE')
    print(PREFIX+'_PACKAGED_ABI_AND_SOURCE_VERIFIED='+key+' bytes='+str(destination.stat().st_size),flush=True)

def check_bundle(data,run_id,run_sha,key,inputs):
    if len(data)>MAX_ARCHIVE:fail('REMOTE_ARCHIVE_TOO_LARGE')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names=z.namelist();expected={'manifest.json'}|{'files/'+name for name in OUTPUTS}
        if set(names)!=expected or len(names)!=len(expected) or z.testzip() is not None:fail('ARCHIVE_ENTRY_INVENTORY_OR_CRC')
        for obj in z.infolist():
            if obj.is_dir() or obj.file_size>MAX_NATIVE or (obj.external_attr>>16)&0o170000==0o120000:
                fail('UNSAFE_ARCHIVE_MEMBER:'+obj.filename)
        receipt=json.loads(z.read('manifest.json'))
        for label,value in [('schema_version',1),('purpose','CI_TEST_ONLY_NEVER_RELEASE'),('abi',ABI),
                 ('ndk',NDK),('source_fingerprint',key),('inputs',inputs),('repo',REPO),
                 ('workflow_path',WORKFLOW),('run_id',str(run_id)),('head_sha',run_sha),
                 ('qualified_physical_arm64',False),('qualified_licensed_1dm',False)]:
            if receipt.get(label)!=value:fail('PROVENANCE_MISMATCH:'+label)
        if set(receipt.get('files',{}))!=set(OUTPUTS):fail('FILE_RECEIPT_INVENTORY')
        files={}
        total=0
        for name in OUTPUTS:
            info=z.getinfo('files/'+name)
            total+=info.file_size
            if total>MAX_NATIVE:fail('EXTRACTED_PAYLOAD_OVERSIZE')
            b=z.read('files/'+name)
            expected_entry=receipt['files'][name]
            if len(b)!=expected_entry.get('size') or sha(b)!=expected_entry.get('sha256'):
                fail('BINARY_DIGEST_MISMATCH:'+name)
            if name in ELF_FILES:elf_check(b,name)
            files[name]=b
        return files

def request_json(uri,token):
    req=urllib.request.Request(uri,headers={
      'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
      'X-GitHub-Api-Version':'2022-11-28','User-Agent':'xgo-x86-ci-source-cache'})
    with urllib.request.urlopen(req,timeout=25) as response:
        return json.loads(response.read(3_000_000))

class SafeArtifactRedirect(urllib.request.HTTPRedirectHandler):
    """Prevent GitHub read token propagation to redirect hosts."""
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        parsed=urllib.parse.urlparse(newurl)
        host=(parsed.hostname or '').lower()
        allowed=(host in ('github.com','api.github.com','objects.githubusercontent.com') or
                 host.endswith('.githubusercontent.com') or
                 host.endswith('.blob.core.windows.net'))
        if parsed.scheme!='https' or not allowed:
            fail('UNTRUSTED_ARTIFACT_REDIRECT')
        new=super().redirect_request(req,fp,code,msg,headers,newurl)
        if new is None:fail('ARTIFACT_REDIRECT_REJECTED')
        # S3/Azure signed URLs require their own query credentials, NOT GH_TOKEN.
        for key in list(new.headers):
            if key.lower() in ('authorization','x-github-api-version'):
                del new.headers[key]
        return new

def download(uri,token):
    req=urllib.request.Request(uri,headers={
      'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
      'X-GitHub-Api-Version':'2022-11-28','User-Agent':'xgo-x86-ci-source-cache'})
    opener=urllib.request.build_opener(SafeArtifactRedirect())
    with opener.open(req,timeout=90) as response:
        data=response.read(MAX_ARCHIVE+1)
    if len(data)>MAX_ARCHIVE:fail('GITHUB_ARTIFACT_TOO_LARGE')
    return data

def restore():
    head=require_host();key,inputs=fingerprint();token=os.environ.get('GH_TOKEN','')
    if not token:fail('ACTIONS_READ_TOKEN_REQUIRED')
    api=os.environ.get('GITHUB_API_URL','https://api.github.com').rstrip('/')
    target=artifact_name(key)
    base=f'{api}/repos/{REPO}'
    try:artifacts=request_json(base+'/actions/artifacts?name='+urllib.parse.quote(target)+'&per_page=100',token)
    except (OSError,ValueError,urllib.error.HTTPError) as exc:
        print(PREFIX+'_LOOKUP_UNAVAILABLE_SOURCE_BUILD_FALLBACK='+type(exc).__name__,flush=True)
        return 10
    candidates=[x for x in artifacts.get('artifacts',[]) if x.get('name')==target and not x.get('expired') and x.get('workflow_run')]
    candidates.sort(key=lambda x:x.get('created_at',''),reverse=True)
    for candidate in candidates[:15]:
        run_id=candidate['workflow_run'].get('id')
        if not isinstance(run_id,int):continue
        try:run=request_json(base+'/actions/runs/'+str(run_id),token)
        except (OSError,ValueError,urllib.error.HTTPError):continue
        if (run.get('conclusion')!='success' or run.get('status')!='completed' or
            run.get('event')!='pull_request' or run.get('path')!=WORKFLOW or
            run.get('head_repository',{}).get('full_name')!=REPO or
            run.get('repository',{}).get('full_name')!=REPO):continue
        source_head=run.get('head_sha','')
        if not re.fullmatch('[a-f0-9]{40}',source_head):continue
        if run_id==int(os.environ.get('GITHUB_RUN_ID','0')):continue
        zipped=download(candidate['archive_download_url'],token)
        with zipfile.ZipFile(io.BytesIO(zipped)) as outer:
            if outer.testzip() is not None or set(outer.namelist())!={'native-output.zip'}:
                fail('GITHUB_OUTER_ARTIFACT_INTEGRITY')
            content=outer.read('native-output.zip')
        files=check_bundle(content,run_id,source_head,key,inputs)
        # ALL checks above complete before any output is written. Fail closed on
        # corrupt output rather than silently substituting a prebuilt binary.
        for name,data in files.items():
            path=ROOT/name
            if path.is_symlink() or (path.exists() and path.read_bytes()!=data):
                fail('REFUSE_OVERWRITE_DIFFERENT_OUTPUT:'+name)
        for name,data in files.items():
            path=ROOT/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        print(PREFIX+'_RESTORED_PROVENANCE_VERIFIED_CROSS_PR='+str(run_id)+' sha='+source_head+' fingerprint='+key,flush=True)
        return 0
    print(PREFIX+'_NO_MATCHING_QUALIFIED_ARTIFACT_BUILD_FROM_SOURCE='+key,flush=True)
    return 10

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['fingerprint','restore','pack'])
    p.add_argument('--out',type=Path);p.add_argument('--github-output',type=Path)
    args=p.parse_args()
    if args.mode=='fingerprint':
        require_host();key,_=fingerprint();name=artifact_name(key)
        print(PREFIX+'_FINGERPRINT='+key+' name='+name,flush=True)
        if args.github_output:
            with args.github_output.open('a') as fp:fp.write('name='+name+'\nsource-fingerprint='+key+'\n')
        return 0
    if args.mode=='restore':return restore()
    if not args.out:fail('PACK_OUTPUT_REQUIRED')
    package(args.out);return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as ex:
        print(str(ex),file=sys.stderr,flush=True);raise SystemExit(2)
