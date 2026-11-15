#!/usr/bin/env python3
"""MP11 P01/P02 exact source relationships; deliberately mutation-tested by overlay launcher."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
APP='app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/'

CHECKS={
    'engine/runtime/android_live_recording.go': ('case "inspect_active":','active.ctrl.SnapshotForMP09()', '"download_ready":false,"published":false', '"dvr_capable":active.dvrCapable'),
    APP+'engine/AndroidMediaUiClient.kt': ('"inspect_active"',),
    APP+'engine/AndroidMediaUiProtocol.kt': ('liveDurableFragments','liveDvrCapable','livePartialReviewRequired'),
    APP+'engine/AndroidLiveRecordingService.kt': ('fun control(context: Context, captureId: String, actionName: String)', 'actionName in setOf(STOP_SAVE, PAUSE, RESUME, CANCEL_DISCARD)', 'fun refreshAuthorized'),
    APP+'engine/MP11LiveUiPolicy.kt': ('fun actions(state:', 'fun validRefresh(root:', '"refresh_required"'),
    APP+'ui/media/MediaCaptureCard.kt': ('onRecordingControls:', 'Text("Recording controls")'),
    APP+'ui/media/MediaInboxScreen.kt': (
        'goManifestClient.liveAction(capture.id, "inspect_active")',
        'AndroidLiveRecordingService.control(context, id, AndroidLiveRecordingService.STOP_SAVE)',
        'AndroidLiveRecordingService.control(context, id, AndroidLiveRecordingService.CANCEL_DISCARD)',
        'confirmDiscardId?.let', 'MP11LiveUiPolicy.validRefresh(',
        'MediaRequestHandoffStore.rememberCapture(',
        'AndroidLiveRecordingService.refreshAuthorized(context, request)',
        'onRecordingControls = onInspectActive',
        'putExtra(AndroidLiveRecordingService.USER_LIMIT_MS,',
        'putExtra(AndroidLiveRecordingService.USER_LIMIT_BYTES,',
    ),
}

def check(contents):
    for name,needles in CHECKS.items():
        data=contents[name]
        for needle in needles:
            if needle not in data: raise AssertionError('MP11_MISSING_CONTRACT: '+name+' '+needle)
    ui=contents[APP+'ui/media/MediaInboxScreen.kt']
    # Never persist credential-bearing refresh URLs into saveable state.
    for forbidden in ('var refreshRootUrl by rememberSaveable', 'var refreshVideoUrl by rememberSaveable',
                      'var refreshAudioUrl by rememberSaveable', 'print(refreshRootUrl)',
                      'Log.d("MP11", refreshRootUrl)'):
        if forbidden in ui: raise AssertionError('MP11_UNSAFE_SECRET_UI: '+forbidden)
    if ui.count('onRecordingControls = onInspectActive')!=2:
        raise AssertionError('MP11_MISSING_CAPTURE_SURFACE')
    if ui.count('USER_CONFIRMED_REFRESH, true') != 1:
        raise AssertionError('MP11_REFRESH_CONFIRMATION_MISSING')

if __name__ == '__main__':
    contents={n:(ROOT/n).read_text() for n in CHECKS}
    check(contents)
    for name,needle in (
        (APP+'ui/media/MediaInboxScreen.kt','MediaRequestHandoffStore.rememberCapture('),
        (APP+'ui/media/MediaInboxScreen.kt','confirmDiscardId?.let'),
        (APP+'engine/AndroidLiveRecordingService.kt','actionName in setOf(STOP_SAVE, PAUSE, RESUME, CANCEL_DISCARD)'),
        ('engine/runtime/android_live_recording.go','case "inspect_active":'),
    ):
        mutated=contents.copy();mutated[name]=mutated[name].replace(needle,'unsafe_mutation',1)
        try:check(mutated)
        except AssertionError:pass
        else:raise AssertionError('MP11_NEGATIVE_MUTATION_NOT_REFUSED: '+name)
    print('MP11_P01_P02_EXACT_SOURCE_AND_NEGATIVE_MUTATIONS_PASS')
