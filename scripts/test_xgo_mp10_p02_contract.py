#!/usr/bin/env python3
"""MP10 P02: explicit reauthorization must be serialized, two-phase and fail closed."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]

class MP10P02SourceContracts(unittest.TestCase):
    def test_reauthorization_is_go_owned_and_all_track_atomic(self):
        s=(ROOT/'engine/media/mp10_rebind.go').read_text()
        for item in ('MP10ValidateRefreshBinding(formerRoot, renewedRoot)',
                     'len(candidates) != len(r.tracks)', 'len(plans) != len(r.tracks)',
                     'e.store.VerifyCommitted(old)', 'manifest.Kind != HLSPlaylistMedia',
                     'len(manifest.Periods) != 1', 'p.poll.refreshRequired = false',
                     'r.refreshGeneration = generation', 'ErrMP10RefreshIdentity',
                     'r.mp10VerifySessionMedia()', 'want, ok := expected[rec.ID]', 'seen[rec.ID]',
                     'len(seen) != len(expected)', 'track.store.VerifyCommitted(want)'):
            self.assertIn(item,s)
        self.assertLess(s.index('r.mp10VerifySessionMedia()'),s.index('track.poll.mp10PrepareRefresh(ctx, candidate)'))
        self.assertLess(s.index('if len(plans) != len(r.tracks)'),s.index('p.poll.refreshRequired = false'))
        for banned in ('os.RemoveAll(', 'DownloadReady: true', 'Published: true','http.Get('):
            self.assertNotIn(banned,s)
    def test_android_binding_requires_current_encrypted_capture(self):
        s=(ROOT/'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidAuthorizedManifestFetcher.kt').read_text()
        for item in ('MediaRequestHandoffStore.forCapture(id)',
                     'if (root != declaredRoot) return rejected("capture_request_changed")',
                     'if (handoff.expiresAtEpochMs <= now)',
                     'if (origin(requested) != rootOrigin'):
            self.assertIn(item,s)
    def test_private_user_review_and_go_result_gate(self):
        p='app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/'
        service=(ROOT/(p+'AndroidLiveRecordingService.kt')).read_text()
        gate=(ROOT/(p+'AndroidMP09RecordingLifecycleState.kt')).read_text()
        controller=(ROOT/'engine/runtime/android_live_recording.go').read_text()
        for item in ('!intent.getBooleanExtra(USER_CONFIRMED_REFRESH, false)',
                     'lifecycle.beginAuthorizationRefresh()',
                     'lifecycle.completeAuthorizationRefresh(accepted)',
                     'result?.ok == true && result.status == "capturing"'):
            self.assertIn(item,service)
        self.assertIn('if (current != Phase.Review) return false',gate)
        for item in ('case "refresh_authorized":', 'req.RefreshApproved',
                     'active.ctrl.MP10Reauthorize(', 'active.root = req.RefreshedRootURL',
                     '"refresh_identity_or_durable_overlap_not_proven"'):
            self.assertIn(item,controller)
        self.assertLess(controller.index('active.ctrl.MP10Reauthorize('), controller.index('active.root = req.RefreshedRootURL'))
    def test_credential_denial_stops_same_poll_transport_burst(self):
        text=(ROOT/'engine/media/live_poll.go').read_text()
        assert text.count('if f.failure != nil && (f.failure.RefreshRequired() || f.failure.RetryAfter > 0)') == 2
        assert text.count('mp10PreferFetchFailure(f.failure, observed)') == 2
        policy=(ROOT/'engine/media/mp10_refresh.go').read_text()
        for anchor in ('next.RefreshRequired() && !current.RefreshRequired()',
                       'next.RetryAfter > current.RetryAfter'):
            self.assertIn(anchor,policy)
        self.assertNotIn('os.Remove(', text)

    def test_no_old_source_contract_weakening(self):
        s=(ROOT/'scripts/test_xgo_mp09_lifecycle_contract.py').read_text()
        self.assertIn("if service.count('commandMutex.withLock') != 4:",s)
        self.assertIn("'if (current != expected) return current'",s)
        self.assertIn("'Control.Pause -> if (dvrVerified'",s)
        self.assertNotIn("continue-on-error",s)

if __name__=='__main__':unittest.main(verbosity=2)
