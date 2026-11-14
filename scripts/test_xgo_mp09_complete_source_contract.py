#!/usr/bin/env python3
"""MP09 final integration: source/negative checks, old MP03-MP08 contracts retained.

No grep-only substitute for Go behavioral tests; those run separately in CI.
"""
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
E='app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/'
UI='app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/ui/media/MediaInboxScreen.kt'

def read(p):return (ROOT/p).read_text(encoding='utf-8')
def required(p,need):
    text=read(p)
    for marker in need:
        assert marker in text, f'MP09_FINAL_MISSING {p}: {marker}'

required('engine/media/mp09_dash_binding.go',['func MP09MapDASHIDs(', 'rawIDs[rep.ID]', 'ErrMP09DASHBinding', 'mp03Identity("video", key)','mp03Identity("track", key)'])
required('engine/media/mp09_live_timeline_restore.go',['MP09RestoreVerifiedTimeline','mp09Continuous(parsed)','e.seenHLS','e.lastDASH'])
required('engine/runtime/mp09_dash_preflight.go',['mp09BindDASH(', 'ResolveManifestGraph(', 'ManifestGraphRevision(', 'ParseDASHManifest(', 'MP09MapDASHIDs(', 'body.FinalURL', 'body.Redirects', 'authorizedRoot.Body', 'rootResponses != 1'])
required('engine/runtime/mp09_live_recovery.go',['mp09ReadSession(', 'mp09BeginSession(', 'mp09SessionRequest(', 'mp09SourceBinding(', 'mp09StableSourceURL(', 'mp09RestoreVerified(', 'mp09Rehydrate(', 's.ReadVerified(', 'mp09FinishSession(', 'mp09SetSessionPhase(', 'mp09InspectSession(', 'meta.Phase != "recording"', 'session.NetworkFailure(now)'])
required('engine/runtime/android_live_recording.go',['mp09SetSessionPhase(ctx, inv, req.CaptureID, "publishing")','mp09SetSessionPhase(ctx, inv, req.CaptureID, "published")','publication_pending_review','published_cleanup_pending','case "bind_dash":', 'case "start", "resume_interrupted":', 'mp09ReadSession(', 'mp09Rehydrate(', 'mp09BeginSession(', 'mp09BindDASH(', 'mp09RestoreVerified('])
required(E+'AndroidLiveDurableFragmentStore.kt',['session-v1.json', 'sessionCaptureKey(', 'validateSession(', 'beginSession(', 'readSession(', 'finishSession(', '"session_begin" -> beginSession(', '"session_read" -> readSession(', '"session_finish" -> finishSession(', '"session_phase" -> changeSessionPhase(', '"session_status" -> sessionStatus(', 'AndroidMP09SessionPhaseGate.mayTransition(', 'capture_session_expired', 'session_already_exists_review_required', 'fragment_readback_failed'])
required(E+'AndroidLiveSelectionGate.kt',['dashBinding:', 'graph.protocol == "dash"', 'graph.periods.size == 1', 'dash_bound_unverified', 'videoRepresentationId', 'audioRepresentationId'])
required(E+'AndroidMediaUiClient.kt',['suspend fun liveBindDash(', '.put("action", "bind_dash")'])
required(E+'AndroidMediaUiProtocol.kt',['liveManifestUrl', 'videoRepresentationId', 'audioRepresentationId', 'cleanupPending'])
required(E+'AndroidLiveRecordingService.kt',['RECOVER_INTERRUPTED', '"resume_interrupted"', 'EXPECTED_REVISION', 'START_NOT_STICKY', 'STOP_SAVE', 'CANCEL_DISCARD', 'result.cleanupPending'])
required(UI,['recoveryReviewState', 'publication_pending_review', 'published_cleanup_pending', '"Reauthorize & resume"','goManifestClient.liveBindDash(', 'userSelectedResumeCaptureId == id', 'AndroidLiveRecordingService.start(context, intent)'])
required('engine/media/mp09_dash_binding_test.go',['TestMP09LIVE01DASHExactRepresentationIDs','TestMP09LIVE02DASHFailClosedBindingMatrix'])
required('engine/media/mp09_live_timeline_restore_test.go',['TestMP09LIVE03RestoredHLSHighWater','TestMP09LIVE04RestoredDASHHighWater','TestMP09LIVE05RestoredTimelineRejectsGapsAndWrongGeneration'])
required('engine/media/mp09_complete_acceptance_test.go',[f'TestMP09LIVE{i:02d}' for i in range(6,12)])
required('engine/runtime/mp09_live_recovery_test.go',[f'TestMP09LIVE{i:02d}' for i in range(12,16)])
required('engine/runtime/mp09_dash_snapshot_contract_test.go',['TestMP09LIVE16DASHGraphAndNativeIDsShareAuthorizedSnapshot'])
required('engine/runtime/mp09_recovery_publication_phase_test.go',[
    'TestMP09LIVE17PublicationFenceRefusesPostCrashRepublish',
    'TestMP09LIVE18PublicationPhaseOnlyAdvancesAndStatusIsScoped'])
required(E+'AndroidMP09SessionPhaseGate.kt',['mayResume(phase: String)',
    'mayTransition(current: String, next: String)', '"published" -> next == "published"',
    '"published_clean" -> next == "published_clean"', 'afterVerifiedDiscard(',
    'mayStartAfterTerminal('])
required(E+'AndroidMP09SessionJournalGuard.kt',['SCHEMA = 2','checksum(fields: List<String>)',
    'exactFields(names: Collection<String>)', 'MessageDigest.getInstance("SHA-256")'])
required(E+'AndroidLiveDurableFragmentStore.kt',['sessionSeal(', 'session_seal',
    'writeSessionRows(', 'published_clean', 'publication_review_required',
    'session_finish_requires_verified_discard', 'terminal_phase_requires_verified_cleanup'])

assert (ROOT/'docs/xgo/MP09_COMPLETE_ACCEPTANCE.md').is_file()

for source in ('engine/media/mp09_dash_binding.go','engine/runtime/mp09_dash_preflight.go','engine/runtime/mp09_live_recovery.go'):
    s=read(source)
    for dangerous in ('http.Get(', 'http.DefaultClient', 'exec.Command(', 'os.RemoveAll(', 'log.Print('):
        assert dangerous not in s,(source,dangerous)

# Strictly keep inherited MP03 UI inspect entry and original Kotlin HLS lane.
card=read('app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/ui/media/MediaCaptureCard.kt')
# HF04: The inherited MP03 inspect control belongs to MediaCaptureCard, NOT
# MediaInboxScreen. Verify live button wiring, not a stray text/comment token.
assert re.search(r'TextButton\s*\(\s*onClick\s*=\s*\{\s*onInspectManifest\(capture\)\s*\}\s*\)\s*\{\s*Text\(\s*"Inspect Go manifest"\s*\)\s*\}', card), 'MP09_FINAL_MP03_CARD_INSPECT_BUTTON_NOT_WIRED'
assert 'onInspectManifest: (MediaCaptureRecord) -> Unit' in card, 'MP09_FINAL_MP03_CARD_INSPECT_CALLBACK_MISSING'
assert 'onReviewInterrupted: (MediaCaptureRecord) -> Unit' in card and 'onReviewInterrupted(capture)' in card, 'MP09_FINAL_MP03_CARD_REVIEW_WIRING_MISSING' 
assert (ROOT/'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidMediaPlatformBroker.kt').is_file()
# Historic files may not be rewritten to make a new phase pass.
legacy=('engine/runtime/android_fragment_store.go',
        'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidDurableFragmentStore.kt',
        'engine/media/manifest_resolver.go',
        'engine/media/fragment_store.go',
        'engine/media/hls_execution.go')
parent='fa79b924d7022f51cf3091b531ba9aff604e855d'
for name in legacy:
    expected=subprocess.check_output(['git','show',f'{parent}:{name}'],cwd=ROOT)
    assert (ROOT/name).read_bytes()==expected,'MP09_FINAL_HISTORIC_SOURCE_DRIFT '+name

# A second root fetch is a moving-MPD race, even when graph IDs match.
preflight=read('engine/runtime/mp09_dash_preflight.go')
assert 'fetch.FetchManifest(ctx, media.ManifestFetchRequest{' not in preflight,'MP09_DASH_MOVING_MPD_REFETCH'
assert 'ParseDASHManifest(authorizedRoot.FinalURL, string(authorizedRoot.Body))' in preflight
assert 'strings.Contains(k, "session")' not in read('engine/runtime/mp09_live_recovery.go'),'MP09_OVERBROAD_AUTH_QUERY_FILTER'
print('XGO_MP09_DASH_SINGLE_SNAPSHOT_SOURCE_AND_LEGACY_CONTRACT_PASS')
