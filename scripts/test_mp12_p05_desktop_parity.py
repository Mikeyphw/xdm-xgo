#!/usr/bin/env python3
"""MP12 P05 source-only parity audit with positive and mutation refusal tests."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

P=Path(__file__).with_name('mp12_p05_desktop_parity.py')
spec=importlib.util.spec_from_file_location('mp12_p05_desktop_parity',P)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

DUMMY={
 'app/XDM/src/XDM.BrowserIntegration/BrowserNativeProtocol.cs':'ProtocolVersion = BrowserCaptureProtocol.ProtocolVersion\nMaximumMessageBytes = 256 * 1024\nMaximumBatchItems = 100',
 'app/XDM/src/XDM.BrowserIntegration/BrowserCaptureProtocol.cs':'ProtocolVersion = "2.0"',
 'app/XDM/src/XDM.BrowserIntegration/NativeMessageFraming.cs':'ReadInt32LittleEndian\nWriteInt32LittleEndian',
 'app/XDM/src/XDM.NativeHost/Program.cs':'FixedTimeEquals(message.SessionId, sessionId) invalid_session',
 'engine/api/v1/wire.go':'ProtocolMajor = 1\nDisallowUnknownFields()',
 'engine/runtime/desktop_ui_media.go':'DesktopUISnapshotKind    = "desktop.ui.snapshot"',
 'engine/runtime/desktop_ui_media_test.go':'fixture test for Go desktop runtime',
 m.GO_SOURCE:'const NativeProtocolVersion = "2.0"\ncommand.Kind = "desktop.ui.snapshot"\nExecutionAuthorized: false\nProductionCutover: false\ntrustedHostOptIn\nexpectedSession\nmessage.SessionID != expectedSession',
 m.GO_TEST:'\n'.join('"'+k+'"' for k in m.FIXTURES),
 m.INTEGRATION:'v1.DecodeCommand(commandBytes)\nengine.Submit(ctx, cmd)\ncmd.Kind != DesktopUISnapshotKind\nfirst.Kind != "desktop.ui.projection"\nsecond.Kind != "command.completed"\nevidence.ExecutionAuthorized || evidence.ProductionCutover',
}

class Audit(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory(prefix='mp12-p05-')
  self.addCleanup(tmp.cleanup)
  self.root=Path(tmp.name)
  self.pins={}
  self.fixtures={}
  for name,content in DUMMY.items():self.write(name,content.encode())
  for name in m.FIXTURES:
   b=json.dumps({'protocolVersion':'2.0','requestId':name,'type':'capture'}).encode()
   self.write(m.BROWSER_FIXTURE+name,b)
   self.write(m.GO_FIXTURE+name,b)
   self.fixtures[name]=m.blob(b)
  self.pins={name:m.blob(content.encode()) for name,content in DUMMY.items() if name not in (m.GO_SOURCE,m.GO_TEST,m.INTEGRATION)}
 def write(self,name,data):
  p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 def audit(self):return m.check_sources(self.root,self.pins,self.fixtures)
 def refused(self):
  with self.assertRaises(m.Refused):self.audit()
 def test_valid_baseline_is_not_a_cutover(self):
  r=self.audit();self.assertEqual(r['byte_identical_native_fixtures'],5)
  self.assertFalse(r['production_cutover_qualified'])
  self.assertFalse(r['browser_capture_executes'])
 def test_dotnet_source_pin_drift_refuses(self):
  p='app/XDM/src/XDM.BrowserIntegration/BrowserNativeProtocol.cs';self.write(p,b'drift');self.refused()
 def test_dotnet_native_framing_drift_refuses(self):
  p='app/XDM/src/XDM.BrowserIntegration/NativeMessageFraming.cs';self.write(p,b'read_be16');self.refused()
 def test_go_wire_major_drift_refuses(self):
  p='engine/api/v1/wire.go';self.write(p,b'ProtocolMajor = 2');self.refused()
 def test_browser_fixture_changed_refuses(self):
  p=m.BROWSER_FIXTURE+'native-capture.json';self.write(p,b'changed');self.refused()
 def test_go_fixture_changed_refuses(self):
  p=m.GO_FIXTURE+'native-capture.json';self.write(p,b'changed');self.refused()
 def test_source_symlink_refuses(self):
  p=self.root/m.GO_FIXTURE/'native-capture.json';p.unlink();p.symlink_to(self.root/(m.BROWSER_FIXTURE+'native-capture.json'));self.refused()
 def test_duplicate_fixture_version_refuses(self):
  p=m.BROWSER_FIXTURE+'native-capture.json';b=json.dumps({'protocolVersion':'1.0'}).encode();self.write(p,b)
  self.write(m.GO_FIXTURE+'native-capture.json',b)
  self.fixtures['native-capture.json']=m.blob(b);self.refused()
 def test_shadow_execution_flag_mutation_refuses(self):
  p=m.GO_SOURCE;s=(self.root/p).read_text().replace('ExecutionAuthorized: false','ExecutionAuthorized: true');self.write(p,s.encode());self.refused()
 def test_shadow_cutover_flag_mutation_refuses(self):
  p=m.GO_SOURCE;s=(self.root/p).read_text().replace('ProductionCutover: false','ProductionCutover: true');self.write(p,s.encode());self.refused()
 def test_parity_source_adds_privileged_exec_refuses(self):
  p=m.GO_SOURCE;s=(self.root/p).read_text()+'\nimport "os/exec"';self.write(p,s.encode());self.refused()
 def test_missing_host_optin_refuses(self):
  p=m.GO_SOURCE;s=(self.root/p).read_text().replace('trustedHostOptIn','UNSAFE');self.write(p,s.encode());self.refused()
 def test_missing_real_go_runtime_replay_refuses(self):
  p=m.INTEGRATION;s=(self.root/p).read_text().replace('engine.Submit(ctx, cmd)','skip');self.write(p,s.encode());self.refused()
 def test_actual_go_runtime_integration_accepts_gofmt_whitespace(self):
  # Catch the exact HF01 regression using the ACTUAL bundled Go test file.
  # In the standalone ZIP self-test, this is copied from the payload, not
  # a synthetic approximation; in the repo it is the staged Go source.
  actual=(P.parents[1]/m.INTEGRATION).read_text()
  self.assertIn('engine.Submit(ctx, cmd)',actual)
  self.write(m.INTEGRATION,actual.encode())
  self.assertEqual(self.audit()['go_native_wire_major'],1)
 def test_go_runtime_submit_whitespace_variants_accept(self):
  p=m.INTEGRATION
  for code in ('engine.Submit(ctx,cmd)', 'engine.Submit( ctx , cmd )', 'engine.Submit(ctx, cmd)'):
   self.write(p,DUMMY[p].replace('engine.Submit(ctx, cmd)',code).encode())
   self.assertEqual(self.audit()['go_native_wire_major'],1)
 def test_go_runtime_decoder_bypass_refuses(self):
  p=m.INTEGRATION;s=(self.root/p).read_text().replace('v1.DecodeCommand(commandBytes)','decodeUnchecked(commandBytes)')
  self.write(p,s.encode());self.refused()
 def test_go_runtime_wrong_command_kind_refuses(self):
  p=m.INTEGRATION;s=(self.root/p).read_text().replace('cmd.Kind != DesktopUISnapshotKind','cmd.Kind != DesktopMediaExecuteKind')
  self.write(p,s.encode());self.refused()
 def test_go_runtime_unverified_projection_refuses(self):
  p=m.INTEGRATION;s=(self.root/p).read_text().replace('first.Kind != "desktop.ui.projection"','first.Kind != "platform.request"')
  self.write(p,s.encode());self.refused()
 def test_go_runtime_unverified_completion_refuses(self):
  p=m.INTEGRATION;s=(self.root/p).read_text().replace('second.Kind != "command.completed"','second.Kind != "command.failed"')
  self.write(p,s.encode());self.refused()
 def test_go_runtime_execution_cutover_guard_missing_refuses(self):
  p=m.INTEGRATION;s=(self.root/p).read_text().replace('evidence.ExecutionAuthorized || evidence.ProductionCutover','false')
  self.write(p,s.encode());self.refused()
 def test_missing_recorded_fixture_refuses(self):
  p=self.root/m.GO_FIXTURE/'native-batch.json';p.unlink();self.refused()
 def test_missing_native_session_guard_refuses(self):
  p='app/XDM/src/XDM.NativeHost/Program.cs';self.write(p,b'not authenticated');self.refused()

if __name__=='__main__':unittest.main(verbosity=2)
