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
 'app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidDurableFragmentStore.kt':[
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
