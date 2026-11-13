#!/usr/bin/env python3
"""MP12 P05 desktop Native Messaging v2 -> Go v1 read-only parity contract.

Source-only fixture/contract audit, not real desktop host, Firefox UI, release,
APK, privileged session, download or production cutover evidence.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

PINS = {
 'app/XDM/src/XDM.BrowserIntegration/BrowserCaptureProtocol.cs':'25935d11c133c41d0a0ebb8c0e8054ef363b306c',
 'app/XDM/src/XDM.BrowserIntegration/BrowserNativeProtocol.cs':'451c94df57cf5491924d157e502fd5e952f0f702',
 'app/XDM/src/XDM.BrowserIntegration/NativeMessageFraming.cs':'953a8ec9f3412e6d8d17e21f1f4d887e6bc1ae35',
 'app/XDM/src/XDM.NativeHost/Program.cs':'f8775013a76dfd4bea23662af196604bb913be73',
 'engine/api/v1/wire.go':'195eafd91695a79126b48737162d41d97c1e62da',
 'engine/runtime/desktop_ui_media.go':'059ebd8e11762b7a63d38eb75ce88fc5a8f8bdf0',
 'engine/runtime/desktop_ui_media_test.go':'f556d7dc0481200ed8cdbd2e9f5a6b2bd154993a',
}
FIXTURES = {
 'native-capture.json':'f18512a316175674721b3fa02a2b96f95abfb377',
 'native-hello.json':'f0186486c2cd356e0b4ee49aed2a8fc0be88dfc3',
 'native-batch.json':'db383cd656033c0e35c034bb3525f3d49f51248e',
 'native-post-capture.json':'1b20958f0d19aa820dd6e8319c6f7590f9d3645b',
 'native-unknown-command.json':'b8a655eb754e49ab2882511f580bb557e763b72e',
}
BROWSER_FIXTURE='app/XDM/src/XDM.BrowserMedia.Tests/Fixtures/'
GO_FIXTURE='engine/runtime/desktopparity/testdata/'
GO_SOURCE='engine/runtime/desktopparity/parity.go'
GO_TEST='engine/runtime/desktopparity/parity_test.go'
INTEGRATION='engine/runtime/mp12_p05_desktop_parity_test.go'

class Refused(ValueError): pass

def require(flag:bool, code:str)->None:
 if not flag: raise Refused('MP12_P05_REFUSED_'+code)

def blob(data:bytes)->str:
 return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()

def read(root:Path,name:str,max_size:int=2_000_000)->bytes:
 p=root/name
 require(p.is_file() and not p.is_symlink(),'SOURCE_MISSING_OR_SYMLINK_'+name.replace('/','_'))
 require(0<p.stat().st_size<=max_size,'SOURCE_SIZE_'+name.replace('/','_'))
 return p.read_bytes()

def check_go_runtime_integration(source:str)->bool:
 """Accept gofmt spacing, but require concrete read-only decoder -> engine -> event.

 Synthetic fixture tests must ALSO exercise the exact checked-in Go runtime
 integration file; superficial string-only fixtures would miss format drift.
 """
 return all((
  re.search(r'\bv1\.DecodeCommand\s*\(\s*commandBytes\s*\)', source),
  re.search(r'\bengine\.Submit\s*\(\s*ctx\s*,\s*cmd\s*\)', source),
  re.search(r'\bcmd\.Kind\s*!=\s*DesktopUISnapshotKind\b', source),
  re.search(r'\bfirst\.Kind\s*!=\s*"desktop\.ui\.projection"', source),
  re.search(r'\bsecond\.Kind\s*!=\s*"command\.completed"', source),
  re.search(r'\bevidence\.ExecutionAuthorized\s*\|\|\s*evidence\.ProductionCutover\b', source),
 ))

def check_sources(root:Path,pins:dict[str,str]=PINS,fixtures:dict[str,str]=FIXTURES)->dict:
 original={name:read(root,name) for name in pins}
 for name,pin in pins.items():
  require(blob(original[name])==pin,'SOURCE_BLOB_DRIFT_'+name.replace('/','_'))
 for name,pin in fixtures.items():
  source=read(root,BROWSER_FIXTURE+name)
  mirror=read(root,GO_FIXTURE+name)
  require(blob(source)==pin,'BROWSER_FIXTURE_DRIFT_'+name)
  require(mirror==source,'GO_FIXTURE_BYTES_DIFFER_FROM_DOTNET_'+name)
  decoded=json.loads(source)
  require(isinstance(decoded,dict) and decoded.get('protocolVersion')=='2.0','FIXTURE_PROTOCOL_DRIFT_'+name)
 browser=original['app/XDM/src/XDM.BrowserIntegration/BrowserNativeProtocol.cs'].decode()
 framing=original['app/XDM/src/XDM.BrowserIntegration/NativeMessageFraming.cs'].decode()
 capture=original['app/XDM/src/XDM.BrowserIntegration/BrowserCaptureProtocol.cs'].decode()
 native=original['app/XDM/src/XDM.NativeHost/Program.cs'].decode()
 wire=original['engine/api/v1/wire.go'].decode()
 desktop=original['engine/runtime/desktop_ui_media.go'].decode()
 parser=read(root,GO_SOURCE).decode()
 tests=read(root,GO_TEST).decode()
 integration=read(root,INTEGRATION).decode()
 for name,ok in {
  'NATIVE_V2': 'ProtocolVersion = BrowserCaptureProtocol.ProtocolVersion' in browser and 'ProtocolVersion = "2.0"' in capture,
  'NATIVE_SIZE_256K': 'MaximumMessageBytes = 256 * 1024' in browser,
  'NATIVE_BATCH_100': 'MaximumBatchItems = 100' in browser,
  'NATIVE_FRAME_LE': 'ReadInt32LittleEndian' in framing and 'WriteInt32LittleEndian' in framing,
  'NATIVE_SESSION_AUTH': 'FixedTimeEquals(message.SessionId, sessionId)' in native and 'invalid_session' in native,
  'GO_MAJOR_V1': bool(re.search(r'ProtocolMajor\s*=\s*1\b',wire)) and 'DisallowUnknownFields()' in wire,
  'GO_DESKTOP_SNAPSHOT': 'DesktopUISnapshotKind    = "desktop.ui.snapshot"' in desktop and 'e.desktopUISnapshotHandler' not in desktop,
  'PARITY_NATIVE_V2': 'NativeProtocolVersion = "2.0"' in parser,
  'PARITY_READONLY_ONLY': 'command.Kind = "desktop.ui.snapshot"' in parser and 'ExecutionAuthorized: false' in parser and 'ProductionCutover: false' in parser,
  'PARITY_EXPLICIT_HOST': 'trustedHostOptIn' in parser and 'expectedSession' in parser and 'message.SessionID != expectedSession' in parser,
  'PARITY_NO_IO': all(x not in parser for x in ('"os"','"os/exec"','"net/http"','"syscall"','"unsafe"')),
  'PARITY_TEST_RUNS_REAL_FIXTURES': all('"'+name+'"' in tests for name in fixtures),
  'PARITY_ACTUAL_GO_RUNTIME': check_go_runtime_integration(integration),
 }.items():
  require(ok,'STRUCTURAL_POLICY_'+name)
 return {'schema':'mp12-p05-source-v1','dotnet_source_pins':len(pins),'byte_identical_native_fixtures':len(fixtures),
         'go_native_wire_major':1,'firefox_native_wire':'2.0',
         'snapshot_probe_only':True,'browser_capture_executes':False,
         'full_desktop_dotnet_parity_qualified':False,'production_cutover_qualified':False}

def main()->None:
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('source-only',));p.add_argument('--repo',default='.')
 args=p.parse_args()
 report=check_sources(Path(args.repo).expanduser().resolve())
 print('MP12_P05_DOTNET_'+str(report['dotnet_source_pins'])+'_BLOB_PINS_'+str(report['byte_identical_native_fixtures'])+'_EXACT_FIXTURES_READ_ONLY_GO_V1_PARITY_PASS_NOT_PRODUCTION')

if __name__=='__main__':
 try:main()
 except (Refused,ValueError,OSError) as e:
  print(str(e) if isinstance(e,Refused) else 'MP12_P05_REFUSED_SOURCE_OR_JSON_ERROR',file=sys.stderr)
  raise SystemExit(2)
