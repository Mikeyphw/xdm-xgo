#!/usr/bin/env python3
"""Fail-closed XP03B AndroidJUnitRunner acceptance for manual x86_64 app tests."""
from __future__ import annotations
import argparse,hashlib,json,re
from pathlib import Path

SUITES={
 'jni':('com.mikeyphw.xdm.android.XgoX86JniSmokeTest',('installedX86CoreLoadsAndInvokesNativeCreate',)),
 'compose':('com.mikeyphw.xdm.android.AppSmokeTest',(
   'downloadsShellIsVisible',
   'addDownloadIsReachableAndBackReturnsToDownloads',
   'settingsIsAVisiblePrimaryDestination',
   'addDownloadAcceptsUrlWithoutManualFilename',
 )),
 'routing':('com.mikeyphw.xdm.android.ExternalControlSecurityInstrumentedTest',
   ('exportedAutomationResolvesOnlyToReviewGate',)),
}

def validate_one(name:str,output:str)->dict[str,object]:
 cls,methods=SUITES[name]
 if 'INSTRUMENTATION_CODE: -1' not in output or re.search(r'^INSTRUMENTATION_STATUS_CODE: -[0-9]+$',output,re.M):
  raise ValueError('XGO_XP03B_INSTRUMENTATION_FAILED:'+name)
 expected_banner='OK ('+str(len(methods))+(' test)' if len(methods)==1 else ' tests)')
 if expected_banner not in output:
  raise ValueError('XGO_XP03B_INSTRUMENTATION_FAILED:'+name)
 observed=[]
 last=None
 for line in output.splitlines():
  if line.startswith('INSTRUMENTATION_STATUS: test='):
   last=line.partition('test=')[2].strip()
  elif line=='INSTRUMENTATION_STATUS_CODE: 0':
   if last is None:raise ValueError('XGO_XP03B_METHOD_COUNT_MISMATCH:'+name)
   observed.append(last);last=None
 if len(observed)!=len(methods):
  raise ValueError('XGO_XP03B_METHOD_COUNT_MISMATCH:'+name)
 if sorted(observed)!=sorted(methods):
  raise ValueError('XGO_XP03B_METHODS_MISMATCH:'+name)
 classes=set(re.findall(r'^INSTRUMENTATION_STATUS: class=(\S+)$',output,re.M))
 if classes!={cls}:
  raise ValueError('XGO_XP03B_CLASS_MISMATCH:'+name)
 return {'count':len(methods),'class':cls,'methods':list(methods),'transcript_sha256':hashlib.sha256(output.encode()).hexdigest()}

def inspect(data:dict[str,str])->dict[str,object]:
 if set(data)!=set(SUITES):raise ValueError('XGO_XP03B_SUITE_SET_MISMATCH')
 suites={k:validate_one(k,data[k]) for k in SUITES}
 return {'status':'EMULATOR_X86_64_APP_JNI_AND_UI_PASS','native_arm64_executed':False,
   'x86_64_opt_in_only':True,'jni_instrumentation_tests':suites['jni']['count'],
   'compose_instrumentation_tests':suites['compose']['count'],
   'routing_instrumentation_tests':suites['routing']['count'],
   'total_instrumentation_tests':sum(x['count'] for x in suites.values()),'suites':suites}

def main()->int:
 ap=argparse.ArgumentParser()
 for key in SUITES:ap.add_argument('--'+key,type=Path,required=True)
 ap.add_argument('--receipt',type=Path,required=True)
 args=ap.parse_args()
 result=inspect({key:getattr(args,key).read_text() for key in SUITES})
 base=json.loads(args.receipt.read_text())
 if base.get('abi')!='x86_64' or base.get('native_arm64_executed') is not False:
  raise ValueError('XGO_XP03B_APK_RECEIPT_MISMATCH')
 base.update(result)
 base.update(app_process_launched=True,optional_arm64_only_media_backends_qualified=False)
 args.receipt.write_text(json.dumps(base,indent=2,sort_keys=True)+'\n')
 print('XGO_XP03B_INSTRUMENTATION_PASS: 1 JNI, 4 Compose, 1 route test; no failures')
 return 0
if __name__=='__main__':raise SystemExit(main())
