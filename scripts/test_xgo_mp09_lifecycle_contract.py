#!/usr/bin/env python3
"""Exact transformed service state and Go-status contract, with negatives.
The launched ZIP also compiles the byte-pinned service with Android API stubs.
"""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
E='app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/'


def check(service:str, gate:str, go:str) -> None:
    must_service=(
        'private val lifecycle = AndroidMP09RecordingLifecycleState()',
        'private val commandMutex = Mutex()',
        'lifecycle.beginStart()', 'lifecycle.started()', 'lifecycle.startFailed()',
        'lifecycle.begin(control, dvrVerified)', 'commandMutex.withLock',
        'lifecycle.complete(control, accepted)', 'lifecycle.available(dvrVerified)',
        'result.status == "cancel_pending_cleanup"',
        'result.status == "completed"', 'if (result != null && result.cleanupPending)',
        'result.status == "paused"', 'result.status == "capturing"',
        'if (poller == null) poller = scope.launch { pollLoop(id) }',
        'lifecycle.interrupted()', 'Stale recording control refused',
        'reportTerminalFailure("Recording could not start',
        'stopSelf()', 'onTimeout(startId: Int, fgsType: Int)',
        'if (AndroidMP09RecordingLifecycleState.Control.Pause in actions)',
        'if (AndroidMP09RecordingLifecycleState.Control.Resume in actions)',
        'if (AndroidMP09RecordingLifecycleState.Control.StopSave in actions)',
        'if (AndroidMP09RecordingLifecycleState.Control.Discard in actions)',
    )
    for token in must_service:
        if token not in service:raise AssertionError('MP09_LIFECYCLE_SERVICE_MISSING '+token)
    if service.count('commandMutex.withLock') != 3:
        raise AssertionError('MP09_LIFECYCLE_COMMAND_SERIALIZATION_COUNT')
    for forbidden in ('private var paused', 'stopping.set(', 'result.ok && action == "pause"',
                      'if (poller != null || stopping.get())'):
        if forbidden in service:raise AssertionError('MP09_LIFECYCLE_DEPRECATED_RACE '+forbidden)
    must_gate=('enum class Phase', 'enum class Control', '@Synchronized fun beginStart()',
               '@Synchronized fun begin(action:', '@Synchronized fun complete(action:',
               '@Synchronized fun available(dvrVerified:', 'if (current != expected) return current',
               'Phase.Review', 'Phase.Saved', 'Phase.Discarded',
               'Control.Pause -> if (dvrVerified', 'Control.Resume -> if (dvrVerified')
    for token in must_gate:
        if token not in gate:raise AssertionError('MP09_LIFECYCLE_GATE_MISSING '+token)
    if 'LiveSessionCancelPending LiveSessionState = "cancel_pending_cleanup"' not in go:
        raise AssertionError('MP09_GO_CANCEL_STATUS_DRIFT')

class LifecycleContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service=(ROOT/(E+'AndroidLiveRecordingService.kt')).read_text()
        cls.gate=(ROOT/(E+'AndroidMP09RecordingLifecycleState.kt')).read_text()
        cls.go=(ROOT/'engine/media/live_session.go').read_text()
    def test_live_contract(self): check(self.service,self.gate,self.go)
    def test_negative_mutations(self):
        cases=[('service','commandMutex.withLock','unlockedAuthorityCall'),
          ('service','lifecycle.begin(control, dvrVerified)','true'),
          ('service','cancel_pending_cleanup','cancel_pending'),
          ('service','Stale recording control refused','stopLegitimateService'),
          ('service','lifecycle.available(dvrVerified)','setOf(allActions)'),
          ('service','result.status == "completed"','result.status == "failed"'),
          ('gate','if (current != expected) return current','require(current == expected)'),
          ('gate','Control.Pause -> if (dvrVerified','Control.Pause -> if (true'),
          ('go','LiveSessionCancelPending LiveSessionState = "cancel_pending_cleanup"',
           'LiveSessionCancelPending LiveSessionState = "cancel_pending"')]
        for target,old,new in cases:
            with self.subTest(target=target,anchor=old):
                inputs={'service':self.service,'gate':self.gate,'go':self.go}
                self.assertIn(old,inputs[target]);inputs[target]=inputs[target].replace(old,new,1)
                with self.assertRaises(AssertionError):check(**inputs)

if __name__=='__main__':unittest.main(verbosity=2)
