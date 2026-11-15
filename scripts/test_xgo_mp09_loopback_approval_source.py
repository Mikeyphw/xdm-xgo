#!/usr/bin/env python3
"""MP09 exact-loopback fixture admission: source contract, never device evidence."""
from pathlib import Path
BASE = Path(__file__).resolve().parents[1]
def read(path):
    return (BASE / path).read_text(encoding="utf-8")
app = "app/XDM.Android/"
ui = read(app + "app/src/main/kotlin/com/mikeyphw/xdm/android/ui/media/MediaInboxScreen.kt")
vm = read(app + "app/src/main/kotlin/com/mikeyphw/xdm/android/MainViewModel.kt")
main = read(app + "app/src/main/kotlin/com/mikeyphw/xdm/android/XdmApp.kt")
fixture = read(app + "media/src/main/kotlin/com/mikeyphw/xdm/android/media/XgoLoopbackFixtureApproval.kt")
guard = read(app + "scheduler/src/main/kotlin/com/mikeyphw/xdm/android/scheduler/AndroidTransferRequestSecurityGuard.kt")
fetcher = read(app + "app/src/main/kotlin/com/mikeyphw/xdm/android/engine/AndroidAuthorizedManifestFetcher.kt")
for marker in ("pendingFixtureApproval", "Allow this fixture", "onPastePageUrl(expected, true)",
               "pageUrlText.trim() == expected", "onPastePageUrl(target, false)"):
    assert marker in ui, "MP09_LOCAL_UI_MISSING " + marker
for marker in ("localFixtureApproved && XgoLoopbackFixtureApproval.isApprovedRootShape(normalized)",
               "privateNetworkApprovalScopes = if (approvalScope == null) emptySet() else setOf(approvalScope)",
               "MediaRequestHandoffStore.rememberCapture(", "privateNetworkApproved = true",
               "cleartextCredentialsApproved = true", "headers = emptyMap()", "fixtureChildScopes",
               "effectivePrivateScopes + fixtureChildScopes"):
    assert marker in vm, "MP09_LOCAL_SCOPE_MISSING " + marker
for marker in ('HOST = "127.0.0.1"', "PORT = 8765", 'MASTER = "/live/hls/master.m3u8"',
               "uri.rawUserInfo == null", "uri.rawQuery == null", "uri.rawFragment == null",
               "uri.rawPath == uri.path"):
    assert marker in fixture, "MP09_LOCAL_FIXTURE_SHAPE_MISSING " + marker
assert "localFixtureApproved = approved" in main
assert "request.privateNetworkApproved && approvalScope in request.privateNetworkApprovalScopes" in guard
assert 'if (privateTarget && !handoff.privateNetworkApproved) error("private_network_denied")' in fetcher
print("XGO_MP09_LOCALHOST_EXPLICIT_CONSENT_AND_EXACT_SCOPE_SOURCE_PASS")
