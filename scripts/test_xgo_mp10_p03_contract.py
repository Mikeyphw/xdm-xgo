#!/usr/bin/env python3
"""MP10 P03 recovery fence source regression + injected structural negatives.

Source contracts are a supplement to real ./engine/runtime Go tests, never a
substitute for Android API36 or physical ARM64 recording qualification.
"""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
PATHS={
 'handler':'engine/runtime/android_live_recording.go',
 'bridge':'engine/runtime/mp10_recovery_p03_integration.go',
 'fence':'engine/runtime/mp10_recovery_p03.go',
 'tests':'engine/runtime/mp10_recovery_p03_test.go',
}

REQUIRED={
 'handler':[
    'var recoverySession mp09StoredSession',
    'recoverySession = meta',
    'mp10FenceInterruptedRecording(ctx, inv,',
    'req.CaptureID, root, req, recoverySession, now, video, audio)',
    'mp10SameRecoveryFence(priorRecoveryFence, confirmedRecoveryFence)',
    'recovery_inventory_preflight_failed',
    'recovery_inventory_changed_during_rehydrate',
    'mp09Rehydrate(session, now, video, audio, vpoll, apoll)',
 ],
 'bridge':[
    'mp09ReadSession(ctx, inv, capture, root, req, now)',
    'mp09SourceBinding(root, req)',
    '"track_role": "all"',
    'VerifyCommitted(found.rec)',
    'mp10CheckRecoveryFence(payload, capture, sealed.Binding,',
    'confirmed != sealed',
    'EncryptionID: rec.Identity.EncryptionID',
    'Range: span',
 ],
 'fence':[
    'len(raw) > 512<<10',
    'inventory.Unbound != 0',
    'len(inventory.Records) != len(expected)',
    'roleMedia["video"] == 0 || roleMedia["audio"] == 0',
    'item.Artifact != safeName',
    'present[got.FragmentID]',
    'sealedBinding != currentBinding',
    'phase != "recording"',
    'item.Protocol != protocol',
    'got.Identity.EncryptionID != want.EncryptionID',
    'got.Identity.Range.Offset != want.Range.Offset',
    'rangeMarker, item.EncryptionID,',
    'verify(item)',
    'sort.Strings(ordered)',
 ],
 'tests':[
    'TestMP10P03REC%02d' % number for number in range(1,20)
 ],
}

def inspect(content):
 for label,needles in REQUIRED.items():
  for needle in needles:
   if needle not in content[label]:
    raise AssertionError('MP10_P03_MISSING_OR_CHANGED_CONTRACT '+label+':'+needle)
 if content['handler'].find('priorRecoveryFence')>=content['handler'].find('mp09Rehydrate(session, now, video, audio, vpoll, apoll)'):
  raise AssertionError('MP10_P03_PRE_FENCE_MUST_PRECEDE_REHYDRATION')
 if content['handler'].find('confirmedRecoveryFence')<=content['handler'].find('mp09Rehydrate(session, now, video, audio, vpoll, apoll)'):
  raise AssertionError('MP10_P03_POST_FENCE_MUST_FOLLOW_REHYDRATION')
 if 'os.Remove(' in content['fence'] or 'os.RemoveAll(' in content['bridge']:
  raise AssertionError('MP10_P03_RECOVERY_MUST_NOT_DELETE_DURABLE_EVIDENCE')
 if 'DownloadReady: true' in content['fence'] or 'download_ready":true' in content['bridge']:
  raise AssertionError('MP10_P03_RECOVERY_MUST_NOT_PUBLISH')

class P03Contract(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.contents={key:(ROOT/path).read_text() for key,path in PATHS.items()}
 def test_real_sources(self):inspect(self.contents)
 def test_targeted_negative_mutations(self):
  mutations=[('handler','recovery_inventory_preflight_failed'),
   ('handler','mp10SameRecoveryFence(priorRecoveryFence, confirmedRecoveryFence)'),
   ('bridge','VerifyCommitted(found.rec)'),
   ('bridge','confirmed != sealed'),
   ('fence','inventory.Unbound != 0'),
   ('fence','sealedBinding != currentBinding'),
   ('fence','verify(item)'),
   ('fence','got.Identity.EncryptionID != want.EncryptionID'),
   ('fence','got.Identity.Range.Offset != want.Range.Offset'),
   ('tests','TestMP10P03REC12')]
  for label,anchor in mutations:
   with self.subTest(label=label,anchor=anchor):
    candidate=dict(self.contents)
    self.assertIn(anchor,candidate[label])
    candidate[label]=candidate[label].replace(anchor,'REMOVED_CONTRACT',1)
    with self.assertRaises(AssertionError):inspect(candidate)

if __name__=='__main__':unittest.main(verbosity=2)
