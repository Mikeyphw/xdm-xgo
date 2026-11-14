#!/usr/bin/env python3
"""MP09 source contract: integration, no phantom publication, no timeout cap."""
from pathlib import Path
import re
root=Path(__file__).resolve().parents[1]
files={
 'engine/media/live_recording.go':[
  'NewMP09Recording(', 'PollDue(', 'StopAndSave(', 'RunMP08VerifiedPublication(',
  'ErrMP09Partial','mp09LiveMP08Plan(', 'MP09ResumeVerified(', 'BindForMP09(',
  'DownloadReady:false','Published:false','MP09VerifiedDiscard'],
 'engine/runtime/android_live_recording.go':[
  'AndroidMediaLiveKind','androidMediaLiveHandler(', 'PlatformRequest(ctx,platform.ManifestFetch',
  'newAndroidMP08Host(', 'Finalize(ctx,', 'read_chunk','discard_capture','capture_not_authorized','preflightNoUnboundJournal'],
 'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidLiveRecordingService.kt':[
  'startForeground(', 'START_NOT_STICKY', 'submitMediaUiCommand("android.media.live"',
  'onStartCommand', 'STOP_SAVE', 'CANCEL_DISCARD', 'Recording interrupted'],
 'engine/runtime/engine.go':['e.handlers[AndroidMediaLiveKind] = e.androidMediaLiveHandler'],
 'app/XDM.Android/app/src/main/AndroidManifest.xml':['.engine.AndroidLiveRecordingService','android:exported="false"','android:foregroundServiceType="dataSync"'],
 'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidLiveDurableFragmentStore.kt':[
  'readChunk(', 'discardCapture(', 'fragment_identity_required', 'fragment_readback_failed'],
 'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidAuthorizedManifestFetcher.kt':[
  'range_content_range_invalid', 'range_scope_denied'],
 'engine/runtime/android_mp08_host.go':['"hls_live"','"dash_live"'],
}
for name,need in files.items():
 src=(root/name).read_text()
 for token in need:
  if token not in src and re.sub(r'\s+', '', token) not in re.sub(r'\s+', '', src):raise AssertionError('MP09_CONSOLIDATED_MISSING '+name+': '+token)
for name in ['engine/media/live_recording.go','engine/runtime/android_live_recording.go']:
 src=(root/name).read_text()
 for forbidden in ['http.Get(', 'http.Client{', 'exec.Command(', 'os.RemoveAll(',
                   'time.After(10*time.Minute)', 'time.After(2*time.Hour)',
                   'DownloadReady:true', 'Published:true']:
  if forbidden in src:raise AssertionError('MP09_CONSOLIDATED_UNSAFE '+name+': '+forbidden)
assert len(re.findall(r'^func TestMP09Consolidated\w+\(', (root/'engine/media/live_recording_test.go').read_text(),re.M)) >= 7
print('XGO_MP09_CONSOLIDATED_SOURCE_CONTRACT_PASS')

# HF02: new behavior lives exclusively in MP09-specific adapters.
import subprocess
originals = {
 'engine/runtime/android_fragment_store.go': '79ee540e52b1f61726dc721614d690774d0c5a8c',
 'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidDurableFragmentStore.kt': '33b015b52187e16ce89b4141964f699d226d064f',
}
for name, blob in originals.items():
 # The inherited MP06/07/08 exact-source checks must never be edited or weakened.
 if (root/name).read_bytes() != subprocess.check_output(['git','show', f'1a0806a069ae27eea322332c9f05f70cf6fd4d34:{name}'],cwd=Path(__import__('os').environ.get('XGO_MP09_HF02_GIT_REPO', str(root)))):
  raise AssertionError('MP09_HF02_MP05_LEGACY_MUTATION '+name)
actual_go=(root/'engine/runtime/android_live_fragment_store.go').read_text()
actual_dispatch=(root/'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidPlatformRequestDispatcher.kt').read_text()
actual_stage=(root/'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidLiveMP08VerifiedStageBroker.kt').read_text()
actual_authority=(root/'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidEngineProcessAuthority.kt').read_text()
# gofmt normalizes spacing in key/value literals. Check identity bindings
# semantically while requiring exactly one copy of each sensitive field.
import re
for marker in ('mp09FragmentStoreAdapter', '"mp09_live"'):
 if marker not in actual_go:raise AssertionError('MP09_HF02_GO_ISOLATION_MISSING '+marker)
if len(re.findall(r'"identity"\s*:\s*rec\.Identity\s*[,}]', actual_go)) != 1:
 raise AssertionError('MP09_HF02_GO_ISOLATION_MISSING_identity_binding')
if len(re.findall(r'"track_role"\s*:\s*a\.roleHint\s*[,}]', actual_go)) != 1:
 raise AssertionError('MP09_HF02_GO_ISOLATION_MISSING_track_role_binding')
for marker in ('mp09LiveStore.execute(payload)', 'mp09StageBroker.execute(payload)',
               'else fragmentStore.execute(payload)', 'else mp08Broker.execute(payload)'):
 if marker not in actual_dispatch:raise AssertionError('MP09_HF02_DISPATCH_DRIFT '+marker)
if '"xgo-fragments-mp09"' not in actual_stage or '"xgo-fragments-mp09"' not in (root/'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidLiveDurableFragmentStore.kt').read_text():
 raise AssertionError('MP09_HF02_LIVE_JOURNAL_NOT_ISOLATED')
if 'AndroidLiveDurableFragmentStore(appContext)' not in actual_authority or 'AndroidLiveMP08VerifiedStageBroker(' not in actual_authority:
 raise AssertionError('MP09_HF02_HOST_NOT_CONNECTED')
print('XGO_MP09_HF02_INHERITED_IMMUTABILITY_AND_LIVE_PORTS_PASS')
